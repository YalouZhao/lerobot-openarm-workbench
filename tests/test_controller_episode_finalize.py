from __future__ import annotations

import json
import sys
import time
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
    sys.modules[
        "lerobot.robots.bi_openarm_follower.config_bi_openarm_follower"
    ].BiOpenArmFollowerConfig = object
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

import workbench.controller as controller_module  # noqa: E402
from workbench.config import DatasetSettings, WorkbenchSettings  # noqa: E402
from workbench.controller import WorkbenchController  # noqa: E402
from workbench.dataset_manifest import DatasetSchemaError  # noqa: E402
from workbench.safety import EXPECTED_FOLLOWER_ACTION_KEYS, parse_safety_settings  # noqa: E402


def make_safety_settings(*, verified: bool = True):
    hard_limits = {
        "right_joint_1.pos": [-75.0, 75.0],
        "right_joint_2.pos": [-9.0, 90.0],
        "right_joint_3.pos": [-85.0, 85.0],
        "right_joint_4.pos": [0.0, 135.0],
        "right_joint_5.pos": [-85.0, 85.0],
        "right_joint_6.pos": [-40.0, 40.0],
        "right_joint_7.pos": [-80.0, 80.0],
        "right_gripper.pos": [-65.0, 0.0],
        "left_joint_1.pos": [-75.0, 75.0],
        "left_joint_2.pos": [-90.0, 9.0],
        "left_joint_3.pos": [-85.0, 85.0],
        "left_joint_4.pos": [0.0, 135.0],
        "left_joint_5.pos": [-85.0, 85.0],
        "left_joint_6.pos": [-40.0, 40.0],
        "left_joint_7.pos": [-80.0, 80.0],
        "left_gripper.pos": [-65.0, 0.0],
    }
    return parse_safety_settings(
        {
            "safety_config_version": "test_safety_v1",
            "safety_config_verified": verified,
            **(
                {
                    "verified_by": "hardware_operator",
                    "verified_at": "2026-06-24T16:30:00+08:00",
                    "verification_basis": "test fixture verified safety config",
                }
                if verified
                else {}
            ),
            "driver_mismatch_atol": 1e-4,
            "mismatch_contamination_frames": 3,
            "tracking_error_persistence_frames": 3,
            "joints": {
                key: {
                    "hard_limit": hard_limits[key],
                    "soft_limit": hard_limits[key],
                    "deadband": 0.0,
                    "max_step": 4.0 if "gripper" in key else 2.0,
                    "max_velocity": 120.0 if "gripper" in key else 60.0,
                    "tracking_error_warning": 5.0,
                    "tracking_error_contamination": 10.0,
                    "tracking_error_freeze": 20.0,
                }
                for key in EXPECTED_FOLLOWER_ACTION_KEYS
            },
        }
    )


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


def test_control_step_safety_precedes_shared_effective_command(
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
            "compat_mapping_verified": True,
        },
        cameras={},
        control={},
        safety=make_safety_settings(),
    )
    controller = WorkbenchController(settings, session_id="safe-command-test")
    dataset = FakeRecordingDataset()

    class FullRobot:
        is_connected = True

        def __init__(self) -> None:
            self.sent_actions: list[dict[str, float]] = []

        def get_observation(self) -> dict[str, float]:
            return {key: 0.0 for key in EXPECTED_FOLLOWER_ACTION_KEYS}

        def send_action(self, action: dict[str, float]) -> dict[str, float]:
            self.sent_actions.append(dict(action))
            return dict(action)

    class FullTeleop:
        is_connected = True

        def get_action(self) -> dict[str, float]:
            action = {key: 0.0 for key in EXPECTED_FOLLOWER_ACTION_KEYS}
            action["right_joint_1.pos"] = 100.0
            action["right_gripper.pos"] = 100.0
            return action

    robot = FullRobot()
    controller.robot = robot
    controller.teleop = FullTeleop()
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

    sent = robot.sent_actions[0]
    recorded = dataset.frames[0]["action"]
    assert sent == recorded
    assert sent["right_joint_1.pos"] == pytest.approx(2.0)
    # Compatibility maps 100 -> -65 exactly once, then safety limits the first step to -4.
    assert sent["right_gripper.pos"] == pytest.approx(-4.0)
    assert controller.last_effective_command == sent


