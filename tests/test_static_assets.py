from __future__ import annotations

import sys
import threading
import types
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _install_fake_lerobot_modules() -> None:
    # Mirror of the stub set used by test_server_dataset_api so importing
    # workbench.server does not require the real lerobot/cv2 stack.
    names = [
        "cv2",
        "lerobot",
        "lerobot.cameras",
        "lerobot.cameras.opencv",
        "lerobot.cameras.opencv.configuration_opencv",
        "lerobot.cameras.realsense",
        "lerobot.cameras.realsense.configuration_realsense",
        "lerobot.datasets",
        "lerobot.processor",
        "lerobot.robots",
        "lerobot.robots.bi_openarm_follower",
        "lerobot.robots.bi_openarm_follower.config_bi_openarm_follower",
        "lerobot.robots.openarm_follower",
        "lerobot.robots.openarm_follower.config_openarm_follower",
        "lerobot.teleoperators",
        "lerobot.teleoperators.openarm_mini",
        "lerobot.teleoperators.openarm_mini.config_openarm_mini",
        "lerobot.utils",
        "lerobot.utils.constants",
        "lerobot.utils.feature_utils",
        "lerobot.utils.robot_utils",
    ]
    for name in names:
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["cv2"].COLOR_RGB2BGR = 0
    sys.modules["cv2"].IMWRITE_JPEG_QUALITY = 1
    sys.modules["cv2"].cvtColor = lambda frame, _: frame
    sys.modules["cv2"].imencode = lambda *args, **kwargs: (False, None)
    sys.modules["lerobot.cameras.opencv.configuration_opencv"].OpenCVCameraConfig = object
    sys.modules["lerobot.cameras.realsense.configuration_realsense"].RealSenseCameraConfig = object
    sys.modules["lerobot.datasets"].LeRobotDataset = object
    sys.modules["lerobot.datasets"].VideoEncodingManager = object
    sys.modules["lerobot.datasets"].aggregate_pipeline_dataset_features = lambda *a, **k: {}
    sys.modules["lerobot.datasets"].create_initial_features = lambda *a, **k: {}
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
    sys.modules["lerobot.utils.feature_utils"].build_dataset_frame = lambda *a, **k: {}
    sys.modules["lerobot.utils.feature_utils"].combine_feature_dicts = lambda *a, **k: {}
    sys.modules["lerobot.utils.robot_utils"].precise_sleep = lambda _: None


_install_fake_lerobot_modules()

from workbench.server import make_handler  # noqa: E402


class FakeController:
    def get_status(self) -> dict:
        return {"ok": True}


def _serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FakeController()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _get(base: str, path: str):
    with urlopen(base + path, timeout=2) as response:
        body = response.read().decode("utf-8")
        return response.status, response.headers.get("content-type", ""), body


def test_index_links_external_static_assets() -> None:
    server, base = _serve()
    try:
        status, ctype, body = _get(base, "/")
        assert status == 200
        assert "text/html" in ctype
        # Slimmed index references the split assets and no longer inlines them.
        assert '<link rel="stylesheet" href="/static/app.css">' in body
        assert '<script src="/static/app.js"></script>' in body
        assert "<style" not in body
        # Core control + dataset + export DOM hooks are preserved verbatim.
        for marker in ("id=\"cameraGrid\"", "id=\"start\"", "id=\"switchDataset\"", "id=\"exportStart\""):
            assert marker in body
    finally:
        server.shutdown()


def test_static_css_route() -> None:
    server, base = _serve()
    try:
        status, ctype, body = _get(base, "/static/app.css")
        assert status == 200
        assert "text/css" in ctype
        assert ":root" in body and "--accent" in body
    finally:
        server.shutdown()


def test_static_js_route() -> None:
    server, base = _serve()
    try:
        status, ctype, body = _get(base, "/static/app.js")
        assert status == 200
        assert "javascript" in ctype
        assert "function updateButtons" in body
        assert "/api/episode/start" in body
    finally:
        server.shutdown()
