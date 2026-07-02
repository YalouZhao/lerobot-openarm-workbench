from __future__ import annotations

import inspect
from typing import Any

from lerobot.robots import make_robot_from_config
from lerobot.teleoperators import make_teleoperator_from_config

from .config import WorkbenchSettings
from .controller import WorkbenchController
from .xlerobot_profile import XLEROBOT_SO101_ACTION_NAMES, XLEROBOT_SO101_PROFILE_ID


def build_xlerobot_so101_probe(settings: WorkbenchSettings) -> dict[str, Any]:
    """Return non-motion XLeRobot SO101 driver/schema facts.

    This function intentionally does not call ``connect()``, ``get_observation()``,
    ``get_action()``, or ``send_action()``. It only builds LeRobot config objects
    and inspects their static feature declarations.
    """

    controller = object.__new__(WorkbenchController)
    controller.settings = settings
    robot_cfg, camera_aliases = controller._make_bi_so_robot_configuration({})
    teleop_cfg = controller._make_bi_so_teleop_configuration()
    robot = make_robot_from_config(robot_cfg)
    teleop = make_teleoperator_from_config(teleop_cfg)

    robot_action_features = tuple(robot.action_features)
    robot_observation_features = tuple(
        key for key in robot.observation_features if key.endswith(".pos")
    )
    teleop_action_features = tuple(teleop.action_features)
    canonical = XLEROBOT_SO101_ACTION_NAMES

    return {
        "robot_profile_id": settings.robot_profile_id,
        "robot_type": settings.robot.get("type"),
        "robot_id": settings.robot.get("id"),
        "teleop_type": settings.teleop.get("type"),
        "teleop_id": settings.teleop.get("id"),
        "camera_aliases": dict(camera_aliases),
        "robot_max_relative_target": settings.robot.get("max_relative_target"),
        "canonical_action_names": list(canonical),
        "robot_action_features": list(robot_action_features),
        "robot_observation_position_features": list(robot_observation_features),
        "teleop_action_features": list(teleop_action_features),
        "robot_action_matches_canonical": robot_action_features == canonical,
        "robot_observation_matches_canonical": robot_observation_features == canonical,
        "teleop_action_matches_canonical": teleop_action_features == canonical,
        "driver_behavior": inspect_so101_driver_behavior(),
    }


def inspect_so101_driver_behavior() -> dict[str, Any]:
    from lerobot.robots.so_follower.so_follower import SOFollower

    source = inspect.getsource(SOFollower.send_action)
    return {
        "send_action_returns_sent_action": "return {f\"{motor}.pos\": val" in source,
        "send_action_uses_max_relative_target": "max_relative_target is not None" in source,
        "send_action_reads_present_position_for_internal_clamp": (
            "sync_read(\"Present_Position\")" in source
        ),
        "send_action_writes_goal_position": "sync_write(\"Goal_Position\"" in source,
        "workbench_config_disables_driver_step_clamp_when_max_relative_target_is_none": True,
        "notes": (
            "SOFollower.send_action returns the action actually written. If "
            "max_relative_target is not None, LeRobot clamps against Present_Position "
            "before sync_write. XLeRobot Workbench config keeps max_relative_target=None "
            "so Workbench safety remains the primary clamp path."
        ),
    }


def assert_xlerobot_probe_passes(probe: dict[str, Any]) -> None:
    if probe.get("robot_profile_id") != XLEROBOT_SO101_PROFILE_ID:
        raise ValueError("robot_profile_id mismatch")
    for field in (
        "robot_action_matches_canonical",
        "robot_observation_matches_canonical",
        "teleop_action_matches_canonical",
    ):
        if probe.get(field) is not True:
            raise ValueError(f"{field} is not true")
    driver = probe.get("driver_behavior") or {}
    for field in (
        "send_action_returns_sent_action",
        "send_action_uses_max_relative_target",
        "send_action_reads_present_position_for_internal_clamp",
        "send_action_writes_goal_position",
    ):
        if driver.get(field) is not True:
            raise ValueError(f"driver_behavior.{field} is not true")
    if probe.get("robot_max_relative_target") is not None:
        raise ValueError("robot.max_relative_target must be None for Phase B deployment")
