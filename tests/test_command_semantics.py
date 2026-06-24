from __future__ import annotations

import pytest

from workbench.command import CommandFrame, command_mismatches
from workbench.openarm_mini_compat import (
    OPENARM_MINI_COMPAT_VERSION,
    OpenArmMiniCompatibilityMapper,
)


def make_command() -> CommandFrame:
    return CommandFrame.absolute_passthrough(
        master_action_raw={"joint.pos": 100.0},
        master_action_processed={"joint.pos": 10.0},
        effective_command={"joint.pos": 12.0},
    )


def test_v2_training_action_is_effective_command() -> None:
    command = make_command()

    assert command.training_action("follower_effective_command") == {"joint.pos": 12.0}


def test_legacy_training_action_is_processed_master_action() -> None:
    command = make_command()

    assert command.training_action("master_absolute_legacy") == {"joint.pos": 10.0}


def test_unknown_action_semantics_is_rejected() -> None:
    command = make_command()

    with pytest.raises(ValueError, match="unsupported action_semantics"):
        command.training_action("unknown")


def test_attaching_driver_return_preserves_effective_command() -> None:
    command = make_command()

    completed = command.with_send_result({"joint.pos": 11.5})

    assert completed.effective_command == {"joint.pos": 12.0}
    assert completed.send_result == {"joint.pos": 11.5}
    assert command.send_result is None


def test_command_mismatches_report_changed_missing_and_extra_keys() -> None:
    mismatches = command_mismatches(
        {"changed.pos": 1.0, "missing.pos": 2.0},
        {"changed.pos": 1.5, "extra.pos": 3.0},
    )

    assert mismatches == {
        "changed": {"changed.pos": {"expected": 1.0, "actual": 1.5}},
        "missing": ["missing.pos"],
        "extra": ["extra.pos"],
    }


def test_command_stage_mappings_are_immutable() -> None:
    command = make_command()

    with pytest.raises(TypeError):
        command.effective_command["joint.pos"] = 0.0  # type: ignore[index]


def test_effective_command_and_dataset_action_use_follower_space_mapping() -> None:
    master_raw = {"right_gripper.pos": 100.0}
    mapped = OpenArmMiniCompatibilityMapper(
        apply_mapping=True,
        mapping_version=OPENARM_MINI_COMPAT_VERSION,
        native_mapping_detected=False,
    ).map_action(master_raw)
    command = CommandFrame.absolute_passthrough(
        master_action_raw=master_raw,
        master_action_processed=mapped,
        effective_command=mapped,
    )

    assert command.effective_command == {"right_gripper.pos": -65.0}
    assert command.training_action("follower_effective_command") == {
        "right_gripper.pos": -65.0
    }
    assert command.master_action_raw == {"right_gripper.pos": 100.0}
