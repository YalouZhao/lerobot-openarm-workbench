from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from workbench.dataset_manifest import CanonicalDatasetManifest
from workbench.episode_manifest import EpisodeRecord
from workbench.web_assets import APP_JS, INDEX_HTML

# The frontend is served as a slimmed INDEX_HTML (markup) plus external
# /static/app.js (behaviour). These invariants must hold across the combined
# assets, so assert against their concatenation.
WEB_SOURCE = INDEX_HTML + "\n" + APP_JS


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
    success_handler = WEB_SOURCE.split('$("success").onclick', 1)[1].split('$("failure").onclick', 1)[0]
    failure_handler = WEB_SOURCE.split('$("failure").onclick', 1)[1].split('$("discard").onclick', 1)[0]

    assert "accepted:" not in success_handler
    assert "accepted:" not in failure_handler


def test_web_exposes_dataset_lifecycle_controls() -> None:
    assert 'id="datasetName"' in WEB_SOURCE
    assert 'id="datasetRoot"' in WEB_SOURCE
    assert 'id="datasetRepoId"' in WEB_SOURCE
    assert 'id="newDataset"' in WEB_SOURCE
    assert 'id="switchDataset"' in WEB_SOURCE
    assert '"/api/dataset/status"' in WEB_SOURCE
    assert '"/api/dataset/new"' in WEB_SOURCE
    assert '"/api/dataset/switch"' in WEB_SOURCE


def test_web_exposes_training_export_controls() -> None:
    assert 'id="exportOutputRoot"' in WEB_SOURCE
    assert 'id="exportOutputRepoId"' in WEB_SOURCE
    assert 'id="exportDryRun"' in WEB_SOURCE
    assert 'id="exportStart"' in WEB_SOURCE
    assert 'id="exportStatus"' in WEB_SOURCE
    assert '"/api/export/training-package/dry-run"' in WEB_SOURCE
    assert '"/api/export/training-package/start"' in WEB_SOURCE
    assert '"/api/export/training-package/status"' in WEB_SOURCE
    assert '$("exportDryRun").disabled = state === "recording" || frozen' in WEB_SOURCE
    assert '$("exportStart").disabled = state === "recording" || frozen' in WEB_SOURCE


def test_web_removes_deprecated_realsense_reset_control() -> None:
    assert "resetRs" not in WEB_SOURCE
    assert "重置深度相机" not in WEB_SOURCE
    assert "/api/realsense/reset" not in WEB_SOURCE


def test_web_exposes_resizable_camera_windows_without_recreating_streams() -> None:
    assert 'class="camera-board"' in WEB_SOURCE
    assert 'class="camera-splitter row"' in WEB_SOURCE
    assert 'class="camera-splitter col"' in WEB_SOURCE
    assert 'class="camera-size-controls"' in WEB_SOURCE
    assert 'id="cameraMainSize"' in WEB_SOURCE
    assert 'id="cameraThumbSize"' in WEB_SOURCE
    assert 'id="cameraWristSplit"' in WEB_SOURCE
    assert "主窗口高度" in WEB_SOURCE
    assert "腕部行高" in WEB_SOURCE
    assert "左右腕宽度" in WEB_SOURCE
    assert "允许留白" in WEB_SOURCE
    assert "applyStageSizing" in WEB_SOURCE
    assert "applyWristSplit" in WEB_SOURCE
    assert "bindSplitter" in WEB_SOURCE
    assert "appendChild(node.wrap)" in WEB_SOURCE
    assert "created once and MOVED" in WEB_SOURCE
    assert ".cam.in-main { position: absolute" not in WEB_SOURCE
    assert "--cam-max" not in WEB_SOURCE
    assert "calc(${mainVh}vh * 16 / 9)" not in WEB_SOURCE


def test_web_exposes_move_to_ready_control() -> None:
    assert 'id="moveReady"' in WEB_SOURCE
    assert '"/api/ready/move"' in WEB_SOURCE
    assert "status.ready?.state" in WEB_SOURCE


def test_web_exposes_sync_master_control() -> None:
    assert 'id="syncMaster"' in WEB_SOURCE
    assert 'id="syncLeft"' in WEB_SOURCE
    assert 'id="syncRight"' in WEB_SOURCE
    assert '"/api/sync/master"' in WEB_SOURCE
    assert 'arm: "left"' in WEB_SOURCE
    assert 'arm: "right"' in WEB_SOURCE
    assert "status.sync?.state" in WEB_SOURCE


def test_web_exposes_dry_teleop_controls() -> None:
    assert 'id="enableTeleop"' in WEB_SOURCE
    assert 'id="disableTeleop"' in WEB_SOURCE
    assert '"/api/teleop/enable"' in WEB_SOURCE
    assert '"/api/teleop/disable"' in WEB_SOURCE
    assert "status.control.dry_teleop_enabled" in WEB_SOURCE
    assert 'status.ready?.required_for_recording && status.ready?.state !== "verified"' in WEB_SOURCE
    assert 'status.sync?.required_for_recording && status.sync?.state !== "valid"' in WEB_SOURCE
    assert "status.control.dry_teleop_enabled" in WEB_SOURCE.split('$("moveReady").disabled', 1)[1].split("\n", 1)[0]


def test_web_exposes_safety_frozen_banner_and_disables_unsafe_controls() -> None:
    assert "Safety Frozen" in WEB_SOURCE
    assert "采集已自动停止并保存" in WEB_SOURCE
    assert "不能 accepted/export" in WEB_SOURCE
    assert "Label 可保存，但 accepted=false" in WEB_SOURCE
    assert '"已自动停止"' in WEB_SOURCE
    assert 'status.control.safety_frozen' in WEB_SOURCE
    assert 'state === "recording" || readyBlocked || syncBlocked || frozen' in WEB_SOURCE
    assert '$("moveReady").disabled = state === "recording" || state === "moving_ready" || status.control.dry_teleop_enabled || frozen' in WEB_SOURCE
    assert '$("syncMaster").disabled = state === "recording" || state === "moving_ready" || frozen' in WEB_SOURCE
    assert '$("enableTeleop").disabled = state === "recording" || state === "moving_ready" || status.control.dry_teleop_enabled || frozen' in WEB_SOURCE
    assert '$("newDataset").disabled = state === "recording" || frozen' in WEB_SOURCE
    assert '$("switchDataset").disabled = state === "recording" || frozen' in WEB_SOURCE


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
