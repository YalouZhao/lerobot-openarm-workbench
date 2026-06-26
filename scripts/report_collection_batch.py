#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from workbench.collection_report import write_collection_report  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a collection batch QA report.")
    parser.add_argument("--root", required=True, help="Collection LeRobot dataset root.")
    parser.add_argument("--repo-id", required=True, help="Expected dataset repo_id.")
    parser.add_argument("--output", required=True, help="Directory for collection_report.json/.md.")
    args = parser.parse_args()

    output_dir = Path(args.output).expanduser()
    report = write_collection_report(root=Path(args.root), repo_id=args.repo_id, output_dir=output_dir)
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(output_dir),
                "episode_count": report["summary"]["episode_count"],
                "exportable_count": report["summary"]["exportable_count"],
                "timing_sidecar_missing_count": report["timing"]["timing_sidecar_missing_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
