#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from workbench.episode_manifest import EpisodeManifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-dir", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    manifest = EpisodeManifest(Path(args.session_dir).expanduser())
    output = manifest.export_accepted(Path(args.output).expanduser() if args.output else None)
    print(output)


if __name__ == "__main__":
    main()
