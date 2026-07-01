from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator, Mapping

from .atomic_io import atomic_write_json, atomic_write_jsonl, atomic_write_text
from .config import (
    ABSOLUTE_PASSTHROUGH_MODE,
    COMMAND_FRAME_VERSION,
    RELATIVE_JOINT_MODE,
    V2_ACTION_SEMANTICS,
    V2_DATASET_SCHEMA,
    validate_semantic_configuration,
)
from .episode_manifest import EpisodeRecord, now_iso


VALID_LABELS = {"success", "failure", "discard", "unlabeled"}
SEMANTIC_FIELDS = (
    "dataset_schema_version",
    "action_semantics",
    "teleop_mode",
    "command_frame_version",
    "compat_mapping_applied",
    "compat_mapping_version",
)
SAFETY_SEMANTIC_FIELDS = (
    "safety_config_version",
    "safety_config_verified",
    "verified_by",
    "verified_at",
    "verification_basis",
    "hard_limits",
    "soft_limits",
    "deadband",
    "max_step",
    "velocity_limit",
    "tracking_error_warning",
    "tracking_error_contamination",
    "tracking_error_freeze",
    "driver_mismatch_atol",
    "mismatch_contamination_frames",
    "tracking_error_persistence_frames",
)


class DatasetSchemaError(RuntimeError):
    pass


def export_v2_accepted_indices(dataset_root: Path, output_path: Path | None = None) -> Path:
    dataset_root = Path(dataset_root).expanduser()
    manifest_path = dataset_root / "dataset_manifest.json"
    if not manifest_path.exists():
        raise DatasetSchemaError("legacy_unknown dataset root: dataset_manifest.json is missing")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = [field for field in SEMANTIC_FIELDS if field not in payload]
    if missing:
        raise DatasetSchemaError(f"legacy_unknown dataset root: missing semantic fields {missing}")
    expected = {
        "dataset_schema_version": V2_DATASET_SCHEMA,
        "action_semantics": V2_ACTION_SEMANTICS,
        "command_frame_version": COMMAND_FRAME_VERSION,
    }
    for field, expected_value in expected.items():
        if payload[field] != expected_value:
            raise DatasetSchemaError(
                f"v2 accepted export requires {field}={expected_value!r}, got {payload[field]!r}"
            )
    valid_v2_modes = {ABSOLUTE_PASSTHROUGH_MODE, RELATIVE_JOINT_MODE}
    if payload["teleop_mode"] not in valid_v2_modes:
        raise DatasetSchemaError(
            f"v2 accepted export requires teleop_mode in {sorted(valid_v2_modes)}, "
            f"got {payload['teleop_mode']!r}"
        )
    if payload["compat_mapping_applied"] is not True:
        raise DatasetSchemaError("v2 accepted export requires compat_mapping_applied=true")
    if payload["compat_mapping_version"] != "openarm_mini_818892a3":
        raise DatasetSchemaError("v2 accepted export requires compat_mapping_version='openarm_mini_818892a3'")
    if payload.get("compat_mapping_verified") is not True:
        raise DatasetSchemaError("v2 accepted export requires compat_mapping_verified=true")
    missing_safety = [field for field in SAFETY_SEMANTIC_FIELDS if field not in payload]
    if missing_safety:
        raise DatasetSchemaError(f"legacy_unknown dataset root: missing semantic fields {missing_safety}")
    if payload.get("safety_config_verified") is not True:
        raise DatasetSchemaError("v2 accepted export requires safety_config_verified=true")

    records = read_jsonl(dataset_root / "episodes.jsonl")
    required_fields = SEMANTIC_FIELDS + SAFETY_SEMANTIC_FIELDS
    expected_episode_semantics = {field: payload[field] for field in required_fields}
    for item in records:
        actual_episode_semantics = {field: item.get(field) for field in required_fields}
        if actual_episode_semantics != expected_episode_semantics:
            raise DatasetSchemaError(
                f"episode {item.get('episode_index')} semantic mismatch: "
                f"expected {expected_episode_semantics}, got {actual_episode_semantics}"
            )
    accepted = [
        str(int(item["episode_index"]))
        for item in records
        if item.get("label") == "success"
        and item.get("accepted") is True
        and item.get("contaminated") is not True
    ]
    output = output_path or (dataset_root / "accepted_episodes.txt")
    output = Path(output).expanduser()
    atomic_write_text(output, "\n".join(accepted) + ("\n" if accepted else ""))
    return output


