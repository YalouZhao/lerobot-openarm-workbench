from __future__ import annotations

import json
import sys
import threading
import types
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _install_fake_lerobot_modules() -> None:
    modules = {
        "cv2": types.ModuleType("cv2"),
        "lerobot": types.ModuleType("lerobot"),
        "lerobot.cameras": types.ModuleType("lerobot.cameras"),
        "lerobot.cameras.opencv": types.ModuleType("lerobot.cameras.opencv"),
        "lerobot.cameras.opencv.configuration_opencv": types.ModuleType(
            "lerobot.cameras.opencv.configuration_opencv"
        ),
        "lerobot.cameras.realsense": types.ModuleType("lerobot.cameras.realsense"),
        "lerobot.cameras.realsense.configuration_realsense": types.ModuleType(
            "lerobot.cameras.realsense.configuration_realsense"
        ),
        "lerobot.datasets": types.ModuleType("lerobot.datasets"),
        "lerobot.processor": types.ModuleType("lerobot.processor"),
        "lerobot.robots": types.ModuleType("lerobot.robots"),
        "lerobot.robots.bi_openarm_follower": types.ModuleType("lerobot.robots.bi_openarm_follower"),
        "lerobot.robots.bi_openarm_follower.config_bi_openarm_follower": types.ModuleType(
            "lerobot.robots.bi_openarm_follower.config_bi_openarm_follower"
        ),
        "lerobot.robots.openarm_follower": types.ModuleType("lerobot.robots.openarm_follower"),
        "lerobot.robots.openarm_follower.config_openarm_follower": types.ModuleType(
            "lerobot.robots.openarm_follower.config_openarm_follower"
        ),
        "lerobot.teleoperators": types.ModuleType("lerobot.teleoperators"),
        "lerobot.teleoperators.openarm_mini": types.ModuleType("lerobot.teleoperators.openarm_mini"),
        "lerobot.teleoperators.openarm_mini.config_openarm_mini": types.ModuleType(
            "lerobot.teleoperators.openarm_mini.config_openarm_mini"
        ),
        "lerobot.utils": types.ModuleType("lerobot.utils"),
        "lerobot.utils.constants": types.ModuleType("lerobot.utils.constants"),
        "lerobot.utils.feature_utils": types.ModuleType("lerobot.utils.feature_utils"),
        "lerobot.utils.robot_utils": types.ModuleType("lerobot.utils.robot_utils"),
    }
    for name, module in modules.items():
        sys.modules.setdefault(name, module)
    sys.modules["cv2"].COLOR_RGB2BGR = 0
    sys.modules["cv2"].IMWRITE_JPEG_QUALITY = 1
    sys.modules["cv2"].cvtColor = lambda frame, _: frame
    sys.modules["cv2"].imencode = lambda *args, **kwargs: (False, None)
    sys.modules["lerobot.cameras.opencv.configuration_opencv"].OpenCVCameraConfig = object
    sys.modules["lerobot.cameras.realsense.configuration_realsense"].RealSenseCameraConfig = object
    sys.modules["lerobot.datasets"].LeRobotDataset = object
    sys.modules["lerobot.datasets"].VideoEncodingManager = object
    sys.modules["lerobot.datasets"].aggregate_pipeline_dataset_features = lambda *args, **kwargs: {}
    sys.modules["lerobot.datasets"].create_initial_features = lambda *args, **kwargs: {}
    sys.modules["lerobot.processor"].make_default_processors = lambda: (None, None, None)
    sys.modules["lerobot.robots"].make_robot_from_config = lambda cfg: None
    sys.modules[
        "lerobot.robots.bi_openarm_follower.config_bi_openarm_follower"
    ].BiOpenArmFollowerConfig = object
    sys.modules["lerobot.robots.openarm_follower.config_openarm_follower"].OpenArmFollowerConfigBase = object
    sys.modules["lerobot.teleoperators"].make_teleoperator_from_config = lambda cfg: None
    sys.modules["lerobot.teleoperators.openarm_mini.config_openarm_mini"].OpenArmMiniConfig = object
    sys.modules["lerobot.utils.constants"].ACTION = "action"
    sys.modules["lerobot.utils.constants"].OBS_STR = "observation"
    sys.modules["lerobot.utils.feature_utils"].build_dataset_frame = lambda *args, **kwargs: {}
    sys.modules["lerobot.utils.feature_utils"].combine_feature_dicts = lambda *args, **kwargs: {}
    sys.modules["lerobot.utils.robot_utils"].precise_sleep = lambda _: None


