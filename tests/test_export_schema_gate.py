from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from workbench.dataset_manifest import (
    CanonicalDatasetManifest,
    DatasetSchemaError,
    export_v2_accepted_indices,
)
from workbench.episode_manifest import EpisodeRecord


def make_manifest(root: Path, *, legacy: bool = False) -> CanonicalDatasetManifest:
    if legacy:
        return CanonicalDatasetManifest(
            root,
            root.name,
            f"local/{root.name}",
            "test task",
            "session-1",
            dataset_schema_version="openarm_workbench_v1_legacy",
            action_semantics="master_absolute_legacy",
            teleop_mode="absolute_legacy",
            command_frame_version=1,
        )
    return CanonicalDatasetManifest(
        root,
        root.name,
        f"local/{root.name}",
        "test task",
        "session-1",
    )


def record(index: int) -> EpisodeRecord:
    return EpisodeRecord(
        episode_index=index,
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
    )


def test_v2_export_rebuilds_success_accepted_indexes_from_canonical_records(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    manifest = make_manifest(root)
    manifest.ensure_initialized()
    manifest.append_episode(record(0))
    manifest.append_episode(record(1))
    manifest.update_label(0, "success")
    manifest.update_label(1, "failure")

    output = export_v2_accepted_indices(root, tmp_path / "accepted.txt")

    assert output.read_text() == "0\n"


def test_legacy_dataset_cannot_export_as_v2_accepted(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    make_manifest(root, legacy=True).ensure_initialized()

    with pytest.raises(DatasetSchemaError, match="openarm_workbench_v2"):
        export_v2_accepted_indices(root)


def test_unknown_dataset_cannot_export_as_v2_accepted(tmp_path: Path) -> None:
    root = tmp_path / "unknown"
    root.mkdir()
    (root / "dataset_manifest.json").write_text(json.dumps({"schema_version": 1}))

    with pytest.raises(DatasetSchemaError, match="legacy_unknown"):
        export_v2_accepted_indices(root)


def test_action_semantics_mismatch_blocks_export(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    manifest = make_manifest(root)
    manifest.ensure_initialized()
    payload = json.loads((root / "dataset_manifest.json").read_text())
    payload["action_semantics"] = "master_absolute_legacy"
    (root / "dataset_manifest.json").write_text(json.dumps(payload))

    with pytest.raises(DatasetSchemaError, match="action_semantics"):
        export_v2_accepted_indices(root)


def test_unverified_compat_mapping_cannot_be_accepted_or_exported(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    manifest = CanonicalDatasetManifest(
        root,
        root.name,
        f"local/{root.name}",
        "test task",
        "session-1",
        lerobot_revision="8fff0fde",
        compat_mapping_applied=True,
        compat_mapping_version="openarm_mini_818892a3",
        compat_mapping_verified=False,
    )
    manifest.ensure_initialized()
    unverified_record = record(0)
    unverified_record.compat_mapping_verified = False
    unverified_record.contaminated = True
    unverified_record.contamination_reasons = ("compat_mapping_unverified",)
    manifest.append_episode(unverified_record)

    labeled = manifest.update_label(0, "success")

    assert labeled["accepted"] is False
    with pytest.raises(DatasetSchemaError, match="compat_mapping_verified"):
        export_v2_accepted_indices(root)


def test_episode_semantic_mismatch_blocks_export(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    manifest = make_manifest(root)
    manifest.ensure_initialized()
    payload = record(0).__dict__ | {
        "label": "success",
        "accepted": True,
        "dataset_schema_version": "openarm_workbench_v1_legacy",
        "action_semantics": "master_absolute_legacy",
        "teleop_mode": "absolute_legacy",
    }
    (root / "episodes.jsonl").write_text(json.dumps(payload) + "\n")

    with pytest.raises(DatasetSchemaError, match="episode 0 semantic mismatch"):
        export_v2_accepted_indices(root)


def test_export_script_requires_dataset_root_and_exports_v2_indexes(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    manifest = make_manifest(root)
    manifest.ensure_initialized()
    manifest.append_episode(record(0))
    manifest.update_label(0, "success")
    output = tmp_path / "accepted.txt"
    script = Path(__file__).parents[1] / "scripts" / "export_accepted_episodes.py"

    result = subprocess.run(
        [sys.executable, str(script), "--dataset-root", str(root), "--output", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output.read_text() == "0\n"
