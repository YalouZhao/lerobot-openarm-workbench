from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np

from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
from lerobot.cameras.realsense.configuration_realsense import RealSenseCameraConfig
from lerobot.processor import make_default_processors
from lerobot.robots import make_robot_from_config
from lerobot.robots.bi_openarm_follower.config_bi_openarm_follower import BiOpenArmFollowerConfig
from lerobot.robots.openarm_follower.config_openarm_follower import OpenArmFollowerConfigBase
from lerobot.teleoperators import make_teleoperator_from_config
try:
    from lerobot.teleoperators.openarm_mini.config_openarm_mini import OpenArmMiniConfig
except ImportError:  # pragma: no cover - depends on installed LeRobot robot set.
    OpenArmMiniConfig = None
from lerobot.utils.constants import ACTION, OBS_STR
from lerobot.utils.robot_utils import precise_sleep

from .command import CommandFrame, command_mismatches
from .config import RELATIVE_JOINT_MODE, WorkbenchSettings
from .dataset_manifest import CanonicalDatasetManifest, DatasetSchemaError
from .device_probe import reset_realsense
from .episode_manifest import EpisodeManifest, EpisodeRecord, now_iso
from .lerobot_compat import (
    LeRobotDataset,
    VideoEncodingManager,
    aggregate_pipeline_dataset_features,
    build_dataset_frame,
    combine_feature_dicts,
    create_initial_features,
    dataset_has_pending_frames,
    adapt_bi_openarm_camera_keys,
    make_bi_openarm_configuration,
    resume_lerobot_dataset,
)
from .openarm_mini_compat import (
    OpenArmMiniCompatibilityMapper,
    detect_lerobot_revision,
    lerobot_applies_compat_mapping_natively,
)
from .ready_controller import ReadyController, ReadySettings
from .safety import FollowerSafetyProcessor, SafetyResult
from .timing import summarize_timing_events, write_timing_sidecar
from .training_export import export_training_package
from .xlerobot_profile import is_xlerobot_so101_schema, xlerobot_so101_profile_metadata
from .xlerobot_mapping import XLeRobotSO101CompatibilityMapper

logger = logging.getLogger(__name__)


@contextmanager
def _press_enter_for_existing_calibration():
    import builtins

    original_input = builtins.input
    builtins.input = lambda prompt="": ""
    try:
        yield
    finally:
        builtins.input = original_input


def _make_camera_config(cfg: dict[str, Any]):
    cam_type = cfg["type"]
    if cam_type == "opencv":
        return OpenCVCameraConfig(
            index_or_path=cfg["index_or_path"],
            width=int(cfg["width"]),
            height=int(cfg["height"]),
            fps=int(cfg["fps"]),
            fourcc=cfg.get("fourcc"),
            warmup_s=int(cfg.get("warmup_s", 1)),
        )
    if cam_type == "intelrealsense":
        return RealSenseCameraConfig(
            serial_number_or_name=str(cfg["serial_number_or_name"]),
            width=int(cfg["width"]),
            height=int(cfg["height"]),
            fps=int(cfg["fps"]),
            warmup_s=int(cfg.get("warmup_s", 1)),
            use_depth=bool(cfg.get("use_depth", False)),
        )
    raise ValueError(f"Unsupported camera type: {cam_type}")


def _encode_jpeg_rgb(frame: np.ndarray, quality: int) -> bytes | None:
    if frame is None:
        return None
    if frame.ndim == 3 and frame.shape[2] == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return None
    return encoded.tobytes()


