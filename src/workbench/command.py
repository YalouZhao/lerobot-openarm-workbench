from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Mapping


FOLLOWER_EFFECTIVE_COMMAND = "follower_effective_command"
MASTER_ABSOLUTE_LEGACY = "master_absolute_legacy"


def _frozen_mapping(values: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if values is None:
        return None
    return MappingProxyType(dict(values))


@dataclass(frozen=True)
class CommandFrame:
    master_action_raw: Mapping[str, Any]
    master_action_processed: Mapping[str, Any]
    relative_target: Mapping[str, Any]
    safe_command: Mapping[str, Any]
    effective_command: Mapping[str, Any]
    send_result: Mapping[str, Any] | None = None
    safety_events: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "master_action_raw",
            "master_action_processed",
            "relative_target",
            "safe_command",
            "effective_command",
            "send_result",
        ):
            object.__setattr__(self, field_name, _frozen_mapping(getattr(self, field_name)))
        object.__setattr__(
            self,
            "safety_events",
            tuple(_frozen_mapping(event) for event in self.safety_events),
        )

    @classmethod
    def absolute_passthrough(
        cls,
        *,
        master_action_raw: Mapping[str, Any],
        master_action_processed: Mapping[str, Any],
        effective_command: Mapping[str, Any],
    ) -> CommandFrame:
        return cls(
            master_action_raw=master_action_raw,
            master_action_processed=master_action_processed,
            relative_target=effective_command,
            safe_command=effective_command,
            effective_command=effective_command,
        )

    def with_send_result(self, send_result: Mapping[str, Any]) -> CommandFrame:
        return replace(self, send_result=send_result)

    def training_action(self, action_semantics: str) -> dict[str, Any]:
        if action_semantics == FOLLOWER_EFFECTIVE_COMMAND:
            return dict(self.effective_command)
        if action_semantics == MASTER_ABSOLUTE_LEGACY:
            return dict(self.master_action_processed)
        raise ValueError(f"unsupported action_semantics: {action_semantics}")


def command_mismatches(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    *,
    atol: float = 1e-6,
) -> dict[str, Any]:
    expected_keys = set(expected)
    actual_keys = set(actual)
    changed: dict[str, dict[str, Any]] = {}
    for key in sorted(expected_keys & actual_keys):
        expected_value = expected[key]
        actual_value = actual[key]
        try:
            is_equal = abs(float(expected_value) - float(actual_value)) <= atol
        except (TypeError, ValueError):
            is_equal = expected_value == actual_value
        if not is_equal:
            changed[key] = {"expected": expected_value, "actual": actual_value}
    return {
        "changed": changed,
        "missing": sorted(expected_keys - actual_keys),
        "extra": sorted(actual_keys - expected_keys),
    }
