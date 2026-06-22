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


def resume_lerobot_dataset(repo_id: str, **kwargs: Any):
    resume = getattr(LeRobotDataset, "resume", None)
    if resume is not None:
        return resume(repo_id, **kwargs)
    return LeRobotDataset(repo_id, **kwargs)


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
