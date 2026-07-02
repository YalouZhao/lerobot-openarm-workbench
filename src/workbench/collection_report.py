from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .atomic_io import atomic_write_json, atomic_write_text
from .dataset_manifest import read_jsonl
from .xlerobot_profile import XLEROBOT_SO101_PROFILE_METADATA_FIELDS


def build_collection_report(*, root: Path, repo_id: str | None = None) -> dict[str, Any]:
    root = Path(root).expanduser()
    manifest = _read_json(root / "dataset_manifest.json")
    episodes = read_jsonl(root / "episodes.jsonl")
    episode_details = [_episode_detail(root, item) for item in episodes]
    summary = _summary(manifest, episodes, repo_id=repo_id)
    dq = _dq_summary(episodes)
    contamination = _contamination_summary(episodes)
    command_quality = _command_quality_summary(episodes)
    tracking = _tracking_summary(episodes)
    timing = _timing_summary(episode_details)
    return {
        "dataset": {
            "root": str(root),
            "repo_id": repo_id or manifest.get("repo_id", ""),
            "dataset_schema_version": manifest.get("dataset_schema_version", ""),
            "action_semantics": manifest.get("action_semantics", ""),
            "safety_config_version": manifest.get("safety_config_version", ""),
            "compat_mapping_version": manifest.get("compat_mapping_version", ""),
            **{
                field: manifest.get(field)
                for field in XLEROBOT_SO101_PROFILE_METADATA_FIELDS
                if field in manifest
            },
        },
        "summary": summary,
        "dq": dq,
        "contamination": contamination,
        "command_quality": command_quality,
        "tracking": tracking,
        "timing": timing,
        "episodes": episode_details,
    }


def write_collection_report(*, root: Path, repo_id: str | None = None, output_dir: Path) -> dict[str, Any]:
    output_dir = Path(output_dir).expanduser()
    report = build_collection_report(root=root, repo_id=repo_id)
    atomic_write_json(output_dir / "collection_report.json", report)
    atomic_write_text(output_dir / "collection_report.md", render_collection_report_markdown(report))
    return report


