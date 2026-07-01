from __future__ import annotations

import pytest

from workbench.openarm_mini_compat import (
    OPENARM_MINI_COMPAT_VERSION,
    OpenArmMiniCompatibilityMapper,
)


def make_mapper(*, native_mapping_detected: bool = False) -> OpenArmMiniCompatibilityMapper:
    return OpenArmMiniCompatibilityMapper(
        apply_mapping=True,
        mapping_version=OPENARM_MINI_COMPAT_VERSION,
        native_mapping_detected=native_mapping_detected,
    )


def test_gripper_master_zero_maps_to_follower_zero() -> None:
    mapped = make_mapper().map_action(
        {"right_gripper.pos": 0.0, "left_gripper.pos": 0.0}
    )

    assert mapped["right_gripper.pos"] == pytest.approx(0.0)
    assert mapped["left_gripper.pos"] == pytest.approx(0.0)


def test_gripper_master_hundred_maps_to_follower_minus_sixty_five() -> None:
    mapped = make_mapper().map_action(
        {"right_gripper.pos": 100.0, "left_gripper.pos": 100.0}
    )

    assert mapped["right_gripper.pos"] == pytest.approx(-65.0)
    assert mapped["left_gripper.pos"] == pytest.approx(-65.0)


def test_joint_six_and_seven_are_remapped_for_both_arms() -> None:
    mapped = make_mapper().map_action(
        {
            "right_joint_6.pos": 6.0,
            "right_joint_7.pos": 7.0,
            "left_joint_6.pos": 16.0,
            "left_joint_7.pos": 17.0,
        }
    )

    assert mapped["right_joint_7.pos"] == pytest.approx(6.0)
    assert mapped["right_joint_6.pos"] == pytest.approx(-7.0)
    assert mapped["left_joint_7.pos"] == pytest.approx(16.0)
    assert mapped["left_joint_6.pos"] == pytest.approx(17.0)


def test_right_joint_seven_direction_correction_precedes_remap() -> None:
    mapped = make_mapper().map_action({"right_joint_7.pos": 12.5})

    assert mapped == {"right_joint_6.pos": pytest.approx(-12.5)}


def test_mapping_refuses_double_application_when_lerobot_maps_natively() -> None:
    with pytest.raises(RuntimeError, match="already applies"):
        make_mapper(native_mapping_detected=True)


def test_unknown_mapping_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="compat_mapping_version"):
        OpenArmMiniCompatibilityMapper(
            apply_mapping=True,
            mapping_version="unknown",
            native_mapping_detected=False,
        )


def test_non_openarm_candidate_mapping_can_pass_through() -> None:
    mapper = OpenArmMiniCompatibilityMapper(
        apply_mapping=False,
        mapping_version="so101_leader_to_xlerobot_follower_v1_candidate",
        native_mapping_detected=False,
    )

    assert mapper.map_action({"left_shoulder_pan.pos": 1.5}) == {"left_shoulder_pan.pos": 1.5}
