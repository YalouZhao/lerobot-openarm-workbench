from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from workbench.ready_controller import (  # noqa: E402
    ReadyController,
    ReadySettings,
    smoothstep,
)


def write_ready_path(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "units": "degrees",
                "waypoints": [
                    {
                        "name": "lift",
                        "duration_s": 1.0,
                        "action": {
                            "left_joint_1.pos": 10.0,
                            "right_joint_1.pos": -10.0,
                            "ignored.torque": 99.0,
                        },
                    },
                    {
                        "name": "ready",
                        "duration_s": 1.0,
                        "action": {
                            "left_joint_1.pos": 20.0,
                            "right_joint_1.pos": -20.0,
                        },
                    },
                ],
            }
        )
    )


class FakeRobot:
    name = "fake_robot"
    action_features = {"left_joint_1.pos": float, "right_joint_1.pos": float}

    def __init__(self) -> None:
        self.qpos = {"left_joint_1.pos": 0.0, "right_joint_1.pos": 0.0}
        self.sent: list[dict[str, float]] = []

    def observe(self) -> dict[str, float]:
        return dict(self.qpos)

    def send_action(self, action: dict[str, float]) -> dict[str, float]:
        self.sent.append(dict(action))
        self.qpos.update(action)
        return dict(action)


class GetObservationOnlyRobot(FakeRobot):
    def observe(self) -> dict[str, float]:
        raise AttributeError("observe is not available")

    def get_observation(self) -> dict[str, float]:
        return dict(self.qpos)


def test_smoothstep_has_zero_slope_endpoints() -> None:
    assert smoothstep(0.0) == 0.0
    assert smoothstep(1.0) == 1.0
    assert smoothstep(0.5) == pytest.approx(0.5)
    assert smoothstep(-1.0) == 0.0
    assert smoothstep(2.0) == 1.0


def test_ready_controller_executes_waypoints_and_verifies_final_pose(tmp_path: Path) -> None:
    path = tmp_path / "ready_path.json"
    write_ready_path(path)
    robot = FakeRobot()
    controller = ReadyController(
        ReadySettings(
            path=path,
            fps=4,
            tolerance=0.01,
            settle_time_s=0.0,
            verify_after_move=True,
        )
    )

    result = controller.move_to_ready(robot, sleep=lambda _: None)

    assert result.ok is True
    assert result.path == str(path)
    assert result.final_target == {"left_joint_1.pos": 20.0, "right_joint_1.pos": -20.0}
    assert result.max_abs_error == 0.0
    assert len(robot.sent) >= 8
    assert robot.sent[-1] == result.final_target


def test_ready_controller_supports_lerobot_get_observation_api(tmp_path: Path) -> None:
    path = tmp_path / "ready_path.json"
    write_ready_path(path)
    robot = GetObservationOnlyRobot()
    controller = ReadyController(
        ReadySettings(
            path=path,
            fps=4,
            tolerance=0.01,
            settle_time_s=0.0,
        )
    )

    result = controller.move_to_ready(robot, sleep=lambda _: None)

    assert result.ok is True
    assert result.final_target["left_joint_1.pos"] == 20.0


def test_ready_controller_rejects_missing_required_action_keys(tmp_path: Path) -> None:
    path = tmp_path / "ready_path.json"
    path.write_text(
        json.dumps(
            {
                "units": "degrees",
                "waypoints": [
                    {"name": "bad", "duration_s": 1.0, "action": {"left_joint_1.pos": 1.0}},
                ],
            }
        )
    )
    controller = ReadyController(ReadySettings(path=path, fps=4, tolerance=0.01))

    with pytest.raises(KeyError, match="missing keys"):
        controller.move_to_ready(FakeRobot(), sleep=lambda _: None)


def test_ready_controller_reports_failed_final_verification(tmp_path: Path) -> None:
    path = tmp_path / "ready_path.json"
    write_ready_path(path)
    robot = FakeRobot()

    def lagging_send(action: dict[str, float]) -> dict[str, float]:
        robot.sent.append(dict(action))
        robot.qpos = {key: value * 0.5 for key, value in action.items()}
        return dict(action)

    robot.send_action = lagging_send  # type: ignore[method-assign]
    controller = ReadyController(ReadySettings(path=path, fps=4, tolerance=0.01, settle_time_s=0.0))

    result = controller.move_to_ready(robot, sleep=lambda _: None)

    assert result.ok is False
    assert result.max_abs_error == pytest.approx(10.0)
