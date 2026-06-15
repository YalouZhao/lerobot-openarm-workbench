#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from workbench.config import default_config_path, load_settings
from workbench.device_probe import print_json, probe_all


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(default_config_path()))
    args = parser.parse_args()
    settings = load_settings(args.config)
    print_json(probe_all(settings))


if __name__ == "__main__":
    main()
