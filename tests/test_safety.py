from __future__ import annotations

from copy import deepcopy

import pytest

from workbench.safety import (
    EXPECTED_FOLLOWER_ACTION_KEYS,
    FollowerSafetyProcessor,
    parse_safety_settings,
)


def safety_payload() -> dict:
    joints = {}
    for key in EXPECTED_FOLLOWER_ACTION_KEYS:
        hard = [-65.0, 0.0] if "gripper" in key else [-100.0, 100.0]
        joints[key] = {
            "hard_limit": hard,
            "soft_limit": hard,
            "deadband": 0.0,
            "max_step": 10.0,
            "max_velocity": 100.0,
            "tracking_error_warning": 5.0,
            "tracking_error_contamination": 10.0,
            "tracking_error_freeze": 20.0,
        }
    return {
        "safety_config_version": "test_safety_v1",
        "safety_config_verified": True,
        "verified_by": "hardware_operator",
        "verified_at": "2026-06-24T16:30:00+08:00",
        "verification_basis": "driver_mismatch=0; max_step_violations=0; no freeze/contamination",
        "joints": joints,
        "driver_mismatch_atol": 1e-4,
        "mismatch_contamination_frames": 3,
        "tracking_error_persistence_frames": 3,
    }


def full_action(value: float = 0.0) -> dict[str, float]:
    return {key: value for key in EXPECTED_FOLLOWER_ACTION_KEYS}


def test_parse_safety_settings_freezes_complete_metadata() -> None:
    settings = parse_safety_settings(safety_payload())

    metadata = settings.to_metadata()
    assert metadata["safety_action_keys"] == list(EXPECTED_FOLLOWER_ACTION_KEYS)
    assert metadata["safety_config_version"] == "test_safety_v1"
    assert metadata["safety_config_verified"] is True
    assert metadata["verified_by"] == "hardware_operator"
    assert metadata["verified_at"] == "2026-06-24T16:30:00+08:00"
    assert "driver_mismatch=0" in metadata["verification_basis"]
    assert metadata["hard_limits"]["left_gripper.pos"] == [-65.0, 0.0]
    assert metadata["max_step"]["right_joint_1.pos"] == 10.0
    assert metadata["velocity_limit"]["right_joint_1.pos"] == 100.0
    assert metadata["tracking_error_warning"]["right_joint_1.pos"] == 5.0
    assert metadata["tracking_error_contamination"]["right_joint_1.pos"] == 10.0
    assert metadata["tracking_error_freeze"]["right_joint_1.pos"] == 20.0
    assert metadata["tracking_error_persistence_frames"] == 3

    with pytest.raises(TypeError):
        settings.joints["left_gripper.pos"] = settings.joints["right_gripper.pos"]  # type: ignore[index]


def test_parse_safety_settings_accepts_so101_action_keys() -> None:
    keys = tuple(
        f"{side}_{joint}.pos"
        for side in ("left", "right")
        for joint in (
            "shoulder_pan",
            "shoulder_lift",
            "elbow_flex",
            "wrist_flex",
            "wrist_roll",
            "gripper",
        )
    )
    payload = safety_payload()
    payload["safety_config_version"] = "xlerobot_so101_safety_v1_candidate"
    payload["safety_config_verified"] = False
    payload.pop("verified_by")
    payload.pop("verified_at")
    payload.pop("verification_basis")
    payload["action_keys"] = list(keys)
    payload["joints"] = {
        key: {
            "hard_limit": [0.0, 100.0] if key.endswith("gripper.pos") else [-100.0, 100.0],
            "soft_limit": [0.0, 100.0] if key.endswith("gripper.pos") else [-100.0, 100.0],
            "deadband": 0.0,
            "max_step": 10.0,
            "max_velocity": 100.0,
            "tracking_error_warning": 5.0,
            "tracking_error_contamination": 10.0,
            "tracking_error_freeze": 20.0,
        }
        for key in keys
    }

    settings = parse_safety_settings(payload)
    processor = FollowerSafetyProcessor(settings)
    result = processor.process(
        follower_target={key: 150.0 for key in keys},
        follower_qpos={key: 0.0 for key in keys},
        previous_effective=None,
        dt_s=1 / 30,
    )

    assert settings.action_keys == keys
    assert tuple(result.command) == keys
    assert result.command["left_gripper.pos"] == 100.0 / 30.0
    assert result.command["left_shoulder_pan.pos"] == 100.0 / 30.0


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p["joints"].pop("left_joint_1.pos"), "missing safety joints"),
        (
            lambda p: p["joints"].__setitem__("extra.pos", p["joints"]["left_joint_1.pos"]),
            "unexpected safety joints",
        ),
        (lambda p: p["joints"]["left_joint_1.pos"].__setitem__("hard_limit", [1.0, 1.0]), "hard_limit"),
        (
            lambda p: p["joints"]["left_joint_1.pos"].__setitem__("soft_limit", [-101.0, 10.0]),
            "inside hard_limit",
        ),
        (lambda p: p["joints"]["left_joint_1.pos"].__setitem__("deadband", -1.0), "deadband"),
        (lambda p: p["joints"]["left_joint_1.pos"].__setitem__("max_step", 0.0), "max_step"),
        (lambda p: p["joints"]["left_joint_1.pos"].__setitem__("max_velocity", float("nan")), "max_velocity"),
        (lambda p: p.__setitem__("safety_config_version", ""), "safety_config_version"),
        (lambda p: p.__setitem__("driver_mismatch_atol", -1.0), "driver_mismatch_atol"),
        (lambda p: p.__setitem__("mismatch_contamination_frames", 0), "mismatch_contamination_frames"),
        (lambda p: p.__setitem__("mismatch_contamination_frames", 1.5), "mismatch_contamination_frames"),
        (lambda p: p.__setitem__("safety_config_verified", "yes"), "safety_config_verified"),
        (lambda p: p.__setitem__("verified_by", ""), "verified_by"),
        (lambda p: p.__setitem__("verified_at", ""), "verified_at"),
        (lambda p: p.__setitem__("verification_basis", ""), "verification_basis"),
        (
            lambda p: p["joints"]["left_joint_1.pos"].__setitem__("tracking_error_contamination", 4.0),
            "tracking error thresholds",
        ),
        (
            lambda p: p.__setitem__("tracking_error_persistence_frames", 0),
            "tracking_error_persistence_frames",
        ),
    ],
)
def test_rejects_invalid_safety_configuration(mutate, message: str) -> None:
    payload = safety_payload()
    mutate(payload)

    with pytest.raises(ValueError, match=message):
        parse_safety_settings(payload)


