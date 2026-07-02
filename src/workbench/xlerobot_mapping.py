from __future__ import annotations

from typing import Any, Mapping


XLEROBOT_SO101_COMPAT_CANDIDATE = "so101_leader_to_xlerobot_follower_v1_candidate"
XLEROBOT_SO101_COMPAT_VERIFIED = "so101_leader_to_xlerobot_follower_v1"


class XLeRobotSO101CompatibilityMapper:
    """SO101 leader to XLeRobot follower compatibility stage.

    The Phase C candidate is intentionally identity: SO101 leader and XLeRobot
    follower currently expose the same normalized LeRobot motor-unit keys.
    Direction/gripper endpoint changes must be added here only after dry-teleop
    joint-by-joint hardware validation.
    """

    def __init__(self, *, mapping_version: str) -> None:
        if mapping_version not in {XLEROBOT_SO101_COMPAT_CANDIDATE, XLEROBOT_SO101_COMPAT_VERIFIED}:
            raise ValueError(f"unsupported XLeRobot SO101 mapping_version: {mapping_version!r}")
        self.mapping_version = mapping_version
        self.apply_mapping = True

    def map_action(self, action: Mapping[str, Any]) -> dict[str, Any]:
        return dict(action)
