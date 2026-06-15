from __future__ import annotations

import json
import sys
import types
from pathlib import Path


def _install_fake_lerobot_modules() -> None:
    modules = {
        "cv2": types.ModuleType("cv2"),
        "lerobot": types.ModuleType("lerobot"),
        "lerobot.cameras": types.ModuleType("lerobot.cameras"),
        "lerobot.cameras.opencv": types.ModuleType("lerobot.cameras.opencv"),
        "lerobot.cameras.opencv.configuration_opencv": types.ModuleType(
            "lerobot.cameras.opencv.configuration_opencv"
        ),
        "lerobot.cameras.realsense": types.ModuleType("lerobot.cameras.realsense"),
        "lerobot.cameras.realsense.configuration_realsense": types.ModuleType(
            "lerobot.cameras.realsense.configuration_realsense"
        ),
        "lerobot.datasets": types.ModuleType("lerobot.datasets"),
        "lerobot.processor": types.ModuleType("lerobot.processor"),
        "lerobot.robots": types.ModuleType("lerobot.robots"),
        "lerobot.robots.bi_openarm_follower": types.ModuleType("lerobot.robots.bi_openarm_follower"),
        "lerobot.robots.bi_openarm_follower.config_bi_openarm_follower": types.ModuleType(
            "lerobot.robots.bi_openarm_follower.config_bi_openarm_follower"
        ),
        "lerobot.robots.openarm_follower": types.ModuleType("lerobot.robots.openarm_follower"),
        "lerobot.robots.openarm_follower.config_openarm_follower": types.ModuleType(
            "lerobot.robots.openarm_follower.config_openarm_follower"
        ),
        "lerobot.teleoperators": types.ModuleType("lerobot.teleoperators"),
        "lerobot.teleoperators.openarm_mini": types.ModuleType("lerobot.teleoperators.openarm_mini"),
        "lerobot.teleoperators.openarm_mini.config_openarm_mini": types.ModuleType(
            "lerobot.teleoperators.openarm_mini.config_openarm_mini"
        ),
        "lerobot.utils": types.ModuleType("lerobot.utils"),
        "lerobot.utils.constants": types.ModuleType("lerobot.utils.constants"),
        "lerobot.utils.feature_utils": types.ModuleType("lerobot.utils.feature_utils"),
        "lerobot.utils.robot_utils": types.ModuleType("lerobot.utils.robot_utils"),
    }
    for name, module in modules.items():
        sys.modules.setdefault(name, module)

    sys.modules["cv2"].COLOR_RGB2BGR = 0
    sys.modules["cv2"].IMWRITE_JPEG_QUALITY = 1
    sys.modules["cv2"].cvtColor = lambda frame, _: frame
    sys.modules["cv2"].imencode = lambda *args, **kwargs: (False, None)

    sys.modules["lerobot.cameras.opencv.configuration_opencv"].OpenCVCameraConfig = object
    sys.modules["lerobot.cameras.realsense.configuration_realsense"].RealSenseCameraConfig = object
    sys.modules["lerobot.datasets"].LeRobotDataset = object
    sys.modules["lerobot.datasets"].VideoEncodingManager = object
    sys.modules["lerobot.datasets"].aggregate_pipeline_dataset_features = lambda *args, **kwargs: {}
    sys.modules["lerobot.datasets"].create_initial_features = lambda *args, **kwargs: {}
    sys.modules["lerobot.processor"].make_default_processors = lambda: (None, None, None)
    sys.modules["lerobot.robots"].make_robot_from_config = lambda cfg: None
    sys.modules["lerobot.robots.bi_openarm_follower.config_bi_openarm_follower"].BiOpenArmFollowerConfig = object
    sys.modules["lerobot.robots.openarm_follower.config_openarm_follower"].OpenArmFollowerConfigBase = object
    sys.modules["lerobot.teleoperators"].make_teleoperator_from_config = lambda cfg: None
    sys.modules["lerobot.teleoperators.openarm_mini.config_openarm_mini"].OpenArmMiniConfig = object
    sys.modules["lerobot.utils.constants"].ACTION = "action"
    sys.modules["lerobot.utils.constants"].OBS_STR = "observation"
    sys.modules["lerobot.utils.feature_utils"].build_dataset_frame = lambda *args, **kwargs: {}
    sys.modules["lerobot.utils.feature_utils"].combine_feature_dicts = lambda *args, **kwargs: {}
    sys.modules["lerobot.utils.robot_utils"].precise_sleep = lambda _: None


_install_fake_lerobot_modules()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from workbench.config import DatasetSettings, WorkbenchSettings
from workbench.controller import WorkbenchController


class FakeDataset:
    def __init__(self) -> None:
        self.saved = False

    def has_pending_frames(self) -> bool:
        return True

    def save_episode(self) -> None:
        self.saved = True


