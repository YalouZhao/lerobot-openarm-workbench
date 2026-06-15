#!/usr/bin/env python
from __future__ import annotations

import argparse
import builtins
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from lerobot.robots import make_robot_from_config
from lerobot.robots.bi_openarm_follower.config_bi_openarm_follower import BiOpenArmFollowerConfig
from lerobot.robots.openarm_follower.config_openarm_follower import OpenArmFollowerConfigBase

from workbench.config import default_config_path, load_settings


def press_enter_for_existing_calibration() -> Any:
    class _Context:
        def __enter__(self):
            self.original_input = builtins.input
            builtins.input = lambda prompt="": ""

        def __exit__(self, exc_type, exc, tb):
            builtins.input = self.original_input

    return _Context()


def build_robot(settings):
    robot_cfg = BiOpenArmFollowerConfig(
        id=settings.robot["id"],
        left_arm_config=OpenArmFollowerConfigBase(
            port=settings.robot["left_arm"]["port"],
            side=settings.robot["left_arm"].get("side"),
        ),
        right_arm_config=OpenArmFollowerConfigBase(
            port=settings.robot["right_arm"]["port"],
            side=settings.robot["right_arm"].get("side"),
        ),
        cameras={},
    )
    return make_robot_from_config(robot_cfg)


def action_from_observation(robot, obs: dict[str, Any]) -> dict[str, float]:
    action = {}
    for key in robot.action_features:
        if key not in obs:
            raise KeyError(f"Observation is missing action key: {key}")
        action[key] = float(obs[key])
    return action


def load_pose(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if "action" not in payload or not isinstance(payload["action"], dict):
        raise ValueError(f"{path} does not contain an action object")
    return payload


def save_pose(path: Path, action: dict[str, float], settings) -> None:
    payload = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "robot_id": settings.robot["id"],
        "units": "degrees",
        "action": action,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def load_ready_path(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"units": "degrees", "waypoints": []}
    payload = json.loads(path.read_text())
    if "waypoints" not in payload or not isinstance(payload["waypoints"], list):
        raise ValueError(f"{path} does not contain a waypoints list")
    return payload


def save_ready_path(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def require_positive_duration(duration_s: float) -> float:
    duration_s = float(duration_s)
    if duration_s <= 0:
        raise ValueError("duration_s must be positive")
    return duration_s


def parse_waypoint_specs(raw_specs: str) -> list[tuple[str, float]]:
    specs: list[tuple[str, float]] = []
    for item in raw_specs.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"Invalid waypoint spec: {item}. Use name:duration_s")
        name, duration_s = item.split(":", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"Invalid waypoint spec: {item}. Waypoint name is empty")
        specs.append((name, require_positive_duration(duration_s)))
    if not specs:
        raise ValueError("No waypoint specs provided")
    return specs


def copy_arm_action(action: dict[str, float], direction: str) -> dict[str, float]:
    if direction == "right-to-left":
        source_prefix = "right_"
        target_prefix = "left_"
    elif direction == "left-to-right":
        source_prefix = "left_"
        target_prefix = "right_"
    else:
        raise ValueError(f"Unsupported copy direction: {direction}")

    copied = dict(action)
    copied_count = 0
    for key, value in action.items():
        if not key.startswith(source_prefix):
            continue
        target_key = target_prefix + key[len(source_prefix) :]
        if target_key in copied:
            copied[target_key] = float(value)
            copied_count += 1

    if copied_count == 0:
        raise ValueError(f"No {source_prefix.rstrip('_')} arm keys were found to copy")
    return copied


def parse_mirror_signs(raw_signs: str | None) -> dict[str, float]:
    # OpenArm bimanual mirror defaults derived from the official URDF with a
    # left/right mirror plane at y=0. Joint 4 and gripper stay same sign.
    signs = {
        "joint_1": -1.0,
        "joint_2": -1.0,
        "joint_3": -1.0,
        "joint_4": 1.0,
        "joint_5": -1.0,
        "joint_6": -1.0,
        "joint_7": -1.0,
        "gripper": 1.0,
    }
    if not raw_signs:
        return signs

    for item in raw_signs.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"Invalid mirror sign entry: {item}. Use joint_1=-1,joint_2=1")
        name, value = item.split("=", 1)
        signs[name.strip()] = float(value)
    return signs


