from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


EXPECTED_FOLLOWER_ACTION_KEYS = tuple(
    f"{side}_{joint}.pos"
    for side in ("right", "left")
    for joint in (
        "joint_1",
        "joint_2",
        "joint_3",
        "joint_4",
        "joint_5",
        "joint_6",
        "joint_7",
        "gripper",
    )
)


def _finite_number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _limit_pair(value: Any, name: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} must contain [minimum, maximum]")
    minimum = _finite_number(value[0], f"{name}[0]")
    maximum = _finite_number(value[1], f"{name}[1]")
    if minimum >= maximum:
        raise ValueError(f"{name} minimum must be less than maximum")
    return minimum, maximum


@dataclass(frozen=True)
class JointSafetyLimits:
    hard_limit: tuple[float, float]
    soft_limit: tuple[float, float]
    deadband: float
    max_step: float
    max_velocity: float
    tracking_error_warning: float
    tracking_error_contamination: float
    tracking_error_freeze: float


@dataclass(frozen=True)
class SafetySettings:
    safety_config_version: str
    safety_config_verified: bool
    verified_by: str | None
    verified_at: str | None
    verification_basis: str | None
    action_keys: tuple[str, ...]
    joints: Mapping[str, JointSafetyLimits]
    driver_mismatch_atol: float
    mismatch_contamination_frames: int
    tracking_error_persistence_frames: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_keys", tuple(self.action_keys))
        object.__setattr__(self, "joints", MappingProxyType(dict(self.joints)))

    def to_metadata(self) -> dict[str, Any]:
        metadata = {
            "safety_config_version": self.safety_config_version,
            "safety_config_verified": self.safety_config_verified,
            "safety_action_keys": list(self.action_keys),
            "hard_limits": {key: list(limits.hard_limit) for key, limits in self.joints.items()},
            "soft_limits": {key: list(limits.soft_limit) for key, limits in self.joints.items()},
            "deadband": {key: limits.deadband for key, limits in self.joints.items()},
            "max_step": {key: limits.max_step for key, limits in self.joints.items()},
            "velocity_limit": {key: limits.max_velocity for key, limits in self.joints.items()},
            "tracking_error_warning": {
                key: limits.tracking_error_warning for key, limits in self.joints.items()
            },
            "tracking_error_contamination": {
                key: limits.tracking_error_contamination for key, limits in self.joints.items()
            },
            "tracking_error_freeze": {
                key: limits.tracking_error_freeze for key, limits in self.joints.items()
            },
            "driver_mismatch_atol": self.driver_mismatch_atol,
            "mismatch_contamination_frames": self.mismatch_contamination_frames,
            "tracking_error_persistence_frames": self.tracking_error_persistence_frames,
        }
        if self.safety_config_verified:
            metadata.update(
                {
                    "verified_by": self.verified_by,
                    "verified_at": self.verified_at,
                    "verification_basis": self.verification_basis,
                }
            )
        return metadata


