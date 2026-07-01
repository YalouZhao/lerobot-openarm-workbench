from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .safety import SafetySettings, parse_safety_settings
from .xlerobot_profile import (
    canonical_xlerobot_so101_dataset_fields,
    is_xlerobot_so101_schema,
    validate_xlerobot_so101_config_payload,
)


LEGACY_DATASET_SCHEMA = "openarm_workbench_v1_legacy"
V2_DATASET_SCHEMA = "openarm_workbench_v2"
XLEROBOT_SO101_DATASET_SCHEMA = "xlerobot_so101_workbench_v1"
LEGACY_ACTION_SEMANTICS = "master_absolute_legacy"
V2_ACTION_SEMANTICS = "follower_effective_command"
LEGACY_TELEOP_MODE = "absolute_legacy"
ABSOLUTE_PASSTHROUGH_MODE = "absolute_passthrough"
RELATIVE_JOINT_MODE = "relative_joint_offset"
COMMAND_FRAME_VERSION = 1


def validate_semantic_configuration(
    *,
    dataset_schema_version: str,
    action_semantics: str,
    teleop_mode: str,
    command_frame_version: int,
) -> None:
    if command_frame_version != COMMAND_FRAME_VERSION:
        raise ValueError(f"command_frame_version must be {COMMAND_FRAME_VERSION}")
    valid_combinations = {
        (LEGACY_DATASET_SCHEMA, LEGACY_ACTION_SEMANTICS, LEGACY_TELEOP_MODE),
        (V2_DATASET_SCHEMA, V2_ACTION_SEMANTICS, ABSOLUTE_PASSTHROUGH_MODE),
        (V2_DATASET_SCHEMA, V2_ACTION_SEMANTICS, RELATIVE_JOINT_MODE),
        (XLEROBOT_SO101_DATASET_SCHEMA, V2_ACTION_SEMANTICS, RELATIVE_JOINT_MODE),
    }
    combination = (dataset_schema_version, action_semantics, teleop_mode)
    if combination not in valid_combinations:
        raise ValueError(f"unsupported dataset semantic combination: {combination}")


@dataclass(frozen=True)
class DatasetSettings:
    repo_id: str
    root: Path
    fps: int
    episode_time_s: float
    streaming_encoding: bool
    vcodec: str
    encoder_threads: int | None
    encoder_queue_maxsize: int
    num_image_writer_processes: int
    num_image_writer_threads_per_camera: int
    video_encoding_batch_size: int
    push_to_hub: bool
    dataset_schema_version: str = V2_DATASET_SCHEMA
    action_semantics: str = V2_ACTION_SEMANTICS
    command_frame_version: int = COMMAND_FRAME_VERSION
    action_schema_version: str = ""
    state_schema_version: str = ""
    camera_schema_version: str = ""
    action_dim: int | None = None
    state_dim: int | None = None
    action_units: str = ""
    state_units: str = ""
    action_names: tuple[str, ...] = ()
    state_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkbenchSettings:
    workspace_root: Path
    session_root: Path
    dataset: DatasetSettings
    robot: dict[str, Any]
    teleop: dict[str, Any]
    cameras: dict[str, dict[str, Any]]
    control: dict[str, Any]
    ready: dict[str, Any] = field(default_factory=dict)
    sync: dict[str, Any] = field(default_factory=dict)
    safety: SafetySettings | None = None
    robot_profile_id: str | None = None

    @property
    def teleop_mode(self) -> str:
        return str(self.teleop.get("mode", ABSOLUTE_PASSTHROUGH_MODE))

    @property
    def apply_openarm_mini_compat_mapping(self) -> bool:
        return bool(self.teleop.get("apply_openarm_mini_compat_mapping", True))

    @property
    def compat_mapping_version(self) -> str:
        return str(self.teleop.get("compat_mapping_version", "openarm_mini_818892a3"))

    @property
    def compat_mapping_verified(self) -> bool:
        return bool(self.teleop.get("compat_mapping_verified", True))