_install_fake_lerobot_modules()

from workbench.dataset_manifest import DatasetSchemaError  # noqa: E402
from workbench.server import make_handler  # noqa: E402


class FakeController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | None]] = []

    def dataset_status(self) -> dict:
        return {
            "root": "/tmp/dataset",
            "repo_id": "local/test",
            "session_root": "/tmp/sessions",
            "root_state": "root_missing",
            "can_create": True,
            "can_append": False,
            "episode_count": 0,
            "reason": "",
            "semantics": {},
        }

    def new_dataset(self, name=None) -> dict:
        self.calls.append(("new", {"name": name}))
        return {"ok": True, "dataset": self.dataset_status() | {"root": "/tmp/new"}}

    def switch_dataset(self, **kwargs) -> dict:
        self.calls.append(("switch", kwargs))
        return {"ok": True, "dataset": self.dataset_status() | {"root": kwargs["root"]}}

    def move_to_ready(self) -> dict:
        self.calls.append(("move_to_ready", None))
        return {"ok": True, "ready": {"ok": True, "max_abs_error": 0.0}}

    def sync_master(self) -> dict:
        self.calls.append(("sync_master", None))
        return {"ok": True, "sync": {"state": "valid", "sample_count": 1}}

    def start_episode(self, task=None) -> dict:
        raise DatasetSchemaError("legacy_unknown dataset root: missing dataset_manifest.json")

    def get_status(self) -> dict:
        return {"ok": True}


def serve(controller: FakeController):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(controller))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def get_json(base: str, path: str) -> dict:
    with urlopen(base + path, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(base: str, path: str, payload: dict) -> dict:
    request = Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def test_dataset_lifecycle_routes_call_controller() -> None:
    controller = FakeController()
    server, base = serve(controller)
    try:
        assert get_json(base, "/api/dataset/status")["root_state"] == "root_missing"
        assert post_json(base, "/api/dataset/new", {"name": "smoke"})["dataset"]["root"] == "/tmp/new"
        switched = post_json(
            base,
            "/api/dataset/switch",
            {"root": "/tmp/other", "repo_id": "local/other", "session_root": "/tmp/other-sessions"},
        )
        assert switched["dataset"]["root"] == "/tmp/other"
        ready = post_json(base, "/api/ready/move", {})
        assert ready["ready"]["ok"] is True
        sync = post_json(base, "/api/sync/master", {})
        assert sync["sync"]["state"] == "valid"
        assert controller.calls == [
            ("new", {"name": "smoke"}),
            (
                "switch",
                {"root": "/tmp/other", "repo_id": "local/other", "session_root": "/tmp/other-sessions"},
            ),
            ("move_to_ready", None),
            ("sync_master", None),
        ]
    finally:
        server.shutdown()
        server.server_close()


def test_dataset_schema_errors_return_structured_dataset_payload() -> None:
    controller = FakeController()
    server, base = serve(controller)
    try:
        request = Request(
            base + "/api/episode/start",
            data=json.dumps({"task": "test"}).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        status_code = None
        try:
            urlopen(request, timeout=2)
        except HTTPError as exc:
            status_code = exc.code
            payload = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("expected HTTPError")

        assert status_code == 400
        assert payload["ok"] is False
        assert payload["error_code"] in {"legacy_unknown", "dataset_create_failed"}
        assert payload["dataset"]["root_state"] == "root_missing"
        assert "Traceback" not in payload["error"]
    finally:
        server.shutdown()
        server.server_close()
