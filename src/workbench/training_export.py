from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .atomic_io import atomic_write_json
from .config import COMMAND_FRAME_VERSION, RELATIVE_JOINT_MODE, V2_ACTION_SEMANTICS, V2_DATASET_SCHEMA
from .dataset_manifest import SAFETY_SEMANTIC_FIELDS, SEMANTIC_FIELDS, read_jsonl
from .xlerobot_profile import (
    XLEROBOT_SO101_CONTRACT_VERSION,
    XLEROBOT_SO101_DATASET_SCHEMA_VERSION,
    XLEROBOT_SO101_PROFILE_METADATA_FIELDS,
    expected_xlerobot_so101_profile_metadata,
    validate_xlerobot_so101_manifest_metadata,
)


CONTRACT_VERSION = "openarm_dataset_action_contract_v1"
GENERATED_FRAME_KEYS = {"index", "episode_index", "frame_index", "task_index", "timestamp"}


class TrainingExportError(RuntimeError):
    pass


def plan_training_export(
    *,
    source_root: Path,
    source_repo_id: str,
    output_root: Path,
    output_repo_id: str,
    task_filter: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    source_root = Path(source_root).expanduser()
    output_root = Path(output_root).expanduser()
    manifest = _load_source_manifest(source_root)
    _validate_source_manifest(manifest)
    records = read_jsonl(source_root / "episodes.jsonl")

    episodes_to_export: list[dict[str, int]] = []
    excluded: list[dict[str, Any]] = []
    for record in records:
        if task_filter and str(record.get("task") or record.get("task_text") or "") != task_filter:
            excluded.append(_excluded(record, "task_filter_mismatch"))
            continue
        reasons = _episode_exclusion_reasons(record, manifest)
        if reasons:
            excluded.append(_excluded(record, *reasons))
            continue
        episodes_to_export.append(
            {
                "source_episode_index": int(record["episode_index"]),
                "export_episode_index": len(episodes_to_export),
            }
        )

    excluded_reasons = Counter(reason for item in excluded for reason in item["reasons"])
    return {
        "dry_run": dry_run,
        "source_root": str(source_root),
        "output_root": str(output_root),
        "source_repo_id": source_repo_id,
        "output_repo_id": output_repo_id,
        "source_episode_count": len(records),
        "exported_episode_count": len(episodes_to_export),
        "excluded_episode_count": len(excluded),
        "excluded_reasons": dict(sorted(excluded_reasons.items())),
        "episodes_to_export": episodes_to_export,
        "excluded_episodes": excluded,
        "dataset_schema_version": manifest["dataset_schema_version"],
        "action_semantics": manifest["action_semantics"],
        "safety_config_version": manifest["safety_config_version"],
        "compat_mapping_version": manifest["compat_mapping_version"],
        **_profile_plan_fields(manifest),
    }


def export_training_package(
    *,
    source_root: Path,
    source_repo_id: str,
    output_root: Path,
    output_repo_id: str,
    task_filter: str | None = None,
    export_name: str | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
    config_file: Path | None = None,
) -> dict[str, Any]:
    source_root = Path(source_root).expanduser()
    output_root = Path(output_root).expanduser()
    plan = plan_training_export(
        source_root=source_root,
        source_repo_id=source_repo_id,
        output_root=output_root,
        output_repo_id=output_repo_id,
        task_filter=task_filter,
        dry_run=dry_run,
    )
    if dry_run:
        return plan
    if output_root.exists():
        if not overwrite:
            raise TrainingExportError(f"output root already exists: {output_root}")
        shutil.rmtree(output_root)
    if not plan["episodes_to_export"]:
        raise TrainingExportError("no exportable episodes found")

    manifest = _load_source_manifest(source_root)
    source_dataset, output_dataset = _create_output_dataset(
        source_root=source_root,
        source_repo_id=source_repo_id,
        output_root=output_root,
        output_repo_id=output_repo_id,
    )
    for mapping in plan["episodes_to_export"]:
        source_episode = int(mapping["source_episode_index"])
        _copy_episode(
            source_root=source_root,
            source_repo_id=source_repo_id,
            source_episode_index=source_episode,
            output_dataset=output_dataset,
        )
    output_dataset.finalize()

    contract = _build_action_contract(manifest, source_dataset.features)
    atomic_write_json(output_root / "dataset_action_contract.json", contract)

    loader_validation = _validate_loader(output_root, output_repo_id)
    report = {
        "export_name": export_name or output_root.name,
        "source_root": str(source_root),
        "output_root": str(output_root),
        "source_repo_id": source_repo_id,
        "output_repo_id": output_repo_id,
        "source_episode_count": plan["source_episode_count"],
        "exported_episode_count": plan["exported_episode_count"],
        "excluded_episode_count": plan["excluded_episode_count"],
        "excluded_reasons": plan["excluded_reasons"],
        "episode_mapping": plan["episodes_to_export"],
        "dataset_schema_version": manifest["dataset_schema_version"],
        "action_semantics": manifest["action_semantics"],
        "safety_config_version": manifest["safety_config_version"],
        "compat_mapping_version": manifest["compat_mapping_version"],
        **_profile_plan_fields(manifest),
        "loader_validation": loader_validation,
    }
    atomic_write_json(output_root / "export_report.json", report)
    provenance = _build_provenance(
        source_root=source_root,
        output_root=output_root,
        source_repo_id=source_repo_id,
        output_repo_id=output_repo_id,
        manifest=manifest,
        config_file=config_file,
    )
    atomic_write_json(output_root / "export_provenance.json", provenance)
    return report


def _load_source_manifest(source_root: Path) -> dict[str, Any]:
    manifest_path = source_root / "dataset_manifest.json"
    if not manifest_path.exists():
        raise TrainingExportError("source dataset is legacy_unknown: dataset_manifest.json is missing")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _validate_source_manifest(manifest: Mapping[str, Any]) -> None:
    required = set(SEMANTIC_FIELDS) | set(SAFETY_SEMANTIC_FIELDS) | {"compat_mapping_verified"}
    if manifest.get("dataset_schema_version") == XLEROBOT_SO101_DATASET_SCHEMA_VERSION:
        required |= set(XLEROBOT_SO101_PROFILE_METADATA_FIELDS)
    missing = sorted(field for field in required if field not in manifest)
    if missing:
        raise TrainingExportError(f"source dataset metadata incomplete: missing {missing}")
    if manifest.get("dataset_schema_version") == XLEROBOT_SO101_DATASET_SCHEMA_VERSION:
        try:
            validate_xlerobot_so101_manifest_metadata(manifest)
        except ValueError as exc:
            raise TrainingExportError(str(exc)) from exc
        expected = {
            "dataset_schema_version": XLEROBOT_SO101_DATASET_SCHEMA_VERSION,
            "action_semantics": V2_ACTION_SEMANTICS,
            "teleop_mode": RELATIVE_JOINT_MODE,
            "command_frame_version": COMMAND_FRAME_VERSION,
            "compat_mapping_applied": True,
            "compat_mapping_verified": True,
            "safety_config_verified": True,
        }
    else:
        expected = {
            "dataset_schema_version": V2_DATASET_SCHEMA,
            "action_semantics": V2_ACTION_SEMANTICS,
            "teleop_mode": RELATIVE_JOINT_MODE,
            "command_frame_version": COMMAND_FRAME_VERSION,
            "compat_mapping_applied": True,
            "compat_mapping_version": "openarm_mini_818892a3",
            "compat_mapping_verified": True,
            "safety_config_verified": True,
        }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise TrainingExportError(
                f"source dataset semantic mismatch for {key}: expected {value!r}, got {manifest.get(key)!r}"
            )


def _episode_exclusion_reasons(record: Mapping[str, Any], manifest: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if record.get("label") != "success":
        reasons.append(str(record.get("label") or "label_not_success"))
    if record.get("accepted") is not True:
        reasons.append("not_accepted")
    if record.get("dq_status") != "pass":
        reasons.append("dq_fail")
    if record.get("contaminated") is True:
        reasons.append("contaminated")
    for field in SEMANTIC_FIELDS + SAFETY_SEMANTIC_FIELDS:
        if record.get(field) != manifest.get(field):
            reasons.append("semantic_mismatch")
            break
    if manifest.get("dataset_schema_version") == XLEROBOT_SO101_DATASET_SCHEMA_VERSION:
        for field in XLEROBOT_SO101_PROFILE_METADATA_FIELDS:
            if record.get(field) != manifest.get(field):
                reasons.append("semantic_mismatch")
                break
    if record.get("compat_mapping_verified") is not True:
        reasons.append("compat_mapping_unverified")
    if record.get("safety_config_verified") is not True:
        reasons.append("safety_config_unverified")
    if not _ready_verified(record):
        reasons.append("ready_not_verified")
    if not _sync_valid_at_record_start(record):
        reasons.append("sync_missing")
    contamination_reasons = set(record.get("contamination_reasons") or [])
    dq_reasons = set(record.get("dq_reasons") or [])
    blocked_events = {
        "emergency_freeze",
        "follower_tracking_freeze",
        "relative_resync_during_recording",
    }
    for reason in sorted(blocked_events & (contamination_reasons | dq_reasons)):
        reasons.append(reason)
    command_validation = record.get("command_validation") or {}
    try:
        consecutive = int(command_validation.get("max_consecutive_mismatch_frames", 0))
        threshold = int(record.get("mismatch_contamination_frames", manifest.get("mismatch_contamination_frames", 1)))
    except (TypeError, ValueError):
        consecutive = threshold = 1
    if consecutive >= threshold:
        reasons.append("driver_mismatch")
    return sorted(set(reasons))


def _ready_verified(record: Mapping[str, Any]) -> bool:
    if record.get("ready_verified") is True:
        return True
    if record.get("ready_state") == "verified":
        return True
    ready_result = record.get("ready_result")
    return isinstance(ready_result, Mapping) and ready_result.get("ok") is True


def _sync_valid_at_record_start(record: Mapping[str, Any]) -> bool:
    if record.get("sync_valid_at_record_start") is True:
        return True
    return record.get("sync_state_at_record_start") == "valid"


def _excluded(record: Mapping[str, Any], *reasons: str) -> dict[str, Any]:
    return {
        "source_episode_index": int(record.get("episode_index", -1)),
        "reasons": list(reasons),
    }


def _create_output_dataset(
    *,
    source_root: Path,
    source_repo_id: str,
    output_root: Path,
    output_repo_id: str,
):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    from .lerobot_compat import create_lerobot_dataset

    source_dataset = LeRobotDataset(source_repo_id, root=source_root)
    output_dataset = create_lerobot_dataset(
        output_repo_id,
        fps=int(source_dataset.fps),
        features=source_dataset.features,
        root=output_root,
        use_videos=bool(getattr(source_dataset.meta, "video_keys", [])),
        streaming_encoding=True,
        vcodec="h264",
        batch_encoding_size=1,
    )
    return source_dataset, output_dataset


def _copy_episode(
    *,
    source_root: Path,
    source_repo_id: str,
    source_episode_index: int,
    output_dataset: Any,
) -> None:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    episode_dataset = LeRobotDataset(source_repo_id, root=source_root, episodes=[source_episode_index])
    for index in range(episode_dataset.num_frames):
        item = episode_dataset[index]
        output_dataset.add_frame(_frame_for_add(item, episode_dataset.features))
    output_dataset.save_episode()


def _frame_for_add(item: Mapping[str, Any], features: Mapping[str, Any]) -> dict[str, Any]:
    frame: dict[str, Any] = {}
    for key, value in item.items():
        if key in GENERATED_FRAME_KEYS:
            continue
        if key not in features and key != "task":
            continue
        if key == "task":
            frame[key] = value
            continue
        dtype = features[key].get("dtype")
        if dtype in {"image", "video"}:
            frame[key] = _image_to_hwc_uint8(value)
        else:
            frame[key] = _tensor_to_numpy_or_scalar(value)
    return frame


def _tensor_to_numpy_or_scalar(value: Any) -> Any:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    if isinstance(value, np.ndarray) and value.shape == ():
        return value.item()
    return value


def _image_to_hwc_uint8(value: Any) -> np.ndarray:
    array = _tensor_to_numpy_or_scalar(value)
    if not isinstance(array, np.ndarray):
        array = np.asarray(array)
    if array.ndim == 3 and array.shape[0] in {1, 3}:
        array = np.transpose(array, (1, 2, 0))
    if array.dtype != np.uint8:
        array = np.clip(array, 0.0, 1.0)
        array = (array * 255.0).round().astype(np.uint8)
    return array


def _build_action_contract(manifest: Mapping[str, Any], features: Mapping[str, Any]) -> dict[str, Any]:
    action_feature = features.get("action")
    if not isinstance(action_feature, Mapping):
        raise TrainingExportError("source dataset is missing action feature")
    action_names = list(action_feature.get("names") or [])
    if not action_names:
        shape = action_feature.get("shape") or ()
        action_names = [f"action_{i}" for i in range(int(shape[0]))]
    if manifest.get("dataset_schema_version") == XLEROBOT_SO101_DATASET_SCHEMA_VERSION:
        return {
            "contract_version": XLEROBOT_SO101_CONTRACT_VERSION,
            "dataset_schema_version": XLEROBOT_SO101_DATASET_SCHEMA_VERSION,
            "action_semantics": V2_ACTION_SEMANTICS,
            "collection_teleop_mode": manifest["teleop_mode"],
            "safety_config_version": manifest["safety_config_version"],
            "compat_mapping_version": manifest["compat_mapping_version"],
            "dataset_action_source": "workbench_effective_command",
            "excluded_action_sources": [
                "master_raw_action",
                "relative_target",
                "target_before_safety",
                "driver_returned_action",
            ],
            "notes": (
                "The action column is the follower-space effective command in normalized "
                "LeRobot motor units after relative_joint_offset and Workbench safety processing."
            ),
            **expected_xlerobot_so101_profile_metadata(),
        }
    return {
        "contract_version": CONTRACT_VERSION,
        "dataset_schema_version": V2_DATASET_SCHEMA,
        "action_semantics": V2_ACTION_SEMANTICS,
        "action_space": "joint_position",
        "action_dim": len(action_names),
        "action_names": action_names,
        "units": "degrees",
        "control_mode": "joint_position_target",
        "collection_teleop_mode": manifest["teleop_mode"],
        "safety_config_version": manifest["safety_config_version"],
        "compat_mapping_version": manifest["compat_mapping_version"],
        "ready_required_for_collection": True,
        "sync_required_for_collection": True,
        "dataset_action_source": "workbench_effective_command",
        "excluded_action_sources": [
            "master_raw_action",
            "relative_target",
            "target_before_safety",
            "driver_returned_action",
        ],
        "notes": (
            "The action column in this training package is the follower-space effective command "
            "generated by the Workbench after compatibility mapping, relative teleop, and "
            "Workbench safety processing."
        ),
    }


def _profile_plan_fields(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: manifest[field]
        for field in XLEROBOT_SO101_PROFILE_METADATA_FIELDS
        if field in manifest
    }


def _validate_loader(output_root: Path, output_repo_id: str) -> dict[str, Any]:
    try:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset

        dataset = LeRobotDataset(output_repo_id, root=output_root)
        return {
            "passed": True,
            "frame_count": int(dataset.num_frames),
            "episode_count": int(dataset.num_episodes),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "passed": False,
            "frame_count": 0,
            "episode_count": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _build_provenance(
    *,
    source_root: Path,
    output_root: Path,
    source_repo_id: str,
    output_repo_id: str,
    manifest: Mapping[str, Any],
    config_file: Path | None,
) -> dict[str, Any]:
    return {
        "export_time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_root": str(source_root),
        "output_root": str(output_root),
        "source_repo_id": source_repo_id,
        "output_repo_id": output_repo_id,
        "workbench_git_commit": _git_commit(),
        "lerobot_revision": str(manifest.get("lerobot_revision", "unknown")),
        "config_file": str(config_file) if config_file is not None else "",
        "dataset_schema_version": manifest["dataset_schema_version"],
        "safety_config_version": manifest["safety_config_version"],
        "compat_mapping_version": manifest["compat_mapping_version"],
    }


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"