def test_persistent_driver_mismatch_contaminates_active_episode(
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
            "compat_mapping_verified": True,
        },
        cameras={},
        control={},
        safety=make_safety_settings(),
    )
    controller = WorkbenchController(settings, session_id="mismatch-test")

    class MismatchRobot:
        is_connected = True

        def get_observation(self) -> dict[str, float]:
            return {key: 0.0 for key in EXPECTED_FOLLOWER_ACTION_KEYS}

        def send_action(self, action: dict[str, float]) -> dict[str, float]:
            returned = dict(action)
            returned["left_joint_1.pos"] += 0.5
            return returned

    class FullTeleop:
        is_connected = True

        def get_action(self) -> dict[str, float]:
            return {key: 0.0 for key in EXPECTED_FOLLOWER_ACTION_KEYS}

    controller.robot = MismatchRobot()
    controller.teleop = FullTeleop()
    controller.dataset = FakeRecordingDataset()
    controller.recording = True
    controller.teleop_action_processor = lambda pair: dict(pair[0])
    controller.robot_action_processor = lambda pair: dict(pair[0])
    controller.robot_observation_processor = lambda obs: obs
    monkeypatch.setattr(
        controller_module,
        "build_dataset_frame",
        lambda features, values, prefix: {prefix: dict(values)},
    )

    for _ in range(3):
        controller._control_step()

    assert "persistent_driver_command_mismatch" in controller.current_contamination_reasons
    assert controller.current_command_validation == {
        "mismatch_frames": 3,
        "max_abs_error": pytest.approx(0.5),
        "affected_joints": ["left_joint_1.pos"],
        "max_consecutive_mismatch_frames": 3,
    }
    events = [
        json.loads(line)
        for line in (tmp_path / "sessions" / "mismatch-test" / "events.jsonl").read_text().splitlines()
    ]
    assert [event["event"] for event in events].count("episode_contaminated") == 1


def test_persistent_follower_tracking_error_contaminates_without_rewriting_command(
    tmp_path: Path,
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
        safety=make_safety_settings(),
    )
    controller = WorkbenchController(settings, session_id="tracking-test")
    controller.recording = True
    target = {key: 0.0 for key in EXPECTED_FOLLOWER_ACTION_KEYS}
    qpos = dict(target)
    previous = dict(target)
    target["left_joint_1.pos"] = 12.0
    previous["left_joint_1.pos"] = 12.0
    result = controller.safety_processor.process(
        follower_target=target,
        follower_qpos=qpos,
        previous_effective=previous,
        dt_s=1 / 30,
    )

    for _ in range(3):
        controller._track_follower_tracking(result)

    assert result.command["left_joint_1.pos"] == 12.0
    assert "persistent_follower_tracking_error" in controller.current_contamination_reasons
    assert "follower_tracking_error" in controller.current_dq_reasons
    assert controller.current_tracking_validation == {
        "warning_frames": 3,
        "contamination_frames": 3,
        "freeze_frames": 0,
        "max_abs_error": pytest.approx(12.0),
        "affected_joints": ["left_joint_1.pos"],
        "max_consecutive_contamination_frames": 3,
    }
    events = [
        json.loads(line)
        for line in (tmp_path / "sessions" / "tracking-test" / "events.jsonl").read_text().splitlines()
    ]
    assert [event["event"] for event in events].count("follower_tracking_warning") == 1


