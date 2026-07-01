from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .atomic_io import atomic_write_jsonl
from .config import (
    ABSOLUTE_PASSTHROUGH_MODE,
    COMMAND_FRAME_VERSION,
    V2_ACTION_SEMANTICS,
    V2_DATASET_SCHEMA,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class EpisodeRecord:
    episode_index: int
    task: str
    accepted: bool
    label: str
    notes: str
    started_at: str
    ended_at: str
    frame_count: int
    fps: float
    save_duration_s: float
    cameras: dict[str, str]
    dataset_schema_version: str = V2_DATASET_SCHEMA
    action_semantics: str = V2_ACTION_SEMANTICS
    teleop_mode: str = ABSOLUTE_PASSTHROUGH_MODE
    command_frame_version: int = COMMAND_FRAME_VERSION
    lerobot_revision: str = "unknown"
    compat_mapping_applied: bool = True
    compat_mapping_version: str = "openarm_mini_818892a3"
    compat_mapping_verified: bool = True
    contaminated: bool = False
    contamination_reasons: tuple[str, ...] = ()
    safety_config_version: str = "unconfigured"
    safety_config_verified: bool = False
    verified_by: str = ""
    verified_at: str = ""
    verification_basis: str = ""
    safety_action_keys: list[str] = field(default_factory=list)
    hard_limits: dict[str, list[float]] = field(default_factory=dict)
    soft_limits: dict[str, list[float]] = field(default_factory=dict)
    deadband: dict[str, float] = field(default_factory=dict)
    max_step: dict[str, float] = field(default_factory=dict)
    velocity_limit: dict[str, float] = field(default_factory=dict)
    tracking_error_warning: dict[str, float] = field(default_factory=dict)
    tracking_error_contamination: dict[str, float] = field(default_factory=dict)
    tracking_error_freeze: dict[str, float] = field(default_factory=dict)
    driver_mismatch_atol: float = 0.0
    mismatch_contamination_frames: int = 1
    tracking_error_persistence_frames: int = 1
    command_validation: dict[str, Any] = field(default_factory=dict)
    tracking_validation: dict[str, Any] = field(default_factory=dict)
    ready_state: str = "invalid"
    ready_result: dict[str, Any] = field(default_factory=dict)
    sync_valid_at_record_start: bool = False
    sync_state_at_record_start: str = "invalid"
    sync_result_at_record_start: dict[str, Any] = field(default_factory=dict)
    auto_stopped_by_safety: bool = False
    auto_stop_save_status: str = ""
    timing_summary: dict[str, Any] = field(default_factory=dict)
    timing_sidecar: str = ""
    dq_status: str = "pass"
    dq_reasons: tuple[str, ...] = ()
    acceptance_reasons: tuple[str, ...] = ()


class EpisodeManifest:
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.episodes_path = self.session_dir / "episodes.jsonl"
        self.events_path = self.session_dir / "events.jsonl"

    def append_episode(self, record: EpisodeRecord) -> None:
        self._append_jsonl(self.episodes_path, asdict(record))

    def replace_episodes(self, records: list[dict[str, Any]]) -> None:
        atomic_write_jsonl(self.episodes_path, records)

    def update_label(
        self,
        episode_index: int,
        label: str,
        accepted: bool,
        notes: str = "",
    ) -> dict[str, Any]:
        records = self.read_episodes()
        updated: dict[str, Any] | None = None
        for item in records:
            if int(item["episode_index"]) == episode_index:
                item["label"] = label
                item["accepted"] = accepted
                item["notes"] = notes
                item["labeled_at"] = now_iso()
                updated = item
                break
        if updated is None:
            raise KeyError(f"episode_index={episode_index} not found")
        self._rewrite_jsonl(self.episodes_path, records)
        return updated

    def read_episodes(self) -> list[dict[str, Any]]:
        if not self.episodes_path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.episodes_path.read_text().splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
        return records

    def export_accepted(self, output_path: Path | None = None) -> Path:
        output = output_path or (self.session_dir / "accepted_episodes.txt")
        accepted = [
            str(item["episode_index"])
            for item in self.read_episodes()
            if item.get("accepted") is True and item.get("label") == "success"
        ]
        output.write_text("\n".join(accepted) + ("\n" if accepted else ""))
        return output

    def event(self, level: str, event: str, message: str, **extra: Any) -> None:
        payload = {
            "time": now_iso(),
            "level": level,
            "event": event,
            "message": message,
            **extra,
        }
        self._append_jsonl(self.events_path, payload)

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    @staticmethod
    def _rewrite_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
        atomic_write_jsonl(path, payloads)
