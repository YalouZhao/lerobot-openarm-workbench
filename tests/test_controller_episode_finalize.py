from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest


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

import workbench.controller as controller_module
from workbench.config import DatasetSettings, WorkbenchSettings
from workbench.controller import WorkbenchController
from workbench.dataset_manifest import DatasetSchemaError


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


class FakeRecordingDataset:
    features = {}

    def __init__(self) -> None:
        self.frames: list[dict] = []

    def add_frame(self, frame: dict) -> None:
        self.frames.append(frame)


class FakeRobot:
    is_connected = True

    def __init__(self) -> None:
        self.sent_actions: list[dict] = []

    def get_observation(self) -> dict:
        return {"joint.pos": 5.0}

    def send_action(self, action: dict) -> dict:
        self.sent_actions.append(dict(action))
        return {"joint.pos": 11.5}


class FakeTeleop:
    is_connected = True

    def get_action(self) -> dict:
        return {"joint.pos": 100.0}


def test_control_step_records_effective_command_and_logs_driver_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
        teleop={"id": "teleop", "mode": "absolute_passthrough"},
        cameras={},
        control={},
    )
    controller = WorkbenchController(settings, session_id="command-test")
    robot = FakeRobot()
    dataset = FakeRecordingDataset()
    controller.robot = robot
    controller.teleop = FakeTeleop()
    controller.dataset = dataset
    controller.recording = True
    controller.teleop_action_processor = lambda pair: {"joint.pos": 10.0}
    controller.robot_action_processor = lambda pair: {"joint.pos": 12.0}
    controller.robot_observation_processor = lambda obs: obs

    monkeypatch.setattr(
        controller_module,
        "build_dataset_frame",
        lambda features, values, prefix: {prefix: dict(values)},
    )

    controller._control_step()
    controller._control_step()

    assert robot.sent_actions == [{"joint.pos": 12.0}, {"joint.pos": 12.0}]
    assert dataset.frames[0]["action"] == {"joint.pos": 12.0}
    events = [
        json.loads(line)
        for line in (tmp_path / "sessions" / "command-test" / "events.jsonl").read_text().splitlines()
    ]
    mismatch = [event for event in events if event["event"] == "driver_command_mismatch"]
    assert len(mismatch) == 1
    assert mismatch[0]["mismatches"]["changed"]["joint.pos"] == {
        "expected": 12.0,
        "actual": 11.5,
    }


def test_control_step_maps_gripper_before_driver_and_dataset(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
        teleop={
            "id": "teleop",
            "mode": "absolute_passthrough",
            "apply_openarm_mini_compat_mapping": True,
            "compat_mapping_version": "openarm_mini_818892a3",
            "compat_mapping_verified": False,
        },
        cameras={},
        control={},
    )
    controller = WorkbenchController(settings, session_id="gripper-command-test")
    dataset = FakeRecordingDataset()

    class GripperRobot(FakeRobot):
        def send_action(self, action: dict) -> dict:
            self.sent_actions.append(dict(action))
            return dict(action)

    class GripperTeleop(FakeTeleop):
        def get_action(self) -> dict:
            return {"right_gripper.pos": 100.0}

    robot = GripperRobot()
    controller.robot = robot
    controller.teleop = GripperTeleop()
    controller.dataset = dataset
    controller.recording = True
    controller.teleop_action_processor = lambda pair: dict(pair[0])
    controller.robot_action_processor = lambda pair: dict(pair[0])
    controller.robot_observation_processor = lambda obs: obs

    monkeypatch.setattr(
        controller_module,
        "build_dataset_frame",
        lambda features, values, prefix: {prefix: dict(values)},
    )

    controller._control_step()

    assert robot.sent_actions == [{"right_gripper.pos": -65.0}]
    assert dataset.frames == [
        {
            "observation": {"joint.pos": 5.0},
            "action": {"right_gripper.pos": -65.0},
            "task": "",
        }
    ]


def test_controller_blocks_legacy_unknown_root_before_opening_lerobot_dataset(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    (root / "meta").mkdir(parents=True)
    (root / "meta" / "info.json").write_text("{}")
    settings = WorkbenchSettings(
        workspace_root=tmp_path,
        session_root=tmp_path / "sessions",
        dataset=DatasetSettings(
            repo_id="local/test",
            root=root,
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
        teleop={"id": "teleop", "mode": "absolute_passthrough"},
        cameras={},
        control={},
    )
    controller = WorkbenchController(settings, session_id="schema-test")
    controller.robot = type(
        "FeatureRobot",
        (),
        {"action_features": {"joint.pos": float}, "observation_features": {"joint.pos": float}},
    )()

    with pytest.raises(DatasetSchemaError, match="legacy_unknown"):
        controller._ensure_dataset()


def test_relative_joint_mode_cannot_collect_before_phase_two(tmp_path: Path) -> None:
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
        teleop={"id": "teleop", "mode": "relative_joint_offset"},
        cameras={},
        control={"default_task": "test task"},
    )
    controller = WorkbenchController(settings, session_id="relative-test")

    with pytest.raises(RuntimeError, match="relative_joint_offset is not available until phase 2"):
        controller.start_episode("test task")


def test_dataset_action_features_are_aggregated_with_robot_action_processor(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
        teleop={"id": "teleop", "mode": "absolute_passthrough"},
        cameras={},
        control={},
    )
    controller = WorkbenchController(settings, session_id="feature-test")
    controller.robot = type(
        "FeatureRobot",
        (),
        {
            "name": "fake_robot",
            "cameras": {},
            "action_features": {"joint.pos": float},
            "observation_features": {"joint.pos": float},
        },
    )()
    controller.robot_action_processor = object()
    controller.robot_observation_processor = object()
    aggregate_calls: list[object] = []
    created: dict = {}

    def aggregate(*, pipeline, initial_features, use_videos):
        aggregate_calls.append(pipeline)
        key = "action" if pipeline is controller.robot_action_processor else "observation.state"
        return {key: {"dtype": "float32", "shape": (1,), "names": ["joint.pos"]}}

    class FakeDatasetFactory:
        @staticmethod
        def create(*args, **kwargs):
            created.update(kwargs)
            return object()

    class FakeVideoManager:
        def __init__(self, dataset):
            self.dataset = dataset

        def __enter__(self):
            return self

    monkeypatch.setattr(controller_module, "aggregate_pipeline_dataset_features", aggregate)
    monkeypatch.setattr(
        controller_module,
        "create_initial_features",
        lambda **kwargs: kwargs,
    )
    monkeypatch.setattr(
        controller_module,
        "combine_feature_dicts",
        lambda *feature_sets: {key: value for features in feature_sets for key, value in features.items()},
    )
    monkeypatch.setattr(controller_module, "LeRobotDataset", FakeDatasetFactory)
    monkeypatch.setattr(controller_module, "VideoEncodingManager", FakeVideoManager)

    controller._ensure_dataset()

    assert aggregate_calls == [controller.robot_action_processor, controller.robot_observation_processor]
    assert created["features"]["action"]["dtype"] == "float32"
