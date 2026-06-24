from __future__ import annotations

import json
import logging
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .controller import WorkbenchController
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
                self.send_error(HTTPStatus.NOT_FOUND)
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
