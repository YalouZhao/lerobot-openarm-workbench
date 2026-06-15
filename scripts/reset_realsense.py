#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from workbench.config import default_config_path, load_settings
from workbench.device_probe import reset_realsense


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(default_config_path()))
    parser.add_argument("--serial", default=None)
    parser.add_argument("--wait-s", type=float, default=8.0)
    args = parser.parse_args()
    settings = load_settings(args.config)
    serial = args.serial or settings.cameras["realsense"]["serial_number_or_name"]
    result = reset_realsense(serial, wait_s=args.wait_s)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