def accepted_for_label(label: str) -> bool:
    if label not in VALID_LABELS:
        raise ValueError("label must be success, failure, discard, or unlabeled")
    return label == "success"


def derive_acceptance(
    item: Mapping[str, Any],
    *,
    label: str,
    compat_mapping_verified: bool,
    safety_config_verified: bool,
) -> tuple[bool, list[str]]:
    accepted_for_label(label)
    reasons: list[str] = []
    if label != "success":
        reasons.append(f"label_not_success:{label}")
    dq_status = str(item.get("dq_status", "unknown"))
    if dq_status != "pass":
        reasons.append(f"dq_status_not_pass:{dq_status}")
    if not compat_mapping_verified:
        reasons.append("compat_mapping_unverified")
    if not safety_config_verified:
        reasons.append("safety_config_unverified")
    if item.get("contaminated") is True:
        contamination_reasons = item.get("contamination_reasons") or ["unspecified"]
        reasons.extend(f"contaminated:{reason}" for reason in contamination_reasons)
    return not reasons, reasons


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as f:
        try:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


class CanonicalDatasetManifest:
    def __init__(
        self,
        dataset_root: Path,
        dataset_name: str,
        repo_id: str,
        task_text: str,
        session_id: str,
        dataset_schema_version: str = V2_DATASET_SCHEMA,
        action_semantics: str = V2_ACTION_SEMANTICS,
        teleop_mode: str = ABSOLUTE_PASSTHROUGH_MODE,
        command_frame_version: int = COMMAND_FRAME_VERSION,
        lerobot_revision: str = "unknown",
        compat_mapping_applied: bool = True,
        compat_mapping_version: str = "openarm_mini_818892a3",
        compat_mapping_verified: bool = True,
        safety_metadata: Mapping[str, Any] | None = None,
        profile_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.dataset_root = dataset_root
        self.dataset_name = dataset_name
        self.repo_id = repo_id
        self.task_text = task_text.strip()
        self.session_id = session_id
        validate_semantic_configuration(
            dataset_schema_version=dataset_schema_version,
            action_semantics=action_semantics,
            teleop_mode=teleop_mode,
            command_frame_version=command_frame_version,
        )
        self.dataset_schema_version = dataset_schema_version
        self.action_semantics = action_semantics
        self.teleop_mode = teleop_mode
        self.command_frame_version = command_frame_version
        self.lerobot_revision = lerobot_revision
        self.compat_mapping_applied = compat_mapping_applied
        self.compat_mapping_version = compat_mapping_version
        self.compat_mapping_verified = compat_mapping_verified
        self.safety_metadata = dict(safety_metadata) if safety_metadata is not None else None
        self.profile_metadata = dict(profile_metadata) if profile_metadata is not None else None
        self.dataset_manifest_path = dataset_root / "dataset_manifest.json"
        self.episodes_path = dataset_root / "episodes.jsonl"
        self.accepted_episodes_path = dataset_root / "accepted_episodes.json"
        self.transactions_path = dataset_root / "manifest_transactions.jsonl"
        self.export_reports_dir = dataset_root / "export_reports"
        self.lock_path = dataset_root / ".manifest.lock"

    def validate_for_collection(self) -> str:
        if not self.dataset_root.exists():
            return "new"
        if not self.dataset_root.is_dir():
            raise DatasetSchemaError(f"dataset root is not a directory: {self.dataset_root}")
        if not any(self.dataset_root.iterdir()):
            return "new"
        existing = self._read_dataset_manifest()
        if existing is None:
            raise DatasetSchemaError(
                "legacy_unknown dataset root: non-empty root has no dataset_manifest.json; "
                "append is blocked until explicit audit or migration"
            )
        self._validate_existing_semantics(existing)
        return "existing"

    def ensure_initialized(self, *, new_dataset_created: bool = False) -> None:
        if new_dataset_created:
            existing = self._read_dataset_manifest()
            if existing is not None:
                self._validate_existing_semantics(existing)
        else:
            self.validate_for_collection()
        with file_lock(self.lock_path):
            self._ensure_initialized_unlocked()

    def append_episode(self, record: EpisodeRecord) -> dict[str, Any]:
        self.validate_for_collection()
        with file_lock(self.lock_path):
            self._ensure_initialized_unlocked()
            records = read_jsonl(self.episodes_path)
            episode_index = int(record.episode_index)
            if any(int(item["episode_index"]) == episode_index for item in records):
                raise ValueError(f"episode_index={episode_index} already exists")
            payload = self._record_payload(record)
            payload["label"] = "unlabeled"
            payload["accepted"] = False
            records.append(payload)
            self._write_records_unlocked(records)
            self._write_transaction_unlocked("stop_episode", episode_index, "ok")
            return payload

    def update_label(self, episode_index: int, label: str, notes: str = "") -> dict[str, Any]:
        self.validate_for_collection()
        with file_lock(self.lock_path):
            self._ensure_initialized_unlocked()
            records = read_jsonl(self.episodes_path)
            updated: dict[str, Any] | None = None
            for item in records:
                if int(item["episode_index"]) == int(episode_index):
                    safety_verified = (
                        True
                        if self.safety_metadata is None
                        else self.safety_metadata.get("safety_config_verified") is True
                    )
                    accepted, acceptance_reasons = derive_acceptance(
                        item,
                        label=label,
                        compat_mapping_verified=self.compat_mapping_verified,
                        safety_config_verified=safety_verified,
                    )
                    item["label"] = label
                    item["accepted"] = accepted
                    item["acceptance_reasons"] = acceptance_reasons
                    item["notes"] = notes
                    item["labeled_at"] = now_iso()
                    item["updated_at"] = now_iso()
                    updated = item
                    break
            if updated is None:
                raise KeyError(f"episode_index={episode_index} not found")
            self._write_records_unlocked(records)
            self._write_transaction_unlocked(f"mark_{label}", int(episode_index), "ok")
            return updated

    def read_episodes(self) -> list[dict[str, Any]]:
        return read_jsonl(self.episodes_path)

    def _ensure_initialized_unlocked(self) -> None:
        self.dataset_root.mkdir(parents=True, exist_ok=True)
        self.export_reports_dir.mkdir(parents=True, exist_ok=True)

        existing = self._read_dataset_manifest()
        now = now_iso()
        if existing is None:
            payload = {
                "schema_version": 1,
                "dataset_schema_version": self.dataset_schema_version,
                "action_semantics": self.action_semantics,
                "teleop_mode": self.teleop_mode,
                "command_frame_version": self.command_frame_version,
                "lerobot_revision": self.lerobot_revision,
                "compat_mapping_applied": self.compat_mapping_applied,
                "compat_mapping_version": self.compat_mapping_version,
                "compat_mapping_verified": self.compat_mapping_verified,
                **(self.profile_metadata or {}),
                **(self.safety_metadata or {}),
                "created_at": now,
                "updated_at": now,
                "dataset_name": self.dataset_name,
                "dataset_root": str(self.dataset_root),
                "repo_id": self.repo_id,
                "data_format": "LeRobot v3",
                "task_text": self.task_text,
                "task_text_locked": True,
                "session_ids": [self.session_id],
                "current_session_id": self.session_id,
                "episode_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "discard_count": 0,
                "unlabeled_count": 0,
            }
            atomic_write_json(self.dataset_manifest_path, payload)
        else:
            self._validate_existing_semantics(existing)
            session_ids = list(existing.get("session_ids") or [])
            if self.session_id not in session_ids:
                session_ids.append(self.session_id)
            existing["session_ids"] = session_ids
            existing["current_session_id"] = self.session_id
            existing["updated_at"] = now
            atomic_write_json(self.dataset_manifest_path, existing)

        if not self.episodes_path.exists():
            atomic_write_text(self.episodes_path, "")
        if not self.transactions_path.exists():
            atomic_write_text(self.transactions_path, "")
        self._rebuild_accepted_unlocked(read_jsonl(self.episodes_path))

    def _record_payload(self, record: EpisodeRecord) -> dict[str, Any]:
        payload = asdict(record)
        expected = self._expected_semantics()
        actual = {field: payload.get(field) for field in expected}
        if actual != expected:
            raise DatasetSchemaError(f"episode semantic mismatch: expected {expected}, got {actual}")
        payload.setdefault("notes", "")
        payload["session_id"] = self.session_id
        payload["dataset_name"] = self.dataset_name
        payload["task_text"] = payload.get("task") or self.task_text
        payload["updated_at"] = now_iso()
        return payload

    def _write_records_unlocked(self, records: list[dict[str, Any]]) -> None:
        atomic_write_jsonl(self.episodes_path, records)
        self._rebuild_accepted_unlocked(records)
        self._update_counts_unlocked(records)

    def _rebuild_accepted_unlocked(self, records: list[dict[str, Any]]) -> None:
        accepted = [
            int(item["episode_index"])
            for item in records
            if item.get("label") == "success"
            and item.get("accepted") is True
            and item.get("contaminated") is not True
        ]
        atomic_write_json(
            self.accepted_episodes_path,
            {
                "updated_at": now_iso(),
                "criteria": {
                    "label": "success",
                    "dq_status": "pass",
                    "accepted": True,
                },
                "episodes": accepted,
            },
        )

    def _update_counts_unlocked(self, records: list[dict[str, Any]]) -> None:
        payload = self._read_dataset_manifest() or {}
        payload["updated_at"] = now_iso()
        payload["episode_count"] = len(records)
        for label in VALID_LABELS:
            payload[f"{label}_count"] = sum(1 for item in records if item.get("label") == label)
        atomic_write_json(self.dataset_manifest_path, payload)

    def _write_transaction_unlocked(self, operation: str, episode_index: int, final_status: str) -> None:
        records = read_jsonl(self.transactions_path)
        records.append(
            {
                "transaction_id": f"{now_iso()}:{operation}:{episode_index}",
                "timestamp": now_iso(),
                "operation": operation,
                "episode_index": episode_index,
                "dataset_name": self.dataset_name,
                "session_id": self.session_id,
                "dataset_root_write_status": "ok",
                "accepted_episodes_rebuild_status": "ok",
                "session_mirror_write_status": "pending",
                "final_status": final_status,
                "error_message": "",
            }
        )
        atomic_write_jsonl(self.transactions_path, records)

    def _read_dataset_manifest(self) -> dict[str, Any] | None:
        if not self.dataset_manifest_path.exists():
            return None
        return json.loads(self.dataset_manifest_path.read_text(encoding="utf-8"))

    def _expected_semantics(self) -> dict[str, Any]:
        expected = {
            "dataset_schema_version": self.dataset_schema_version,
            "action_semantics": self.action_semantics,
            "teleop_mode": self.teleop_mode,
            "command_frame_version": self.command_frame_version,
            "compat_mapping_applied": self.compat_mapping_applied,
            "compat_mapping_version": self.compat_mapping_version,
        }
        if self.safety_metadata is not None:
            expected.update(self.safety_metadata)
        if self.profile_metadata is not None:
            expected.update(self.profile_metadata)
        return expected

    def _validate_existing_semantics(self, payload: dict[str, Any]) -> None:
        expected = self._expected_semantics()
        missing = [field for field in expected if field not in payload]
        if missing:
            raise DatasetSchemaError(
                f"legacy_unknown dataset root: missing semantic fields {missing}; "
                "append is blocked until explicit audit or migration"
            )
        for field, expected_value in expected.items():
            actual_value = payload[field]
            if actual_value != expected_value:
                raise DatasetSchemaError(
                    f"dataset semantic mismatch for {field}: expected {expected_value!r}, got {actual_value!r}"
                )