class WorkbenchController:
    def __init__(self, settings: WorkbenchSettings, session_id: str | None = None):
        self.settings = settings
        self.lerobot_revision = detect_lerobot_revision()
        self.native_compat_mapping = lerobot_applies_compat_mapping_natively()
        if is_xlerobot_so101_schema(settings.dataset.dataset_schema_version):
            self.compat_mapper = XLeRobotSO101CompatibilityMapper(
                mapping_version=settings.compat_mapping_version,
            )
        else:
            self.compat_mapper = OpenArmMiniCompatibilityMapper(
                apply_mapping=settings.apply_openarm_mini_compat_mapping,
                mapping_version=settings.compat_mapping_version,
                native_mapping_detected=self.native_compat_mapping,
            )
        self.safety_processor = (
            FollowerSafetyProcessor(settings.safety) if settings.safety is not None else None
        )
        self.session_id = session_id or time.strftime("%Y%m%d_%H%M%S")
        self.session_dir = settings.session_root / self.session_id
        self.manifest = EpisodeManifest(self.session_dir)
        self.dataset_manifest = CanonicalDatasetManifest(
            dataset_root=settings.dataset.root,
            dataset_name=settings.dataset.root.name,
            repo_id=settings.dataset.repo_id,
            task_text=str(settings.control.get("default_task", "")),
            session_id=self.session_id,
            dataset_schema_version=settings.dataset.dataset_schema_version,
            action_semantics=settings.dataset.action_semantics,
            teleop_mode=settings.teleop_mode,
            command_frame_version=settings.dataset.command_frame_version,
            lerobot_revision=self.lerobot_revision,
            compat_mapping_applied=self._compat_mapping_applied(),
            compat_mapping_version=settings.compat_mapping_version,
            compat_mapping_verified=settings.compat_mapping_verified,
            safety_metadata=(settings.safety.to_metadata() if settings.safety is not None else None),
        )

        self.lock = threading.RLock()
        self.dataset_lock = threading.RLock()
        self.device_io_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.loop_thread: threading.Thread | None = None
        self.export_thread: threading.Thread | None = None
        self.training_export_job: dict[str, Any] = {"ok": True, "status": "idle", "job_id": ""}

        self.robot = None
        self.teleop = None
        self.dataset: LeRobotDataset | None = None
        self.video_manager: VideoEncodingManager | None = None
        self.teleop_action_processor = None
        self.robot_action_processor = None
        self.robot_observation_processor = None

        self.state = "starting"
        self.message = "initializing"
        self.recording = False
        self.discard_requested = False
        self.current_task = str(settings.control.get("default_task", ""))
        self.current_episode_index = 0
        self.current_started_at: str | None = None
        self.current_frame_count = 0
        self.current_record_start = 0.0
        self.last_saved_episode_index: int | None = None
        self.last_save_duration_s: float | None = None
        self.last_reconnect_attempt = 0.0
        self.last_driver_mismatches: dict[str, Any] | None = None
        self.last_effective_command: dict[str, float] | None = None
        self.last_effective_time_ns: int | None = None
        self.ready_state = "invalid"
        self.latest_ready_result: dict[str, Any] | None = None
        self.sync_state = "invalid"
        self.latest_sync_result: dict[str, Any] | None = None
        self.sync_offsets: dict[str, float] | None = None
        self.sync_arms: set[str] = set()
        self.sync_calibration: dict[str, dict[str, float]] | None = None
        self.latest_relative_result: dict[str, dict[str, float]] | None = None
        self.freeze_reason = ""
        self.freeze_message = ""
        self.auto_stopped_by_safety = False
        self.auto_stop_save_status = ""
        self.current_contamination_reasons: set[str] = set()
        self.current_dq_reasons: set[str] = set()
        self.current_command_validation: dict[str, Any] = {}
        self.current_tracking_validation: dict[str, Any] = {}
        self.current_timing_events: list[dict[str, Any]] = []
        self.current_sync_valid_at_record_start = False
        self.current_sync_state_at_record_start = "invalid"
        self.current_sync_result_at_record_start: dict[str, Any] = {}
        self.safety_frozen = False
        self._mismatch_streak = 0
        self._tracking_contamination_streak = 0
        self._tracking_warning_logged = False
        self._reset_episode_command_validation()
        self._reset_episode_tracking_validation()

        self.jpeg_quality = int(settings.control.get("jpeg_quality", 80))
        self.camera_timeout_s = float(settings.control.get("camera_timeout_s", 2.0))
        self.connect_retries = int(settings.control.get("connect_retries", 3))
        self.connect_retry_delay_s = float(settings.control.get("connect_retry_delay_s", 2.0))
        self.auto_reconnect_when_idle = bool(settings.control.get("auto_reconnect_when_idle", True))
        self.reconnect_cooldown_s = float(settings.control.get("reconnect_cooldown_s", 5.0))
        self.teleop_when_idle = bool(settings.control.get("teleop_when_idle", True))
        self.dry_teleop_enabled = False
        self.frame_cache: dict[str, dict[str, Any]] = {
            name: {
                "jpeg": None,
                "timestamp": None,
                "fps": 0.0,
                "frames": 0,
                "ok": False,
                "last_error": None,
            }
            for name in settings.cameras
        }

    def start(self) -> None:
        self._connect_devices()
        self.stop_event.clear()
        self.loop_thread = threading.Thread(target=self._control_loop, name="workbench-control", daemon=True)
        self.loop_thread.start()

    def shutdown(self) -> None:
        self.stop_event.set()
        if self.loop_thread:
            self.loop_thread.join(timeout=5)
        with self.lock:
            self.recording = False
            self.state = "stopping"
            self.message = "stopping"
        self._finalize_dataset()
        self._disconnect_devices()
        with self.lock:
            self.state = "stopped"
            self.message = "stopped"

    def start_episode(self, task: str | None) -> dict[str, Any]:
        with self.lock:
            if self.recording:
                raise RuntimeError("episode already recording")
            if self.safety_frozen:
                raise RuntimeError(
                    "safety is frozen after follower tracking error; reconnect devices before collection"
                )
            if self._ready_required_for_recording() and self.ready_state != "verified":
                raise RuntimeError("Move to Ready must be verified before recording")
            if self._sync_required_for_recording() and self.sync_state != "valid":
                raise RuntimeError("Sync Master must be valid before recording")
            self.dry_teleop_enabled = False
            self._ensure_dataset()
            self.current_task = (
                task or self.current_task or self.settings.control.get("default_task") or ""
            ).strip()
            if not self.current_task:
                raise ValueError("task is required")
            self.current_episode_index = int(getattr(self.dataset, "num_episodes", 0))
            self.current_started_at = now_iso()
            self.current_frame_count = 0
            self.current_record_start = time.perf_counter()
            self.last_save_duration_s = None
            self.discard_requested = False
            self.current_contamination_reasons = set()
            self.current_dq_reasons = set()
            self.current_timing_events = []
            self.current_sync_valid_at_record_start = self.sync_state == "valid"
            self.current_sync_state_at_record_start = self.sync_state
            self.current_sync_result_at_record_start = dict(self.latest_sync_result or {})
            self.auto_stopped_by_safety = False
            self.auto_stop_save_status = ""
            if self.settings.safety is not None and not self.settings.safety.safety_config_verified:
                self.current_contamination_reasons.add("safety_config_unverified")
            self._reset_episode_command_validation()
            self._reset_episode_tracking_validation()
            self.recording = True
            self.state = "recording"
            self.message = "recording"
            self.manifest.event(
                "info",
                "episode_start",
                "Episode started",
                episode_index=self.current_episode_index,
                task=self.current_task,
            )
            return {"ok": True, "episode_index": self.current_episode_index}

    def stop_episode(self, *, auto_stopped_by_safety: bool = False) -> dict[str, Any]:
        with self.lock:
            if not self.recording:
                raise RuntimeError("no episode is recording")
            episode_index = self.current_episode_index
            task = self.current_task
            started_at = self.current_started_at or now_iso()
            frame_count = self.current_frame_count
            self.recording = False
            self.state = "saving"
            self.message = "saving episode"

        save_start = time.perf_counter()
        saved = False
        error: str | None = None
        try:
            with self.dataset_lock:
                dataset = self.dataset
                if dataset is not None and dataset_has_pending_frames(dataset):
                    dataset.save_episode()
                    self._finalize_dataset()
                    saved = True
                else:
                    error = "empty episode buffer"
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            self.manifest.event("error", "save_episode_failed", error, episode_index=episode_index)

        save_duration = time.perf_counter() - save_start
        with self.lock:
            self.last_save_duration_s = round(save_duration, 3)
            if saved:
                self.last_saved_episode_index = episode_index
                contamination_reasons = set(self.current_contamination_reasons)
                if not self.settings.compat_mapping_verified:
                    contamination_reasons.add("compat_mapping_unverified")
                safety_metadata = (
                    self.settings.safety.to_metadata() if self.settings.safety is not None else {}
                )
                fps = self._episode_fps(frame_count)
                camera_labels = self._camera_health_labels()
                hard_gate_reasons = self._episode_dq_hard_gate_reasons(
                    frame_count=frame_count,
                    fps=fps,
                    cameras=camera_labels,
                    safety_metadata=safety_metadata,
                    contamination_reasons=contamination_reasons,
                )
                dq_reasons = set(contamination_reasons | self.current_dq_reasons | hard_gate_reasons)
                dq_status = "fail" if contamination_reasons or hard_gate_reasons else (
                    "warning" if self.current_dq_reasons else "pass"
                )
                timing_events = list(self.current_timing_events)
                timing_summary = summarize_timing_events(
                    timing_events,
                    target_fps=float(self.settings.dataset.fps),
                )
                timing_sidecar = write_timing_sidecar(
                    self.manifest.session_dir,
                    episode_index=episode_index,
                    events=timing_events,
                    summary=timing_summary,
                )
                record = EpisodeRecord(
                    episode_index=episode_index,
                    task=task,
                    accepted=False,
                    label="unlabeled",
                    notes="",
                    started_at=started_at,
                    ended_at=now_iso(),
                    frame_count=frame_count,
                    fps=fps,
                    save_duration_s=self.last_save_duration_s,
                    cameras=camera_labels,
                    **self._profile_episode_metadata(),
                    dataset_schema_version=self.settings.dataset.dataset_schema_version,
                    action_semantics=self.settings.dataset.action_semantics,
                    teleop_mode=self.settings.teleop_mode,
                    command_frame_version=self.settings.dataset.command_frame_version,
                    lerobot_revision=self.lerobot_revision,
                    compat_mapping_applied=self._compat_mapping_applied(),
                    compat_mapping_version=self.settings.compat_mapping_version,
                    compat_mapping_verified=self.settings.compat_mapping_verified,
                    contaminated=bool(contamination_reasons),
                    contamination_reasons=tuple(sorted(contamination_reasons)),
                    safety_config_version=str(safety_metadata.get("safety_config_version", "unconfigured")),
                    safety_config_verified=bool(safety_metadata.get("safety_config_verified", False)),
                    verified_by=str(safety_metadata.get("verified_by", "")),
                    verified_at=str(safety_metadata.get("verified_at", "")),
                    verification_basis=str(safety_metadata.get("verification_basis", "")),
                    safety_action_keys=list(safety_metadata.get("safety_action_keys", [])),
                    hard_limits=dict(safety_metadata.get("hard_limits", {})),
                    soft_limits=dict(safety_metadata.get("soft_limits", {})),
                    deadband=dict(safety_metadata.get("deadband", {})),
                    max_step=dict(safety_metadata.get("max_step", {})),
                    velocity_limit=dict(safety_metadata.get("velocity_limit", {})),
                    tracking_error_warning=dict(safety_metadata.get("tracking_error_warning", {})),
                    tracking_error_contamination=dict(
                        safety_metadata.get("tracking_error_contamination", {})
                    ),
                    tracking_error_freeze=dict(safety_metadata.get("tracking_error_freeze", {})),
                    driver_mismatch_atol=float(safety_metadata.get("driver_mismatch_atol", 0.0)),
                    mismatch_contamination_frames=int(
                        safety_metadata.get("mismatch_contamination_frames", 1)
                    ),
                    tracking_error_persistence_frames=int(
                        safety_metadata.get("tracking_error_persistence_frames", 1)
                    ),
                    command_validation=dict(self.current_command_validation),
                    tracking_validation=dict(self.current_tracking_validation),
                    ready_state=self.ready_state,
                    ready_result=dict(self.latest_ready_result or {}),
                    sync_valid_at_record_start=self.current_sync_valid_at_record_start,
                    sync_state_at_record_start=self.current_sync_state_at_record_start,
                    sync_result_at_record_start=dict(self.current_sync_result_at_record_start),
                    auto_stopped_by_safety=auto_stopped_by_safety,
                    auto_stop_save_status="saved" if auto_stopped_by_safety else "",
                    timing_summary=dict(timing_summary),
                    timing_sidecar=timing_sidecar.name,
                    dq_status=dq_status,
                    dq_reasons=tuple(sorted(dq_reasons)),
                )
                self.dataset_manifest.task_text = task
                self.dataset_manifest.append_episode(record)
                self.manifest.replace_episodes(self.dataset_manifest.read_episodes())
                self.state = "unlabeled"
                self.message = "episode saved; label required"
                self.manifest.event(
                    "info",
                    "episode_stop",
                    "Episode saved",
                    episode_index=episode_index,
                    frame_count=frame_count,
                    save_duration_s=self.last_save_duration_s,
                    auto_stopped_by_safety=auto_stopped_by_safety,
                )
            else:
                self.state = "idle"
                self.message = error or "empty episode skipped"
                with self.dataset_lock:
                    if self.dataset is not None:
                        self.dataset.clear_episode_buffer()
        if not saved:
            raise RuntimeError(error or "episode was not saved")
        return {
            "ok": True,
            "episode_index": episode_index,
            "frame_count": frame_count,
            "save_duration_s": self.last_save_duration_s,
        }

    def discard_episode(self) -> dict[str, Any]:
        with self.lock:
            if self.recording:
                episode_index = self.current_episode_index
                self.recording = False
                self.discard_requested = True
                with self.dataset_lock:
                    if self.dataset is not None:
                        self.dataset.clear_episode_buffer()
                self.state = "idle"
                self.message = "current episode discarded"
                self.manifest.event(
                    "info", "episode_discard", "Current episode discarded", episode_index=episode_index
                )
                return {"ok": True, "episode_index": episode_index}

            if self.last_saved_episode_index is None:
                raise RuntimeError("no saved episode to mark discard")
            record = self.dataset_manifest.update_label(
                self.last_saved_episode_index,
                label="discard",
                notes="discarded after save",
            )
            self.manifest.replace_episodes(self.dataset_manifest.read_episodes())
            self.state = "idle"
            self.message = "episode marked discard"
            return {"ok": True, "episode_index": record["episode_index"]}

    def label_episode(
        self,
        label: str,
        notes: str = "",
        episode_index: int | None = None,
    ) -> dict[str, Any]:
        if label not in {"success", "failure", "discard", "unlabeled"}:
            raise ValueError("label must be success, failure, discard, or unlabeled")
        with self.lock:
            if self.recording or self.state == "saving":
                raise RuntimeError("cannot label while recording or saving")
            target = self.last_saved_episode_index if episode_index is None else episode_index
            if target is None:
                raise RuntimeError("no saved episode to label")
            record = self.dataset_manifest.update_label(target, label=label, notes=notes)
            self.manifest.replace_episodes(self.dataset_manifest.read_episodes())
            self.state = "idle"
            self.message = f"episode {target} labeled {label}"
            self.manifest.event(
                "info",
                "episode_label",
                "Episode labeled",
                episode_index=target,
                label=label,
                accepted=record["accepted"],
                acceptance_reasons=record.get("acceptance_reasons", []),
            )
            return {"ok": True, "episode_index": target, "record": record}

    def reset_realsense(self) -> dict[str, Any]:
        with self.lock:
            if self.recording:
                raise RuntimeError("cannot reset RealSense while recording")
            if "realsense" not in self.settings.cameras:
                raise RuntimeError("RealSense camera is not configured")
            serial = self.settings.cameras["realsense"]["serial_number_or_name"]
            self.state = "resetting_realsense"
            self.message = "disconnecting devices for RealSense reset"
            self._disconnect_devices()
            self._finalize_dataset()
        result = reset_realsense(serial)
        with self.lock:
            self.message = "reconnecting devices"
            self._connect_devices()
            self.state = "idle"
            self.message = "RealSense reset complete" if result.get("ok") else "RealSense reset failed"
            self.manifest.event(
                "info" if result.get("ok") else "error", "realsense_reset", self.message, **result
            )
        return result

    def get_status(self) -> dict[str, Any]:
        with self.lock:
            cameras = {}
            now = time.time()
            for name, item in self.frame_cache.items():
                timestamp = item.get("timestamp")
                age_ms = None if timestamp is None else int((now - timestamp) * 1000)
                ok = bool(timestamp is not None and (now - timestamp) <= self.camera_timeout_s)
                cameras[name] = {
                    "ok": ok,
                    "fps": round(float(item.get("fps") or 0.0), 2),
                    "frames": int(item.get("frames") or 0),
                    "last_frame_age_ms": age_ms,
                    "last_error": item.get("last_error"),
                }
            return {
                "ok": True,
                "session_id": self.session_id,
                "message": self.message,
                "robot": {
                    "connected": bool(self.robot is not None and self.robot.is_connected),
                    "id": self.settings.robot["id"],
                },
                "teleop": {
                    "connected": bool(self.teleop is not None and self.teleop.is_connected),
                    "id": self.settings.teleop["id"],
                },
                "dataset": {
                    "repo_id": self.settings.dataset.repo_id,
                    "root": str(self.settings.dataset.root),
                    "fps": self.settings.dataset.fps,
                    "streaming_encoding": self.settings.dataset.streaming_encoding,
                    "vcodec": self.settings.dataset.vcodec,
                    "dataset_schema_version": self.settings.dataset.dataset_schema_version,
                    "action_semantics": self.settings.dataset.action_semantics,
                    "teleop_mode": self.settings.teleop_mode,
                    "command_frame_version": self.settings.dataset.command_frame_version,
                    "lerobot_revision": self.lerobot_revision,
                    "compat_mapping_applied": self._compat_mapping_applied(),
                    "compat_mapping_version": self.settings.compat_mapping_version,
                    "compat_mapping_verified": self.settings.compat_mapping_verified,
                },
                "episode": {
                    "state": self.state,
                    "episode_index": self.current_episode_index,
                    "task": self.current_task,
                    "frame_count": self.current_frame_count,
                    "started_at": self.current_started_at,
                    "last_saved_episode_index": self.last_saved_episode_index,
                    "save_duration_s": self.last_save_duration_s,
                    "auto_stopped_by_safety": self.auto_stopped_by_safety,
                    "auto_stop_save_status": self.auto_stop_save_status,
                },
                "cameras": cameras,
                "control": {
                    "default_task": str(self.settings.control.get("default_task", "")),
                    "task_profile_name": self.settings.control.get("task_profile_name"),
                    "task_profile_path": self.settings.control.get("task_profile_path"),
                    "task_profile_sop": self.settings.control.get("task_profile_sop"),
                    "teleop_when_idle": self.teleop_when_idle,
                    "dry_teleop_enabled": self.dry_teleop_enabled,
                    "has_realsense": "realsense" in self.settings.cameras,
                    "safety_frozen": self.safety_frozen,
                    "freeze_reason": self.freeze_reason,
                    "freeze_message": self.freeze_message,
                },
                "ready": {
                    "state": self.ready_state,
                    "required_for_recording": self._ready_required_for_recording(),
                    "latest_result": self.latest_ready_result,
                },
                "sync": {
                    "state": self.sync_state,
                    "required_for_recording": self._sync_required_for_recording(),
                    "latest_result": self.latest_sync_result,
                    "latest_relative_result": self.latest_relative_result,
                },
            }

    def move_to_ready(self, *, sleep=precise_sleep) -> dict[str, Any]:
        with self.lock:
            if self.recording:
                raise RuntimeError("cannot Move to Ready while recording")
            if self.robot is None:
                raise RuntimeError("robot is not connected")
            robot = self.robot
            self._invalidate_sync("Move to Ready requested")
            self.ready_state = "moving"
            self.latest_ready_result = None
            self.state = "moving_ready"
            self.message = "moving to ready"
        try:
            with self.device_io_lock:
                result = ReadyController(self._ready_settings()).move_to_ready(robot, sleep=sleep)
        except Exception as exc:
            with self.lock:
                self.ready_state = "failed"
                self.state = "idle"
                self.message = f"Move to Ready failed: {type(exc).__name__}: {exc}"
                self.latest_ready_result = {
                    "ok": False,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
                self.manifest.event("error", "move_to_ready_failed", self.message)
            raise
        payload = result.to_dict()
        with self.lock:
            self.latest_ready_result = payload
            self.ready_state = "verified" if result.ok else "failed"
            self.state = "idle"
            self.message = "ready verified" if result.ok else "ready verification failed"
            self.last_effective_command = dict(result.final_target) if result.final_target else None
            self.last_effective_time_ns = time.monotonic_ns() if result.final_target else None
            self.manifest.event(
                "info" if result.ok else "warning",
                "move_to_ready",
                self.message,
                **payload,
            )
        return {"ok": result.ok, "ready": payload}

    def sync_master(self, arm: str = "both") -> dict[str, Any]:
        arm = self._normalize_sync_arm(arm)
        with self.lock:
            if self.recording:
                reason = "relative_resync_during_recording"
                self.current_contamination_reasons.add(reason)
                self.current_dq_reasons.add(reason)
                self.manifest.event(
                    "warning",
                    "episode_contaminated",
                    "Sync Master requested while recording; active episode contaminated",
                    episode_index=self.current_episode_index,
                    reason=reason,
                )
                raise RuntimeError("cannot Sync Master while recording")
            if self.robot is None:
                raise RuntimeError("robot is not connected")
            if self.teleop is None:
                raise RuntimeError("teleop is not connected")
            robot = self.robot
            teleop = self.teleop
            robot_observation_processor = self.robot_observation_processor
            teleop_action_processor = self.teleop_action_processor
            robot_action_processor = self.robot_action_processor

        if not robot.is_connected or not teleop.is_connected:
            raise RuntimeError("robot and teleop must be connected before Sync Master")

        sample_count = max(1, int(self.settings.sync.get("samples", 1)))
        sample_interval_s = max(0.0, float(self.settings.sync.get("sample_interval_s", 0.0)))
        obs_samples: list[dict[str, Any]] = []
        target_samples: list[dict[str, Any]] = []
        for sample_index in range(sample_count):
            with self.device_io_lock:
                obs = robot.get_observation()
                act = teleop.get_action()
            obs_processed = robot_observation_processor(obs)
            act_compat = self.compat_mapper.map_action(act)
            act_processed_teleop = teleop_action_processor((act_compat, obs))
            follower_target = robot_action_processor((act_processed_teleop, obs))
            obs_samples.append(dict(obs_processed))
            target_samples.append(dict(follower_target))
            if sample_index < sample_count - 1 and sample_interval_s > 0:
                precise_sleep(sample_interval_s)
        keys = sorted(
            key
            for key in target_samples[0]
            if self._sync_key_matches_arm(key, arm)
            and all(
                key in obs_sample
                and key in target_sample
                and self._is_number(obs_sample[key])
                and self._is_number(target_sample[key])
                for obs_sample, target_sample in zip(obs_samples, target_samples)
            )
        )
        if not keys:
            raise RuntimeError(f"Sync Master found no shared numeric {arm} follower-space action keys")
        follower_start = {
            key: float(np.median([float(sample[key]) for sample in obs_samples])) for key in keys
        }
        follower_target_start = {
            key: float(np.median([float(sample[key]) for sample in target_samples])) for key in keys
        }
        offsets = {key: follower_start[key] - follower_target_start[key] for key in keys}
        synced_arms = self._arms_for_keys(keys)
        required_arms = self._required_sync_arms()
        payload = {
            "ok": True,
            "state": "valid",
            "teleop_mode": self.settings.teleop_mode,
            "arm": arm,
            "sample_count": sample_count,
            "synced_at": now_iso(),
            "keys": keys,
            "offsets": offsets,
            "follower_start": follower_start,
            "follower_target_start": follower_target_start,
            "max_abs_offset": max(abs(value) for value in offsets.values()),
        }
        with self.lock:
            merged_offsets = dict(self.sync_offsets or {})
            merged_offsets.update(offsets)
            calibration = {
                "follower_start": dict((self.sync_calibration or {}).get("follower_start", {})),
                "follower_target_start": dict(
                    (self.sync_calibration or {}).get("follower_target_start", {})
                ),
            }
            calibration["follower_start"].update(follower_start)
            calibration["follower_target_start"].update(follower_target_start)
            if arm == "both":
                self.sync_arms = synced_arms
            else:
                self.sync_arms.update(synced_arms)
            state = "valid" if required_arms.issubset(self.sync_arms) else "partial"
            payload["state"] = state
            payload["synced_arms"] = sorted(self.sync_arms)
            payload["required_arms"] = sorted(required_arms)
            self.sync_state = state
            self.latest_sync_result = payload
            self.sync_offsets = merged_offsets
            self.sync_calibration = calibration
            self.manifest.event("info", "sync_master", "Sync Master verified", **payload)
        return {"ok": True, "sync": payload}

    def enable_teleop(self) -> dict[str, Any]:
        with self.lock:
            if self.recording:
                raise RuntimeError("cannot Enable Teleop while recording")
            if self.safety_frozen:
                raise RuntimeError(
                    "safety is frozen after follower tracking error; reconnect devices before teleop"
                )
            if self._ready_required_for_recording() and self.ready_state != "verified":
                raise RuntimeError("Move to Ready must be verified before Enable Teleop")
            if self._sync_required_for_recording() and self.sync_state != "valid":
                raise RuntimeError("Sync Master must be valid before Enable Teleop")
            self.dry_teleop_enabled = True
            self.state = "idle"
            self.message = "dry teleop enabled"
            self.manifest.event("info", "dry_teleop_enabled", "Dry teleop enabled")
            return {"ok": True, "teleop": {"enabled": True, "mode": "dry"}}

    def disable_teleop(self) -> dict[str, Any]:
        with self.lock:
            self.dry_teleop_enabled = False
            self.message = "dry teleop disabled"
            self.manifest.event("info", "dry_teleop_disabled", "Dry teleop disabled")
            return {"ok": True, "teleop": {"enabled": False, "mode": "dry"}}

    def dataset_status(
        self,
        *,
        root: str | Path | None = None,
        repo_id: str | None = None,
        session_root: str | Path | None = None,
    ) -> dict[str, Any]:
        candidate_root = Path(root).expanduser() if root is not None else self.settings.dataset.root
        candidate_repo_id = repo_id or self.settings.dataset.repo_id
        candidate_session_root = (
            Path(session_root).expanduser() if session_root is not None else self.settings.session_root
        )
        manifest = self._dataset_manifest_for(root=candidate_root, repo_id=candidate_repo_id)
        status: dict[str, Any] = {
            "root": str(candidate_root),
            "repo_id": candidate_repo_id,
            "session_root": str(candidate_session_root),
            "root_state": "unknown",
            "can_create": False,
            "can_append": False,
            "episode_count": 0,
            "reason": "",
            "semantics": self._dataset_semantic_summary(),
        }
        if not candidate_root.exists():
            status.update({"root_state": "root_missing", "can_create": True})
            return status
        if not candidate_root.is_dir():
            status.update({"root_state": "invalid_dataset_root", "reason": "root is not a directory"})
            return status
        if not any(candidate_root.iterdir()):
            status.update({"root_state": "empty_root", "can_create": True})
            return status
        try:
            state = manifest.validate_for_collection()
            existing = manifest._read_dataset_manifest()
            if existing is not None and existing.get("repo_id") != candidate_repo_id:
                status.update(
                    {
                        "root_state": "semantic_mismatch",
                        "reason": (
                            f"repo_id semantic mismatch: expected {candidate_repo_id!r}, "
                            f"got {existing.get('repo_id')!r}"
                        ),
                    }
                )
                return status
            status.update(
                {
                    "root_state": "appendable" if state == "existing" else "root_missing",
                    "can_append": state == "existing",
                    "can_create": state == "new",
                    "episode_count": len(manifest.read_episodes()),
                }
            )
        except DatasetSchemaError as exc:
            message = str(exc)
            root_state = "semantic_mismatch" if "semantic mismatch" in message else "legacy_unknown"
            status.update({"root_state": root_state, "reason": message})
        return status

    def new_dataset(self, name: str | None = None) -> dict[str, Any]:
        with self.lock:
            self._assert_dataset_switch_allowed()
            safe_name = self._safe_dataset_name(name or time.strftime("dataset_%Y%m%d_%H%M%S"))
            base = self.settings.dataset.root.parent
            root = base / safe_name
            suffix = 1
            while root.exists():
                root = base / f"{safe_name}_{suffix}"
                suffix += 1
            repo_id = f"local/{root.name}"
            session_root = self.settings.session_root.parent / f"{root.name}_sessions"
            self._finalize_dataset()
            self._apply_dataset_settings(root=root, repo_id=repo_id, session_root=session_root)
            return {"ok": True, "dataset": self.dataset_status()}

    def switch_dataset(
        self,
        *,
        root: str,
        repo_id: str,
        session_root: str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            self._assert_dataset_switch_allowed()
            candidate_root = Path(root).expanduser()
            candidate_repo_id = str(repo_id).strip()
            if not candidate_repo_id:
                raise ValueError("repo_id is required")
            candidate_session_root = (
                Path(session_root).expanduser() if session_root else self.settings.session_root
            )
            status = self.dataset_status(
                root=candidate_root,
                repo_id=candidate_repo_id,
                session_root=candidate_session_root,
            )
            if status["root_state"] in {"invalid_dataset_root", "legacy_unknown", "semantic_mismatch"}:
                raise DatasetSchemaError(status["reason"] or f"dataset root is {status['root_state']}")
            self._finalize_dataset()
            self._apply_dataset_settings(
                root=candidate_root,
                repo_id=candidate_repo_id,
                session_root=candidate_session_root,
            )
            return {"ok": True, "dataset": self.dataset_status()}

    def export_training_dry_run(
        self,
        *,
        source_root: str,
        source_repo_id: str,
        output_root: str,
        output_repo_id: str,
        config_file: str | None = None,
    ) -> dict[str, Any]:
        self._assert_export_allowed()
        return export_training_package(
            source_root=Path(source_root).expanduser(),
            source_repo_id=str(source_repo_id),
            output_root=Path(output_root).expanduser(),
            output_repo_id=str(output_repo_id),
            dry_run=True,
            config_file=Path(config_file).expanduser() if config_file else None,
        )

    def start_training_export(
        self,
        *,
        source_root: str,
        source_repo_id: str,
        output_root: str,
        output_repo_id: str,
        config_file: str | None = None,
    ) -> dict[str, Any]:
        self._assert_export_allowed()
        with self.lock:
            if self.training_export_job.get("status") == "running":
                raise RuntimeError("training export already running")
            job_id = uuid.uuid4().hex
            self.training_export_job = {
                "ok": True,
                "job_id": job_id,
                "status": "running",
                "source_root": str(source_root),
                "output_root": str(output_root),
                "started_at": now_iso(),
                "finished_at": "",
                "result": None,
                "error": "",
            }
        args = {
            "source_root": Path(source_root).expanduser(),
            "source_repo_id": str(source_repo_id),
            "output_root": Path(output_root).expanduser(),
            "output_repo_id": str(output_repo_id),
            "config_file": Path(config_file).expanduser() if config_file else None,
        }
        self.export_thread = threading.Thread(
            target=self._run_training_export_job,
            args=(job_id, args),
            daemon=True,
        )
        self.export_thread.start()
        return self.training_export_status()

    def training_export_status(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.training_export_job)

    def _run_training_export_job(self, job_id: str, args: dict[str, Any]) -> None:
        try:
            result = export_training_package(**args)
            with self.lock:
                if self.training_export_job.get("job_id") == job_id:
                    self.training_export_job.update(
                        {
                            "ok": True,
                            "status": "succeeded",
                            "finished_at": now_iso(),
                            "result": result,
                            "error": "",
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            logger.exception("training export failed")
            with self.lock:
                if self.training_export_job.get("job_id") == job_id:
                    self.training_export_job.update(
                        {
                            "ok": False,
                            "status": "failed",
                            "finished_at": now_iso(),
                            "result": None,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

    def _assert_export_allowed(self) -> None:
        with self.lock:
            if self.recording or self.state == "saving":
                raise RuntimeError("training export is disabled while recording or saving")
            if self.safety_frozen:
                raise RuntimeError("training export is disabled while safety is frozen")

    def latest_jpeg(self, camera: str) -> bytes | None:
        with self.lock:
            item = self.frame_cache.get(camera)
            if not item:
                return None
            return item.get("jpeg")

    def _connect_devices(self) -> None:
        attempts = max(1, self.connect_retries)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                self._disconnect_devices()
                self._connect_devices_once()
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                self.manifest.event(
                    "warning" if attempt < attempts else "error",
                    "devices_connect_failed",
                    f"{type(exc).__name__}: {exc}",
                    attempt=attempt,
                    attempts=attempts,
                )
                self._disconnect_devices()
                if attempt < attempts:
                    with self.lock:
                        self.message = f"connect failed; retrying {attempt}/{attempts}"
                    time.sleep(self.connect_retry_delay_s)
        assert last_error is not None
        raise last_error

    def _connect_devices_once(self) -> None:
        cameras = {name: _make_camera_config(cfg) for name, cfg in self.settings.cameras.items()}
        robot_type = str(self.settings.robot.get("type", "bi_openarm_follower"))
        teleop_type = str(self.settings.teleop.get("type", "openarm_mini"))
        if robot_type == "bi_so_follower":
            robot_cfg, camera_aliases = self._make_bi_so_robot_configuration(cameras)
        elif robot_type == "bi_openarm_follower":
            robot_cfg, camera_aliases = make_bi_openarm_configuration(
                BiOpenArmFollowerConfig,
                OpenArmFollowerConfigBase,
                robot_id=self.settings.robot["id"],
                left_arm={
                    "port": self.settings.robot["left_arm"]["port"],
                    "side": self.settings.robot["left_arm"].get("side"),
                },
                right_arm={
                    "port": self.settings.robot["right_arm"]["port"],
                    "side": self.settings.robot["right_arm"].get("side"),
                },
                cameras=cameras,
            )
        else:
            raise ValueError(f"Unsupported robot type: {robot_type}")

        if teleop_type == "bi_so_leader":
            teleop_cfg = self._make_bi_so_teleop_configuration()
        elif teleop_type == "openarm_mini":
            if OpenArmMiniConfig is None:
                raise RuntimeError("installed LeRobot does not provide OpenArmMiniConfig")
            teleop_cfg = OpenArmMiniConfig(
                id=self.settings.teleop["id"],
                port_right=self.settings.teleop["port_right"],
                port_left=self.settings.teleop["port_left"],
            )
        else:
            raise ValueError(f"Unsupported teleop type: {teleop_type}")

        self.robot = adapt_bi_openarm_camera_keys(make_robot_from_config(robot_cfg), camera_aliases)
        self.teleop = make_teleoperator_from_config(teleop_cfg)
        self.teleop_action_processor, self.robot_action_processor, self.robot_observation_processor = (
            make_default_processors()
        )

        self.message = "connecting robot"
        self._assert_existing_calibration_cache()
        with _press_enter_for_existing_calibration():
            self.robot.connect()
        self.message = "connecting teleop"
        with _press_enter_for_existing_calibration():
            self.teleop.connect()
        self.safety_frozen = False
        self.freeze_reason = ""
        self.freeze_message = ""
        self.auto_stopped_by_safety = False
        self.auto_stop_save_status = ""
        self.last_effective_command = None
        self.last_effective_time_ns = None
        self.state = "idle"
        self.message = "ready"
        self.manifest.event("info", "devices_connected", "Robot, teleop, and cameras connected")

    def _make_bi_so_robot_configuration(self, cameras: Mapping[str, Any]) -> tuple[Any, dict[str, str]]:
        from lerobot.robots.bi_so_follower.config_bi_so_follower import BiSOFollowerConfig
        from lerobot.robots.so_follower.config_so_follower import SOFollowerConfig

        left_cameras = {name: cfg for name, cfg in cameras.items() if name != "wrist_right"}
        right_cameras = {name: cfg for name, cfg in cameras.items() if name == "wrist_right"}
        common = {
            "disable_torque_on_disconnect": bool(
                self.settings.robot.get("disable_torque_on_disconnect", True)
            ),
            "max_relative_target": self.settings.robot.get("max_relative_target"),
            "use_degrees": bool(self.settings.robot.get("use_degrees", False)),
        }
        robot_cfg = BiSOFollowerConfig(
            id=self.settings.robot.get("id"),
            left_arm_config=SOFollowerConfig(
                port=self.settings.robot["left_arm"]["port"],
                cameras=left_cameras,
                **common,
            ),
            right_arm_config=SOFollowerConfig(
                port=self.settings.robot["right_arm"]["port"],
                cameras=right_cameras,
                **common,
            ),
        )
        aliases = {
            **{f"left_{name}": name for name in left_cameras},
            **{f"right_{name}": name for name in right_cameras},
        }
        return robot_cfg, aliases

    def _make_bi_so_teleop_configuration(self) -> Any:
        from lerobot.teleoperators.bi_so_leader.config_bi_so_leader import BiSOLeaderConfig
        from lerobot.teleoperators.so_leader.config_so_leader import SOLeaderConfig

        return BiSOLeaderConfig(
            id=self.settings.teleop.get("id"),
            left_arm_config=SOLeaderConfig(
                port=self.settings.teleop["left_arm"]["port"],
                use_degrees=bool(self.settings.teleop.get("use_degrees", False)),
            ),
            right_arm_config=SOLeaderConfig(
                port=self.settings.teleop["right_arm"]["port"],
                use_degrees=bool(self.settings.teleop.get("use_degrees", False)),
            ),
        )

    def _assert_existing_calibration_cache(self) -> None:
        missing: list[str] = []
        for name in ("left_arm", "right_arm"):
            arm = getattr(self.robot, name, None)
            if arm is not None and not getattr(arm, "calibration", None):
                missing.append(f"robot.{name}")
        if self.teleop is not None:
            teleop_arms = [
                (name, getattr(self.teleop, name, None)) for name in ("left_arm", "right_arm")
            ]
            if any(arm is not None for _, arm in teleop_arms):
                for name, arm in teleop_arms:
                    if arm is not None and not getattr(arm, "calibration", None):
                        missing.append(f"teleop.{name}")
            elif hasattr(self.teleop, "calibration") and not getattr(self.teleop, "calibration", None):
                missing.append("teleop")
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(
                f"Missing calibration cache for {joined}. Run lerobot-calibrate manually before starting the workbench."
            )

    def _disconnect_devices(self) -> None:
        self.last_effective_command = None
        self.last_effective_time_ns = None
        self.dry_teleop_enabled = False
        self._invalidate_ready("devices disconnected")
        self._invalidate_sync("devices disconnected")
        try:
            if self.teleop is not None:
                self.teleop.disconnect()
        except Exception as exc:  # noqa: BLE001
            self.manifest.event("warning", "teleop_disconnect_failed", str(exc))
        try:
            if self.robot is not None:
                self.robot.disconnect()
        except Exception as exc:  # noqa: BLE001
            self.manifest.event("warning", "robot_disconnect_failed", str(exc))
        self._force_release_partial_robot()
        self.robot = None
        self.teleop = None

    def _force_release_partial_robot(self) -> None:
        if self.robot is None:
            return
        for arm_name in ("left_arm", "right_arm"):
            arm = getattr(self.robot, arm_name, None)
            if arm is None:
                continue
            for camera_name, camera in getattr(arm, "cameras", {}).items():
                try:
                    has_capture = getattr(camera, "videocapture", None) is not None
                    has_thread = getattr(camera, "thread", None) is not None
                    if camera.is_connected or has_capture or has_thread:
                        camera.disconnect()
                except Exception as exc:  # noqa: BLE001
                    self.manifest.event(
                        "warning", "camera_force_release_failed", str(exc), camera=camera_name
                    )
            bus = getattr(arm, "bus", None)
            if bus is None:
                continue
            try:
                if getattr(bus, "is_connected", False):
                    bus.disconnect(disable_torque=True)
            except Exception as exc:  # noqa: BLE001
                self.manifest.event("warning", "bus_disconnect_failed", str(exc), arm=arm_name)
            canbus = getattr(bus, "canbus", None)
            if canbus is not None:
                try:
                    canbus.shutdown()
                except Exception as exc:  # noqa: BLE001
                    self.manifest.event("warning", "canbus_shutdown_failed", str(exc), arm=arm_name)
                try:
                    bus.canbus = None
                    bus._is_connected = False
                except Exception:
                    pass

    def _ensure_dataset(self) -> None:
        if self.dataset is not None:
            return
        assert self.robot is not None
        settings = self.settings.dataset
        settings.root.parent.mkdir(parents=True, exist_ok=True)
        self.dataset_manifest.validate_for_collection()

        dataset_features = combine_feature_dicts(
            aggregate_pipeline_dataset_features(
                pipeline=self.robot_action_processor,
                initial_features=create_initial_features(action=self.robot.action_features),
                use_videos=True,
            ),
            aggregate_pipeline_dataset_features(
                pipeline=self.robot_observation_processor,
                initial_features=create_initial_features(observation=self.robot.observation_features),
                use_videos=True,
            ),
        )
        num_cameras = len(getattr(self.robot, "cameras", {}))
        should_resume = self._prepare_dataset_root_for_recording(Path(settings.root))
        kwargs = dict(
            batch_encoding_size=settings.video_encoding_batch_size,
            vcodec=settings.vcodec,
            streaming_encoding=settings.streaming_encoding,
            encoder_queue_maxsize=settings.encoder_queue_maxsize,
            encoder_threads=settings.encoder_threads,
        )
        if should_resume:
            self.dataset = resume_lerobot_dataset(
                settings.repo_id,
                root=settings.root,
                image_writer_processes=settings.num_image_writer_processes if num_cameras else 0,
                image_writer_threads=settings.num_image_writer_threads_per_camera * num_cameras
                if num_cameras
                else 0,
                **kwargs,
            )
        else:
            self.dataset = LeRobotDataset.create(
                settings.repo_id,
                settings.fps,
                root=settings.root,
                robot_type=self.robot.name,
                features=dataset_features,
                use_videos=True,
                image_writer_processes=settings.num_image_writer_processes,
                image_writer_threads=settings.num_image_writer_threads_per_camera * num_cameras,
                **kwargs,
            )
        self.dataset_manifest.ensure_initialized(new_dataset_created=not should_resume)
        self.video_manager = VideoEncodingManager(self.dataset)
        self.video_manager.__enter__()

    def _is_resumable_dataset_root(self, root: Path) -> bool:
        return all(
            path.exists()
            for path in (
                root / "meta" / "info.json",
                root / "meta" / "tasks.parquet",
                root / "meta" / "stats.json",
            )
        ) and any((root / "data").glob("**/*.parquet"))

    def _prepare_dataset_root_for_recording(self, root: Path) -> bool:
        if root.exists() and root.is_dir() and not any(root.iterdir()):
            root.rmdir()
            return False
        info_json = root / "meta" / "info.json"
        if not info_json.exists():
            return False
        if self._is_resumable_dataset_root(root):
            return True

        archive = root.with_name(f"{root.name}_incomplete_{time.strftime('%Y%m%d_%H%M%S')}")
        suffix = 1
        while archive.exists():
            archive = root.with_name(f"{root.name}_incomplete_{time.strftime('%Y%m%d_%H%M%S')}_{suffix}")
            suffix += 1
        root.rename(archive)
        self.manifest.event(
            "warning",
            "dataset_root_archived",
            "Incomplete dataset root archived before recording",
            root=str(root),
            archive=str(archive),
        )
        return False

    def _dataset_manifest_for(self, *, root: Path, repo_id: str) -> CanonicalDatasetManifest:
        return CanonicalDatasetManifest(
            dataset_root=root,
            dataset_name=root.name,
            repo_id=repo_id,
            task_text=self.current_task or str(self.settings.control.get("default_task", "")),
            session_id=self.session_id,
            dataset_schema_version=self.settings.dataset.dataset_schema_version,
            action_semantics=self.settings.dataset.action_semantics,
            teleop_mode=self.settings.teleop_mode,
            command_frame_version=self.settings.dataset.command_frame_version,
            lerobot_revision=self.lerobot_revision,
            compat_mapping_applied=self._compat_mapping_applied(),
            compat_mapping_version=self.settings.compat_mapping_version,
            compat_mapping_verified=self.settings.compat_mapping_verified,
            safety_metadata=(self.settings.safety.to_metadata() if self.settings.safety is not None else None),
            profile_metadata=self._profile_episode_metadata(),
        )

    def _dataset_semantic_summary(self) -> dict[str, Any]:
        safety_metadata = self.settings.safety.to_metadata() if self.settings.safety is not None else {}
        summary = {
            "dataset_schema_version": self.settings.dataset.dataset_schema_version,
            "action_semantics": self.settings.dataset.action_semantics,
            "teleop_mode": self.settings.teleop_mode,
            "command_frame_version": self.settings.dataset.command_frame_version,
            "compat_mapping_version": self.settings.compat_mapping_version,
            "compat_mapping_verified": self.settings.compat_mapping_verified,
            "safety_config_version": safety_metadata.get("safety_config_version"),
            "safety_config_verified": safety_metadata.get("safety_config_verified"),
        }
        summary.update(self._profile_episode_metadata())
        return summary

    def _compat_mapping_applied(self) -> bool:
        if is_xlerobot_so101_schema(self.settings.dataset.dataset_schema_version):
            return True
        return bool(self.settings.apply_openarm_mini_compat_mapping or self.native_compat_mapping)

    def _profile_episode_metadata(self) -> dict[str, Any]:
        if is_xlerobot_so101_schema(self.settings.dataset.dataset_schema_version):
            return xlerobot_so101_profile_metadata(self.settings)
        return {}

    def _ready_required_for_recording(self) -> bool:
        return bool(self.settings.ready.get("require_ready_for_recording", False))

    def _sync_required_for_recording(self) -> bool:
        return bool(self.settings.sync.get("require_sync_for_recording", False))

    def _ready_settings(self) -> ReadySettings:
        path = Path(self.settings.ready.get("path", "config/ready_path.json")).expanduser()
        if not path.is_absolute():
            path = self.settings.workspace_root / path
        return ReadySettings(
            path=path,
            fps=int(self.settings.ready.get("fps", self.settings.dataset.fps)),
            tolerance=float(self.settings.ready.get("tolerance", 2.0)),
            settle_time_s=float(self.settings.ready.get("settle_time_s", 0.2)),
            verify_after_move=bool(self.settings.ready.get("verify_after_move", True)),
        )

    def _invalidate_ready(self, reason: str) -> None:
        if self.ready_state != "invalid":
            self.manifest.event("info", "ready_invalidated", reason)
        self.ready_state = "invalid"
        self.latest_ready_result = None
        self.dry_teleop_enabled = False

    def _invalidate_sync(self, reason: str) -> None:
        if self.sync_state != "invalid":
            self.manifest.event("info", "sync_invalidated", reason)
        self.sync_state = "invalid"
        self.latest_sync_result = None
        self.sync_offsets = None
        self.sync_arms = set()
        self.sync_calibration = None
        self.latest_relative_result = None
        self.dry_teleop_enabled = False

    def _assert_dataset_switch_allowed(self) -> None:
        if self.safety_frozen:
            raise RuntimeError("cannot change dataset while safety is frozen")
        if self.recording:
            raise RuntimeError("cannot change dataset while recording")
        if self.state not in {"idle", "error", "unlabeled", "frozen"}:
            raise RuntimeError(f"cannot change dataset while state={self.state}")

    @staticmethod
    def _safe_dataset_name(name: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in name.strip())
        safe = safe.strip("._-")
        if not safe:
            raise ValueError("dataset name must contain letters or numbers")
        return safe

    def _apply_dataset_settings(self, *, root: Path, repo_id: str, session_root: Path) -> None:
        dataset = replace(self.settings.dataset, root=root, repo_id=repo_id)
        self.settings = replace(self.settings, dataset=dataset, session_root=session_root)
        self.session_dir = self.settings.session_root / self.session_id
        self.manifest = EpisodeManifest(self.session_dir)
        self.dataset_manifest = self._dataset_manifest_for(root=root, repo_id=repo_id)
        self._invalidate_ready("dataset switched")
        self._invalidate_sync("dataset switched")

    def _finalize_dataset(self) -> None:
        if self.video_manager is not None:
            try:
                with self.dataset_lock:
                    self.video_manager.__exit__(None, None, None)
            finally:
                self.video_manager = None
        if self.dataset is not None:
            with self.dataset_lock:
                self.dataset.finalize()
            self.dataset = None

    def _control_loop(self) -> None:
        fps = self.settings.dataset.fps
        interval = 1 / fps
        last_tick = time.perf_counter()
        while not self.stop_event.is_set():
            start = time.perf_counter()
            try:
                self._control_step()
            except Exception as exc:  # noqa: BLE001
                logger.exception("control loop failed")
                message = f"{type(exc).__name__}: {exc}"
                with self.lock:
                    is_recording = self.recording
                    self.message = message
                    self.state = "error" if not is_recording else "recording"
                    self.manifest.event("error", "control_loop_error", message)
                if is_recording:
                    self._abort_recording_after_error(message)
                    if self._is_camera_failure_message(message):
                        self._reconnect_devices_after_error(message)
                elif self._should_reconnect_after_error(exc, is_recording):
                    self._reconnect_devices_after_error(message)
                time.sleep(0.5)

            elapsed = time.perf_counter() - start
            if elapsed > 0:
                measured_fps = 1 / max(time.perf_counter() - last_tick, 1e-6)
                with self.lock:
                    for item in self.frame_cache.values():
                        if item.get("timestamp") is not None:
                            item["fps"] = 0.9 * float(item.get("fps") or measured_fps) + 0.1 * measured_fps
                last_tick = time.perf_counter()
            precise_sleep(max(interval - elapsed, 0.0))

    def _should_reconnect_after_error(self, exc: Exception, is_recording: bool) -> bool:
        if is_recording or not self.auto_reconnect_when_idle:
            return False
        message = f"{type(exc).__name__}: {exc}"
        if not self._is_camera_failure_message(message):
            return False
        now = time.monotonic()
        if now - self.last_reconnect_attempt < self.reconnect_cooldown_s:
            return False
        self.last_reconnect_attempt = now
        return True

    def _is_camera_failure_message(self, message: str) -> bool:
        return "OpenCVCamera" in message and (
            "read thread is not running" in message
            or "has not captured any frames" in message
            or "latest frame is too old" in message
            or "read failed" in message
            or "No such device" in message
        )

    def _abort_recording_after_error(self, message: str) -> None:
        with self.lock:
            if not self.recording:
                return
            episode_index = self.current_episode_index
            self.recording = False
            self.discard_requested = True
            self.state = "error"
            self.message = f"recording aborted: {message}"

        with self.dataset_lock:
            if self.dataset is not None:
                try:
                    self.dataset.clear_episode_buffer()
                except Exception as exc:  # noqa: BLE001
                    self.manifest.event(
                        "warning",
                        "clear_episode_buffer_failed",
                        f"{type(exc).__name__}: {exc}",
                        episode_index=episode_index,
                    )

        self.manifest.event(
            "error",
            "episode_abort",
            "Recording aborted and current episode buffer cleared",
            episode_index=episode_index,
            reason=message,
        )

    def _reconnect_devices_after_error(self, reason: str) -> None:
        with self.lock:
            if self.recording:
                return
            self.state = "reconnecting"
            self.message = "camera error; reconnecting devices"
        self.manifest.event("warning", "devices_reconnect_start", reason)
        try:
            self._finalize_dataset()
            self._connect_devices()
            self.manifest.event("info", "devices_reconnect_done", "Devices reconnected")
        except Exception as exc:  # noqa: BLE001
            message = f"{type(exc).__name__}: {exc}"
            logger.exception("device reconnect failed")
            with self.lock:
                self.state = "error"
                self.message = message
            self.manifest.event("error", "devices_reconnect_failed", message)

    def _control_step(self) -> None:
        with self.lock:
            robot = self.robot
            teleop = self.teleop
            is_recording = self.recording
            can_teleop = (
                is_recording or self.dry_teleop_enabled or self.teleop_when_idle
            ) and not self.safety_frozen
            dataset = self.dataset
            task = self.current_task

        if robot is None or teleop is None or not robot.is_connected or not teleop.is_connected:
            time.sleep(0.1)
            return

        control_step_start_time_ns = time.monotonic_ns()
        with self.device_io_lock:
            obs = robot.get_observation()
            follower_obs_time_ns = time.monotonic_ns()
            obs_processed = self.robot_observation_processor(obs)
            self._update_preview_frames(obs_processed)

            if not can_teleop:
                return

            act = teleop.get_action()
            master_read_time_ns = time.monotonic_ns()
            act_compat = self.compat_mapper.map_action(act)
            act_processed_teleop = self.teleop_action_processor((act_compat, obs))
            robot_action_to_send = self.robot_action_processor((act_processed_teleop, obs))
            follower_target = self._apply_sync_to_follower_target(robot_action_to_send)
            now_ns = time.monotonic_ns()
            safety_result: SafetyResult | None = None
            previous_effective = self.last_effective_command
            if self.safety_processor is None:
                command = CommandFrame.absolute_passthrough(
                    master_action_raw=act,
                    master_action_processed=act_processed_teleop,
                    effective_command=follower_target,
                )
                self._track_action_quality(command.effective_command, previous_effective)
                self.last_effective_command = dict(command.effective_command)
                self.last_effective_time_ns = now_ns
            else:
                dt_s = (
                    1.0 / self.settings.dataset.fps
                    if self.last_effective_time_ns is None
                    else max((now_ns - self.last_effective_time_ns) / 1_000_000_000, 1e-9)
                )
                safety_result = self.safety_processor.process(
                    follower_target=follower_target,
                    follower_qpos=obs_processed,
                    previous_effective=self.last_effective_command,
                    dt_s=dt_s,
                )
                command = CommandFrame(
                    master_action_raw=act,
                    master_action_processed=act_processed_teleop,
                    relative_target=follower_target,
                    safe_command=safety_result.command,
                    effective_command=safety_result.command,
                    safety_events=safety_result.events,
                )
                self._track_action_quality(command.effective_command, previous_effective)
                self.last_effective_command = dict(command.effective_command)
                self.last_effective_time_ns = now_ns
                self._track_follower_tracking(safety_result)
            send_result = robot.send_action(dict(command.effective_command))
            action_send_time_ns = time.monotonic_ns()
        command = command.with_send_result(send_result)
        mismatch_atol = (
            self.settings.safety.driver_mismatch_atol if self.settings.safety is not None else 1e-6
        )
        mismatches = command_mismatches(
            command.effective_command,
            command.send_result,
            atol=mismatch_atol,
        )
        has_mismatch = bool(mismatches["changed"] or mismatches["missing"] or mismatches["extra"])
        if has_mismatch and mismatches != self.last_driver_mismatches:
            self.manifest.event(
                "warning",
                "driver_command_mismatch",
                "Driver return differs from effective command",
                mismatches=mismatches,
            )
        self.last_driver_mismatches = mismatches if has_mismatch else None
        self._track_driver_mismatch(mismatches, has_mismatch=has_mismatch)

        if safety_result is not None and safety_result.freeze_requested:
            self._enter_safety_freeze(
                "follower_tracking_freeze",
                "Follower tracking error triggered safety freeze",
            )
            return

        with self.lock:
            is_recording = self.recording
            dataset = self.dataset
            task = self.current_task
            frame_index = self.current_frame_count
        if is_recording and dataset is not None:
            observation_frame = build_dataset_frame(dataset.features, obs_processed, prefix=OBS_STR)
            training_action = command.training_action(self.settings.dataset.action_semantics)
            action_frame = build_dataset_frame(dataset.features, training_action, prefix=ACTION)
            frame = {**observation_frame, **action_frame, "task": task}
            should_add = False
            with self.lock:
                if self.recording and self.dataset is dataset:
                    should_add = True
                    self.current_frame_count += 1
            if should_add:
                with self.dataset_lock:
                    if self.dataset is dataset:
                        dataset.add_frame(frame)
                self._append_timing_event(
                    {
                        "frame_index": frame_index,
                        "control_step_start_time_ns": control_step_start_time_ns,
                        "follower_obs_time_ns": follower_obs_time_ns,
                        "master_read_time_ns": master_read_time_ns,
                        "action_send_time_ns": action_send_time_ns,
                        "control_step_end_time_ns": time.monotonic_ns(),
                        **self._image_timing_fields(obs_processed, follower_obs_time_ns),
                    }
                )

    @staticmethod
    def _is_number(value: Any) -> bool:
        try:
            float(value)
        except (TypeError, ValueError):
            return False
        return True

    def _append_timing_event(self, event: Mapping[str, Any]) -> None:
        with self.lock:
            if self.recording:
                self.current_timing_events.append(dict(event))

    def _image_timing_fields(self, obs_processed: Mapping[str, Any], timestamp_ns: int) -> dict[str, int]:
        fields: dict[str, int] = {}
        for camera_name in self.settings.cameras:
            if camera_name in obs_processed:
                fields[f"{camera_name}_image_acquire_time_ns"] = timestamp_ns
        return fields

    def _enter_safety_freeze(self, reason: str, message: str) -> None:
        was_recording = False
        with self.lock:
            was_recording = self.recording
            self.freeze_reason = reason
            self.freeze_message = message
            self.auto_stopped_by_safety = was_recording
            self.auto_stop_save_status = "pending" if was_recording else ""

        save_failed = False
        if was_recording:
            try:
                self.stop_episode(auto_stopped_by_safety=True)
                with self.lock:
                    self.auto_stop_save_status = "saved"
            except Exception as exc:  # noqa: BLE001
                save_failed = True
                with self.lock:
                    self.auto_stop_save_status = "failed"
                self.manifest.event(
                    "error",
                    "tracking_freeze_save_failed",
                    f"{type(exc).__name__}: {exc}",
                )

        with self.lock:
            self.recording = False
            self.dry_teleop_enabled = False
            self.safety_frozen = True
            self._invalidate_ready("safety freeze")
            self._invalidate_sync("safety freeze")
            self.freeze_reason = reason
            self.freeze_message = message
            self.auto_stopped_by_safety = was_recording
            if was_recording and not self.auto_stop_save_status:
                self.auto_stop_save_status = "failed" if save_failed else "saved"
            self.state = "frozen_error" if save_failed else "frozen"
            self.message = (
                "safety freeze save failed; manual intervention required"
                if save_failed
                else "safety frozen; episode auto-saved; reconnect required"
            )

    def _apply_sync_to_follower_target(self, follower_target: Mapping[str, Any]) -> dict[str, Any]:
        if self.settings.teleop_mode != RELATIVE_JOINT_MODE:
            return dict(follower_target)
        with self.lock:
            offsets = dict(self.sync_offsets or {}) if self.sync_state == "valid" else None
            calibration = dict(self.sync_calibration or {}) if self.sync_state == "valid" else None
        if not offsets:
            return dict(follower_target)
        synced = dict(follower_target)
        diagnostics: dict[str, dict[str, float]] = {}
        follower_start = dict((calibration or {}).get("follower_start", {}))
        follower_target_start = dict((calibration or {}).get("follower_target_start", {}))
        for key, value in follower_target.items():
            if key in offsets and self._is_number(value):
                raw_target = float(value)
                if key in follower_start and key in follower_target_start:
                    base = float(follower_start[key])
                    target_base = float(follower_target_start[key])
                    delta = raw_target - target_base
                    deadband = self._relative_deadband_for_key(key)
                    if abs(delta) < deadband:
                        delta = 0.0
                    gain = self._relative_gain_for_key(key)
                    command = base + gain * delta
                    synced[key] = command
                    diagnostics[key] = {
                        "raw_target": raw_target,
                        "target_start": target_base,
                        "follower_start": base,
                        "delta": delta,
                        "gain": gain,
                        "deadband": deadband,
                        "command": command,
                    }
                else:
                    command = raw_target + offsets[key]
                    synced[key] = command
                    diagnostics[key] = {
                        "raw_target": raw_target,
                        "target_start": raw_target,
                        "follower_start": command,
                        "delta": 0.0,
                        "gain": 1.0,
                        "deadband": 0.0,
                        "command": command,
                    }
        with self.lock:
            self.latest_relative_result = diagnostics
        return synced

    @staticmethod
    def _normalize_sync_arm(arm: str | None) -> str:
        normalized = str(arm or "both").strip().lower()
        aliases = {"all": "both", "dual": "both", "both_arms": "both"}
        normalized = aliases.get(normalized, normalized)
        if normalized not in {"left", "right", "both"}:
            raise ValueError("sync arm must be left, right, or both")
        return normalized

    @staticmethod
    def _sync_key_matches_arm(key: str, arm: str) -> bool:
        if arm == "both":
            return True
        return key.startswith(f"{arm}_")

    @staticmethod
    def _arms_for_keys(keys: list[str]) -> set[str]:
        arms = {key.split("_", 1)[0] for key in keys if key.startswith(("left_", "right_"))}
        return arms or {"both"}

    def _required_sync_arms(self) -> set[str]:
        configured = self.settings.sync.get("required_arms")
        if configured is None:
            return {"left", "right"}
        if isinstance(configured, str):
            configured = [configured]
        arms = {self._normalize_sync_arm(str(arm)) for arm in configured}
        if "both" in arms:
            return {"left", "right"}
        return arms or {"left", "right"}

    def _relative_gain_for_key(self, key: str) -> float:
        gains = self.settings.sync.get("gains", {})
        if isinstance(gains, Mapping) and key in gains:
            return float(gains[key])
        return float(self.settings.sync.get("gain", 1.0))

    def _relative_deadband_for_key(self, key: str) -> float:
        deadband = self.settings.sync.get("deadband", {})
        if isinstance(deadband, Mapping) and key in deadband:
            return max(0.0, float(deadband[key]))
        if isinstance(deadband, (int, float, str)):
            return max(0.0, float(deadband))
        return 0.0

    def _reset_episode_command_validation(self) -> None:
        self._mismatch_streak = 0
        self.current_command_validation = {
            "mismatch_frames": 0,
            "max_abs_error": 0.0,
            "affected_joints": [],
            "max_consecutive_mismatch_frames": 0,
            "action_spike_frames": 0,
            "max_action_delta": 0.0,
            "nonfinite_action_frames": 0,
        }

    def _reset_episode_tracking_validation(self) -> None:
        self._tracking_contamination_streak = 0
        self._tracking_warning_logged = False
        self.current_tracking_validation = {
            "warning_frames": 0,
            "contamination_frames": 0,
            "freeze_frames": 0,
            "max_abs_error": 0.0,
            "affected_joints": [],
            "max_consecutive_contamination_frames": 0,
        }

    def _track_action_quality(
        self,
        effective_command: Mapping[str, Any],
        previous_effective: Mapping[str, Any] | None,
    ) -> None:
        nonfinite_joints: list[str] = []
        spike_joints: list[str] = []
        max_delta = 0.0
        threshold = float(self.settings.control.get("action_spike_threshold", 0.0) or 0.0)
        for key, value in effective_command.items():
            if not self._is_number(value):
                nonfinite_joints.append(key)
                continue
            current = float(value)
            if not math.isfinite(current):
                nonfinite_joints.append(key)
                continue
            if previous_effective is None or key not in previous_effective:
                continue
            previous = previous_effective[key]
            if not self._is_number(previous):
                continue
            previous_float = float(previous)
            if not math.isfinite(previous_float):
                continue
            delta = abs(current - previous_float)
            max_delta = max(max_delta, delta)
            if threshold > 0.0 and delta > threshold:
                spike_joints.append(key)

        summary = self.current_command_validation
        summary["max_action_delta"] = max(float(summary.get("max_action_delta", 0.0)), max_delta)
        affected = set(summary.get("affected_joints", []))
        if nonfinite_joints:
            summary["nonfinite_action_frames"] = int(summary.get("nonfinite_action_frames", 0)) + 1
            affected.update(nonfinite_joints)
            self.current_dq_reasons.add("nonfinite_action")
            self.manifest.event(
                "error",
                "episode_dq_fail",
                "Non-finite effective command detected",
                reason="nonfinite_action",
                affected_joints=sorted(nonfinite_joints),
            )
        if spike_joints:
            summary["action_spike_frames"] = int(summary.get("action_spike_frames", 0)) + 1
            affected.update(spike_joints)
            self.current_dq_reasons.add("action_spike")
            self.manifest.event(
                "error",
                "episode_dq_fail",
                "Effective command action spike exceeded configured threshold",
                reason="action_spike",
                threshold=threshold,
                max_delta=max_delta,
                affected_joints=sorted(spike_joints),
            )
        summary["affected_joints"] = sorted(affected)

    def _track_follower_tracking(self, result: SafetyResult) -> None:
        levels = dict(result.tracking_levels)
        contamination_present = any(level in {"contamination", "freeze"} for level in levels.values())
        if contamination_present:
            self._tracking_contamination_streak += 1
        else:
            self._tracking_contamination_streak = 0

        if not self.recording:
            if result.freeze_requested:
                self.safety_frozen = True
                self.manifest.event(
                    "error",
                    "follower_tracking_freeze",
                    "Follower tracking error triggered safety freeze",
                    tracking_levels=levels,
                )
            return
        if not levels:
            return

        if not self._tracking_warning_logged:
            self._tracking_warning_logged = True
            self.manifest.event(
                "warning",
                "follower_tracking_warning",
                "Follower tracking error exceeded a configured threshold",
                tracking_levels=levels,
                tracking_errors={key: float(result.tracking_errors[key]) for key in levels},
            )

        summary = self.current_tracking_validation
        summary["warning_frames"] = int(summary["warning_frames"]) + 1
        if contamination_present:
            summary["contamination_frames"] = int(summary["contamination_frames"]) + 1
        if result.freeze_requested:
            summary["freeze_frames"] = int(summary["freeze_frames"]) + 1
        summary["max_consecutive_contamination_frames"] = max(
            int(summary["max_consecutive_contamination_frames"]),
            self._tracking_contamination_streak,
        )
        affected = set(summary["affected_joints"])
        affected.update(levels)
        summary["affected_joints"] = sorted(affected)
        summary["max_abs_error"] = max(
            float(summary["max_abs_error"]),
            max(float(result.tracking_errors[key]) for key in levels),
        )
        self.current_dq_reasons.add("follower_tracking_error")

        if result.freeze_requested:
            reason = "follower_tracking_freeze"
            self.current_contamination_reasons.add(reason)
            self.safety_frozen = True
            self.manifest.event(
                "error",
                "follower_tracking_freeze",
                "Follower tracking error triggered safety freeze",
                reason=reason,
                tracking_validation=dict(summary),
                tracking_levels=levels,
            )
            return

        threshold = self.settings.safety.tracking_error_persistence_frames
        reason = "persistent_follower_tracking_error"
        if (
            self._tracking_contamination_streak >= threshold
            and reason not in self.current_contamination_reasons
        ):
            self.current_contamination_reasons.add(reason)
            self.manifest.event(
                "error",
                "episode_contaminated",
                "Persistent follower tracking error contaminated the active episode",
                reason=reason,
                tracking_validation=dict(summary),
            )

    def _track_driver_mismatch(
        self,
        mismatches: Mapping[str, Any],
        *,
        has_mismatch: bool,
    ) -> None:
        if not self.recording:
            return
        if not has_mismatch:
            self._mismatch_streak = 0
            return

        self._mismatch_streak += 1
        summary = self.current_command_validation
        summary["mismatch_frames"] = int(summary["mismatch_frames"]) + 1
        summary["max_consecutive_mismatch_frames"] = max(
            int(summary["max_consecutive_mismatch_frames"]),
            self._mismatch_streak,
        )
        affected = set(summary["affected_joints"])
        affected.update(mismatches["changed"])
        affected.update(mismatches["missing"])
        affected.update(mismatches["extra"])
        summary["affected_joints"] = sorted(affected)
        for values in mismatches["changed"].values():
            try:
                error = abs(float(values["actual"]) - float(values["expected"]))
            except (TypeError, ValueError):
                continue
            summary["max_abs_error"] = max(float(summary["max_abs_error"]), error)

        threshold = (
            self.settings.safety.mismatch_contamination_frames if self.settings.safety is not None else 1
        )
        reason = "persistent_driver_command_mismatch"
        if self._mismatch_streak >= threshold and reason not in self.current_contamination_reasons:
            self.current_contamination_reasons.add(reason)
            self.manifest.event(
                "error",
                "episode_contaminated",
                "Persistent driver command mismatch contaminated the active episode",
                reason=reason,
                command_validation=dict(self.current_command_validation),
            )

    def _update_preview_frames(self, obs: dict[str, Any]) -> None:
        now = time.time()
        for camera_name in self.settings.cameras:
            frame = obs.get(camera_name)
            if frame is None:
                continue
            jpeg = _encode_jpeg_rgb(frame, self.jpeg_quality)
            if jpeg is None:
                continue
            with self.lock:
                item = self.frame_cache[camera_name]
                item["jpeg"] = jpeg
                item["timestamp"] = now
                item["frames"] = int(item.get("frames") or 0) + 1
                item["ok"] = True
                item["last_error"] = None

    def _episode_fps(self, frame_count: int) -> float:
        elapsed = max(time.perf_counter() - self.current_record_start, 1e-6)
        return round(frame_count / elapsed, 2)

    def _episode_dq_hard_gate_reasons(
        self,
        *,
        frame_count: int,
        fps: float,
        cameras: Mapping[str, str],
        safety_metadata: Mapping[str, Any],
        contamination_reasons: set[str],
    ) -> set[str]:
        reasons: set[str] = set()
        min_frames = int(self.settings.control.get("min_episode_frames", 1) or 1)
        if frame_count < min_frames:
            reasons.add(f"episode_too_short:{frame_count}<{min_frames}")

        min_fps_ratio = float(self.settings.control.get("min_control_fps_ratio", 0.0) or 0.0)
        if min_fps_ratio > 0.0:
            min_fps = float(self.settings.dataset.fps) * min_fps_ratio
            if fps < min_fps:
                reasons.add("control_fps_too_low")

        for camera_name in self.settings.cameras:
            if cameras.get(camera_name) != "ok":
                reasons.add(f"camera_missing:{camera_name}")

        command_validation = self.current_command_validation
        if int(command_validation.get("action_spike_frames", 0) or 0) > 0:
            reasons.add("action_spike")
        if int(command_validation.get("nonfinite_action_frames", 0) or 0) > 0:
            reasons.add("nonfinite_action")

        if self.settings.safety is not None:
            required_metadata = {
                "safety_config_version": safety_metadata.get("safety_config_version"),
                "hard_limits": safety_metadata.get("hard_limits"),
                "soft_limits": safety_metadata.get("soft_limits"),
                "max_step": safety_metadata.get("max_step"),
                "velocity_limit": safety_metadata.get("velocity_limit"),
            }
            if bool(safety_metadata.get("safety_config_verified", False)):
                required_metadata.update(
                    {
                        "verified_by": safety_metadata.get("verified_by"),
                        "verified_at": safety_metadata.get("verified_at"),
                        "verification_basis": safety_metadata.get("verification_basis"),
                    }
                )
            for key, value in required_metadata.items():
                if value is None or value == "" or value == () or value == [] or value == {}:
                    reasons.add(f"metadata_incomplete:{key}")

        if reasons:
            self.manifest.event(
                "error",
                "episode_dq_fail",
                "Episode failed data-quality hard gates",
                reasons=sorted(reasons),
                contamination_reasons=sorted(contamination_reasons),
            )
        return reasons

    def _camera_health_labels(self) -> dict[str, str]:
        now = time.time()
        labels: dict[str, str] = {}
        for name, item in self.frame_cache.items():
            timestamp = item.get("timestamp")
            labels[name] = (
                "ok" if timestamp is not None and now - timestamp <= self.camera_timeout_s else "timeout"
            )
        return labels