def mirror_arm_action(
    action: dict[str, float],
    direction: str,
    signs: dict[str, float] | None = None,
) -> dict[str, float]:
    if direction == "right-to-left":
        source_prefix = "right_"
        target_prefix = "left_"
    elif direction == "left-to-right":
        source_prefix = "left_"
        target_prefix = "right_"
    else:
        raise ValueError(f"Unsupported mirror direction: {direction}")

    signs = signs or parse_mirror_signs(None)
    mirrored = dict(action)
    copied_count = 0
    for key, value in action.items():
        if not key.startswith(source_prefix):
            continue
        target_key = target_prefix + key[len(source_prefix) :]
        if target_key not in mirrored:
            continue
        joint_name = key[len(source_prefix) :].split(".", 1)[0]
        mirrored[target_key] = float(value) * float(signs.get(joint_name, 1.0))
        copied_count += 1

    if copied_count == 0:
        raise ValueError(f"No {source_prefix.rstrip('_')} arm keys were found to mirror")
    return mirrored


def append_waypoint(
    path: Path,
    name: str,
    action: dict[str, float],
    duration_s: float,
    settings,
) -> dict[str, Any]:
    duration_s = require_positive_duration(duration_s)
    payload = load_ready_path(path)
    payload.setdefault("created_at", datetime.now().astimezone().isoformat(timespec="seconds"))
    payload["robot_id"] = settings.robot["id"]
    payload["units"] = "degrees"
    payload["waypoints"].append(
        {
            "name": name,
            "duration_s": float(duration_s),
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "action": action,
        }
    )
    save_ready_path(path, payload)
    return payload


def print_action(title: str, action: dict[str, float]) -> None:
    print(f"\n{title}")
    for key in sorted(action):
        print(f"  {key:24s} {action[key]:8.3f}")


def interpolate_action(start: dict[str, float], target: dict[str, float], alpha: float) -> dict[str, float]:
    return {key: start[key] + (target[key] - start[key]) * alpha for key in start}


def validate_target_keys(current: dict[str, float], target: dict[str, Any]) -> dict[str, float]:
    missing = sorted(set(current) - set(target))
    extra = sorted(set(target) - set(current))
    if missing:
        raise KeyError(f"Ready pose is missing keys: {missing}")
    if extra:
        print(f"Warning: ready pose has unused extra keys: {extra}")
    return {key: float(target[key]) for key in current}


def list_waypoints(path: Path) -> None:
    payload = load_ready_path(path)
    waypoints = payload.get("waypoints", [])
    print(f"Path: {path}")
    if not waypoints:
        print("No waypoints recorded yet.")
        return
    for index, waypoint in enumerate(waypoints, start=1):
        print(f"{index:02d}. {waypoint.get('name', 'unnamed')}  duration_s={waypoint.get('duration_s')}")


def load_targets(current: dict[str, float], pose_path: Path, path_path: Path) -> list[dict[str, Any]]:
    if path_path.exists():
        payload = load_ready_path(path_path)
        waypoints = payload.get("waypoints", [])
        if waypoints:
            targets = []
            for waypoint in waypoints:
                duration_s = require_positive_duration(waypoint.get("duration_s", 4.0))
                targets.append(
                    {
                        "name": str(waypoint.get("name", f"waypoint_{len(targets) + 1}")),
                        "duration_s": duration_s,
                        "action": validate_target_keys(current, waypoint["action"]),
                    }
                )
            return targets

    payload = load_pose(pose_path)
    duration_s = require_positive_duration(payload.get("duration_s", 8.0))
    return [
        {
            "name": "ready",
            "duration_s": duration_s,
            "action": validate_target_keys(current, payload["action"]),
        }
    ]