def test_stop_episode_finalizes_dataset_after_saving(tmp_path: Path) -> None:
    settings = WorkbenchSettings(
        workspace_root=tmp_path,
        session_root=tmp_path / "sessions",
        dataset=DatasetSettings(
            repo_id="local/test",
            root=tmp_path / "dataset",
            fps=30,
            episode_time_s=60,
            streaming_encoding=True,
            vcodec="h264",
            encoder_threads=2,
            encoder_queue_maxsize=30,
            num_image_writer_processes=0,
            num_image_writer_threads_per_camera=4,
            video_encoding_batch_size=1,
            push_to_hub=False,
        ),
        robot={"id": "robot", "left_arm": {}, "right_arm": {}},
        teleop={"id": "teleop"},
        cameras={},
        control={},
    )
    controller = WorkbenchController(settings, session_id="test")
    fake_dataset = FakeDataset()
    finalized = []

    controller.dataset = fake_dataset
    controller.recording = True
    controller.current_episode_index = 0
    controller.current_task = "test task"
    controller.current_started_at = "2026-06-09T00:00:00+08:00"
    controller.current_frame_count = 3
    controller.current_record_start = 1.0
    controller._finalize_dataset = lambda: finalized.append(True) or setattr(controller, "dataset", None)

    result = controller.stop_episode()

    assert result["ok"] is True
    assert fake_dataset.saved is True
    assert finalized == [True]
    assert controller.dataset is None


def test_stop_and_label_episode_update_dataset_root_and_session_manifest(tmp_path: Path) -> None:
    settings = WorkbenchSettings(
        workspace_root=tmp_path,
        session_root=tmp_path / "sessions",
        dataset=DatasetSettings(
            repo_id="local/test",
            root=tmp_path / "dataset",
            fps=30,
            episode_time_s=60,
            streaming_encoding=True,
            vcodec="h264",
            encoder_threads=2,
            encoder_queue_maxsize=30,
            num_image_writer_processes=0,
            num_image_writer_threads_per_camera=4,
            video_encoding_batch_size=1,
            push_to_hub=False,
        ),
        robot={"id": "robot", "left_arm": {}, "right_arm": {}},
        teleop={"id": "teleop"},
        cameras={},
        control={},
    )
    controller = WorkbenchController(settings, session_id="test")
    fake_dataset = FakeDataset()

    controller.dataset = fake_dataset
    controller.recording = True
    controller.current_episode_index = 0
    controller.current_task = "test task"
    controller.current_started_at = "2026-06-09T00:00:00+08:00"
    controller.current_frame_count = 3
    controller.current_record_start = 1.0
    controller._finalize_dataset = lambda: setattr(controller, "dataset", None)

    controller.stop_episode()
    result = controller.label_episode("success")

    assert result["ok"] is True
    dataset_records = [
        json.loads(line)
        for line in (tmp_path / "dataset" / "episodes.jsonl").read_text().splitlines()
        if line.strip()
    ]
    session_records = [
        json.loads(line)
        for line in (tmp_path / "sessions" / "test" / "episodes.jsonl").read_text().splitlines()
        if line.strip()
    ]
    accepted = json.loads((tmp_path / "dataset" / "accepted_episodes.json").read_text())

    assert dataset_records == session_records
    assert dataset_records[0]["label"] == "success"
    assert dataset_records[0]["accepted"] is True
    assert accepted["episodes"] == [0]


def test_discard_after_stop_marks_dataset_root_without_clearing_saved_episode(tmp_path: Path) -> None:
    settings = WorkbenchSettings(
        workspace_root=tmp_path,
        session_root=tmp_path / "sessions",
        dataset=DatasetSettings(
            repo_id="local/test",
            root=tmp_path / "dataset",
            fps=30,
            episode_time_s=60,
            streaming_encoding=True,
            vcodec="h264",
            encoder_threads=2,
            encoder_queue_maxsize=30,
            num_image_writer_processes=0,
            num_image_writer_threads_per_camera=4,
            video_encoding_batch_size=1,
            push_to_hub=False,
        ),
        robot={"id": "robot", "left_arm": {}, "right_arm": {}},
        teleop={"id": "teleop"},
        cameras={},
        control={},
    )
    controller = WorkbenchController(settings, session_id="test")
    fake_dataset = FakeDataset()

    controller.dataset = fake_dataset
    controller.recording = True
    controller.current_episode_index = 0
    controller.current_task = "test task"
    controller.current_started_at = "2026-06-09T00:00:00+08:00"
    controller.current_frame_count = 3
    controller.current_record_start = 1.0
    controller._finalize_dataset = lambda: setattr(controller, "dataset", None)

    controller.stop_episode()
    result = controller.discard_episode()

    assert result == {"ok": True, "episode_index": 0}
    dataset_records = [
        json.loads(line)
        for line in (tmp_path / "dataset" / "episodes.jsonl").read_text().splitlines()
        if line.strip()
    ]
    accepted = json.loads((tmp_path / "dataset" / "accepted_episodes.json").read_text())

    assert fake_dataset.saved is True
    assert dataset_records[0]["label"] == "discard"
    assert dataset_records[0]["accepted"] is False
    assert accepted["episodes"] == []
