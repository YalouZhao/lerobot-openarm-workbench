from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from workbench.dataset_manifest import CanonicalDatasetManifest, DatasetSchemaError
from workbench.episode_manifest import EpisodeRecord
from workbench.safety import EXPECTED_FOLLOWER_ACTION_KEYS


def safety_metadata(*, verified: bool = True) -> dict:
    hard_limits = {
        key: ([-65.0, 0.0] if "gripper" in key else [-100.0, 100.0]) for key in EXPECTED_FOLLOWER_ACTION_KEYS
    }
    return {
        "safety_config_version": "test_safety_v1",
        "safety_config_verified": verified,
        "verified_by": "hardware_operator",
        "verified_at": "2026-06-24T16:30:00+08:00",
        "verification_basis": "driver_mismatch=0; max_step_violations=0; no freeze/contamination",
        "hard_limits": hard_limits,
        "soft_limits": hard_limits,
        "deadband": {key: 0.0 for key in EXPECTED_FOLLOWER_ACTION_KEYS},
        "max_step": {key: 2.0 for key in EXPECTED_FOLLOWER_ACTION_KEYS},
        "velocity_limit": {key: 60.0 for key in EXPECTED_FOLLOWER_ACTION_KEYS},
        "tracking_error_warning": {key: 5.0 for key in EXPECTED_FOLLOWER_ACTION_KEYS},
        "tracking_error_contamination": {key: 10.0 for key in EXPECTED_FOLLOWER_ACTION_KEYS},
        "tracking_error_freeze": {key: 20.0 for key in EXPECTED_FOLLOWER_ACTION_KEYS},
        "driver_mismatch_atol": 1e-4,
        "mismatch_contamination_frames": 3,
        "tracking_error_persistence_frames": 3,
    }


def make_manifest(root: Path, **overrides) -> CanonicalDatasetManifest:
    values = {
        "dataset_root": root,
        "dataset_name": root.name,
        "repo_id": f"local/{root.name}",
        "task_text": "test task",
        "session_id": "session-1",
        "dataset_schema_version": "openarm_workbench_v2",
        "action_semantics": "follower_effective_command",
        "teleop_mode": "absolute_passthrough",
        "command_frame_version": 1,
        "lerobot_revision": "8fff0fde",
        "compat_mapping_applied": True,
        "compat_mapping_version": "openarm_mini_818892a3",
        "compat_mapping_verified": False,
        "safety_metadata": safety_metadata(),
    }
    values.update(overrides)
    return CanonicalDatasetManifest(**values)


def make_record(**overrides) -> EpisodeRecord:
    record = EpisodeRecord(
        episode_index=0,
        task="test task",
        accepted=False,
        label="unlabeled",
        notes="",
        started_at="2026-06-23T10:00:00+08:00",
        ended_at="2026-06-23T10:00:03+08:00",
        frame_count=90,
        fps=30.0,
        save_duration_s=0.1,
        cameras={"main": "ok", "wrist_left": "ok", "wrist_right": "ok"},
        lerobot_revision="8fff0fde",
        compat_mapping_applied=True,
        compat_mapping_version="openarm_mini_818892a3",
        compat_mapping_verified=False,
        safety_config_version="test_safety_v1",
        safety_config_verified=True,
        verified_by="hardware_operator",
        verified_at="2026-06-24T16:30:00+08:00",
        verification_basis="driver_mismatch=0; max_step_violations=0; no freeze/contamination",
        hard_limits=safety_metadata()["hard_limits"],
        soft_limits=safety_metadata()["soft_limits"],
        deadband=safety_metadata()["deadband"],
        max_step=safety_metadata()["max_step"],
        velocity_limit=safety_metadata()["velocity_limit"],
        tracking_error_warning=safety_metadata()["tracking_error_warning"],
        tracking_error_contamination=safety_metadata()["tracking_error_contamination"],
        tracking_error_freeze=safety_metadata()["tracking_error_freeze"],
        driver_mismatch_atol=1e-4,
        mismatch_contamination_frames=3,
        tracking_error_persistence_frames=3,
        command_validation={
            "mismatch_frames": 0,
            "max_abs_error": 0.0,
            "affected_joints": [],
            "max_consecutive_mismatch_frames": 0,
        },
    )
    return replace(record, **overrides)


def test_missing_root_is_available_for_new_dataset(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path / "new-dataset")

    assert manifest.validate_for_collection() == "new"


