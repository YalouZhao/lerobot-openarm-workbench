from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from workbench.dataset_manifest import CanonicalDatasetManifest
from workbench.episode_manifest import EpisodeRecord
from workbench.web_assets import INDEX_HTML


def record(**overrides) -> EpisodeRecord:
    base = EpisodeRecord(
        episode_index=0,
        task="test task",
        accepted=False,
        label="unlabeled",
        notes="",
        started_at="2026-06-24T10:00:00+08:00",
        ended_at="2026-06-24T10:00:01+08:00",
        frame_count=30,
        fps=30.0,
        save_duration_s=0.1,
        cameras={"main": "ok", "wrist_left": "ok", "wrist_right": "ok"},
        dq_status="pass",
    )
    return replace(base, **overrides)


def test_web_label_requests_do_not_submit_accepted() -> None:
    success_handler = INDEX_HTML.split('$("success").onclick', 1)[1].split('$("failure").onclick', 1)[0]
    failure_handler = INDEX_HTML.split('$("failure").onclick', 1)[1].split('$("discard").onclick', 1)[0]

    assert "accepted:" not in success_handler
    assert "accepted:" not in failure_handler


def test_web_exposes_dataset_lifecycle_controls() -> None:
    assert 'id="datasetName"' in INDEX_HTML
    assert 'id="datasetRoot"' in INDEX_HTML
    assert 'id="datasetRepoId"' in INDEX_HTML
    assert 'id="newDataset"' in INDEX_HTML
    assert 'id="switchDataset"' in INDEX_HTML
    assert '"/api/dataset/status"' in INDEX_HTML
    assert '"/api/dataset/new"' in INDEX_HTML
    assert '"/api/dataset/switch"' in INDEX_HTML


def test_web_exposes_training_export_controls() -> None:
    assert 'id="exportOutputRoot"' in INDEX_HTML
    assert 'id="exportOutputRepoId"' in INDEX_HTML
    assert 'id="exportDryRun"' in INDEX_HTML
    assert 'id="exportStart"' in INDEX_HTML
    assert 'id="exportStatus"' in INDEX_HTML
    assert '"/api/export/training-package/dry-run"' in INDEX_HTML
    assert '"/api/export/training-package/start"' in INDEX_HTML
    assert '"/api/export/training-package/status"' in INDEX_HTML
    assert '$("exportDryRun").disabled = state === "recording" || frozen' in INDEX_HTML
    assert '$("exportStart").disabled = state === "recording" || frozen' in INDEX_HTML


def test_web_exposes_move_to_ready_control() -> None:
    assert 'id="moveReady"' in INDEX_HTML
    assert '"/api/ready/move"' in INDEX_HTML
    assert "status.ready?.state" in INDEX_HTML


def test_web_exposes_sync_master_control() -> None:
    assert 'id="syncMaster"' in INDEX_HTML
    assert 'id="syncLeft"' in INDEX_HTML
    assert 'id="syncRight"' in INDEX_HTML
    assert '"/api/sync/master"' in INDEX_HTML
    assert 'arm: "left"' in INDEX_HTML
    assert 'arm: "right"' in INDEX_HTML
    assert "status.sync?.state" in INDEX_HTML


def test_web_exposes_dry_teleop_controls() -> None:
    assert 'id="enableTeleop"' in INDEX_HTML
    assert 'id="disableTeleop"' in INDEX_HTML
    assert '"/api/teleop/enable"' in INDEX_HTML
    assert '"/api/teleop/disable"' in INDEX_HTML
    assert "status.control.dry_teleop_enabled" in INDEX_HTML
    assert 'status.ready?.required_for_recording && status.ready?.state !== "verified"' in INDEX_HTML
    assert 'status.sync?.required_for_recording && status.sync?.state !== "valid"' in INDEX_HTML
    assert "status.control.dry_teleop_enabled" in INDEX_HTML.split('$("moveReady").disabled', 1)[1].split("\n", 1)[0]


def test_web_exposes_safety_frozen_banner_and_disables_unsafe_controls() -> None:
    assert "Safety Frozen" in INDEX_HTML
    assert "采集已自动停止并保存" in INDEX_HTML
    assert "不能 accepted/export" in INDEX_HTML
    assert "Label 可保存，但 accepted=false" in INDEX_HTML
    assert '"已自动停止"' in INDEX_HTML
    assert 'status.control.safety_frozen' in INDEX_HTML
    assert 'state === "recording" || readyBlocked || syncBlocked || frozen' in INDEX_HTML
    assert '$("moveReady").disabled = state === "recording" || state === "moving_ready" || status.control.dry_teleop_enabled || frozen' in INDEX_HTML
    assert '$("syncMaster").disabled = state === "recording" || state === "moving_ready" || frozen' in INDEX_HTML
    assert '$("enableTeleop").disabled = state === "recording" || state === "moving_ready" || status.control.dry_teleop_enabled || frozen' in INDEX_HTML
    assert '$("newDataset").disabled = state === "recording" || frozen' in INDEX_HTML
    assert '$("switchDataset").disabled = state === "recording" || frozen' in INDEX_HTML


def test_dq_warning_success_label_is_saved_but_not_accepted(tmp_path: Path) -> None:
    manifest = CanonicalDatasetManifest(
        dataset_root=tmp_path / "dataset",
        dataset_name="dataset",
        repo_id="local/dataset",
        task_text="test task",
        session_id="session-1",
    )
    manifest.append_episode(record(dq_status="warning", dq_reasons=("tracking_warning",)))

    labeled = manifest.update_label(0, "success")

    assert labeled["label"] == "success"
    assert labeled["accepted"] is False
    assert "dq_status_not_pass:warning" in labeled["acceptance_reasons"]


def test_contaminated_success_returns_complete_acceptance_reasons(tmp_path: Path) -> None:
    manifest = CanonicalDatasetManifest(
        dataset_root=tmp_path / "dataset",
        dataset_name="dataset",
        repo_id="local/dataset",
        task_text="test task",
        session_id="session-1",
        compat_mapping_verified=True,
        safety_metadata={"safety_config_verified": False},
    )
    manifest.append_episode(
        record(
            dq_status="fail",
            dq_reasons=("safety_config_unverified",),
            safety_config_verified=False,
            contaminated=True,
            contamination_reasons=("safety_config_unverified",),
        )
    )

    labeled = manifest.update_label(0, "success")

    assert labeled["label"] == "success"
    assert labeled["accepted"] is False
    assert labeled["acceptance_reasons"] == [
        "dq_status_not_pass:fail",
        "safety_config_unverified",
        "contaminated:safety_config_unverified",
    ]
