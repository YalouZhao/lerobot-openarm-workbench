from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.dataset_manifest import CanonicalDatasetManifest, accepted_for_label, atomic_write_text
from workbench.episode_manifest import EpisodeRecord


def make_record(episode_index: int = 0, label: str = "unlabeled", accepted: bool = False) -> EpisodeRecord:
    return EpisodeRecord(
        episode_index=episode_index,
        task="pick up the cup",
        accepted=accepted,
        label=label,
        notes="",
        started_at="2026-06-15T10:00:00+08:00",
        ended_at="2026-06-15T10:00:03+08:00",
        frame_count=90,
        fps=30.0,
        save_duration_s=0.5,
        cameras={"main": "ok", "wrist_left": "ok", "wrist_right": "ok"},
    )


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_initializes_canonical_dataset_files(tmp_path: Path) -> None:
    manifest = CanonicalDatasetManifest(
        dataset_root=tmp_path / "dataset",
        dataset_name="pour_water__20260615_100000",
        repo_id="local/pour_water__20260615_100000",
        task_text="Pour water into the cup.",
        session_id="session-1",
    )

    manifest.ensure_initialized()

    root = tmp_path / "dataset"
    assert (root / "dataset_manifest.json").exists()
    assert (root / "episodes.jsonl").read_text() == ""
    assert (root / "manifest_transactions.jsonl").exists()
    assert (root / "export_reports").is_dir()

    accepted = json.loads((root / "accepted_episodes.json").read_text())
    assert accepted["criteria"] == {"label": "success", "accepted": True}
    assert accepted["episodes"] == []

    dataset_manifest = json.loads((root / "dataset_manifest.json").read_text())
    assert dataset_manifest["data_format"] == "LeRobot v3"
    assert dataset_manifest["task_text"] == "Pour water into the cup."
    assert dataset_manifest["task_text_locked"] is True
    assert dataset_manifest["session_ids"] == ["session-1"]


@pytest.mark.parametrize(
    ("label", "accepted"),
    [
        ("success", True),
        ("failure", False),
        ("discard", False),
        ("unlabeled", False),
    ],
)
def test_accepted_status_is_derived_from_label(label: str, accepted: bool) -> None:
    assert accepted_for_label(label) is accepted


def test_appends_episode_and_rebuilds_accepted_episodes(tmp_path: Path) -> None:
    manifest = CanonicalDatasetManifest(
        dataset_root=tmp_path / "dataset",
        dataset_name="pour_water__20260615_100000",
        repo_id="local/pour_water__20260615_100000",
        task_text="Pour water into the cup.",
        session_id="session-1",
    )

    manifest.append_episode(make_record(episode_index=0))
    manifest.append_episode(make_record(episode_index=1))
    manifest.update_label(1, label="success", notes="good")

    records = read_jsonl(tmp_path / "dataset" / "episodes.jsonl")
    transactions = read_jsonl(tmp_path / "dataset" / "manifest_transactions.jsonl")
    assert records[0]["label"] == "unlabeled"
    assert records[0]["accepted"] is False
    assert records[1]["label"] == "success"
    assert records[1]["accepted"] is True
    assert records[1]["notes"] == "good"
    assert [item["operation"] for item in transactions] == [
        "stop_episode",
        "stop_episode",
        "mark_success",
    ]

    accepted = json.loads((tmp_path / "dataset" / "accepted_episodes.json").read_text())
    assert accepted["episodes"] == [1]


def test_rejects_duplicate_episode_index(tmp_path: Path) -> None:
    manifest = CanonicalDatasetManifest(
        dataset_root=tmp_path / "dataset",
        dataset_name="pour_water__20260615_100000",
        repo_id="local/pour_water__20260615_100000",
        task_text="Pour water into the cup.",
        session_id="session-1",
    )
    manifest.append_episode(make_record(episode_index=0))

    with pytest.raises(ValueError, match="already exists"):
        manifest.append_episode(make_record(episode_index=0))


def test_atomic_write_does_not_truncate_existing_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "episodes.jsonl"
    target.write_text('{"episode_index": 0}\n')

    def fail_replace(src: Path, dst: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("workbench.atomic_io.os.replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write_text(target, '{"episode_index": 1}\n')

    assert target.read_text() == '{"episode_index": 0}\n'
