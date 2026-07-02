from __future__ import annotations

from workbench.xlerobot_profile import (
    XLEROBOT_SO101_ACTION_NAMES,
    XLEROBOT_SO101_ACTION_SCHEMA_VERSION,
    XLEROBOT_SO101_ACTION_UNITS,
    XLEROBOT_SO101_CAMERA_KEYS,
    XLEROBOT_SO101_CAMERA_SCHEMA_VERSION,
    XLEROBOT_SO101_CONTRACT_VERSION,
    XLEROBOT_SO101_DATASET_SCHEMA_VERSION,
    XLEROBOT_SO101_PROFILE_ID,
    XLEROBOT_SO101_STATE_NAMES,
    XLEROBOT_SO101_STATE_SCHEMA_VERSION,
    XLEROBOT_SO101_STATE_UNITS,
    xlerobot_so101_contract_metadata,
)


def test_xlerobot_so101_action_schema_is_left_first_12d_normalized() -> None:
    assert XLEROBOT_SO101_ACTION_SCHEMA_VERSION == "xlerobot_so101_action_v1"
    assert XLEROBOT_SO101_ACTION_UNITS == "normalized_lerobot_motor_units"
    assert XLEROBOT_SO101_ACTION_NAMES == (
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


def test_xlerobot_so101_state_and_camera_schema_are_frozen() -> None:
    assert XLEROBOT_SO101_DATASET_SCHEMA_VERSION == "xlerobot_so101_workbench_v1"
    assert XLEROBOT_SO101_STATE_SCHEMA_VERSION == "xlerobot_so101_state_v1"
    assert XLEROBOT_SO101_STATE_UNITS == "normalized_lerobot_motor_units"
    assert XLEROBOT_SO101_STATE_NAMES == XLEROBOT_SO101_ACTION_NAMES
    assert XLEROBOT_SO101_CAMERA_SCHEMA_VERSION == "xlerobot_so101_3rgb_v1"
    assert XLEROBOT_SO101_CAMERA_KEYS == ("main", "wrist_left", "wrist_right")


def test_xlerobot_so101_contract_metadata_contains_training_action_semantics() -> None:
    metadata = xlerobot_so101_contract_metadata(
        compat_mapping_version="so101_leader_to_xlerobot_follower_v1_candidate",
        safety_config_version="xlerobot_so101_safety_v1_candidate",
        ready_required_for_collection=True,
        sync_required_for_collection=True,
    )

    assert metadata["contract_version"] == XLEROBOT_SO101_CONTRACT_VERSION
    assert metadata["robot_profile_id"] == XLEROBOT_SO101_PROFILE_ID
    assert metadata["action_dim"] == 12
    assert metadata["state_dim"] == 12
    assert metadata["action_names"] == list(XLEROBOT_SO101_ACTION_NAMES)
    assert metadata["state_names"] == list(XLEROBOT_SO101_STATE_NAMES)
    assert metadata["action_units"] == "normalized_lerobot_motor_units"
    assert metadata["action_semantics"] == "follower_effective_command"
    assert "follower-space effective command" in metadata["action_description_en"]
