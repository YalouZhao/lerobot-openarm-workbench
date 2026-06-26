from __future__ import annotations

import json
import logging
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .controller import WorkbenchController
from .dataset_manifest import DatasetSchemaError
from .web_assets import INDEX_HTML

logger = logging.getLogger(__name__)


def make_handler(controller: WorkbenchController):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LeRobotWorkbench/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.info("%s - %s", self.address_string(), fmt % args)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_bytes(INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path == "/api/status":
                self._send_json(controller.get_status())
                return
            if parsed.path == "/api/dataset/status":
                self._send_json(controller.dataset_status())
                return
            if parsed.path == "/api/export/training-package/status":
                self._send_json(controller.training_export_status())
                return
            if parsed.path.startswith("/stream/"):
                camera = parsed.path.rsplit("/", 1)[-1]
                self._stream_camera(camera)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                body = self._read_json()
                if parsed.path == "/api/episode/start":
                    self._send_json(controller.start_episode(body.get("task")))
                    return
                if parsed.path == "/api/episode/stop":
                    self._send_json(controller.stop_episode())
                    return
                if parsed.path == "/api/episode/label":
                    self._send_json(
                        controller.label_episode(
                            label=str(body.get("label", "")),
                            notes=str(body.get("notes", "")),
                            episode_index=body.get("episode_index"),
                        )
                    )
                    return
                if parsed.path == "/api/episode/discard":
                    self._send_json(controller.discard_episode())
                    return
                if parsed.path == "/api/realsense/reset":
                    self._send_json(controller.reset_realsense())
                    return
                if parsed.path == "/api/ready/move":
                    self._send_json(controller.move_to_ready())
                    return
                if parsed.path == "/api/sync/master":
                    self._send_json(controller.sync_master(arm=str(body.get("arm", "both"))))
                    return
                if parsed.path == "/api/teleop/enable":
                    self._send_json(controller.enable_teleop())
                    return
                if parsed.path == "/api/teleop/disable":
                    self._send_json(controller.disable_teleop())
                    return
                if parsed.path == "/api/dataset/new":
                    self._send_json(controller.new_dataset(body.get("name") or body.get("suffix")))
                    return
                if parsed.path == "/api/dataset/switch":
                    self._send_json(
                        controller.switch_dataset(
                            root=str(body.get("root", "")),
                            repo_id=str(body.get("repo_id", "")),
                            session_root=body.get("session_root"),
                        )
                    )
                    return
                if parsed.path == "/api/export/training-package/dry-run":
                    self._send_json(
                        controller.export_training_dry_run(
                            source_root=str(body.get("source_root", "")),
                            source_repo_id=str(body.get("source_repo_id", "")),
                            output_root=str(body.get("output_root", "")),
                            output_repo_id=str(body.get("output_repo_id", "")),
                            config_file=body.get("config_file"),
                        )
                    )
                    return
                if parsed.path == "/api/export/training-package/start":
                    self._send_json(
                        controller.start_training_export(
                            source_root=str(body.get("source_root", "")),
                            source_repo_id=str(body.get("source_repo_id", "")),
                            output_root=str(body.get("output_root", "")),
                            output_repo_id=str(body.get("output_repo_id", "")),
                            config_file=body.get("config_file"),
                        )
                    )
                    return
                self.send_error(HTTPStatus.NOT_FOUND)
            except DatasetSchemaError as exc:
                logger.exception("dataset lifecycle request failed")
                dataset = controller.dataset_status()
                root_state = str(dataset.get("root_state", "unknown"))
                self._send_json(
                    {
                        "ok": False,
                        "error_code": root_state
                        if root_state in {"legacy_unknown", "semantic_mismatch", "invalid_dataset_root"}
                        else "dataset_create_failed",
                        "error": str(exc),
                        "dataset": dataset,
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
            except FileExistsError:
                logger.exception("dataset create failed")
                self._send_json(
                    {
                        "ok": False,
                        "error_code": "dataset_create_failed",
                        "error": "dataset root already exists but could not be initialized safely",
                        "dataset": controller.dataset_status(),
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("request failed")
                self._send_json(
                    {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                    status=HTTPStatus.BAD_REQUEST,
                )

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("content-length", "0") or "0")
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(data)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _send_bytes(self, data: bytes, content_type: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(data)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _stream_camera(self, camera: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("cache-control", "no-store")
            self.end_headers()
            last: bytes | None = None
            while True:
                frame = controller.latest_jpeg(camera)
                if frame is None:
                    time.sleep(0.1)
                    continue
                if frame is last:
                    time.sleep(0.03)
                    continue
                try:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                    last = frame
                    time.sleep(0.03)
                except (BrokenPipeError, ConnectionResetError):
                    return

    return Handler


def serve(controller: WorkbenchController, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(controller))
    try:
        server.serve_forever()
    finally:
        server.server_close()
