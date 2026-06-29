#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from workbench.dataset_manifest import export_v2_accepted_indices


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    output = export_v2_accepted_indices(
        Path(args.dataset_root).expanduser(),
        Path(args.output).expanduser() if args.output else None,
    )
    print(output)


if __name__ == "__main__":
    main()
