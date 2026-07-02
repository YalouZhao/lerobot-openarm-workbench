from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.config import load_settings
from workbench.xlerobot_profile import (
    XLEROBOT_SO101_ACTION_NAMES,
    XLEROBOT_SO101_PROFILE_ID,
    xlerobot_so101_semantic_metadata,
)


CONFIG_PATH = Path(__file__).parents[1] / "config" / "workbench_config.xlerobot_so101.json"


def _write_config(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "workbench_config.xlerobot_so101.json"
    path.write_text(json.dumps(payload))
    return path


def _payload() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def test_xlerobot_so101_config_loads_with_profile_and_schema_metadata() -> None:
    settings = load_settings(CONFIG_PATH)

    assert settings.robot_profile_id == XLEROBOT_SO101_PROFILE_ID
    assert settings.dataset.dataset_schema_version == "xlerobot_so101_workbench_v1"
    assert settings.dataset.action_schema_version == "xlerobot_so101_action_v1"
    assert settings.dataset.state_schema_version == "xlerobot_so101_state_v1"
    assert settings.dataset.camera_schema_version == "xlerobot_so101_3rgb_v1"
    assert settings.dataset.action_dim == 12
    assert settings.dataset.state_dim == 12
    assert settings.dataset.action_units == "normalized_lerobot_motor_units"
    assert settings.dataset.state_units == "normalized_lerobot_motor_units"
    assert settings.dataset.action_names == XLEROBOT_SO101_ACTION_NAMES
    assert settings.dataset.state_names == XLEROBOT_SO101_ACTION_NAMES
    assert settings.robot["type"] == "bi_so_follower"
    assert settings.robot["id"] == "xlerobot_follower"
    assert settings.teleop["type"] == "bi_so_leader"
    assert settings.teleop["id"] == "so101_leader"
    assert set(settings.cameras) == {"main", "wrist_left", "wrist_right"}


def test_xlerobot_so101_profile_id_must_not_be_used_as_lerobot_robot_id(tmp_path: Path) -> None:
    payload = _payload()
    payload["robot"]["id"] = XLEROBOT_SO101_PROFILE_ID

    with pytest.raises(ValueError, match="robot.id must stay 'xlerobot_follower'"):
        load_settings(_write_config(tmp_path, payload))


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("dataset", "action_dim", 16, "action_dim must be 12"),
        ("dataset", "action_units", "degrees", "action_units must be 'normalized_lerobot_motor_units'"),
        ("dataset", "action_schema_version", "openarm_action_v2", "action_schema_version"),
        ("dataset", "camera_schema_version", "openarm_3rgb_v1", "camera_schema_version"),
        ("teleop", "mode", "absolute_passthrough", "teleop.mode must be 'relative_joint_offset'"),
    ],
)
def test_xlerobot_so101_config_rejects_openarm_or_wrong_schema_values(
    tmp_path: Path,
    section: str,
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _payload()
    payload[section][field] = value

    with pytest.raises(ValueError, match=message):
        load_settings(_write_config(tmp_path, payload))


def test_xlerobot_so101_semantic_metadata_is_manifest_ready() -> None:
    payload = _payload()
    settings = load_settings(CONFIG_PATH)
    metadata = xlerobot_so101_semantic_metadata(settings)

    assert metadata == {
        "robot_profile_id": "xlerobot_so101_dual_v1",
        "robot_family": "so101_compatible",
        "robot_model": "xlerobot",
        "robot_driver": "SOFollower",
        "teleop_driver": "SOLeader",
        "dataset_schema_version": "xlerobot_so101_workbench_v1",
        "action_schema_version": "xlerobot_so101_action_v1",
        "state_schema_version": "xlerobot_so101_state_v1",
        "camera_schema_version": "xlerobot_so101_3rgb_v1",
        "action_dim": 12,
        "state_dim": 12,
        "action_names": list(XLEROBOT_SO101_ACTION_NAMES),
        "state_names": list(XLEROBOT_SO101_ACTION_NAMES),
        "action_units": "normalized_lerobot_motor_units",
        "state_units": "normalized_lerobot_motor_units",
        "action_semantics": "follower_effective_command",
        "control_mode": "joint_position_target",
        "action_space": "joint_position",
        "camera_keys": ["main", "wrist_left", "wrist_right"],
        "compat_mapping_version": payload["teleop"]["compat_mapping_version"],
        "safety_config_version": payload["safety"]["safety_config_version"],
        "ready_required_for_collection": True,
        "sync_required_for_collection": True,
    }
