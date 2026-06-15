from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from .atomic_io import atomic_write_json, atomic_write_jsonl, atomic_write_text
from .episode_manifest import EpisodeRecord, now_iso


VALID_LABELS = {"success", "failure", "discard", "unlabeled"}


def accepted_for_label(label: str) -> bool:
    if label not in VALID_LABELS:
        raise ValueError("label must be success, failure, discard, or unlabeled")
    return label == "success"


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
    ) -> None:
        self.dataset_root = dataset_root
        self.dataset_name = dataset_name
        self.repo_id = repo_id
        self.task_text = task_text.strip()
        self.session_id = session_id
        self.dataset_manifest_path = dataset_root / "dataset_manifest.json"
        self.episodes_path = dataset_root / "episodes.jsonl"
        self.accepted_episodes_path = dataset_root / "accepted_episodes.json"
        self.transactions_path = dataset_root / "manifest_transactions.jsonl"
        self.export_reports_dir = dataset_root / "export_reports"
        self.lock_path = dataset_root / ".manifest.lock"

    def ensure_initialized(self) -> None:
        with file_lock(self.lock_path):
            self._ensure_initialized_unlocked()

    def append_episode(self, record: EpisodeRecord) -> dict[str, Any]:
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
        accepted = accepted_for_label(label)
        with file_lock(self.lock_path):
            self._ensure_initialized_unlocked()
            records = read_jsonl(self.episodes_path)
            updated: dict[str, Any] | None = None
            for item in records:
                if int(item["episode_index"]) == int(episode_index):
                    item["label"] = label
                    item["accepted"] = accepted
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
            if item.get("label") == "success" and item.get("accepted") is True
        ]
        atomic_write_json(
            self.accepted_episodes_path,
            {
                "updated_at": now_iso(),
                "criteria": {"label": "success", "accepted": True},
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
