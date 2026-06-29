from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest


def _clear_fake_lerobot_modules() -> None:
    datasets = sys.modules.get("lerobot.datasets")
    if datasets is not None and not hasattr(datasets, "__path__"):
        for name in list(sys.modules):
            if name == "lerobot" or name.startswith("lerobot."):
                del sys.modules[name]


_clear_fake_lerobot_modules()

from lerobot.datasets.lerobot_dataset import LeRobotDataset

from workbench.dataset_manifest import CanonicalDatasetManifest
from workbench.episode_manifest import EpisodeRecord
from workbench.safety import EXPECTED_FOLLOWER_ACTION_KEYS
from workbench.training_export import (
    TrainingExportError,
    export_training_package,
    plan_training_export,
)


ACTION_NAMES = list(EXPECTED_FOLLOWER_ACTION_KEYS)


def safety_metadata() -> dict:
    limits = {
        key: ([-65.0, 0.0] if "gripper" in key else [-100.0, 100.0])
        for key in EXPECTED_FOLLOWER_ACTION_KEYS
    }
    return {
        "safety_config_version": "openarm_follower_safety_v2",
        "safety_config_verified": True,
        "verified_by": "hardware_operator",
        "verified_at": "2026-06-24T16:30:00+08:00",
        "verification_basis": "hardware acceptance test fixture",
        "hard_limits": limits,
        "soft_limits": limits,
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


def make_record(index: int, *, label: str = "success", dq_status: str = "pass", contaminated: bool = False):
    metadata = safety_metadata()
    return EpisodeRecord(
        episode_index=index,
        task="pour water",
        accepted=label == "success" and dq_status == "pass" and not contaminated,
        label="unlabeled",
        notes="",
        started_at="2026-06-26T10:00:00+08:00",
        ended_at="2026-06-26T10:00:02+08:00",
        frame_count=2,
        fps=30.0,
        save_duration_s=0.01,
        cameras={},
        teleop_mode="relative_joint_offset",
        safety_config_version=metadata["safety_config_version"],
        safety_config_verified=True,
        verified_by=metadata["verified_by"],
        verified_at=metadata["verified_at"],
        verification_basis=metadata["verification_basis"],
        hard_limits=metadata["hard_limits"],
        soft_limits=metadata["soft_limits"],
        deadband=metadata["deadband"],
        max_step=metadata["max_step"],
        velocity_limit=metadata["velocity_limit"],
        tracking_error_warning=metadata["tracking_error_warning"],
        tracking_error_contamination=metadata["tracking_error_contamination"],
        tracking_error_freeze=metadata["tracking_error_freeze"],
        driver_mismatch_atol=metadata["driver_mismatch_atol"],
        mismatch_contamination_frames=metadata["mismatch_contamination_frames"],
        tracking_error_persistence_frames=metadata["tracking_error_persistence_frames"],
        command_validation={
            "mismatch_frames": 0,
            "max_abs_error": 0.0,
            "affected_joints": [],
            "max_consecutive_mismatch_frames": 0,
            "action_spike_frames": 0,
            "nonfinite_action_frames": 0,
        },
        tracking_validation={"freeze_frames": 0},
        ready_state="verified",
        ready_result={"ok": True},
        sync_valid_at_record_start=True,
        sync_state_at_record_start="valid",
        sync_result_at_record_start={"ok": True, "state": "valid"},
        dq_status=dq_status,
        dq_reasons=(() if dq_status == "pass" else ("action_spike",)),
    )


def create_source_dataset(root: Path, *, labels: list[str] | None = None) -> None:
    labels = labels or ["success", "failure", "success"]
    features = {
        "action": {"dtype": "float32", "shape": (16,), "names": ACTION_NAMES},
        "observation.state": {"dtype": "float32", "shape": (16,), "names": ACTION_NAMES},
    }
    dataset = LeRobotDataset.create(
        "local/source_collection",
        fps=30,
        features=features,
        root=root,
        use_videos=False,
    )
    for episode_index, _label in enumerate(labels):
        for frame_index in range(2):
            value = float(episode_index * 10 + frame_index)
            dataset.add_frame(
                {
                    "action": np.full((16,), value, dtype=np.float32),
                    "observation.state": np.full((16,), value + 0.5, dtype=np.float32),
                    "task": "pour water",
                }
            )
        dataset.save_episode()
    dataset.finalize()

    manifest = CanonicalDatasetManifest(
        root,
        root.name,
        "local/source_collection",
        "pour water",
        "session-1",
        teleop_mode="relative_joint_offset",
        safety_metadata=safety_metadata(),
    )
    manifest.ensure_initialized(new_dataset_created=True)
    for index, label in enumerate(labels):
        dq_status = "fail" if label == "failure" else "pass"
        manifest.append_episode(make_record(index, label=label, dq_status=dq_status))
        manifest.update_label(index, label)


def test_training_export_filters_clean_accepted_episodes_and_reindexes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "exported"
    create_source_dataset(source)
    before = {
        path.relative_to(source): path.stat().st_mtime_ns
        for path in source.rglob("*")
        if path.is_file()
    }

    result = export_training_package(
        source_root=source,
        source_repo_id="local/source_collection",
        output_root=output,
        output_repo_id="local/exported_training",
        config_file=Path("config/workbench_config.phase1-hardware-test.json"),
    )

    report = json.loads((output / "export_report.json").read_text())
    contract = json.loads((output / "dataset_action_contract.json").read_text())
    provenance = json.loads((output / "export_provenance.json").read_text())
    exported = LeRobotDataset("local/exported_training", root=output)

    assert result["exported_episode_count"] == 2
    assert report["episode_mapping"] == [
        {"source_episode_index": 0, "export_episode_index": 0},
        {"source_episode_index": 2, "export_episode_index": 1},
    ]
    assert report["excluded_reasons"]["dq_fail"] == 1
    assert report["loader_validation"]["passed"] is True
    assert report["loader_validation"]["episode_count"] == 2
    assert exported.num_episodes == 2
    assert exported[0]["episode_index"].item() == 0
    assert exported[2]["episode_index"].item() == 1
    assert contract["action_semantics"] == "follower_effective_command"
    assert contract["dataset_action_source"] == "workbench_effective_command"
    assert "driver_returned_action" in contract["excluded_action_sources"]
    assert "runtime" not in json.dumps(contract).lower()
    assert provenance["config_file"] == "config/workbench_config.phase1-hardware-test.json"
    assert provenance["dataset_schema_version"] == "openarm_workbench_v2"
    assert (output / "meta" / "stats.json").exists()
    after = {
        path.relative_to(source): path.stat().st_mtime_ns
        for path in source.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_training_export_dry_run_does_not_write_output_or_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "dry_export"
    create_source_dataset(source)
    before = {
        path.relative_to(source): path.stat().st_mtime_ns
        for path in source.rglob("*")
        if path.is_file()
    }

    plan = plan_training_export(
        source_root=source,
        source_repo_id="local/source_collection",
        output_root=output,
        output_repo_id="local/exported_training",
        dry_run=True,
    )

    after = {
        path.relative_to(source): path.stat().st_mtime_ns
        for path in source.rglob("*")
        if path.is_file()
    }
    assert plan["dry_run"] is True
    assert [item["source_episode_index"] for item in plan["episodes_to_export"]] == [0, 2]
    assert output.exists() is False
    assert after == before


def test_training_export_refuses_existing_output_without_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "exported"
    create_source_dataset(source, labels=["success"])
    output.mkdir()

    with pytest.raises(TrainingExportError, match="output root already exists"):
        export_training_package(
            source_root=source,
            source_repo_id="local/source_collection",
            output_root=output,
            output_repo_id="local/exported_training",
        )


def test_training_export_script_writes_package(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "script_exported"
    create_source_dataset(source, labels=["success"])
    script = Path(__file__).parents[1] / "scripts" / "export_training_package.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--source-root",
            str(source),
            "--source-repo-id",
            "local/source_collection",
            "--output-root",
            str(output),
            "--output-repo-id",
            "local/script_exported",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads((output / "export_report.json").read_text())
    assert report["exported_episode_count"] == 1