def parse_safety_settings(payload: Mapping[str, Any]) -> SafetySettings:
    version = str(payload.get("safety_config_version", "")).strip()
    if not version:
        raise ValueError("safety_config_version must be non-empty")

    raw_action_keys = payload.get("action_keys", EXPECTED_FOLLOWER_ACTION_KEYS)
    if not isinstance(raw_action_keys, (list, tuple)) or not raw_action_keys:
        raise ValueError("safety action_keys must be a non-empty list")
    action_keys = tuple(str(key) for key in raw_action_keys)
    if len(set(action_keys)) != len(action_keys):
        raise ValueError("safety action_keys must not contain duplicates")
    for key in action_keys:
        if not key.endswith(".pos"):
            raise ValueError(f"safety action key must end with '.pos': {key}")

    raw_joints = payload.get("joints")
    if not isinstance(raw_joints, Mapping):
        raise ValueError("safety joints must be a mapping")
    expected = set(action_keys)
    actual = set(raw_joints)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise ValueError(f"missing safety joints: {missing}")
    if extra:
        raise ValueError(f"unexpected safety joints: {extra}")

    joints: dict[str, JointSafetyLimits] = {}
    for key in action_keys:
        raw = raw_joints[key]
        if not isinstance(raw, Mapping):
            raise ValueError(f"safety joint {key} must be a mapping")
        hard = _limit_pair(raw.get("hard_limit"), f"{key}.hard_limit")
        soft = _limit_pair(raw.get("soft_limit"), f"{key}.soft_limit")
        if soft[0] < hard[0] or soft[1] > hard[1]:
            raise ValueError(f"{key}.soft_limit must be inside hard_limit")
        deadband = _finite_number(raw.get("deadband"), f"{key}.deadband")
        max_step = _finite_number(raw.get("max_step"), f"{key}.max_step")
        max_velocity = _finite_number(raw.get("max_velocity"), f"{key}.max_velocity")
        tracking_warning = _finite_number(raw.get("tracking_error_warning"), f"{key}.tracking_error_warning")
        tracking_contamination = _finite_number(
            raw.get("tracking_error_contamination"),
            f"{key}.tracking_error_contamination",
        )
        tracking_freeze = _finite_number(raw.get("tracking_error_freeze"), f"{key}.tracking_error_freeze")
        if deadband < 0:
            raise ValueError(f"{key}.deadband must be non-negative")
        if max_step <= 0:
            raise ValueError(f"{key}.max_step must be positive")
        if max_velocity <= 0:
            raise ValueError(f"{key}.max_velocity must be positive")
        if not 0 < tracking_warning < tracking_contamination < tracking_freeze:
            raise ValueError(
                f"{key} tracking error thresholds must satisfy 0 < warning < contamination < freeze"
            )
        joints[key] = JointSafetyLimits(
            hard_limit=hard,
            soft_limit=soft,
            deadband=deadband,
            max_step=max_step,
            max_velocity=max_velocity,
            tracking_error_warning=tracking_warning,
            tracking_error_contamination=tracking_contamination,
            tracking_error_freeze=tracking_freeze,
        )

    mismatch_atol = _finite_number(payload.get("driver_mismatch_atol"), "driver_mismatch_atol")
    if mismatch_atol < 0:
        raise ValueError("driver_mismatch_atol must be non-negative")
    raw_contamination_frames = payload.get("mismatch_contamination_frames")
    if isinstance(raw_contamination_frames, bool) or not isinstance(raw_contamination_frames, int):
        raise ValueError("mismatch_contamination_frames must be a positive integer")
    contamination_frames = raw_contamination_frames
    if contamination_frames <= 0:
        raise ValueError("mismatch_contamination_frames must be a positive integer")

    raw_tracking_frames = payload.get("tracking_error_persistence_frames")
    if isinstance(raw_tracking_frames, bool) or not isinstance(raw_tracking_frames, int):
        raise ValueError("tracking_error_persistence_frames must be a positive integer")
    if raw_tracking_frames <= 0:
        raise ValueError("tracking_error_persistence_frames must be a positive integer")

    verified = payload.get("safety_config_verified")
    if not isinstance(verified, bool):
        raise ValueError("safety_config_verified must be a boolean")
    verified_by: str | None = None
    verified_at: str | None = None
    verification_basis: str | None = None
    if verified:
        verified_by = str(payload.get("verified_by", "")).strip()
        verified_at = str(payload.get("verified_at", "")).strip()
        verification_basis = str(payload.get("verification_basis", "")).strip()
        if not verified_by:
            raise ValueError("verified_by must be non-empty when safety_config_verified=true")
        if not verified_at:
            raise ValueError("verified_at must be non-empty when safety_config_verified=true")
        if not verification_basis:
            raise ValueError("verification_basis must be non-empty when safety_config_verified=true")

    return SafetySettings(
        safety_config_version=version,
        safety_config_verified=verified,
        verified_by=verified_by,
        verified_at=verified_at,
        verification_basis=verification_basis,
        action_keys=action_keys,
        joints=joints,
        driver_mismatch_atol=mismatch_atol,
        mismatch_contamination_frames=contamination_frames,
        tracking_error_persistence_frames=raw_tracking_frames,
    )


@dataclass(frozen=True)
class SafetyResult:
    command: Mapping[str, float]
    events: tuple[Mapping[str, Any], ...]
    tracking_errors: Mapping[str, float]
    tracking_levels: Mapping[str, str]
    freeze_requested: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "command", MappingProxyType(dict(self.command)))
        object.__setattr__(self, "tracking_errors", MappingProxyType(dict(self.tracking_errors)))
        object.__setattr__(self, "tracking_levels", MappingProxyType(dict(self.tracking_levels)))
        object.__setattr__(
            self,
            "events",
            tuple(MappingProxyType(dict(event)) for event in self.events),
        )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


