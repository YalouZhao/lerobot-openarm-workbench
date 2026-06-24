from __future__ import annotations

import importlib
import subprocess
from pathlib import Path
from typing import Any, Mapping


OPENARM_MINI_COMPAT_VERSION = "openarm_mini_818892a3"
GRIPPER_TELEOP_TO_DEGREES = -0.65
JOINT_REMAP = {"joint_6": "joint_7", "joint_7": "joint_6"}


class OpenArmMiniCompatibilityMapper:
    def __init__(
        self,
        *,
        apply_mapping: bool,
        mapping_version: str,
        native_mapping_detected: bool,
    ) -> None:
        if apply_mapping and mapping_version != OPENARM_MINI_COMPAT_VERSION:
            raise ValueError(
                "compat_mapping_version must be "
                f"{OPENARM_MINI_COMPAT_VERSION!r} when mapping is enabled"
            )
        if apply_mapping and native_mapping_detected:
            raise RuntimeError(
                "installed LeRobot already applies the OpenArm Mini compatibility mapping; "
                "refusing to apply it twice"
            )
        if not apply_mapping and not native_mapping_detected:
            raise RuntimeError(
                "OpenArm Mini compatibility mapping is disabled, but the installed "
                "LeRobot teleoperator does not apply it natively"
            )
        self.apply_mapping = apply_mapping
        self.mapping_version = mapping_version
        self.native_mapping_detected = native_mapping_detected

    def map_action(self, action: Mapping[str, Any]) -> dict[str, Any]:
        if not self.apply_mapping:
            return dict(action)

        mapped: dict[str, Any] = {}
        for key, value in action.items():
            if not key.endswith(".pos"):
                mapped[key] = value
                continue
            motor_key = key.removesuffix(".pos")
            side, separator, motor = motor_key.partition("_")
            if separator == "" or side not in {"left", "right"}:
                mapped[key] = value
                continue

            target_motor = JOINT_REMAP.get(motor, motor)
            mapped_value = float(value)
            if motor == "gripper":
                mapped_value *= GRIPPER_TELEOP_TO_DEGREES
            elif side == "right" and motor == "joint_7":
                # The pre-818892a3 bimanual teleop omitted this source-joint flip.
                mapped_value = -mapped_value
            mapped[f"{side}_{target_motor}.pos"] = mapped_value
        return mapped


def lerobot_applies_compat_mapping_natively() -> bool:
    try:
        module = importlib.import_module("lerobot.teleoperators.openarm_mini.openarm_mini")
    except ImportError:
        return False
    return bool(
        getattr(module, "GRIPPER_TELEOP_TO_DEGREES", None) is not None
        and getattr(module, "JOINT_REMAP", None) is not None
    )


def detect_lerobot_revision() -> str:
    try:
        module = importlib.import_module("lerobot")
        module_file = getattr(module, "__file__", None)
        if module_file is None:
            return "unknown"
        module_path = Path(module_file).resolve()
        for parent in module_path.parents:
            if (parent / ".git").exists():
                return subprocess.check_output(
                    ["git", "-C", str(parent), "rev-parse", "HEAD"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
    except (ImportError, OSError, subprocess.SubprocessError):
        pass
    return "unknown"
