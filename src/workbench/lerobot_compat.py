from __future__ import annotations

import inspect
from typing import Any

try:
    from lerobot.datasets import (
        LeRobotDataset,
        VideoEncodingManager,
        aggregate_pipeline_dataset_features,
        create_initial_features,
    )
except ImportError:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.datasets.pipeline_features import (
        aggregate_pipeline_dataset_features,
        create_initial_features,
    )
    from lerobot.datasets.video_utils import VideoEncodingManager

try:
    from lerobot.utils.feature_utils import build_dataset_frame, combine_feature_dicts
except ImportError:
    from lerobot.datasets.utils import build_dataset_frame, combine_feature_dicts


__all__ = [
    "LeRobotDataset",
    "VideoEncodingManager",
    "adapt_bi_openarm_camera_keys",
    "aggregate_pipeline_dataset_features",
    "build_dataset_frame",
    "combine_feature_dicts",
    "create_initial_features",
    "create_lerobot_dataset",
    "dataset_has_pending_frames",
    "make_bi_openarm_configuration",
    "resume_lerobot_dataset",
]


def _filter_kwargs(callable_obj: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    parameters = inspect.signature(callable_obj).parameters
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return dict(kwargs)
    return {key: value for key, value in kwargs.items() if key in parameters}


def resume_lerobot_dataset(repo_id: str, **kwargs: Any):
    resume = getattr(LeRobotDataset, "resume", None)
    if resume is not None:
        return resume(repo_id, **_filter_kwargs(resume, kwargs))
    image_writer_processes = int(kwargs.pop("image_writer_processes", 0))
    image_writer_threads = int(kwargs.pop("image_writer_threads", 0))
    dataset = LeRobotDataset(repo_id, **_filter_kwargs(LeRobotDataset, kwargs))
    if image_writer_processes or image_writer_threads:
        dataset.start_image_writer(image_writer_processes, image_writer_threads)
    return dataset


def create_lerobot_dataset(repo_id: str, **kwargs: Any):
    try:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset as DatasetClass
    except ImportError:
        DatasetClass = LeRobotDataset

    create = DatasetClass.create
    return create(repo_id, **_filter_kwargs(create, kwargs))


def dataset_has_pending_frames(dataset: Any) -> bool:
    """Return True if the dataset's current episode buffer holds unsaved frames.

    Older LeRobot releases exposed ``LeRobotDataset.has_pending_frames()``; it was
    removed by 0.4.x. In 0.4.x the unsaved-frame state lives in ``episode_buffer``
    (``None`` before the first ``add_frame``/``create``, otherwise a dict whose
    ``"size"`` counts buffered frames and resets to 0 on ``clear_episode_buffer``).
    Prefer the native method when present so this keeps working on either API.
    """
    native = getattr(dataset, "has_pending_frames", None)
    if callable(native):
        return bool(native())
    buffer = getattr(dataset, "episode_buffer", None)
    if not buffer:
        return False
    try:
        return int(buffer.get("size", 0)) > 0
    except AttributeError:
        return False


def make_bi_openarm_configuration(
    bi_config_cls,
    arm_config_cls,
    *,
    robot_id: str,
    left_arm: dict[str, Any],
    right_arm: dict[str, Any],
    cameras: dict[str, Any],
):
    bi_parameters = inspect.signature(bi_config_cls).parameters
    if "cameras" in bi_parameters:
        config = bi_config_cls(
            id=robot_id,
            left_arm_config=arm_config_cls(**left_arm),
            right_arm_config=arm_config_cls(**right_arm),
            cameras=cameras,
        )
        return config, {}

    left_cameras = {name: cfg for name, cfg in cameras.items() if name != "wrist_right"}
    right_cameras = {name: cfg for name, cfg in cameras.items() if name == "wrist_right"}
    config = bi_config_cls(
        id=robot_id,
        left_arm_config=arm_config_cls(**left_arm, cameras=left_cameras),
        right_arm_config=arm_config_cls(**right_arm, cameras=right_cameras),
    )
    aliases = {
        **{f"left_{name}": name for name in left_cameras},
        **{f"right_{name}": name for name in right_cameras},
    }
    return config, aliases


class _CameraKeyRobotAdapter:
    def __init__(self, robot: Any, aliases: dict[str, str]):
        self._robot = robot
        self._aliases = aliases
        self._camera_order = list(aliases.values())

    def __getattr__(self, name: str):
        return getattr(self._robot, name)

    @property
    def observation_features(self):
        return self._canonical_observation(self._robot.observation_features)

    @property
    def action_features(self):
        return dict(self._ordered_positions(self._robot.action_features))

    def get_observation(self):
        return self._canonical_observation(self._robot.get_observation())

    def _canonical_observation(self, values: dict[str, Any]) -> dict[str, Any]:
        renamed = {self._aliases.get(key, key): value for key, value in values.items()}
        positions = self._ordered_positions(renamed)
        cameras = [(key, renamed[key]) for key in self._camera_order if key in renamed]
        return dict([*positions, *cameras])

    @staticmethod
    def _ordered_positions(values: dict[str, Any]) -> list[tuple[str, Any]]:
        positions = [(key, value) for key, value in values.items() if key.endswith(".pos")]
        right = [(key, value) for key, value in positions if key.startswith("right_")]
        left = [(key, value) for key, value in positions if key.startswith("left_")]
        other = [(key, value) for key, value in positions if not key.startswith(("right_", "left_"))]
        return [*right, *left, *other]


def adapt_bi_openarm_camera_keys(robot: Any, aliases: dict[str, str]):
    if not aliases:
        return robot
    return _CameraKeyRobotAdapter(robot, aliases)
