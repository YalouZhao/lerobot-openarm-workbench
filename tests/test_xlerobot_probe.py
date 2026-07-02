from __future__ import annotations

import pytest

pytest.importorskip("lerobot.robots.bi_so_follower")
pytest.importorskip("lerobot.teleoperators.bi_so_leader")

from workbench.config import load_settings
from workbench.xlerobot_probe import (
    assert_xlerobot_probe_passes,
    build_xlerobot_so101_probe,
    inspect_so101_driver_behavior,
)
from workbench.xlerobot_profile import XLEROBOT_SO101_ACTION_NAMES


def test_xlerobot_probe_confirms_static_feature_keys_match_canonical_schema() -> None:
    settings = load_settings("config/workbench_config.xlerobot_so101.json")

    probe = build_xlerobot_so101_probe(settings)

    assert probe["robot_action_features"] == list(XLEROBOT_SO101_ACTION_NAMES)
    assert probe["robot_observation_position_features"] == list(XLEROBOT_SO101_ACTION_NAMES)
    assert probe["teleop_action_features"] == list(XLEROBOT_SO101_ACTION_NAMES)
    assert probe["robot_max_relative_target"] is None
    assert_xlerobot_probe_passes(probe)


def test_xlerobot_probe_documents_sofollower_send_action_behavior() -> None:
    behavior = inspect_so101_driver_behavior()

    assert behavior["send_action_returns_sent_action"] is True
    assert behavior["send_action_uses_max_relative_target"] is True
    assert behavior["send_action_reads_present_position_for_internal_clamp"] is True
    assert behavior["send_action_writes_goal_position"] is True
