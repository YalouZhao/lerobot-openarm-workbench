from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
from lerobot.cameras.realsense.configuration_realsense import RealSenseCameraConfig
from lerobot.datasets import (
    LeRobotDataset,
    VideoEncodingManager,
    aggregate_pipeline_dataset_features,
    create_initial_features,
)
from lerobot.processor import make_default_processors
from lerobot.robots import make_robot_from_config
from lerobot.robots.bi_openarm_follower.config_bi_openarm_follower import BiOpenArmFollowerConfig
from lerobot.robots.openarm_follower.config_openarm_follower import OpenArmFollowerConfigBase
from lerobot.teleoperators import make_teleoperator_from_config
from lerobot.teleoperators.openarm_mini.config_openarm_mini import OpenArmMiniConfig
from lerobot.utils.constants import ACTION, OBS_STR
from lerobot.utils.feature_utils import build_dataset_frame, combine_feature_dicts
from lerobot.utils.robot_utils import precise_sleep

from .config import WorkbenchSettings
from .dataset_manifest import CanonicalDatasetManifest
from .device_probe import reset_realsense
from .episode_manifest import EpisodeManifest, EpisodeRecord, now_iso

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
        self.session_id = session_id or time.strftime("%Y%m%d_%H%M%S")
        self.session_dir = settings.session_root / self.session_id
        self.manifest = EpisodeManifest(self.session_dir)
        self.dataset_manifest = CanonicalDatasetManifest(
            dataset_root=settings.dataset.root,
            dataset_name=settings.dataset.root.name,
            repo_id=settings.dataset.repo_id,
            task_text=str(settings.control.get("default_task", "")),
            session_id=self.session_id,
        )

        self.lock = threading.RLock()
        self.dataset_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.loop_thread: threading.Thread | None = None

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

        self.jpeg_quality = int(settings.control.get("jpeg_quality", 80))
        self.camera_timeout_s = float(settings.control.get("camera_timeout_s", 2.0))
        self.connect_retries = int(settings.control.get("connect_retries", 3))
        self.connect_retry_delay_s = float(settings.control.get("connect_retry_delay_s", 2.0))
        self.auto_reconnect_when_idle = bool(settings.control.get("auto_reconnect_when_idle", True))
        self.reconnect_cooldown_s = float(settings.control.get("reconnect_cooldown_s", 5.0))
        self.teleop_when_idle = bool(settings.control.get("teleop_when_idle", True))
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
            self._ensure_dataset()
            self.current_task = (task or self.current_task or self.settings.control.get("default_task") or "").strip()
            if not self.current_task:
                raise ValueError("task is required")
            self.current_episode_index = int(getattr(self.dataset, "num_episodes", 0))
            self.current_started_at = now_iso()
            self.current_frame_count = 0
            self.current_record_start = time.perf_counter()
            self.last_save_duration_s = None
            self.discard_requested = False
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

    def stop_episode(self) -> dict[str, Any]:
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
                if dataset is not None and dataset.has_pending_frames():
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
                record = EpisodeRecord(
                    episode_index=episode_index,
                    task=task,
                    accepted=False,
                    label="unlabeled",
                    notes="",
                    started_at=started_at,
                    ended_at=now_iso(),
                    frame_count=frame_count,
                    fps=self._episode_fps(frame_count),
                    save_duration_s=self.last_save_duration_s,
                    cameras=self._camera_health_labels(),
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
                self.manifest.event("info", "episode_discard", "Current episode discarded", episode_index=episode_index)
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
        accepted: bool | None = None,
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
            if accepted is None:
                accepted = label == "success"
            expected_accepted = label == "success"
            if bool(accepted) != expected_accepted:
                raise ValueError("accepted must match label in this workbench version")
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
                accepted=accepted,
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
            self.manifest.event("info" if result.get("ok") else "error", "realsense_reset", self.message, **result)
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
                },
                "episode": {
                    "state": self.state,
                    "episode_index": self.current_episode_index,
                    "task": self.current_task,
                    "frame_count": self.current_frame_count,
                    "started_at": self.current_started_at,
                    "last_saved_episode_index": self.last_saved_episode_index,
                    "save_duration_s": self.last_save_duration_s,
                },
                "cameras": cameras,
                "control": {
                    "default_task": str(self.settings.control.get("default_task", "")),
                    "teleop_when_idle": self.teleop_when_idle,
                    "has_realsense": "realsense" in self.settings.cameras,
                },
            }

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
        robot_cfg = BiOpenArmFollowerConfig(
            id=self.settings.robot["id"],
            left_arm_config=OpenArmFollowerConfigBase(
                port=self.settings.robot["left_arm"]["port"],
                side=self.settings.robot["left_arm"].get("side"),
            ),
            right_arm_config=OpenArmFollowerConfigBase(
                port=self.settings.robot["right_arm"]["port"],
                side=self.settings.robot["right_arm"].get("side"),
            ),
            cameras=cameras,
        )
        teleop_cfg = OpenArmMiniConfig(
            id=self.settings.teleop["id"],
            port_right=self.settings.teleop["port_right"],
            port_left=self.settings.teleop["port_left"],
        )

        self.robot = make_robot_from_config(robot_cfg)
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
        self.state = "idle"
        self.message = "ready"
        self.manifest.event("info", "devices_connected", "Robot, teleop, and cameras connected")

    def _assert_existing_calibration_cache(self) -> None:
        missing: list[str] = []
        for name in ("left_arm", "right_arm"):
            arm = getattr(self.robot, name, None)
            if arm is not None and not getattr(arm, "calibration", None):
                missing.append(f"robot.{name}")
        if self.teleop is not None and not getattr(self.teleop, "calibration", None):
            missing.append("teleop.openarm_mini")
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(
                f"Missing calibration cache for {joined}. Run lerobot-calibrate manually before starting the workbench."
            )

    def _disconnect_devices(self) -> None:
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
                    self.manifest.event("warning", "camera_force_release_failed", str(exc), camera=camera_name)
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

        dataset_features = combine_feature_dicts(
            aggregate_pipeline_dataset_features(
                pipeline=self.teleop_action_processor,
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
            self.dataset = LeRobotDataset.resume(
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
            can_teleop = is_recording or self.teleop_when_idle
            dataset = self.dataset
            task = self.current_task

        if robot is None or teleop is None or not robot.is_connected or not teleop.is_connected:
            time.sleep(0.1)
            return

        obs = robot.get_observation()
        obs_processed = self.robot_observation_processor(obs)
        self._update_preview_frames(obs_processed)

        if not can_teleop:
            return

        act = teleop.get_action()
        act_processed_teleop = self.teleop_action_processor((act, obs))
        robot_action_to_send = self.robot_action_processor((act_processed_teleop, obs))
        robot.send_action(robot_action_to_send)

        with self.lock:
            is_recording = self.recording
            dataset = self.dataset
            task = self.current_task
        if is_recording and dataset is not None:
            observation_frame = build_dataset_frame(dataset.features, obs_processed, prefix=OBS_STR)
            action_frame = build_dataset_frame(dataset.features, act_processed_teleop, prefix=ACTION)
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

    def _camera_health_labels(self) -> dict[str, str]:
        now = time.time()
        labels: dict[str, str] = {}
        for name, item in self.frame_cache.items():
            timestamp = item.get("timestamp")
            labels[name] = "ok" if timestamp is not None and now - timestamp <= self.camera_timeout_s else "timeout"
        return labels
