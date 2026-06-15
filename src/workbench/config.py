from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


@dataclass(frozen=True)
class WorkbenchSettings:
    workspace_root: Path
    session_root: Path
    dataset: DatasetSettings
    robot: dict[str, Any]
    teleop: dict[str, Any]
    cameras: dict[str, dict[str, Any]]
    control: dict[str, Any]


def load_settings(path: str | Path) -> WorkbenchSettings:
    config_path = Path(path).expanduser()
    data = json.loads(config_path.read_text())
    dataset = data["dataset"]
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
        ),
        robot=dict(data["robot"]),
        teleop=dict(data["teleop"]),
        cameras={str(k): dict(v) for k, v in data["cameras"].items()},
        control=dict(data.get("control", {})),
    )


def default_config_path() -> Path:
    return Path.home() / "lerobot_workbench" / "config" / "workbench_config.json"