def render_collection_report_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Collection Batch QA Report",
        "",
        "## Dataset",
        "",
        "| field | value |",
        "| --- | --- |",
    ]
    for key, value in report["dataset"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## Summary", "", "| field | value |", "| --- | --- |"])
    for key, value in report["summary"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## DQ Reasons", "", "| reason | count |", "| --- | ---: |"])
    for reason, count in sorted(report["dq"]["reason_counts"].items()):
        lines.append(f"| {reason} | {count} |")
    lines.extend(["", "## Contamination Reasons", "", "| reason | count |", "| --- | ---: |"])
    for reason, count in sorted(report["contamination"]["reason_counts"].items()):
        lines.append(f"| {reason} | {count} |")
    lines.extend(["", "## Timing", "", "| field | value |", "| --- | --- |"])
    for key, value in report["timing"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## Episode Details",
            "",
            "| episode | label | accepted | dq | contaminated | frames | fps | timing |",
            "| ---: | --- | --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for item in report["episodes"]:
        lines.append(
            "| {episode_index} | {label} | {accepted} | {dq_status} | {contaminated} | "
            "{frame_count} | {fps} | {timing_sidecar} |".format(**item)
        )
    lines.append("")
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _summary(manifest: Mapping[str, Any], episodes: list[dict[str, Any]], *, repo_id: str | None) -> dict[str, Any]:
    labels = Counter(str(item.get("label", "unlabeled")) for item in episodes)
    dq_statuses = Counter(str(item.get("dq_status", "unknown")) for item in episodes)
    return {
        "repo_id": repo_id or manifest.get("repo_id", ""),
        "episode_count": len(episodes),
        "frame_count": sum(int(item.get("frame_count") or 0) for item in episodes),
        "success_count": labels.get("success", 0),
        "failure_count": labels.get("failure", 0),
        "discard_count": labels.get("discard", 0),
        "accepted_count": sum(1 for item in episodes if item.get("accepted") is True),
        "dq_pass_count": dq_statuses.get("pass", 0),
        "dq_fail_count": dq_statuses.get("fail", 0),
        "contaminated_count": sum(1 for item in episodes if item.get("contaminated") is True),
        "exportable_count": sum(1 for item in episodes if _is_exportable(item)),
    }


def _dq_summary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    reasons = Counter(reason for item in episodes for reason in (item.get("dq_reasons") or []))
    return {
        "dq_pass_count": sum(1 for item in episodes if item.get("dq_status") == "pass"),
        "dq_fail_count": sum(1 for item in episodes if item.get("dq_status") == "fail"),
        "reason_counts": dict(sorted(reasons.items())),
    }


def _contamination_summary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    reasons = Counter(reason for item in episodes for reason in (item.get("contamination_reasons") or []))
    return {
        "contaminated_count": sum(1 for item in episodes if item.get("contaminated") is True),
        "reason_counts": dict(sorted(reasons.items())),
    }


def _command_quality_summary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "action_spike_count": sum(_nested_int(item, "command_validation", "action_spike_frames") for item in episodes),
        "driver_mismatch_count": sum(_nested_int(item, "command_validation", "mismatch_frames") for item in episodes),
        "nonfinite_action_count": sum(_nested_int(item, "command_validation", "nonfinite_action_frames") for item in episodes),
    }


def _tracking_summary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tracking_warning_count": sum(_nested_int(item, "tracking_validation", "warning_frames") for item in episodes),
        "tracking_freeze_count": sum(_nested_int(item, "tracking_validation", "freeze_frames") for item in episodes),
    }


def _timing_summary(episode_details: list[dict[str, Any]]) -> dict[str, Any]:
    fps_values = [float(item["fps"]) for item in episode_details if _is_number(item.get("fps"))]
    step_max = [
        float(item.get("max_control_step_duration_ms"))
        for item in episode_details
        if _is_number(item.get("max_control_step_duration_ms"))
    ]
    action_mean = [
        float(item.get("mean_action_send_latency_ms"))
        for item in episode_details
        if _is_number(item.get("mean_action_send_latency_ms"))
    ]
    return {
        "mean_control_fps": round(sum(fps_values) / len(fps_values), 3) if fps_values else 0.0,
        "min_control_fps": round(min(fps_values), 3) if fps_values else 0.0,
        "max_control_step_duration_ms": round(max(step_max), 3) if step_max else 0.0,
        "mean_action_send_latency_ms": round(sum(action_mean) / len(action_mean), 3) if action_mean else 0.0,
        "timing_sidecar_missing_count": sum(1 for item in episode_details if item.get("timing_sidecar_missing")),
    }


def _episode_detail(root: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    timing = item.get("timing_summary") if isinstance(item.get("timing_summary"), Mapping) else {}
    step = timing.get("control_step_duration_ms") if isinstance(timing.get("control_step_duration_ms"), Mapping) else {}
    action = timing.get("action_send_latency_ms") if isinstance(timing.get("action_send_latency_ms"), Mapping) else {}
    timing_sidecar = str(item.get("timing_sidecar") or "")
    timing_missing = bool(timing_sidecar) and _resolve_timing_sidecar(root, item, timing_sidecar) is None
    return {
        "episode_index": int(item.get("episode_index", -1)),
        "label": str(item.get("label", "unlabeled")),
        "accepted": bool(item.get("accepted") is True),
        "dq_status": str(item.get("dq_status", "unknown")),
        "contaminated": bool(item.get("contaminated") is True),
        "contamination_reasons": list(item.get("contamination_reasons") or []),
        "dq_reasons": list(item.get("dq_reasons") or []),
        "frame_count": int(item.get("frame_count") or 0),
        "duration_s": _duration_s(item),
        "fps": float(item.get("fps") or 0.0),
        "action_spike_frames": _nested_int(item, "command_validation", "action_spike_frames"),
        "driver_mismatch_count": _nested_int(item, "command_validation", "mismatch_frames"),
        "timing_sidecar": timing_sidecar,
        "timing_sidecar_missing": timing_missing,
        "max_control_step_duration_ms": step.get("max", 0.0),
        "mean_action_send_latency_ms": action.get("mean", 0.0),
    }


def _is_exportable(item: Mapping[str, Any]) -> bool:
    return (
        item.get("label") == "success"
        and item.get("accepted") is True
        and item.get("dq_status") == "pass"
        and item.get("contaminated") is not True
    )


def _resolve_timing_sidecar(root: Path, item: Mapping[str, Any], timing_sidecar: str) -> Path | None:
    direct = root / timing_sidecar
    if direct.exists():
        return direct
    session_id = str(item.get("session_id") or "")
    if session_id:
        sibling_session = root.parent / f"{root.name}_sessions" / session_id / timing_sidecar
        if sibling_session.exists():
            return sibling_session
    return None


def _nested_int(item: Mapping[str, Any], parent: str, key: str) -> int:
    value = item.get(parent)
    if not isinstance(value, Mapping):
        return 0
    try:
        return int(value.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _duration_s(item: Mapping[str, Any]) -> float:
    fps = item.get("fps")
    frames = item.get("frame_count")
    try:
        fps_float = float(fps)
        frame_int = int(frames)
    except (TypeError, ValueError):
        return 0.0
    if fps_float <= 0:
        return 0.0
    return round(frame_int / fps_float, 3)


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
