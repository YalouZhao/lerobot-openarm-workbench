#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from workbench.training_export import export_training_package  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--source-repo-id", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--output-repo-id", required=True)
    parser.add_argument("--task-filter", default=None)
    parser.add_argument("--export-name", default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config-file", default=None)
    args = parser.parse_args()

    result = export_training_package(
        source_root=Path(args.source_root),
        source_repo_id=args.source_repo_id,
        output_root=Path(args.output_root),
        output_repo_id=args.output_repo_id,
        task_filter=args.task_filter,
        export_name=args.export_name,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        config_file=Path(args.config_file) if args.config_file else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
