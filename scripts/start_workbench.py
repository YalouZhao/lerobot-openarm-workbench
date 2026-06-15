#!/usr/bin/env python
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from workbench.config import default_config_path, load_settings
from workbench.controller import WorkbenchController
from workbench.server import serve


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(default_config_path()))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--session-id", default=None)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings(args.config)
    controller = WorkbenchController(settings, session_id=args.session_id)

    def stop(_signum, _frame) -> None:
        controller.shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    controller.start()
    print(f"LeRobot workbench listening on http://{args.host}:{args.port}")
    serve(controller, args.host, args.port)


if __name__ == "__main__":
    main()
