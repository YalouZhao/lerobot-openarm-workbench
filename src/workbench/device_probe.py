from __future__ import annotations

import glob
import json
import os
import time
from pathlib import Path
from typing import Any


def path_status(path: str) -> dict[str, Any]:
    return {
        "path": path,
        "exists": os.path.exists(path),
        "realpath": os.path.realpath(path) if os.path.exists(path) else None,
    }


def probe_opencv_camera(cfg: dict[str, Any], frames: int = 10) -> dict[str, Any]:
    import cv2

    path = cfg["index_or_path"]
    result: dict[str, Any] = {
        "type": "opencv",
        "path": path,
        "exists": os.path.exists(path),
        "ok": False,
        "frames": 0,
        "width": None,
        "height": None,
        "fps": None,
        "error": None,
    }
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            result["error"] = "failed_to_open"
            return result
        fourcc = cfg.get("fourcc")
        if fourcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(cfg.get("width", 640)))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(cfg.get("height", 480)))
        cap.set(cv2.CAP_PROP_FPS, int(cfg.get("fps", 30)))
        start = time.perf_counter()
        width = height = None
        read = 0
        for _ in range(frames):
            ok, frame = cap.read()
            if ok and frame is not None:
                read += 1
                height, width = frame.shape[:2]
        elapsed = max(time.perf_counter() - start, 1e-6)
        result.update(
            {
                "ok": read > 0,
                "frames": read,
                "width": width,
                "height": height,
                "fps": round(read / elapsed, 2),
            }
        )
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    finally:
        cap.release()


def probe_realsense_camera(cfg: dict[str, Any], timeout_ms: int = 5000) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "intelrealsense",
        "serial_number_or_name": cfg["serial_number_or_name"],
        "enumerated": False,
        "ok": False,
        "frames": 0,
        "width": None,
        "height": None,
        "fps": None,
        "error": None,
    }
    try:
        import pyrealsense2 as rs

        ctx = rs.context()
        devices = list(ctx.query_devices())
        serials = [dev.get_info(rs.camera_info.serial_number) for dev in devices]
        result["available_serials"] = serials
        serial = str(cfg["serial_number_or_name"])
        if serial not in serials:
            result["error"] = "serial_not_found"
            return result
        result["enumerated"] = True

        pipe = rs.pipeline()
        rs_cfg = rs.config()
        rs_cfg.enable_device(serial)
        rs_cfg.enable_stream(
            rs.stream.color,
            int(cfg.get("width", 640)),
            int(cfg.get("height", 480)),
            rs.format.rgb8,
            int(cfg.get("fps", 30)),
        )
        profile = pipe.start(rs_cfg)
        start = time.perf_counter()
        read = 0
        width = height = None
        try:
            while read < 10 and (time.perf_counter() - start) * 1000 < timeout_ms:
                frames = pipe.wait_for_frames(timeout_ms)
                color = frames.get_color_frame()
                if color:
                    read += 1
                    width = color.get_width()
                    height = color.get_height()
            elapsed = max(time.perf_counter() - start, 1e-6)
            result.update(
                {
                    "ok": read > 0,
                    "frames": read,
                    "width": width,
                    "height": height,
                    "fps": round(read / elapsed, 2),
                }
            )
        finally:
            pipe.stop()
            del profile
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result


def reset_realsense(serial: str, wait_s: float = 8.0) -> dict[str, Any]:
    import pyrealsense2 as rs

    ctx = rs.context()
    for dev in ctx.query_devices():
        dev_serial = dev.get_info(rs.camera_info.serial_number)
        if dev_serial == str(serial):
            dev.hardware_reset()
            time.sleep(wait_s)
            return {"ok": True, "serial": serial, "wait_s": wait_s}
    return {"ok": False, "serial": serial, "error": "serial_not_found"}


def probe_all(settings: Any) -> dict[str, Any]:
    cameras: dict[str, Any] = {}
    for name, cfg in settings.cameras.items():
        if cfg.get("type") == "opencv":
            cameras[name] = probe_opencv_camera(cfg)
        elif cfg.get("type") == "intelrealsense":
            cameras[name] = probe_realsense_camera(cfg)
        else:
            cameras[name] = {"ok": False, "error": f"unsupported camera type {cfg.get('type')}"}

    robot = settings.robot
    teleop = settings.teleop
    report = {
        "robot": {
            "can0": path_status("/sys/class/net/can0"),
            "can1": path_status("/sys/class/net/can1"),
            "left_arm_port": robot["left_arm"]["port"],
            "right_arm_port": robot["right_arm"]["port"],
        },
        "teleop": {
            "port_right": path_status(teleop["port_right"]),
            "port_left": path_status(teleop["port_left"]),
        },
        "cameras": cameras,
        "video_devices": sorted(glob.glob("/dev/video*")),
        "v4l_by_path": sorted(glob.glob("/dev/v4l/by-path/*")),
        "dataset_root": {
            "path": str(settings.dataset.root),
            "parent_exists": settings.dataset.root.parent.exists(),
            "parent_writable": os.access(settings.dataset.root.parent, os.W_OK),
        },
    }
    report["ok"] = (
        report["dataset_root"]["parent_writable"]
        and report["teleop"]["port_right"]["exists"]
        and report["teleop"]["port_left"]["exists"]
        and all(item.get("ok") for item in cameras.values())
    )
    return report


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
