from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from workbench.dataset_manifest import CanonicalDatasetManifest, DatasetSchemaError
from workbench.episode_manifest import EpisodeRecord


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
