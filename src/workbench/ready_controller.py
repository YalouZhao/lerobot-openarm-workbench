from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


def smoothstep(value: float) -> float:
    x = min(1.0, max(0.0, float(value)))
    return x * x * (3.0 - 2.0 * x)


@dataclass(frozen=True)
class ReadySettings:
    path: Path
    fps: int = 30
    tolerance: float = 2.0
    settle_time_s: float = 0.2
    verify_after_move: bool = True


@dataclass(frozen=True)
class ReadyResult:
    ok: bool
    path: str
    final_target: dict[str, float]
    actual_qpos: dict[str, float]
    errors: dict[str, float]
    max_abs_error: float
    started_at: str
    ended_at: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "path": self.path,
            "final_target": self.final_target,
            "actual_qpos": self.actual_qpos,
            "errors": self.errors,
            "max_abs_error": self.max_abs_error,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "reason": self.reason,
        }


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class ReadyController:
    def __init__(self, settings: ReadySettings):
        if settings.fps <= 0:
            raise ValueError("ready fps must be positive")
        if settings.tolerance < 0:
            raise ValueError("ready tolerance must be non-negative")
        if settings.settle_time_s < 0:
            raise ValueError("ready settle_time_s must be non-negative")
        self.settings = settings

    def load_waypoints(self) -> list[dict[str, Any]]:
        payload = json.loads(self.settings.path.read_text(encoding="utf-8"))
        waypoints = payload.get("waypoints")
        if not isinstance(waypoints, list) or not waypoints:
            raise ValueError(f"{self.settings.path} must contain non-empty waypoints")
        return waypoints

    def move_to_ready(
        self,
        robot: Any,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> ReadyResult:
        started_at = _now_iso()
        current = self._current_action(robot)
        final_target: dict[str, float] = {}
        for waypoint in self.load_waypoints():
            target = self._target_for_current_keys(current, waypoint)
            final_target = target
            duration_s = float(waypoint.get("duration_s", 0.0))
            if duration_s <= 0:
                raise ValueError("ready waypoint duration_s must be positive")
            steps = max(1, int(round(duration_s * self.settings.fps)))
            start = dict(current)
            for index in range(1, steps + 1):
                alpha = smoothstep(index / steps)
                command = {
                    key: start[key] + (target[key] - start[key]) * alpha
                    for key in current
                }
                robot.send_action(command)
                current = dict(command)
                sleep(1.0 / self.settings.fps)
        if self.settings.settle_time_s:
            sleep(self.settings.settle_time_s)

        actual = self._current_action(robot)
        errors = {key: float(actual[key]) - float(final_target[key]) for key in final_target}
        max_abs_error = max((abs(value) for value in errors.values()), default=0.0)
        ok = (not self.settings.verify_after_move) or max_abs_error <= self.settings.tolerance
        return ReadyResult(
            ok=ok,
            path=str(self.settings.path),
            final_target=final_target,
            actual_qpos=actual,
            errors=errors,
            max_abs_error=max_abs_error,
            started_at=started_at,
            ended_at=_now_iso(),
            reason="" if ok else "ready final pose outside tolerance",
        )

    @staticmethod
    def _current_action(robot: Any) -> dict[str, float]:
        if hasattr(robot, "get_observation"):
            obs = robot.get_observation()
        elif hasattr(robot, "observe"):
            obs = robot.observe()
        else:
            raise AttributeError("robot must provide get_observation() or observe()")
        missing = sorted(key for key in robot.action_features if key.endswith(".pos") and key not in obs)
        if missing:
            raise KeyError(f"ready observation is missing keys: {missing}")
        return {key: float(obs[key]) for key in robot.action_features if key.endswith(".pos")}

    @staticmethod
    def _target_for_current_keys(current: dict[str, float], waypoint: dict[str, Any]) -> dict[str, float]:
        raw_action = waypoint.get("action")
        if not isinstance(raw_action, dict):
            raise ValueError("ready waypoint action must be an object")
        target = {key: float(value) for key, value in raw_action.items() if key.endswith(".pos")}
        missing = sorted(set(current) - set(target))
        if missing:
            raise KeyError(f"ready waypoint is missing keys: {missing}")
        return {key: target[key] for key in current}