def load_settings(path: str | Path, *, task_profile: str | Path | None = None) -> WorkbenchSettings:
    config_path = Path(path).expanduser()
    data = json.loads(config_path.read_text())
    if task_profile is not None:
        _apply_task_profile(data, Path(task_profile).expanduser())
    dataset = data["dataset"]
    teleop = dict(data["teleop"])
    if "safety" not in data:
        raise ValueError("missing required safety configuration: safety")
    safety = parse_safety_settings(data["safety"])
    try:
        dataset_schema_version = str(dataset["dataset_schema_version"])
        action_semantics = str(dataset["action_semantics"])
        command_frame_version = int(dataset["command_frame_version"])
        teleop_mode = str(teleop["mode"])
        apply_compat_mapping = bool(teleop["apply_openarm_mini_compat_mapping"])
        compat_mapping_version = str(teleop["compat_mapping_version"])
        bool(teleop["compat_mapping_verified"])
    except KeyError as exc:
        raise ValueError(f"missing required semantic configuration: {exc.args[0]}") from exc
    if is_xlerobot_so101_schema(dataset_schema_version):
        validate_xlerobot_so101_config_payload(data)
    validate_semantic_configuration(
        dataset_schema_version=dataset_schema_version,
        action_semantics=action_semantics,
        teleop_mode=teleop_mode,
        command_frame_version=command_frame_version,
    )
    if apply_compat_mapping and compat_mapping_version != "openarm_mini_818892a3":
        raise ValueError(
            "compat_mapping_version must be 'openarm_mini_818892a3' when "
            "apply_openarm_mini_compat_mapping=true"
        )
    canonical_dataset_fields: dict[str, Any] = {}
    if is_xlerobot_so101_schema(dataset_schema_version):
        canonical_dataset_fields = canonical_xlerobot_so101_dataset_fields()
    return WorkbenchSettings(
        robot_profile_id=(str(data["robot_profile_id"]) if data.get("robot_profile_id") else None),
        workspace_root=Path(data["workspace_root"]).expanduser(),
        session_root=Path(data["session_root"]).expanduser(),
        dataset=DatasetSettings(
            repo_id=str(dataset["repo_id"]),
            root=Path(dataset["root"]).expanduser(),
            fps=int(dataset.get("fps", 30)),
            episode_time_s=float(dataset.get("episode_time_s", 60)),
            streaming_encoding=bool(dataset.get("streaming_encoding", True)),
            vcodec=str(dataset.get("vcodec", "auto")),
            encoder_threads=dataset.get("encoder_threads"),
            encoder_queue_maxsize=int(dataset.get("encoder_queue_maxsize", 30)),
            num_image_writer_processes=int(dataset.get("num_image_writer_processes", 0)),
            num_image_writer_threads_per_camera=int(
                dataset.get("num_image_writer_threads_per_camera", 4)
            ),
            video_encoding_batch_size=int(dataset.get("video_encoding_batch_size", 1)),
            push_to_hub=bool(dataset.get("push_to_hub", False)),
            dataset_schema_version=dataset_schema_version,
            action_semantics=action_semantics,
            command_frame_version=command_frame_version,
            action_schema_version=str(
                dataset.get(
                    "action_schema_version",
                    canonical_dataset_fields.get("action_schema_version", ""),
                )
            ),
            state_schema_version=str(
                dataset.get(
                    "state_schema_version",
                    canonical_dataset_fields.get("state_schema_version", ""),
                )
            ),
            camera_schema_version=str(
                dataset.get(
                    "camera_schema_version",
                    canonical_dataset_fields.get("camera_schema_version", ""),
                )
            ),
            action_dim=(
                int(dataset["action_dim"])
                if "action_dim" in dataset
                else canonical_dataset_fields.get("action_dim")
            ),
            state_dim=(
                int(dataset["state_dim"])
                if "state_dim" in dataset
                else canonical_dataset_fields.get("state_dim")
            ),
            action_units=str(
                dataset.get("action_units", canonical_dataset_fields.get("action_units", ""))
            ),
            state_units=str(dataset.get("state_units", canonical_dataset_fields.get("state_units", ""))),
            action_names=tuple(dataset.get("action_names", canonical_dataset_fields.get("action_names", ()))),
            state_names=tuple(dataset.get("state_names", canonical_dataset_fields.get("state_names", ()))),
        ),
        robot=dict(data["robot"]),
        teleop=teleop,
        cameras={str(k): dict(v) for k, v in data["cameras"].items()},
        control=dict(data.get("control", {})),
        ready=dict(data.get("ready", {})),
        sync=dict(data.get("sync", {})),
        safety=safety,
    )


def default_config_path() -> Path:
    return Path.home() / "lerobot_workbench" / "config" / "workbench_config.json"


def _apply_task_profile(config: dict[str, Any], profile_path: Path) -> None:
    profile = json.loads(profile_path.read_text())
    profile_name = str(profile.get("profile_name") or profile_path.stem)
    profile_safety_version = _profile_safety_config_version(profile)
    runtime_safety_version = str(config.get("safety", {}).get("safety_config_version", ""))
    if profile_safety_version and profile_safety_version != runtime_safety_version:
        raise ValueError(
            "task profile safety_config_version mismatch: "
            f"expected {runtime_safety_version!r}, got {profile_safety_version!r}"
        )

    control = config.setdefault("control", {})
    if "task_prompt" in profile:
        control["default_task"] = str(profile["task_prompt"])
    control["task_profile_name"] = profile_name
    control["task_profile_path"] = str(profile_path)
    if "sop" in profile:
        control["task_profile_sop"] = str(profile["sop"])

    if "ready_path" in profile:
        config.setdefault("ready", {})["path"] = str(profile["ready_path"])

    dataset_profile = profile.get("dataset")
    if isinstance(dataset_profile, dict):
        dataset = config.setdefault("dataset", {})
        if "root" in dataset_profile:
            dataset["root"] = str(dataset_profile["root"])
        if "repo_id" in dataset_profile:
            dataset["repo_id"] = str(dataset_profile["repo_id"])
        if "session_root" in dataset_profile:
            config["session_root"] = str(dataset_profile["session_root"])

    if "teleop_mode" in profile:
        config.setdefault("teleop", {})["mode"] = str(profile["teleop_mode"])

    dq = profile.get("dq")
    if isinstance(dq, dict):
        control.update(dq)

    cameras = profile.get("cameras")
    if isinstance(cameras, dict):
        config["cameras"] = cameras


def _profile_safety_config_version(profile: dict[str, Any]) -> str:
    if "safety_config_version" in profile:
        return str(profile["safety_config_version"])
    safety = profile.get("safety")
    if isinstance(safety, dict) and "safety_config_version" in safety:
        return str(safety["safety_config_version"])
    return ""
