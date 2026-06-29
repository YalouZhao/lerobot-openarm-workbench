from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "src" / "workbench" / "lerobot_compat.py"


def _load_compat(monkeypatch, *, legacy_exports: bool):
    modules = {
        "lerobot": types.ModuleType("lerobot"),
        "lerobot.datasets": types.ModuleType("lerobot.datasets"),
        "lerobot.datasets.lerobot_dataset": types.ModuleType("lerobot.datasets.lerobot_dataset"),
        "lerobot.datasets.pipeline_features": types.ModuleType("lerobot.datasets.pipeline_features"),
        "lerobot.datasets.utils": types.ModuleType("lerobot.datasets.utils"),
        "lerobot.datasets.video_utils": types.ModuleType("lerobot.datasets.video_utils"),
        "lerobot.utils": types.ModuleType("lerobot.utils"),
        "lerobot.utils.feature_utils": types.ModuleType("lerobot.utils.feature_utils"),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    class Dataset:
        def __init__(self, repo_id, **kwargs):
            self.repo_id = repo_id
            self.kwargs = kwargs

    class LegacyDataset(Dataset):
        @classmethod
        def resume(cls, repo_id, **kwargs):
            result = cls(repo_id, **kwargs)
            result.used_resume = True
            return result

    dataset_type = LegacyDataset if legacy_exports else Dataset
    marker = object()
    if legacy_exports:
        modules["lerobot.datasets"].LeRobotDataset = dataset_type
        modules["lerobot.datasets"].VideoEncodingManager = marker
        modules["lerobot.datasets"].aggregate_pipeline_dataset_features = marker
        modules["lerobot.datasets"].create_initial_features = marker
        modules["lerobot.utils.feature_utils"].build_dataset_frame = marker
        modules["lerobot.utils.feature_utils"].combine_feature_dicts = marker
    else:
        modules["lerobot.datasets.lerobot_dataset"].LeRobotDataset = dataset_type
        modules["lerobot.datasets.video_utils"].VideoEncodingManager = marker
        modules["lerobot.datasets.pipeline_features"].aggregate_pipeline_dataset_features = marker
        modules["lerobot.datasets.pipeline_features"].create_initial_features = marker
        modules["lerobot.datasets.utils"].build_dataset_frame = marker
        modules["lerobot.datasets.utils"].combine_feature_dicts = marker

    spec = importlib.util.spec_from_file_location("workbench_test_lerobot_compat", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, dataset_type


def test_imports_lerobot_04_module_locations(monkeypatch) -> None:
    compat, dataset_type = _load_compat(monkeypatch, legacy_exports=False)

    assert compat.LeRobotDataset is dataset_type


def test_resume_uses_constructor_when_classmethod_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    compat, _ = _load_compat(monkeypatch, legacy_exports=False)

    dataset = compat.resume_lerobot_dataset("local/test", root=tmp_path, vcodec="h264")

    assert dataset.repo_id == "local/test"
    assert dataset.kwargs == {"root": tmp_path, "vcodec": "h264"}


def test_resume_lerobot_04_starts_image_writer_outside_constructor(monkeypatch, tmp_path: Path) -> None:
    compat, _ = _load_compat(monkeypatch, legacy_exports=False)

    class Dataset04:
        def __init__(self, repo_id, root=None, vcodec="libsvtav1"):
            self.repo_id = repo_id
            self.root = root
            self.vcodec = vcodec
            self.writer_args = None

        def start_image_writer(self, num_processes=0, num_threads=4):
            self.writer_args = (num_processes, num_threads)

    compat.LeRobotDataset = Dataset04

    dataset = compat.resume_lerobot_dataset(
        "local/test",
        root=tmp_path,
        vcodec="h264",
        image_writer_processes=2,
        image_writer_threads=6,
    )

    assert dataset.root == tmp_path
    assert dataset.vcodec == "h264"
    assert dataset.writer_args == (2, 6)


def test_resume_uses_classmethod_when_available(monkeypatch, tmp_path: Path) -> None:
    compat, _ = _load_compat(monkeypatch, legacy_exports=True)

    dataset = compat.resume_lerobot_dataset("local/test", root=tmp_path)

    assert dataset.used_resume is True


def test_builds_lerobot_04_bimanual_config_with_arm_cameras(monkeypatch) -> None:
    compat, _ = _load_compat(monkeypatch, legacy_exports=False)

    @dataclass
    class ArmConfig:
        port: str
        side: str
        cameras: dict = field(default_factory=dict)

    @dataclass
    class BiConfig:
        left_arm_config: ArmConfig
        right_arm_config: ArmConfig
        id: str

    cameras = {"main": "main_cfg", "wrist_left": "left_cfg", "wrist_right": "right_cfg"}
    config, aliases = compat.make_bi_openarm_configuration(
        BiConfig,
        ArmConfig,
        robot_id="robot",
        left_arm={"port": "can1", "side": "left"},
        right_arm={"port": "can0", "side": "right"},
        cameras=cameras,
    )

    assert config.left_arm_config.cameras == {"main": "main_cfg", "wrist_left": "left_cfg"}
    assert config.right_arm_config.cameras == {"wrist_right": "right_cfg"}
    assert aliases == {
        "left_main": "main",
        "left_wrist_left": "wrist_left",
        "right_wrist_right": "wrist_right",
    }


def test_builds_lerobot_05_bimanual_config_with_top_level_cameras(monkeypatch) -> None:
    compat, _ = _load_compat(monkeypatch, legacy_exports=False)

    @dataclass
    class ArmConfig:
        port: str
        side: str

    @dataclass
    class BiConfig:
        left_arm_config: ArmConfig
        right_arm_config: ArmConfig
        id: str
        cameras: dict = field(default_factory=dict)

    cameras = {"main": "main_cfg", "wrist_left": "left_cfg", "wrist_right": "right_cfg"}
    config, aliases = compat.make_bi_openarm_configuration(
        BiConfig,
        ArmConfig,
        robot_id="robot",
        left_arm={"port": "can1", "side": "left"},
        right_arm={"port": "can0", "side": "right"},
        cameras=cameras,
    )

    assert config.cameras == cameras
    assert aliases == {}


def test_camera_adapter_restores_canonical_observation_keys(monkeypatch) -> None:
    compat, _ = _load_compat(monkeypatch, legacy_exports=False)

    class Robot:
        action_features = {
            "left_joint_1.pos": float,
            "left_joint_1.vel": float,
            "left_joint_1.torque": float,
            "right_joint_1.pos": float,
        }
        observation_features = {
            "left_joint_1.pos": float,
            "left_joint_1.vel": float,
            "left_joint_1.torque": float,
            "right_joint_1.pos": float,
            "left_main": (480, 640, 3),
            "left_wrist_left": (480, 640, 3),
            "right_wrist_right": (480, 640, 3),
        }

        def get_observation(self):
            return {
                "left_joint_1.pos": 1.0,
                "left_joint_1.vel": 2.0,
                "left_joint_1.torque": 3.0,
                "right_joint_1.pos": 4.0,
                "left_main": "main_frame",
                "left_wrist_left": "left_frame",
                "right_wrist_right": "right_frame",
            }

    robot = compat.adapt_bi_openarm_camera_keys(
        Robot(),
        {
            "left_main": "main",
            "left_wrist_left": "wrist_left",
            "right_wrist_right": "wrist_right",
        },
    )

    assert list(robot.observation_features) == [
        "right_joint_1.pos",
        "left_joint_1.pos",
        "main",
        "wrist_left",
        "wrist_right",
    ]
    assert list(robot.action_features) == ["right_joint_1.pos", "left_joint_1.pos"]
    assert robot.get_observation() == {
        "right_joint_1.pos": 4.0,
        "left_joint_1.pos": 1.0,
        "main": "main_frame",
        "wrist_left": "left_frame",
        "wrist_right": "right_frame",
    }