def test_unverified_safety_configuration_may_omit_verification_provenance() -> None:
    payload = safety_payload()
    payload["safety_config_verified"] = False
    payload.pop("verified_by")
    payload.pop("verified_at")
    payload.pop("verification_basis")

    metadata = parse_safety_settings(payload).to_metadata()

    assert metadata["safety_config_verified"] is False
    assert "verified_by" not in metadata


def test_processor_applies_deadband_soft_step_velocity_hard_in_fixed_order() -> None:
    payload = safety_payload()
    joint = payload["joints"]["left_joint_1.pos"]
    joint.update(
        {
            "hard_limit": [-6.0, 6.0],
            "soft_limit": [-8.0, 8.0],
            "deadband": 0.5,
            "max_step": 4.0,
            "max_velocity": 2.0,
        }
    )
    # The parser normally requires soft inside hard. This targeted ordering case
    # uses a valid nested pair where hard still provides the final defense.
    joint["hard_limit"] = [-8.0, 8.0]
    joint["soft_limit"] = [-6.0, 6.0]
    processor = FollowerSafetyProcessor(parse_safety_settings(payload))
    target = full_action()
    current = full_action()
    previous = full_action()
    target["left_joint_1.pos"] = 20.0

    result = processor.process(
        follower_target=target,
        follower_qpos=current,
        previous_effective=previous,
        dt_s=1.0,
    )

    # soft: 20 -> 6; step: 6 -> 4; velocity: 4 -> 2; hard unchanged.
    assert result.command["left_joint_1.pos"] == 2.0
    assert [event["stage"] for event in result.events if event["joint"] == "left_joint_1.pos"] == [
        "soft_limit",
        "max_step",
        "velocity_limit",
    ]


def test_processor_clamps_driver_hard_limit_before_effective_command() -> None:
    processor = FollowerSafetyProcessor(parse_safety_settings(safety_payload()))
    target = full_action()
    current = full_action()
    target["left_gripper.pos"] = -100.0
    current["left_gripper.pos"] = -60.0

    result = processor.process(
        follower_target=target,
        follower_qpos=current,
        previous_effective=current,
        dt_s=1.0,
    )

    assert result.command["left_gripper.pos"] == -65.0
    assert result.events[-1]["stage"] == "soft_limit"


def test_safety_does_not_repeat_openarm_gripper_mapping() -> None:
    processor = FollowerSafetyProcessor(parse_safety_settings(safety_payload()))
    target = full_action()
    current = full_action()
    target["right_gripper.pos"] = -32.5
    current["right_gripper.pos"] = -32.5

    result = processor.process(
        follower_target=target,
        follower_qpos=current,
        previous_effective=current,
        dt_s=1 / 30,
    )

    assert result.command["right_gripper.pos"] == -32.5


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_processor_rejects_non_finite_follower_values(bad: float) -> None:
    processor = FollowerSafetyProcessor(parse_safety_settings(safety_payload()))
    target = full_action()
    target["left_joint_1.pos"] = bad

    with pytest.raises(ValueError, match="finite"):
        processor.process(
            follower_target=target,
            follower_qpos=full_action(),
            previous_effective=None,
            dt_s=1 / 30,
        )


