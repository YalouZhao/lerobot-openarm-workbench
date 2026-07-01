from __future__ import annotations

from typing import Any, Mapping


XLEROBOT_SO101_PROFILE_ID = "xlerobot_so101_dual_v1"
XLEROBOT_SO101_ROBOT_FAMILY = "so101_compatible"
XLEROBOT_SO101_ROBOT_MODEL = "xlerobot"
XLEROBOT_SO101_ROBOT_DRIVER = "SOFollower"
XLEROBOT_SO101_TELEOP_DRIVER = "SOLeader"
XLEROBOT_SO101_DATASET_SCHEMA_VERSION = "xlerobot_so101_workbench_v1"
XLEROBOT_SO101_ACTION_SCHEMA_VERSION = "xlerobot_so101_action_v1"
XLEROBOT_SO101_STATE_SCHEMA_VERSION = "xlerobot_so101_state_v1"
XLEROBOT_SO101_CAMERA_SCHEMA_VERSION = "xlerobot_so101_3rgb_v1"
XLEROBOT_SO101_CONTRACT_VERSION = "xlerobot_so101_dataset_action_contract_v1"
XLEROBOT_SO101_ACTION_UNITS = "normalized_lerobot_motor_units"
XLEROBOT_SO101_STATE_UNITS = "normalized_lerobot_motor_units"
XLEROBOT_SO101_ACTION_SEMANTICS = "follower_effective_command"
XLEROBOT_SO101_ACTION_SPACE = "joint_position"
XLEROBOT_SO101_CONTROL_MODE = "joint_position_target"
XLEROBOT_SO101_TELEOP_MODE = "relative_joint_offset"
XLEROBOT_SO101_COMPAT_MAPPING_CANDIDATE = "so101_leader_to_xlerobot_follower_v1_candidate"
XLEROBOT_SO101_SAFETY_CANDIDATE = "xlerobot_so101_safety_v1_candidate"

XLEROBOT_SO101_ACTION_NAMES = (
    "left_shoulder_pan.pos",
    "left_shoulder_lift.pos",
    "left_elbow_flex.pos",
    "left_wrist_flex.pos",
    "left_wrist_roll.pos",
    "left_gripper.pos",
    "right_shoulder_pan.pos",
    "right_shoulder_lift.pos",
    "right_elbow_flex.pos",
    "right_wrist_flex.pos",
    "right_wrist_roll.pos",
    "right_gripper.pos",
)
XLEROBOT_SO101_STATE_NAMES = XLEROBOT_SO101_ACTION_NAMES
XLEROBOT_SO101_CAMERA_KEYS = ("main", "wrist_left", "wrist_right")


def is_xlerobot_so101_schema(dataset_schema_version: str) -> bool:
    return dataset_schema_version == XLEROBOT_SO101_DATASET_SCHEMA_VERSION


def canonical_xlerobot_so101_dataset_fields() -> dict[str, Any]:
    return {
        "action_schema_version": XLEROBOT_SO101_ACTION_SCHEMA_VERSION,
        "state_schema_version": XLEROBOT_SO101_STATE_SCHEMA_VERSION,
        "camera_schema_version": XLEROBOT_SO101_CAMERA_SCHEMA_VERSION,
        "action_dim": len(XLEROBOT_SO101_ACTION_NAMES),
        "state_dim": len(XLEROBOT_SO101_STATE_NAMES),
        "action_units": XLEROBOT_SO101_ACTION_UNITS,
        "state_units": XLEROBOT_SO101_STATE_UNITS,
        "action_names": XLEROBOT_SO101_ACTION_NAMES,
        "state_names": XLEROBOT_SO101_STATE_NAMES,
    }


def validate_xlerobot_so101_config_payload(payload: Mapping[str, Any]) -> None:
    dataset = payload.get("dataset", {})
    robot = payload.get("robot", {})
    teleop = payload.get("teleop", {})
    cameras = payload.get("cameras", {})
    ready = payload.get("ready", {})
    sync = payload.get("sync", {})

    _expect(payload, "robot_profile_id", XLEROBOT_SO101_PROFILE_ID)
    _expect(dataset, "dataset_schema_version", XLEROBOT_SO101_DATASET_SCHEMA_VERSION)
    _expect(dataset, "action_schema_version", XLEROBOT_SO101_ACTION_SCHEMA_VERSION)
    _expect(dataset, "state_schema_version", XLEROBOT_SO101_STATE_SCHEMA_VERSION)
    _expect(dataset, "camera_schema_version", XLEROBOT_SO101_CAMERA_SCHEMA_VERSION)
    _expect(dataset, "action_semantics", XLEROBOT_SO101_ACTION_SEMANTICS)
    _expect(dataset, "action_dim", len(XLEROBOT_SO101_ACTION_NAMES))
    _expect(dataset, "action_units", XLEROBOT_SO101_ACTION_UNITS)
    _expect_optional(dataset, "state_dim", len(XLEROBOT_SO101_STATE_NAMES))
    _expect_optional(dataset, "state_units", XLEROBOT_SO101_STATE_UNITS)
    _expect_optional_sequence(dataset, "action_names", XLEROBOT_SO101_ACTION_NAMES)
    _expect_optional_sequence(dataset, "state_names", XLEROBOT_SO101_STATE_NAMES)

    _expect(robot, "type", "bi_so_follower")
    _expect(robot, "id", "xlerobot_follower", label="robot.id", verb="stay")
    _expect(teleop, "type", "bi_so_leader")
    _expect(teleop, "id", "so101_leader", label="teleop.id")
    _expect(teleop, "mode", XLEROBOT_SO101_TELEOP_MODE, label="teleop.mode")
    _expect(teleop, "apply_openarm_mini_compat_mapping", False)

    if set(cameras) != set(XLEROBOT_SO101_CAMERA_KEYS):
        raise ValueError(
            "xlerobot_so101 cameras must be exactly "
            f"{sorted(XLEROBOT_SO101_CAMERA_KEYS)}, got {sorted(cameras)}"
        )
    if ready.get("require_ready_for_recording") is not True:
        raise ValueError("xlerobot_so101 ready.require_ready_for_recording must be true")
    if sync.get("require_sync_for_recording") is not True:
        raise ValueError("xlerobot_so101 sync.require_sync_for_recording must be true")
    if list(sync.get("required_arms", [])) != ["left", "right"]:
        raise ValueError("xlerobot_so101 sync.required_arms must be ['left', 'right']")