def send_interpolated_segment(
    robot,
    start: dict[str, float],
    target: dict[str, float],
    duration_s: float,
    fps: float,
) -> None:
    steps = max(1, int(duration_s * fps))
    interval = 1.0 / max(fps, 1e-6)
    for step in range(1, steps + 1):
        alpha = step / steps
        robot.send_action(interpolate_action(start, target, alpha))
        time.sleep(interval)


def connect_robot(settings):
    robot = build_robot(settings)
    with press_enter_for_existing_calibration():
        robot.connect()
    return robot


def disable_robot_torque(robot) -> None:
    for arm_name in ("left_arm", "right_arm"):
        arm = getattr(robot, arm_name, None)
        bus = getattr(arm, "bus", None)
        if bus is not None:
            bus.disable_torque()


def apply_arm_transform(action: dict[str, float], copy_arm: str | None, mirror_arm: str | None, mirror_signs: str | None):
    if copy_arm:
        return copy_arm_action(action, copy_arm)
    if mirror_arm:
        return mirror_arm_action(action, mirror_arm, parse_mirror_signs(mirror_signs))
    return action


def teach_path(robot, path: Path, waypoint_specs: list[tuple[str, float]], args, settings) -> None:
    if path.exists() and not args.append_path:
        path.unlink()
        print(f"Deleted existing path before teaching: {path}")

    print("\nTeach mode connected. Disabling torque so you can move the arms by hand.")
    disable_robot_torque(robot)
    print("Move to each waypoint, keep the arm still, then press ENTER to record.")
    for name, duration_s in waypoint_specs:
        input(f"\nMove robot to waypoint '{name}' and press ENTER to record...")
        action = action_from_observation(robot, robot.get_observation())
        action = apply_arm_transform(action, args.copy_arm, args.mirror_arm, args.mirror_signs)
        payload = append_waypoint(path, name, action, duration_s, settings)
        print_action(f"Captured waypoint: {name}", action)
        print(f"Total waypoints: {len(payload['waypoints'])}")

    print(f"\nSaved taught path to: {path}")
    list_waypoints(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print, capture, or execute a safe OpenArm ready pose/path.",
    )
    parser.add_argument("--config", default=str(default_config_path()))
    parser.add_argument(
        "--pose",
        default=str(Path.home() / "lerobot_workbench" / "config" / "ready_pose.json"),
        help="Path to legacy single ready pose JSON.",
    )
    parser.add_argument(
        "--path",
        default=str(Path.home() / "lerobot_workbench" / "config" / "ready_path.json"),
        help="Path to waypoint ready path JSON.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--print-current", action="store_true", help="Print current joint positions and exit.")
    mode.add_argument("--capture", action="store_true", help="Save current joint positions as ready pose.")
    mode.add_argument("--capture-waypoint", metavar="NAME", help="Append current joint positions as a path waypoint.")
    mode.add_argument(
        "--teach-path",
        action="store_true",
        help="Interactively record multiple waypoints in one connection without commanding motion.",
    )
    mode.add_argument("--list-waypoints", action="store_true", help="List recorded waypoints without connecting.")
    mode.add_argument("--clear-path", action="store_true", help="Delete the waypoint path file without connecting.")
    mode.add_argument("--execute", action="store_true", help="Move slowly to the saved ready pose.")
    parser.add_argument("--duration-s", type=float, default=8.0, help="Move duration for --execute or captured waypoint.")
    parser.add_argument(
        "--waypoints",
        default="lift_clear_table:5,above_workspace:5,ready:4",
        help="For --teach-path, comma-separated waypoint specs like name:duration_s,name:duration_s.",
    )
    parser.add_argument(
        "--append-path",
        action="store_true",
        help="For --teach-path, append to the existing path instead of replacing it.",
    )
    parser.add_argument("--fps", type=float, default=20.0, help="Command rate for --execute.")
    parser.add_argument("--hold-s", type=float, default=1.0, help="Hold target pose before disconnect.")
    parser.add_argument("--dry-run", action="store_true", help="For --execute, print target diff without moving.")
    parser.add_argument("--yes", action="store_true", help="Required for --execute to actually move.")
    parser.add_argument(
        "--copy-arm",
        choices=["right-to-left", "left-to-right"],
        help="For capture modes, copy one arm's recorded pose to the other arm before saving.",
    )
    parser.add_argument(
        "--mirror-arm",
        choices=["right-to-left", "left-to-right"],
        help="For capture modes, mirror one arm's recorded pose to the other arm before saving.",
    )
    parser.add_argument(
        "--mirror-signs",
        help="Optional comma-separated mirror signs, for example: joint_1=-1,joint_2=1,joint_5=-1.",
    )
    args = parser.parse_args()

    settings = load_settings(args.config)
    pose_path = Path(args.pose).expanduser()
    path_path = Path(args.path).expanduser()

    if args.list_waypoints:
        list_waypoints(path_path)
        return

    if args.clear_path:
        if path_path.exists():
            path_path.unlink()
            print(f"Deleted: {path_path}")
        else:
            print(f"Path file does not exist: {path_path}")
        return

    if args.execute and not args.dry_run and not args.yes:
        raise SystemExit("Refusing to move without --yes. Use --dry-run first, then --execute --yes.")
    if args.copy_arm and args.mirror_arm:
        raise SystemExit("Use either --copy-arm or --mirror-arm, not both.")

    if args.teach_path:
        waypoint_specs = parse_waypoint_specs(args.waypoints)
        input(
            "Before teach mode connects, put both arms in the calibrated hanging/rest zero pose, "
            "then press ENTER..."
        )
        robot = connect_robot(settings)
        try:
            teach_path(robot, path_path, waypoint_specs, args, settings)
        finally:
            if robot.is_connected:
                robot.disconnect()
        return

    robot = connect_robot(settings)
    try:
        current = action_from_observation(robot, robot.get_observation())
        if args.capture or args.capture_waypoint:
            current = apply_arm_transform(current, args.copy_arm, args.mirror_arm, args.mirror_signs)

        if args.print_current:
            print_action("Current robot action pose (degrees):", current)
            return

        if args.capture:
            save_pose(pose_path, current, settings)
            print_action("Captured ready pose (degrees):", current)
            print(f"\nSaved to: {pose_path}")
            return

        if args.capture_waypoint:
            payload = append_waypoint(path_path, args.capture_waypoint, current, args.duration_s, settings)
            print_action(f"Captured waypoint: {args.capture_waypoint}", current)
            print(f"\nSaved to: {path_path}")
            print(f"Total waypoints: {len(payload['waypoints'])}")
            return

        targets = load_targets(current, pose_path, path_path)
        print_action("Current pose (degrees):", current)
        previous = current
        for index, waypoint in enumerate(targets, start=1):
            target = waypoint["action"]
            print_action(
                f"Target {index}/{len(targets)}: {waypoint['name']} ({waypoint['duration_s']}s)",
                target,
            )
            diff = {key: target[key] - previous[key] for key in current}
            print_action(f"Delta for segment {index}: {waypoint['name']}", diff)
            previous = target

        if args.dry_run:
            print("\nDry run only. No commands were sent.")
            return

        interval = 1.0 / max(args.fps, 1e-6)
        previous = current
        print(f"\nMoving through {len(targets)} target(s).")
        for index, waypoint in enumerate(targets, start=1):
            target = waypoint["action"]
            duration_s = waypoint["duration_s"]
            print(f"Segment {index}/{len(targets)}: {waypoint['name']} over {duration_s:.1f}s.")
            send_interpolated_segment(robot, previous, target, duration_s, args.fps)
            previous = target
        if args.hold_s > 0:
            target = targets[-1]["action"]
            end = time.time() + args.hold_s
            while time.time() < end:
                robot.send_action(target)
                time.sleep(interval)
        print("\nReached ready path target.")
    finally:
        if robot.is_connected:
            robot.disconnect()


if __name__ == "__main__":
    main()