def test_processor_rejects_incomplete_or_extra_follower_action() -> None:
    processor = FollowerSafetyProcessor(parse_safety_settings(safety_payload()))
    incomplete = full_action()
    incomplete.pop("left_joint_1.pos")

    with pytest.raises(ValueError, match="follower_target keys"):
        processor.process(
            follower_target=incomplete,
            follower_qpos=full_action(),
            previous_effective=None,
            dt_s=1 / 30,
        )

    extra = full_action()
    extra["not_a_joint.pos"] = 0.0
    with pytest.raises(ValueError, match="follower_target keys"):
        processor.process(
            follower_target=extra,
            follower_qpos=full_action(),
            previous_effective=None,
            dt_s=1 / 30,
        )


def test_processor_does_not_mutate_inputs() -> None:
    processor = FollowerSafetyProcessor(parse_safety_settings(safety_payload()))
    target = full_action()
    current = full_action()
    target_before = deepcopy(target)
    current_before = deepcopy(current)

    processor.process(
        follower_target=target,
        follower_qpos=current,
        previous_effective=None,
        dt_s=1 / 30,
    )

    assert target == target_before
    assert current == current_before


def test_max_step_uses_qpos_once_then_previous_effective_despite_qpos_jitter() -> None:
    payload = safety_payload()
    payload["joints"]["right_gripper.pos"].update({"max_step": 4.0, "max_velocity": 1000.0})
    processor = FollowerSafetyProcessor(parse_safety_settings(payload))
    target = full_action()
    target["right_gripper.pos"] = 0.0

    first_qpos = full_action()
    first_qpos["right_gripper.pos"] = -40.0
    first = processor.process(
        follower_target=target,
        follower_qpos=first_qpos,
        previous_effective=None,
        dt_s=1 / 30,
    )

    jittered_qpos = full_action()
    jittered_qpos["right_gripper.pos"] = -42.0
    second = processor.process(
        follower_target=target,
        follower_qpos=jittered_qpos,
        previous_effective=first.command,
        dt_s=1 / 30,
    )

    assert first.command["right_gripper.pos"] == -36.0
    assert second.command["right_gripper.pos"] == -32.0


def test_tracking_warning_and_contamination_do_not_rewrite_command() -> None:
    processor = FollowerSafetyProcessor(parse_safety_settings(safety_payload()))
    target = full_action()
    current = full_action()
    previous = full_action()
    previous["left_joint_1.pos"] = 12.0
    target["left_joint_1.pos"] = 12.0

    result = processor.process(
        follower_target=target,
        follower_qpos=current,
        previous_effective=previous,
        dt_s=1 / 30,
    )

    assert result.command["left_joint_1.pos"] == 12.0
    assert result.tracking_errors["left_joint_1.pos"] == 12.0
    assert result.tracking_levels["left_joint_1.pos"] == "contamination"
    assert result.freeze_requested is False


def test_tracking_freeze_holds_current_qpos_then_applies_hard_limit() -> None:
    payload = safety_payload()
    payload["joints"]["right_joint_4.pos"].update({"hard_limit": [0.0, 135.0], "soft_limit": [0.0, 135.0]})
    processor = FollowerSafetyProcessor(parse_safety_settings(payload))
    target = full_action()
    current = full_action()
    previous = full_action()
    previous["right_joint_4.pos"] = 25.0
    target["right_joint_4.pos"] = 30.0
    current["right_joint_4.pos"] = -1.0

    result = processor.process(
        follower_target=target,
        follower_qpos=current,
        previous_effective=previous,
        dt_s=1 / 30,
    )

    assert result.freeze_requested is True
    assert result.tracking_levels["right_joint_4.pos"] == "freeze"
    assert result.command["right_joint_4.pos"] == 0.0
    assert [event["stage"] for event in result.events][-2:] == [
        "tracking_freeze_hold",
        "hard_limit",
    ]


def test_example_hard_limits_match_openarm_follower_driver_tables() -> None:
    import json
    from pathlib import Path

    payload = json.loads((Path(__file__).parents[1] / "config" / "workbench_config.example.json").read_text())
    actual = {key: value["hard_limit"] for key, value in payload["safety"]["joints"].items()}
    assert actual == {
        "right_joint_1.pos": [-75.0, 75.0],
        "right_joint_2.pos": [-9.0, 90.0],
        "right_joint_3.pos": [-85.0, 85.0],
        "right_joint_4.pos": [0.0, 135.0],
        "right_joint_5.pos": [-85.0, 85.0],
        "right_joint_6.pos": [-40.0, 40.0],
        "right_joint_7.pos": [-80.0, 80.0],
        "right_gripper.pos": [-65.0, 0.0],
        "left_joint_1.pos": [-75.0, 75.0],
        "left_joint_2.pos": [-90.0, 9.0],
        "left_joint_3.pos": [-85.0, 85.0],
        "left_joint_4.pos": [0.0, 135.0],
        "left_joint_5.pos": [-85.0, 85.0],
        "left_joint_6.pos": [-40.0, 40.0],
        "left_joint_7.pos": [-80.0, 80.0],
        "left_gripper.pos": [-65.0, 0.0],
    }
