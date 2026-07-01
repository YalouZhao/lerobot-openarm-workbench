#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from workbench.config import load_settings
from workbench.xlerobot_probe import assert_xlerobot_probe_passes, build_xlerobot_so101_probe


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print non-motion XLeRobot/SO101 driver and schema facts."
    )
    parser.add_argument(
        "--config",
        default="config/workbench_config.xlerobot_so101.json",
        help="Workbench config path.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if static feature/schema checks fail.",
    )
    args = parser.parse_args()

    settings = load_settings(args.config)
    probe = build_xlerobot_so101_probe(settings)
    if args.check:
        assert_xlerobot_probe_passes(probe)
    print(json.dumps(probe, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