def test_tracking_freeze_sends_hold_stops_episode_and_locks_collection(
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
        safety=make_safety_settings(),
    )
    controller = WorkbenchController(settings, session_id="freeze-test")
    dataset = FakeRecordingDataset()

    class FreezeRobot:
        is_connected = True

        def __init__(self) -> None:
            self.sent_actions: list[dict[str, float]] = []

        def get_observation(self) -> dict[str, float]:
            obs = {key: 0.0 for key in EXPECTED_FOLLOWER_ACTION_KEYS}
            obs["right_joint_4.pos"] = -1.0
            return obs

        def send_action(self, action: dict[str, float]) -> dict[str, float]:
            self.sent_actions.append(dict(action))
            return dict(action)

    class FreezeTeleop:
        is_connected = True

        def get_action(self) -> dict[str, float]:
            action = {key: 0.0 for key in EXPECTED_FOLLOWER_ACTION_KEYS}
            action["right_joint_4.pos"] = 30.0
            return action

    robot = FreezeRobot()
    controller.robot = robot
    controller.teleop = FreezeTeleop()
    controller.dataset = dataset
    controller.recording = True
    controller.last_effective_command = {
        key: (25.0 if key == "right_joint_4.pos" else 0.0) for key in EXPECTED_FOLLOWER_ACTION_KEYS
    }
    controller.last_effective_time_ns = time.monotonic_ns()
    controller.teleop_action_processor = lambda pair: dict(pair[0])
    controller.robot_action_processor = lambda pair: dict(pair[0])
    controller.robot_observation_processor = lambda obs: obs
    stopped: list[bool] = []

    def stop_episode() -> dict:
        stopped.append(True)
        controller.recording = False
        return {"ok": True}

    monkeypatch.setattr(controller, "stop_episode", stop_episode)
    monkeypatch.setattr(
        controller_module,
        "build_dataset_frame",
        lambda features, values, prefix: {prefix: dict(values)},
    )

    controller._control_step()

    assert robot.sent_actions[-1]["right_joint_4.pos"] == 0.0
    assert stopped == [True]
    assert controller.safety_frozen is True
    assert controller.state == "frozen"
    assert "follower_tracking_freeze" in controller.current_contamination_reasons
    assert dataset.frames == []
    with pytest.raises(RuntimeError, match="frozen"):
        controller.start_episode("blocked")


def test_stop_episode_persists_safety_metadata_and_blocks_unverified_acceptance(
    tmp_path: Path,
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
            "compat_mapping_verified": True,
        },
        cameras={},
        control={},
        safety=make_safety_settings(verified=False),
    )
    controller = WorkbenchController(settings, session_id="safety-metadata-test")
    fake_dataset = FakeDataset()
    controller.dataset = fake_dataset
    controller.recording = True
    controller.current_episode_index = 0
    controller.current_task = "test task"
    controller.current_started_at = "2026-06-24T00:00:00+08:00"
    controller.current_frame_count = 3
    controller.current_record_start = 1.0
    controller.current_contamination_reasons = {"safety_config_unverified"}
    controller.ready_state = "verified"
    controller.latest_ready_result = {"ok": True, "path": "config/ready_path.json", "max_abs_error": 0.5}
    controller._finalize_dataset = lambda: setattr(controller, "dataset", None)

    controller.stop_episode()
    labeled = controller.label_episode("success")

    record = labeled["record"]
    assert record["safety_config_version"] == "test_safety_v1"
    assert record["safety_config_verified"] is False
    assert record["hard_limits"]["left_gripper.pos"] == [-65.0, 0.0]
    assert record["tracking_error_warning"]["left_joint_1.pos"] == 5.0
    assert record["tracking_error_contamination"]["left_joint_1.pos"] == 10.0
    assert record["tracking_error_freeze"]["left_joint_1.pos"] == 20.0
    assert record["tracking_error_persistence_frames"] == 3
    assert record["command_validation"]["mismatch_frames"] == 0
    assert record["tracking_validation"]["warning_frames"] == 0
    assert record["ready_state"] == "verified"
    assert record["ready_result"]["path"] == "config/ready_path.json"
    assert record["contaminated"] is True
    assert record["contamination_reasons"] == ["safety_config_unverified"]
    assert record["dq_status"] == "fail"
    assert record["dq_reasons"] == ["safety_config_unverified"]
    assert "safety_config_unverified" in record["acceptance_reasons"]
    assert record["accepted"] is False


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