def xlerobot_so101_semantic_metadata(settings: Any) -> dict[str, Any]:
    return {
        "robot_profile_id": XLEROBOT_SO101_PROFILE_ID,
        "robot_family": XLEROBOT_SO101_ROBOT_FAMILY,
        "robot_model": XLEROBOT_SO101_ROBOT_MODEL,
        "robot_driver": XLEROBOT_SO101_ROBOT_DRIVER,
        "teleop_driver": XLEROBOT_SO101_TELEOP_DRIVER,
        "dataset_schema_version": XLEROBOT_SO101_DATASET_SCHEMA_VERSION,
        "action_schema_version": XLEROBOT_SO101_ACTION_SCHEMA_VERSION,
        "state_schema_version": XLEROBOT_SO101_STATE_SCHEMA_VERSION,
        "camera_schema_version": XLEROBOT_SO101_CAMERA_SCHEMA_VERSION,
        "action_dim": len(XLEROBOT_SO101_ACTION_NAMES),
        "state_dim": len(XLEROBOT_SO101_STATE_NAMES),
        "action_names": list(XLEROBOT_SO101_ACTION_NAMES),
        "state_names": list(XLEROBOT_SO101_STATE_NAMES),
        "action_units": XLEROBOT_SO101_ACTION_UNITS,
        "state_units": XLEROBOT_SO101_STATE_UNITS,
        "action_semantics": XLEROBOT_SO101_ACTION_SEMANTICS,
        "control_mode": XLEROBOT_SO101_CONTROL_MODE,
        "action_space": XLEROBOT_SO101_ACTION_SPACE,
        "camera_keys": list(XLEROBOT_SO101_CAMERA_KEYS),
        "compat_mapping_version": settings.compat_mapping_version,
        "safety_config_version": settings.safety.safety_config_version,
        "ready_required_for_collection": bool(settings.ready.get("require_ready_for_recording")),
        "sync_required_for_collection": bool(settings.sync.get("require_sync_for_recording")),
    }


def xlerobot_so101_contract_metadata(
    *,
    compat_mapping_version: str,
    safety_config_version: str,
    ready_required_for_collection: bool,
    sync_required_for_collection: bool,
) -> dict[str, Any]:
    metadata = {
        **xlerobot_so101_semantic_metadata(
            _ContractSettings(
                compat_mapping_version=compat_mapping_version,
                safety_config_version=safety_config_version,
                ready_required_for_collection=ready_required_for_collection,
                sync_required_for_collection=sync_required_for_collection,
            )
        ),
        "contract_version": XLEROBOT_SO101_CONTRACT_VERSION,
        "dataset_action_source": "effective_command",
        "action_description_en": (
            "The action column is the follower-space effective command in normalized "
            "LeRobot motor units after relative_joint_offset and Workbench safety processing."
        ),
        "action_description_zh": (
            "训练包中的 action 是经过 relative_joint_offset 和 Workbench safety 后生成的 "
            "XLeRobot follower normalized joint position target。"
        ),
    }
    return metadata


class _ContractSafety:
    def __init__(self, safety_config_version: str):
        self.safety_config_version = safety_config_version


class _ContractSettings:
    def __init__(
        self,
        *,
        compat_mapping_version: str,
        safety_config_version: str,
        ready_required_for_collection: bool,
        sync_required_for_collection: bool,
    ):
        self.compat_mapping_version = compat_mapping_version
        self.safety = _ContractSafety(safety_config_version)
        self.ready = {"require_ready_for_recording": ready_required_for_collection}
        self.sync = {"require_sync_for_recording": sync_required_for_collection}


def _expect(
    mapping: Mapping[str, Any],
    key: str,
    expected: Any,
    *,
    label: str | None = None,
    verb: str = "be",
) -> None:
    actual = mapping.get(key)
    name = label or key
    if actual != expected:
        raise ValueError(f"{name} must {verb} {expected!r}, got {actual!r}")


def _expect_optional(mapping: Mapping[str, Any], key: str, expected: Any) -> None:
    if key in mapping:
        _expect(mapping, key, expected)


def _expect_optional_sequence(mapping: Mapping[str, Any], key: str, expected: tuple[str, ...]) -> None:
    if key in mapping and tuple(mapping[key]) != expected:
        raise ValueError(f"{key} must be {list(expected)!r}, got {mapping[key]!r}")
