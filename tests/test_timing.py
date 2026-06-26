from __future__ import annotations

import json
from pathlib import Path

from workbench.timing import summarize_timing_events, write_timing_sidecar


def test_timing_summary_and_sidecar_are_parseable(tmp_path: Path) -> None:
    events = [
        {
            "frame_index": 0,
            "control_step_start_time_ns": 100_000_000,
            "follower_obs_time_ns": 110_000_000,
            "master_read_time_ns": 120_000_000,
            "action_send_time_ns": 150_000_000,
            "control_step_end_time_ns": 160_000_000,
        },
        {
            "frame_index": 1,
            "control_step_start_time_ns": 200_000_000,
            "follower_obs_time_ns": 210_000_000,
            "master_read_time_ns": 225_000_000,
            "action_send_time_ns": 260_000_000,
            "control_step_end_time_ns": 280_000_000,
        },
    ]

    summary = summarize_timing_events(events, target_fps=30)
    path = write_timing_sidecar(tmp_path, episode_index=3, events=events, summary=summary)

    payload = json.loads(path.read_text())
    assert path.name == "timing_episode_000003.json"
    assert payload["episode_index"] == 3
    assert payload["format"] == "openarm_workbench_timing_v1"
    assert payload["summary"]["event_count"] == 2
    assert payload["summary"]["control_step_duration_ms"]["max"] == 80.0
    assert payload["summary"]["target_period_ms"] == 33.333
    assert payload["events"] == events


def test_empty_timing_summary_is_explicit() -> None:
    summary = summarize_timing_events([], target_fps=30)

    assert summary == {
        "event_count": 0,
        "target_fps": 30.0,
        "target_period_ms": 33.333,
        "control_step_duration_ms": {},
        "action_send_latency_ms": {},
    }
