from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.atomic_io import atomic_write_json, atomic_write_jsonl
from workbench.collection_report import build_collection_report
from workbench.dataset_manifest import CanonicalDatasetManifest, DatasetSchemaError
from workbench.episode_manifest import EpisodeRecord
from workbench.training_export import plan_training_export
from workbench.xlerobot_profile import (
    XLEROBOT_SO101_ACTION_NAMES,
    XLEROBOT_SO101_PROFILE_ID,
    xlerobot_so101_contract_metadata,
)


def profile_metadata() -> dict:
    metadata = xlerobot_so101_contract_metadata(
        compat_mapping_version="so101_leader_to_xlerobot_follower_v1",
        safety_config_version="xlerobot_so101_safety_v1",
        ready_required_for_collection=True,
        sync_required_for_collection=True,
    )
    metadata.pop("contract_version")
    metadata.pop("dataset_action_source")
    metadata.pop("action_description_en")
    metadata.pop("action_description_zh")
    metadata.pop("dataset_schema_version")
    metadata.pop("action_semantics")
    metadata.pop("compat_mapping_version")
    metadata.pop("safety_config_version")
    return metadata


def safety_metadata() -> dict:
    keys = XLEROBOT_SO101_ACTION_NAMES
    return {
        "safety_config_version": "xlerobot_so101_safety_v1",
        "safety_config_verified": True,
        "verified_by": "hardware_operator",
        "verified_at": "2026-07-01T15:30:00+08:00",
        "verification_basis": "xlerobot short episode validation",
        "safety_action_keys": list(keys),
        "hard_limits": {key: ([0.0, 100.0] if "gripper" in key else [-100.0, 100.0]) for key in keys},
        "soft_limits": {key: ([0.0, 100.0] if "gripper" in key else [-100.0, 100.0]) for key in keys},
        "deadband": {key: 0.0 for key in keys},
        "max_step": {key: (35.0 if "gripper" in key else 15.0) for key in keys},
        "velocity_limit": {key: (1050.0 if "gripper" in key else 450.0) for key in keys},
        "tracking_error_warning": {key: 20.0 for key in keys},
        "tracking_error_contamination": {key: 40.0 for key in keys},
        "tracking_error_freeze": {key: 80.0 for key in keys},
        "driver_mismatch_atol": 1e-4,
        "mismatch_contamination_frames": 3,
        "tracking_error_persistence_frames": 3,
    }


def manifest(root: Path, *, metadata: dict | None = None) -> CanonicalDatasetManifest:
    return CanonicalDatasetManifest(
        root,
        root.name,
        "local/xlerobot_so101",
        "xlerobot task",
        "session-1",
        dataset_schema_version="xlerobot_so101_workbench_v1",
        action_semantics="follower_effective_command",
        teleop_mode="relative_joint_offset",
        compat_mapping_applied=False,
        compat_mapping_version="so101_leader_to_xlerobot_follower_v1",
        compat_mapping_verified=True,
        safety_metadata=safety_metadata(),
        profile_metadata=metadata if metadata is not None else profile_metadata(),
    )


def record(index: int = 0, *, metadata: dict | None = None) -> EpisodeRecord:
    profile = metadata if metadata is not None else profile_metadata()
    safety = safety_metadata()
    return EpisodeRecord(
        episode_index=index,
        task="xlerobot task",
        accepted=False,
        label="unlabeled",
        notes="",
        started_at="2026-07-01T15:00:00+08:00",
        ended_at="2026-07-01T15:00:02+08:00",
        frame_count=60,
        fps=30.0,
        save_duration_s=0.1,
        cameras={"main": "ok", "wrist_left": "ok", "wrist_right": "ok"},
        dataset_schema_version="xlerobot_so101_workbench_v1",
        action_semantics="follower_effective_command",
        teleop_mode="relative_joint_offset",
        compat_mapping_applied=False,
        compat_mapping_version="so101_leader_to_xlerobot_follower_v1",
        compat_mapping_verified=True,
        dq_status="pass",
        ready_state="verified",
        ready_result={"ok": True},
        sync_valid_at_record_start=True,
        sync_state_at_record_start="valid",
        sync_result_at_record_start={"state": "valid"},
        command_validation={"mismatch_frames": 0, "max_consecutive_mismatch_frames": 0},
        tracking_validation={"freeze_frames": 0},
        **profile,
        **safety,
    )


def test_xlerobot_profile_metadata_is_written_to_dataset_and_episode_manifest(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    m = manifest(root)
    m.ensure_initialized()
    m.append_episode(record())

    dataset_manifest = json.loads((root / "dataset_manifest.json").read_text())
    episode = json.loads((root / "episodes.jsonl").read_text().splitlines()[0])

    assert dataset_manifest["robot_profile_id"] == XLEROBOT_SO101_PROFILE_ID
    assert dataset_manifest["action_schema_version"] == "xlerobot_so101_action_v1"
    assert dataset_manifest["action_dim"] == 12
    assert dataset_manifest["action_names"] == list(XLEROBOT_SO101_ACTION_NAMES)
    assert episode["robot_profile_id"] == XLEROBOT_SO101_PROFILE_ID
    assert episode["state_dim"] == 12
    assert episode["camera_keys"] == ["main", "wrist_left", "wrist_right"]


def test_xlerobot_append_rejects_profile_semantic_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    m = manifest(root)
    m.ensure_initialized()

    changed = profile_metadata()
    changed["robot_profile_id"] = "other_robot"
    with pytest.raises(DatasetSchemaError, match="robot_profile_id"):
        manifest(root, metadata=changed).validate_for_collection()


def test_xlerobot_training_export_plan_and_qa_report_include_profile_metadata(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    m = manifest(root)
    m.ensure_initialized()
    m.append_episode(record())
    m.update_label(0, "success")

    plan = plan_training_export(
        source_root=root,
        source_repo_id="local/xlerobot_so101",
        output_root=tmp_path / "export",
        output_repo_id="local/xlerobot_so101_export",
        dry_run=True,
    )
    report = build_collection_report(root=root, repo_id="local/xlerobot_so101")

    assert plan["robot_profile_id"] == XLEROBOT_SO101_PROFILE_ID
    assert plan["action_schema_version"] == "xlerobot_so101_action_v1"
    assert plan["action_dim"] == 12
    assert plan["episodes_to_export"] == [{"source_episode_index": 0, "export_episode_index": 0}]
    assert report["dataset"]["robot_profile_id"] == XLEROBOT_SO101_PROFILE_ID
    assert report["dataset"]["camera_schema_version"] == "xlerobot_so101_3rgb_v1"


def test_xlerobot_training_export_plan_rejects_openarm_hardcoded_schema(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    m = manifest(root)
    m.ensure_initialized()
    payload = json.loads((root / "dataset_manifest.json").read_text())
    payload["action_dim"] = 16
    atomic_write_json(root / "dataset_manifest.json", payload)
    atomic_write_jsonl(root / "episodes.jsonl", [record().__dict__])

    with pytest.raises(Exception, match="action_dim"):
        plan_training_export(
            source_root=root,
            source_repo_id="local/xlerobot_so101",
            output_root=tmp_path / "export",
            output_repo_id="local/xlerobot_so101_export",
            dry_run=True,
        )