def test_nonempty_root_without_manifest_is_legacy_unknown(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    (root / "meta").mkdir(parents=True)
    (root / "meta" / "info.json").write_text("{}")

    with pytest.raises(DatasetSchemaError, match="legacy_unknown"):
        make_manifest(root).validate_for_collection()


def test_append_cannot_backfill_legacy_unknown_root(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    (root / "meta").mkdir(parents=True)
    (root / "meta" / "info.json").write_text("{}")

    with pytest.raises(DatasetSchemaError, match="legacy_unknown"):
        make_manifest(root).append_episode(make_record())

    assert not (root / "dataset_manifest.json").exists()


def test_manifest_missing_semantic_fields_is_legacy_unknown(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    root.mkdir()
    (root / "dataset_manifest.json").write_text(json.dumps({"schema_version": 1}))

    with pytest.raises(DatasetSchemaError, match="legacy_unknown"):
        make_manifest(root).validate_for_collection()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dataset_schema_version", "openarm_workbench_v1_legacy"),
        ("action_semantics", "master_absolute_legacy"),
        ("teleop_mode", "relative_joint_offset"),
        ("command_frame_version", 2),
    ],
)
def test_existing_semantic_mismatch_blocks_collection(tmp_path: Path, field: str, value: object) -> None:
    root = tmp_path / "dataset"
    manifest = make_manifest(root)
    manifest.ensure_initialized()
    payload = json.loads((root / "dataset_manifest.json").read_text())
    payload[field] = value
    (root / "dataset_manifest.json").write_text(json.dumps(payload))

    with pytest.raises(DatasetSchemaError, match=field):
        manifest.validate_for_collection()


def test_new_manifest_preserves_manifest_schema_and_writes_dataset_semantics(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    manifest = make_manifest(root)

    manifest.ensure_initialized()

    payload = json.loads((root / "dataset_manifest.json").read_text())
    assert payload["schema_version"] == 1
    assert payload["dataset_schema_version"] == "openarm_workbench_v2"
    assert payload["action_semantics"] == "follower_effective_command"
    assert payload["teleop_mode"] == "absolute_passthrough"
    assert payload["command_frame_version"] == 1
    assert payload["lerobot_revision"] == "8fff0fde"
    assert payload["compat_mapping_applied"] is True
    assert payload["compat_mapping_version"] == "openarm_mini_818892a3"
    assert payload["compat_mapping_verified"] is False
    assert payload["safety_config_version"] == "test_safety_v1"
    assert payload["verified_by"] == "hardware_operator"
    assert "max_step_violations=0" in payload["verification_basis"]
    assert payload["hard_limits"]["left_gripper.pos"] == [-65.0, 0.0]
    assert payload["velocity_limit"]["right_joint_1.pos"] == 60.0


def test_episode_records_compatibility_mapping_debug_metadata(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    manifest = make_manifest(root)
    manifest.ensure_initialized()

    manifest.append_episode(make_record())

    record = json.loads((root / "episodes.jsonl").read_text().strip())
    assert record["lerobot_revision"] == "8fff0fde"
    assert record["compat_mapping_applied"] is True
    assert record["compat_mapping_version"] == "openarm_mini_818892a3"
    assert record["compat_mapping_verified"] is False
    assert record["safety_config_version"] == "test_safety_v1"
    assert record["verified_at"] == "2026-06-24T16:30:00+08:00"
    assert record["hard_limits"]["left_gripper.pos"] == [-65.0, 0.0]


def test_safety_config_mismatch_blocks_existing_dataset_append(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    manifest = make_manifest(root)
    manifest.ensure_initialized()
    changed = safety_metadata()
    changed["safety_config_version"] = "other_safety_v2"

    with pytest.raises(DatasetSchemaError, match="safety_config_version"):
        make_manifest(root, safety_metadata=changed).validate_for_collection()


def test_contaminated_episode_cannot_be_accepted(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    manifest = make_manifest(root, compat_mapping_verified=True)
    manifest.ensure_initialized()
    manifest.append_episode(
        make_record(
            compat_mapping_verified=True,
            contaminated=True,
            contamination_reasons=("persistent_driver_command_mismatch",),
        )
    )

    labeled = manifest.update_label(0, "success")

    assert labeled["accepted"] is False


def test_episode_semantics_must_match_dataset_root(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    manifest = make_manifest(root)
    manifest.ensure_initialized()
    legacy_record = make_record(
        dataset_schema_version="openarm_workbench_v1_legacy",
        action_semantics="master_absolute_legacy",
        teleop_mode="absolute_legacy",
    )

    with pytest.raises(DatasetSchemaError, match="episode semantic mismatch"):
        manifest.append_episode(legacy_record)
