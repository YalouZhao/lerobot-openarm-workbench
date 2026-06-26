from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.config import load_settings, validate_semantic_configuration
from workbench.safety import EXPECTED_FOLLOWER_ACTION_KEYS


def safety_payload() -> dict:
    return {
        "safety_config_version": "test_safety_v1",
        "safety_config_verified": False,
        "joints": {
            key: {
                "hard_limit": [-65.0, 0.0] if "gripper" in key else [-100.0, 100.0],
                "soft_limit": [-65.0, 0.0] if "gripper" in key else [-100.0, 100.0],
                "deadband": 0.0,
                "max_step": 2.0,
                "max_velocity": 60.0,
                "tracking_error_warning": 5.0,
                "tracking_error_contamination": 10.0,
                "tracking_error_freeze": 20.0,
            }
            for key in EXPECTED_FOLLOWER_ACTION_KEYS
        },
        "driver_mismatch_atol": 1e-4,
        "mismatch_contamination_frames": 3,
        "tracking_error_persistence_frames": 3,
    }


def config_payload() -> dict:
    return {
        "workspace_root": "/tmp/workbench",
        "session_root": "/tmp/workbench/sessions",
        "dataset": {
            "repo_id": "local/test",
            "root": "/tmp/test",
            "fps": 30,
            "dataset_schema_version": "openarm_workbench_v2",
            "action_semantics": "follower_effective_command",
            "command_frame_version": 1,
        },
        "robot": {"id": "robot", "left_arm": {}, "right_arm": {}},
        "teleop": {
            "id": "teleop",
            "mode": "absolute_passthrough",
            "apply_openarm_mini_compat_mapping": True,
            "compat_mapping_version": "openarm_mini_818892a3",
            "compat_mapping_verified": False,
        },
        "cameras": {},
        "control": {
            "min_episode_frames": 10,
            "min_control_fps_ratio": 0.5,
            "action_spike_threshold": 8.0,
        },
        "ready": {
            "path": "config/ready_path.json",
            "fps": 30,
            "tolerance": 2.0,
            "settle_time_s": 0.2,
            "verify_after_move": True,
            "require_ready_for_recording": False,
        },
        "sync": {
            "samples": 3,
            "sample_interval_s": 0.02,
            "require_sync_for_recording": False,
        },
        "safety": safety_payload(),
    }


def write_config(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload))
    return path


def test_loads_explicit_v2_semantics(tmp_path: Path) -> None:
    settings = load_settings(write_config(tmp_path, config_payload()))

    assert settings.dataset.dataset_schema_version == "openarm_workbench_v2"
    assert settings.dataset.action_semantics == "follower_effective_command"
    assert settings.dataset.command_frame_version == 1
    assert settings.teleop["mode"] == "absolute_passthrough"
    assert settings.apply_openarm_mini_compat_mapping is True
    assert settings.compat_mapping_version == "openarm_mini_818892a3"
    assert settings.compat_mapping_verified is False
    assert settings.safety.safety_config_version == "test_safety_v1"
    assert settings.safety.safety_config_verified is False
    assert settings.safety.joints["left_gripper.pos"].hard_limit == (-65.0, 0.0)
    assert settings.control["min_episode_frames"] == 10
    assert settings.control["min_control_fps_ratio"] == 0.5
    assert settings.control["action_spike_threshold"] == 8.0
    assert settings.ready["path"] == "config/ready_path.json"
    assert settings.sync["samples"] == 3
    assert settings.sync["sample_interval_s"] == 0.02
    assert settings.sync["require_sync_for_recording"] is False


def test_v2_json_config_requires_safety_section(tmp_path: Path) -> None:
    payload = config_payload()
    del payload["safety"]

    with pytest.raises(ValueError, match="missing required safety configuration"):
        load_settings(write_config(tmp_path, payload))


@pytest.mark.parametrize(
    "missing_path",
    [
        ("dataset", "dataset_schema_version"),
        ("dataset", "action_semantics"),
        ("dataset", "command_frame_version"),
        ("teleop", "mode"),
        ("teleop", "apply_openarm_mini_compat_mapping"),
        ("teleop", "compat_mapping_version"),
        ("teleop", "compat_mapping_verified"),
    ],
)
def test_json_config_requires_semantic_fields(tmp_path: Path, missing_path: tuple[str, str]) -> None:
    payload = config_payload()
    del payload[missing_path[0]][missing_path[1]]

    with pytest.raises(ValueError, match="missing required semantic configuration"):
        load_settings(write_config(tmp_path, payload))


@pytest.mark.parametrize(
    ("dataset_schema_version", "action_semantics", "teleop_mode"),
    [
        ("openarm_workbench_v1_legacy", "follower_effective_command", "absolute_legacy"),
        ("openarm_workbench_v2", "master_absolute_legacy", "absolute_passthrough"),
        ("openarm_workbench_v2", "follower_effective_command", "absolute_legacy"),
        ("unknown", "follower_effective_command", "absolute_passthrough"),
    ],
)
def test_rejects_invalid_semantic_combinations(
    dataset_schema_version: str,
    action_semantics: str,
    teleop_mode: str,
) -> None:
    with pytest.raises(ValueError, match="unsupported dataset semantic combination"):
        validate_semantic_configuration(
            dataset_schema_version=dataset_schema_version,
            action_semantics=action_semantics,
            teleop_mode=teleop_mode,
            command_frame_version=1,
        )


def test_rejects_unknown_command_frame_version() -> None:
    with pytest.raises(ValueError, match="command_frame_version must be 1"):
        validate_semantic_configuration(
            dataset_schema_version="openarm_workbench_v2",
            action_semantics="follower_effective_command",
            teleop_mode="absolute_passthrough",
            command_frame_version=2,
        )


def test_example_config_declares_v2_semantics() -> None:
    payload = json.loads((Path(__file__).parents[1] / "config" / "workbench_config.example.json").read_text())

    assert payload["dataset"]["dataset_schema_version"] == "openarm_workbench_v2"
    assert payload["dataset"]["action_semantics"] == "follower_effective_command"
    assert payload["dataset"]["command_frame_version"] == 1
    assert payload["teleop"]["mode"] == "absolute_passthrough"
    assert payload["teleop"]["apply_openarm_mini_compat_mapping"] is True
    assert payload["teleop"]["compat_mapping_version"] == "openarm_mini_818892a3"
    assert payload["teleop"]["compat_mapping_verified"] is False
    assert payload["safety"]["safety_config_version"] == "openarm_follower_safety_v2"
    assert payload["safety"]["safety_config_verified"] is True
    assert payload["safety"]["verified_by"] == "hardware_operator"
    assert "driver_mismatch=0" in payload["safety"]["verification_basis"]
    assert payload["control"]["min_episode_frames"] == 10
    assert payload["control"]["min_control_fps_ratio"] == 0.5
    assert payload["control"]["action_spike_threshold"] == 8.0
    assert payload["ready"]["path"] == "config/ready_path.json"
    assert payload["ready"]["require_ready_for_recording"] is False
    assert payload["sync"]["samples"] == 3
    assert payload["sync"]["sample_interval_s"] == 0.02
    assert payload["sync"]["require_sync_for_recording"] is False
    assert payload["safety"]["tracking_error_persistence_frames"] == 3
    assert payload["safety"]["joints"]["left_joint_2.pos"]["hard_limit"] == [-90.0, 9.0]
    assert payload["safety"]["joints"]["right_joint_2.pos"]["hard_limit"] == [-9.0, 90.0]