def test_empty_dataset_root_is_removed_before_lerobot_create(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "dataset"
    root.mkdir()
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
    controller = WorkbenchController(settings, session_id="empty-root-test")
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

    class FakeDatasetFactory:
        @staticmethod
        def create(*args, **kwargs):
            assert not Path(kwargs["root"]).exists()
            return object()

    class FakeVideoManager:
        def __init__(self, dataset):
            self.dataset = dataset

        def __enter__(self):
            return self

    monkeypatch.setattr(controller_module, "LeRobotDataset", FakeDatasetFactory)
    monkeypatch.setattr(controller_module, "VideoEncodingManager", FakeVideoManager)

    controller._ensure_dataset()

    assert (root / "dataset_manifest.json").exists()


def test_dataset_status_reports_root_lifecycle_states(tmp_path: Path) -> None:
    settings = WorkbenchSettings(
        workspace_root=tmp_path,
        session_root=tmp_path / "sessions",
        dataset=DatasetSettings(
            repo_id="local/test",
            root=tmp_path / "missing",
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
        safety=make_safety_settings(),
    )
    controller = WorkbenchController(settings, session_id="dataset-status-test")

    missing = controller.dataset_status()
    assert missing["root_state"] == "root_missing"
    assert missing["can_create"] is True

    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    empty = controller.dataset_status(root=empty_root)
    assert empty["root_state"] == "empty_root"
    assert empty["can_create"] is True

    legacy_root = tmp_path / "legacy"
    (legacy_root / "meta").mkdir(parents=True)
    (legacy_root / "meta" / "info.json").write_text("{}")
    legacy = controller.dataset_status(root=legacy_root)
    assert legacy["root_state"] == "legacy_unknown"
    assert legacy["can_append"] is False

    appendable_root = tmp_path / "appendable"
    manifest = controller._dataset_manifest_for(
        root=appendable_root,
        repo_id="local/appendable",
    )
    manifest.ensure_initialized()
    appendable = controller.dataset_status(root=appendable_root, repo_id="local/appendable")
    assert appendable["root_state"] == "appendable"
    assert appendable["can_append"] is True

    mismatch = controller.dataset_status(root=appendable_root, repo_id="local/other")
    assert mismatch["root_state"] == "semantic_mismatch"
    assert mismatch["can_append"] is False


def test_dataset_new_and_switch_update_runtime_settings_when_idle(tmp_path: Path) -> None:
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
    controller = WorkbenchController(settings, session_id="dataset-api-test")
    controller.state = "idle"

    created = controller.new_dataset("smoke")

    assert created["ok"] is True
    assert created["dataset"]["root_state"] == "root_missing"
    assert controller.settings.dataset.root.name.endswith("smoke")

    target = tmp_path / "switched"
    switched = controller.switch_dataset(
        root=str(target),
        repo_id="local/switched",
        session_root=str(tmp_path / "switch-sessions"),
    )

    assert switched["ok"] is True
    assert switched["dataset"]["root"] == str(target)
    assert controller.settings.dataset.repo_id == "local/switched"
    assert controller.settings.session_root == tmp_path / "switch-sessions"

    controller.recording = True
    with pytest.raises(RuntimeError, match="while recording"):
        controller.switch_dataset(root=str(tmp_path / "other"), repo_id="local/other")


def test_start_episode_requires_verified_ready_when_configured(tmp_path: Path) -> None:
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
        control={"default_task": "test task"},
        ready={"require_ready_for_recording": True},
    )
    controller = WorkbenchController(settings, session_id="ready-gate-test")
    controller.state = "idle"

    with pytest.raises(RuntimeError, match="Move to Ready"):
        controller.start_episode("test task")


def test_move_to_ready_marks_ready_verified_and_allows_recording_gate(tmp_path: Path, monkeypatch) -> None:
    ready_path = tmp_path / "ready_path.json"
    ready_path.write_text(
        json.dumps(
            {
                "units": "degrees",
                "waypoints": [
                    {
                        "name": "ready",
                        "duration_s": 0.1,
                        "action": {"left_joint_1.pos": 1.0, "right_joint_1.pos": -1.0},
                    }
                ],
            }
        )
    )
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
        control={"default_task": "test task"},
        ready={
            "path": str(ready_path),
            "fps": 4,
            "tolerance": 0.01,
            "settle_time_s": 0.0,
            "require_ready_for_recording": True,
        },
    )
    controller = WorkbenchController(settings, session_id="ready-move-test")
    controller.state = "idle"

    class ReadyRobot:
        name = "fake_robot"
        action_features = {"left_joint_1.pos": float, "right_joint_1.pos": float}

        def __init__(self) -> None:
            self.qpos = {"left_joint_1.pos": 0.0, "right_joint_1.pos": 0.0}
            self.sent = []

        def observe(self):
            return dict(self.qpos)

        def send_action(self, action):
            self.sent.append(dict(action))
            self.qpos.update(action)
            return dict(action)

    controller.robot = ReadyRobot()
    monkeypatch.setattr(controller_module.precise_sleep, "__call__", lambda _: None, raising=False)

    result = controller.move_to_ready(sleep=lambda _: None)

    assert result["ok"] is True
    assert controller.ready_state == "verified"
    assert controller.latest_ready_result["ok"] is True


