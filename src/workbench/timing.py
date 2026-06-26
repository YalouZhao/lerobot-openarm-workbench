from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .atomic_io import atomic_write_json


TIMING_FORMAT = "openarm_workbench_timing_v1"


def _round_ms(ns: int | float) -> float:
    return round(float(ns) / 1_000_000.0, 3)


def _stats_ms(values_ns: Sequence[int | float]) -> dict[str, float]:
    if not values_ns:
        return {}
    values_ms = sorted(_round_ms(value) for value in values_ns)
    count = len(values_ms)
    return {
        "min": values_ms[0],
        "max": values_ms[-1],
        "mean": round(sum(values_ms) / count, 3),
        "p95": values_ms[min(count - 1, int(count * 0.95))],
    }


def summarize_timing_events(
    events: Sequence[Mapping[str, Any]],
    *,
    target_fps: float,
) -> dict[str, Any]:
    target_fps = float(target_fps)
    target_period_ms = round(1000.0 / target_fps, 3) if target_fps > 0 else 0.0
    control_durations: list[int] = []
    send_latencies: list[int] = []
    for event in events:
        start = event.get("control_step_start_time_ns")
        end = event.get("control_step_end_time_ns")
        send = event.get("action_send_time_ns")
        if isinstance(start, int) and isinstance(end, int) and end >= start:
            control_durations.append(end - start)
            if isinstance(send, int) and send >= start:
                send_latencies.append(send - start)
    return {
        "event_count": len(events),
        "target_fps": target_fps,
        "target_period_ms": target_period_ms,
        "control_step_duration_ms": _stats_ms(control_durations),
        "action_send_latency_ms": _stats_ms(send_latencies),
    }


def write_timing_sidecar(
    session_dir: Path,
    *,
    episode_index: int,
    events: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> Path:
    session_dir.mkdir(parents=True, exist_ok=True)
    output = session_dir / f"timing_episode_{episode_index:06d}.json"
    atomic_write_json(
        output,
        {
            "format": TIMING_FORMAT,
            "episode_index": episode_index,
            "summary": dict(summary),
            "events": [dict(event) for event in events],
        },
    )
    return output
