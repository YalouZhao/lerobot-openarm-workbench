from __future__ import annotations

import json
from pathlib import Path

from workbench.config import load_settings
from workbench.controller import WorkbenchController
from workbench.safety import FollowerSafetyProcessor
from workbench.xlerobot_mapping import XLeRobotSO101CompatibilityMapper
from workbench.xlerobot_profile import XLEROBOT_SO101_ACTION_NAMES


CONFIG_PATH = Path(__file__).parents[1] / "config" / "workbench_config.xlerobot_so101.json"


def test_xlerobot_mapping_candidate_is_identity_and_does_not_apply_openarm_endpoint_rules() -> None:
    mapper = XLeRobotSO101CompatibilityMapper(
        mapping_version="so101_leader_to_xlerobot_follower_v1_candidate"
    )
    action = {key: float(index) for index, key in enumerate(XLEROBOT_SO101_ACTION_NAMES)}
    action["debug.extra"] = "kept"

    mapped = mapper.map_action(action)

    assert mapped == action
    assert mapped["left_gripper.pos"] == action["left_gripper.pos"]
    assert mapped["right_wrist_roll.pos"] == action["right_wrist_roll.pos"]


def test_xlerobot_controller_uses_so101_mapper_and_marks_compat_mapping_applied(tmp_path: Path) -> None:
    payload = json.loads(CONFIG_PATH.read_text())
    payload["workspace_root"] = str(tmp_path)
    payload["session_root"] = str(tmp_path / "sessions")
    payload["dataset"]["root"] = str(tmp_path / "dataset")
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload))

    controller = WorkbenchController(load_settings(path), session_id="session-1")

    assert isinstance(controller.compat_mapper, XLeRobotSO101CompatibilityMapper)
    assert controller._compat_mapping_applied() is True
    assert controller.dataset_manifest.compat_mapping_applied is True


def test_xlerobot_safety_candidate_clamps_in_follower_space_without_endpoint_mapping() -> None:
    settings = load_settings(CONFIG_PATH)
    processor = FollowerSafetyProcessor(settings.safety)
    follower_target = {key: 150.0 for key in XLEROBOT_SO101_ACTION_NAMES}
    follower_qpos = {key: 0.0 for key in XLEROBOT_SO101_ACTION_NAMES}

    result = processor.process(
        follower_target=follower_target,
        follower_qpos=follower_qpos,
        previous_effective=None,
        dt_s=1.0 / 30.0,
    )

    for key, value in result.command.items():
        if "gripper" in key:
            assert value == 35.0
        else:
            assert value == 15.0