class FollowerSafetyProcessor:
    def __init__(self, settings: SafetySettings):
        self.settings = settings

    def process(
        self,
        *,
        follower_target: Mapping[str, Any],
        follower_qpos: Mapping[str, Any],
        previous_effective: Mapping[str, Any] | None,
        dt_s: float,
    ) -> SafetyResult:
        expected_keys = self.settings.action_keys
        expected = set(expected_keys)
        target_keys = set(follower_target)
        if target_keys != expected:
            raise ValueError(
                "follower_target keys must exactly match configured follower action keys: "
                f"missing={sorted(expected - target_keys)}, extra={sorted(target_keys - expected)}"
            )
        missing_qpos = sorted(expected - set(follower_qpos))
        if missing_qpos:
            raise ValueError(f"follower_qpos is missing keys: {missing_qpos}")
        if previous_effective is not None and set(previous_effective) != expected:
            raise ValueError("previous_effective keys must match follower action keys")
        dt = _finite_number(dt_s, "dt_s")
        if dt <= 0:
            raise ValueError("dt_s must be positive")

        candidates: dict[str, float] = {}
        current_qpos: dict[str, float] = {}
        tracking_errors: dict[str, float] = {}
        tracking_levels: dict[str, str] = {}
        events: list[dict[str, Any]] = []
        for key in expected_keys:
            limits = self.settings.joints[key]
            current = _finite_number(follower_qpos[key], f"follower_qpos[{key}]")
            current_qpos[key] = current
            value = _finite_number(follower_target[key], f"follower_target[{key}]")

            if abs(value - current) <= limits.deadband:
                value = self._record_change(events, "deadband", key, value, current)

            value = self._clamp_stage(events, "soft_limit", key, value, limits.soft_limit)
            previous = (
                None
                if previous_effective is None
                else _finite_number(previous_effective[key], f"previous_effective[{key}]")
            )
            step_reference = current if previous is None else previous
            value = self._delta_stage(
                events,
                "max_step",
                key,
                value,
                reference=step_reference,
                maximum_delta=limits.max_step,
            )
            velocity_reference = current if previous is None else previous
            value = self._delta_stage(
                events,
                "velocity_limit",
                key,
                value,
                reference=velocity_reference,
                maximum_delta=limits.max_velocity * dt,
            )
            candidates[key] = value

            tracking_error = 0.0 if previous is None else abs(previous - current)
            tracking_errors[key] = tracking_error
            level = self._tracking_level(tracking_error, limits)
            if level is not None:
                tracking_levels[key] = level
                events.append(
                    {
                        "stage": "tracking_error",
                        "joint": key,
                        "error": tracking_error,
                        "level": level,
                    }
                )

        freeze_requested = "freeze" in tracking_levels.values()
        if freeze_requested:
            for key in expected_keys:
                candidates[key] = self._record_change(
                    events,
                    "tracking_freeze_hold",
                    key,
                    candidates[key],
                    current_qpos[key],
                )

        command: dict[str, float] = {}
        for key in expected_keys:
            command[key] = self._clamp_stage(
                events,
                "hard_limit",
                key,
                candidates[key],
                self.settings.joints[key].hard_limit,
            )

        return SafetyResult(
            command=command,
            events=tuple(events),
            tracking_errors=tracking_errors,
            tracking_levels=tracking_levels,
            freeze_requested=freeze_requested,
        )

    @staticmethod
    def _tracking_level(error: float, limits: JointSafetyLimits) -> str | None:
        if error >= limits.tracking_error_freeze:
            return "freeze"
        if error >= limits.tracking_error_contamination:
            return "contamination"
        if error >= limits.tracking_error_warning:
            return "warning"
        return None

    @staticmethod
    def _record_change(
        events: list[dict[str, Any]],
        stage: str,
        joint: str,
        input_value: float,
        output_value: float,
    ) -> float:
        if output_value != input_value:
            events.append(
                {
                    "stage": stage,
                    "joint": joint,
                    "input": input_value,
                    "output": output_value,
                }
            )
        return output_value

    @classmethod
    def _clamp_stage(
        cls,
        events: list[dict[str, Any]],
        stage: str,
        joint: str,
        value: float,
        limits: tuple[float, float],
    ) -> float:
        return cls._record_change(events, stage, joint, value, _clamp(value, *limits))

    @classmethod
    def _delta_stage(
        cls,
        events: list[dict[str, Any]],
        stage: str,
        joint: str,
        value: float,
        *,
        reference: float,
        maximum_delta: float,
    ) -> float:
        output = _clamp(value, reference - maximum_delta, reference + maximum_delta)
        return cls._record_change(events, stage, joint, value, output)
