from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest


def _install_fake_lerobot_modules() -> None:
    modules = {
        "lerobot": types.ModuleType("lerobot"),
        "lerobot.robots": types.ModuleType("lerobot.robots"),
        "lerobot.robots.bi_openarm_follower": types.ModuleType("lerobot.robots.bi_openarm_follower"),
        "lerobot.robots.bi_openarm_follower.config_bi_openarm_follower": types.ModuleType(
            "lerobot.robots.bi_openarm_follower.config_bi_openarm_follower"
        ),
        "lerobot.robots.openarm_follower": types.ModuleType("lerobot.robots.openarm_follower"),
        "lerobot.robots.openarm_follower.config_openarm_follower": types.ModuleType(
            "lerobot.robots.openarm_follower.config_openarm_follower"
        ),
    }
    for name, module in modules.items():
        sys.modules.setdefault(name, module)

    sys.modules["lerobot.robots"].make_robot_from_config = lambda cfg: cfg

    @dataclass
    class FakeOpenArmFollowerConfigBase:
        port: str
        side: str | None = None

    @dataclass
    class FakeBiOpenArmFollowerConfig:
        left_arm_config: FakeOpenArmFollowerConfigBase
        right_arm_config: FakeOpenArmFollowerConfigBase

    sys.modules[
        "lerobot.robots.bi_openarm_follower.config_bi_openarm_follower"
    ].BiOpenArmFollowerConfig = FakeBiOpenArmFollowerConfig
    sys.modules[
        "lerobot.robots.openarm_follower.config_openarm_follower"
    ].OpenArmFollowerConfigBase = FakeOpenArmFollowerConfigBase


_install_fake_lerobot_modules()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

SCRIPT_PATH = PROJECT_ROOT / "scripts" / "move_to_ready.py"
spec = importlib.util.spec_from_file_location("move_to_ready", SCRIPT_PATH)
move_to_ready = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(move_to_ready)


def test_load_targets_prefers_waypoint_path_over_legacy_pose(tmp_path: Path) -> None:
    current = {"joint_1.pos": 0.0, "joint_2.pos": 10.0}
    pose_path = tmp_path / "ready_pose.json"
    path_path = tmp_path / "ready_path.json"
    pose_path.write_text(
        '{"action": {"joint_1.pos": 99.0, "joint_2.pos": 99.0}}\n',
        encoding="utf-8",
    )
    path_path.write_text(
        """
{
  "units": "degrees",
  "waypoints": [
    {
      "name": "lift_clear_table",
      "duration_s": 4,
      "action": {"joint_1.pos": 1.0, "joint_2.pos": 11.0}
    },
    {
      "name": "ready",
      "duration_s": 3,
      "action": {"joint_1.pos": 2.0, "joint_2.pos": 12.0}
    }
  ]
}
""",
        encoding="utf-8",
    )

    targets = move_to_ready.load_targets(current, pose_path, path_path)

    assert [target["name"] for target in targets] == ["lift_clear_table", "ready"]
    assert [target["duration_s"] for target in targets] == [4.0, 3.0]
    assert targets[0]["action"] == {"joint_1.pos": 1.0, "joint_2.pos": 11.0}


def test_append_waypoint_rejects_non_positive_duration(tmp_path: Path) -> None:
    settings = types.SimpleNamespace(robot={"id": "my_bimanual_openarm"})

    with pytest.raises(ValueError, match="duration_s must be positive"):
        move_to_ready.append_waypoint(
            tmp_path / "ready_path.json",
            "unsafe_jump",
            {"joint_1.pos": 0.0},
            0,
            settings,
        )


def test_copy_arm_action_copies_source_side_to_target_side() -> None:
    action = {
        "left_joint_1.pos": 0.0,
        "left_joint_2.pos": 0.0,
        "left_gripper.pos": 0.0,
        "right_joint_1.pos": 10.0,
        "right_joint_2.pos": 20.0,
        "right_gripper.pos": 30.0,
    }

    copied = move_to_ready.copy_arm_action(action, "right-to-left")

    assert copied["right_joint_1.pos"] == 10.0
    assert copied["right_joint_2.pos"] == 20.0
    assert copied["right_gripper.pos"] == 30.0
    assert copied["left_joint_1.pos"] == 10.0
    assert copied["left_joint_2.pos"] == 20.0
    assert copied["left_gripper.pos"] == 30.0


def test_mirror_arm_action_uses_openarm_default_signs() -> None:
    action = {
        "left_joint_1.pos": 0.0,
        "left_joint_2.pos": 0.0,
        "left_joint_3.pos": 0.0,
        "left_joint_4.pos": 0.0,
        "left_joint_5.pos": 0.0,
        "left_joint_6.pos": 0.0,
        "left_joint_7.pos": 0.0,
        "left_gripper.pos": 0.0,
        "right_joint_1.pos": 10.0,
        "right_joint_2.pos": 20.0,
        "right_joint_3.pos": 30.0,
        "right_joint_4.pos": 40.0,
        "right_joint_5.pos": 50.0,
        "right_joint_6.pos": 60.0,
        "right_joint_7.pos": 70.0,
        "right_gripper.pos": 30.0,
    }

    mirrored = move_to_ready.mirror_arm_action(action, "right-to-left")

    assert mirrored["right_joint_1.pos"] == 10.0
    assert mirrored["right_joint_2.pos"] == 20.0
    assert mirrored["right_gripper.pos"] == 30.0
    assert mirrored["left_joint_1.pos"] == -10.0
    assert mirrored["left_joint_2.pos"] == -20.0
    assert mirrored["left_joint_3.pos"] == -30.0
    assert mirrored["left_joint_4.pos"] == 40.0
    assert mirrored["left_joint_5.pos"] == -50.0
    assert mirrored["left_joint_6.pos"] == -60.0
    assert mirrored["left_joint_7.pos"] == -70.0
    assert mirrored["left_gripper.pos"] == 30.0


def test_parse_waypoint_specs_uses_names_and_durations() -> None:
    specs = move_to_ready.parse_waypoint_specs("lift:5,above:6.5,ready:4")

    assert specs == [("lift", 5.0), ("above", 6.5), ("ready", 4.0)]


def test_parse_waypoint_specs_rejects_non_positive_duration() -> None:
    with pytest.raises(ValueError, match="duration_s must be positive"):
        move_to_ready.parse_waypoint_specs("lift:0")


def test_build_robot_uses_current_bi_openarm_config_signature() -> None:
    settings = types.SimpleNamespace(
        robot={
            "id": "my_bimanual_openarm",
            "left_arm": {"port": "can1", "side": "left"},
            "right_arm": {"port": "can0", "side": "right"},
        }
    )

    cfg = move_to_ready.build_robot(settings)

    assert cfg.left_arm_config.port == "can1"
    assert cfg.right_arm_config.port == "can0"
