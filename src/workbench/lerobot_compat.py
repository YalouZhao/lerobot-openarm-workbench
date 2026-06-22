from __future__ import annotations

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