def test_start_episode_requires_sync_when_configured(tmp_path: Path) -> None:
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
        sync={"require_sync_for_recording": True},
    )
    controller = WorkbenchController(settings, session_id="sync-gate-test")
    controller.ready_state = "verified"

    with pytest.raises(RuntimeError, match="Sync Master"):
        controller.start_episode("test task")


def test_move_to_ready_invalidates_existing_sync(tmp_path: Path, monkeypatch) -> None:
    ready_path = tmp_path / "ready_path.json"
    ready_path.write_text(
        json.dumps(
            {
                "units": "degrees",
                "waypoints": [
                    {
                        "name": "ready",
                        "duration_s": 0.1,
                        "action": {"left_joint_1.pos": 1.0, "right_joint_1.pos": -1.0},
                    }
                ],
            }
        )
    )
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
        ready={
            "path": str(ready_path),
            "fps": 4,
            "tolerance": 0.01,
            "settle_time_s": 0.0,
        },
        sync={"require_sync_for_recording": True},
    )
    controller = WorkbenchController(settings, session_id="sync-invalidated-test")
    controller.state = "idle"

    class ReadyRobot:
        is_connected = True
        action_features = {"left_joint_1.pos": float, "right_joint_1.pos": float}

        def __init__(self) -> None:
            self.qpos = {"left_joint_1.pos": 0.0, "right_joint_1.pos": 0.0}

        def get_observation(self) -> dict[str, float]:
            return dict(self.qpos)

        def send_action(self, action: dict[str, float]) -> dict[str, float]:
            self.qpos.update(action)
            return dict(action)

    controller.robot = ReadyRobot()
    controller.sync_state = "valid"
    controller.latest_sync_result = {"ok": True}

    result = controller.move_to_ready(sleep=lambda _: None)

    assert result["ok"] is True
    assert controller.ready_state == "verified"
    assert controller.sync_state == "invalid"
    assert controller.latest_sync_result is None


def test_relative_sync_first_command_stays_at_follower_ready_pose(
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
        teleop={"id": "teleop", "mode": "relative_joint_offset"},
        cameras={},
        control={"default_task": "test task"},
        sync={"require_sync_for_recording": True},
    )
    controller = WorkbenchController(settings, session_id="relative-sync-test")
    dataset = FakeRecordingDataset()

    class ReadyPoseRobot:
        is_connected = True

        def __init__(self) -> None:
            self.qpos = {"left_joint_1.pos": 15.0, "right_joint_1.pos": -12.0}
            self.sent_actions: list[dict[str, float]] = []

        def get_observation(self) -> dict[str, float]:
            return dict(self.qpos)

        def send_action(self, action: dict[str, float]) -> dict[str, float]:
            self.sent_actions.append(dict(action))
            self.qpos.update(action)
            return dict(action)

    class OriginMasterTeleop:
        is_connected = True

        def get_action(self) -> dict[str, float]:
            return {"left_joint_1.pos": 0.0, "right_joint_1.pos": 0.0}

    robot = ReadyPoseRobot()
    controller.robot = robot
    controller.teleop = OriginMasterTeleop()
    controller.dataset = dataset
    controller.ready_state = "verified"
    controller.teleop_action_processor = lambda pair: dict(pair[0])
    controller.robot_action_processor = lambda pair: dict(pair[0])
    controller.robot_observation_processor = lambda obs: obs
    monkeypatch.setattr(
        controller_module,
        "build_dataset_frame",
        lambda features, values, prefix: {prefix: dict(values)},
    )

    sync_result = controller.sync_master()
    controller.recording = True
    controller._control_step()

    assert sync_result["ok"] is True
    assert controller.sync_state == "valid"
    assert robot.sent_actions == [{"left_joint_1.pos": 15.0, "right_joint_1.pos": -12.0}]
    assert dataset.frames[0]["action"] == {"left_joint_1.pos": 15.0, "right_joint_1.pos": -12.0}


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
