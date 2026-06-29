from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from workbench.atomic_io import atomic_write_json, atomic_write_jsonl, atomic_write_text
from workbench.collection_report import build_collection_report, write_collection_report


def make_dataset(root: Path) -> None:
    root.mkdir()
    atomic_write_json(
        root / "dataset_manifest.json",
        {
            "dataset_name": "collection",
            "dataset_root": str(root),
            "repo_id": "local/collection",
            "dataset_schema_version": "openarm_workbench_v2",
            "action_semantics": "follower_effective_command",
            "teleop_mode": "relative_joint_offset",
            "safety_config_version": "openarm_follower_safety_v2",
            "compat_mapping_version": "openarm_mini_818892a3",
            "episode_count": 4,
            "success_count": 1,
            "failure_count": 1,
            "discard_count": 1,
        },
    )
    records = [
        {
            "episode_index": 0,
            "label": "success",
            "accepted": True,
            "dq_status": "pass",
            "dq_reasons": [],
            "contaminated": False,
            "contamination_reasons": [],
            "frame_count": 100,
            "fps": 30.0,
            "started_at": "2026-06-26T10:00:00+08:00",
            "ended_at": "2026-06-26T10:00:03+08:00",
            "timing_sidecar": "timing_episode_000000.json",
            "timing_summary": {
                "control_step_duration_ms": {"max": 8.0, "mean": 6.0},
                "action_send_latency_ms": {"mean": 5.0},
                "target_fps": 30.0,
            },
            "command_validation": {
                "mismatch_frames": 0,
                "action_spike_frames": 0,
                "nonfinite_action_frames": 0,
            },
            "tracking_validation": {"warning_frames": 0, "freeze_frames": 0},
        },
        {
            "episode_index": 1,
            "label": "failure",
            "accepted": False,
            "dq_status": "fail",
            "dq_reasons": ["camera_missing", "action_spike"],
            "contaminated": False,
            "contamination_reasons": [],
            "frame_count": 8,
            "fps": 12.0,
            "command_validation": {
                "mismatch_frames": 0,
                "action_spike_frames": 2,
                "nonfinite_action_frames": 0,
            },
            "tracking_validation": {"warning_frames": 3, "freeze_frames": 0},
        },
        {
            "episode_index": 2,
            "label": "discard",
            "accepted": False,
            "dq_status": "pass",
            "dq_reasons": [],
            "contaminated": False,
            "contamination_reasons": [],
            "frame_count": 20,
            "fps": 30.0,
            "command_validation": {},
            "tracking_validation": {},
        },
        {
            "episode_index": 3,
            "label": "success",
            "accepted": False,
            "dq_status": "fail",
            "dq_reasons": ["follower_tracking_freeze"],
            "contaminated": True,
            "contamination_reasons": ["relative_resync_during_recording"],
            "frame_count": 50,
            "fps": 25.0,
            "timing_sidecar": "missing_timing.json",
            "command_validation": {
                "mismatch_frames": 4,
                "action_spike_frames": 0,
                "nonfinite_action_frames": 1,
            },
            "tracking_validation": {"warning_frames": 5, "freeze_frames": 1},
        },
    ]
    atomic_write_jsonl(root / "episodes.jsonl", records)
    atomic_write_text(root / "timing_episode_000000.json", "{}\n")


def test_collection_report_aggregates_dataset_quality(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    out = tmp_path / "report"
    make_dataset(root)

    report = write_collection_report(root=root, repo_id="local/collection", output_dir=out)

    assert report["summary"]["episode_count"] == 4
    assert report["summary"]["frame_count"] == 178
    assert report["summary"]["success_count"] == 2
    assert report["summary"]["failure_count"] == 1
    assert report["summary"]["discard_count"] == 1
    assert report["summary"]["accepted_count"] == 1
    assert report["summary"]["exportable_count"] == 1
    assert report["dq"]["dq_fail_count"] == 2
    assert report["dq"]["reason_counts"]["camera_missing"] == 1
    assert report["dq"]["reason_counts"]["action_spike"] == 1
    assert report["dq"]["reason_counts"]["follower_tracking_freeze"] == 1
    assert report["contamination"]["contaminated_count"] == 1
    assert report["contamination"]["reason_counts"]["relative_resync_during_recording"] == 1
    assert report["command_quality"]["action_spike_count"] == 2
    assert report["command_quality"]["driver_mismatch_count"] == 4
    assert report["command_quality"]["nonfinite_action_count"] == 1
    assert report["tracking"]["tracking_warning_count"] == 8
    assert report["tracking"]["tracking_freeze_count"] == 1
    assert report["timing"]["timing_sidecar_missing_count"] == 1
    assert (out / "collection_report.json").exists()
    markdown = (out / "collection_report.md").read_text()
    assert "# Collection Batch QA Report" in markdown
    assert "| exportable_count | 1 |" in markdown
    assert "camera_missing" in markdown


def test_collection_report_build_does_not_require_timing_sidecars(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    make_dataset(root)

    report = build_collection_report(root=root, repo_id="local/collection")

    assert report["timing"]["timing_sidecar_missing_count"] == 1
    assert report["episodes"][3]["timing_sidecar"] == "missing_timing.json"


def test_collection_report_script_writes_json_and_markdown(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    out = tmp_path / "report"
    make_dataset(root)
    script = Path(__file__).parents[1] / "scripts" / "report_collection_batch.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(root),
            "--repo-id",
            "local/collection",
            "--output",
            str(out),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads((out / "collection_report.json").read_text())["summary"]["exportable_count"] == 1
    assert (out / "collection_report.md").exists()
