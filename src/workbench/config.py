from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .safety import SafetySettings, parse_safety_settings


LEGACY_DATASET_SCHEMA = "openarm_workbench_v1_legacy"
V2_DATASET_SCHEMA = "openarm_workbench_v2"
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
    safety: SafetySettings | None = None

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


def load_settings(path: str | Path) -> WorkbenchSettings:
    config_path = Path(path).expanduser()
    data = json.loads(config_path.read_text())
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
    return WorkbenchSettings(
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
        ),
        robot=dict(data["robot"]),
        teleop=teleop,
        cameras={str(k): dict(v) for k, v in data["cameras"].items()},
        control=dict(data.get("control", {})),
        ready=dict(data.get("ready", {})),
        safety=safety,
    )


def default_config_path() -> Path:
    return Path.home() / "lerobot_workbench" / "config" / "workbench_config.json"
