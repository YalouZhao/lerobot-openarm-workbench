#!/usr/bin/env python3
"""Switch the workbench to a new LeRobot dataset root."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any


VALID_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def expand(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


def validate_name(name: str) -> None:
    if not VALID_NAME.match(name):
        raise ValueError(
            "dataset name must start with a letter or number and may only contain "
            "letters, numbers, dot, underscore, and dash"
        )


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    return json.loads(path.read_text())


def configure_dataset(
    *,
    config_path: Path,
    name: str,
    root_parent: Path,
    root: Path | None,
    repo_id: str | None,
    allow_existing: bool,
    dry_run: bool,
    timestamp: str | None = None,
) -> dict[str, Any]:
    validate_name(name)

    config_path = expand(config_path)
    root_parent = expand(root_parent)
    dataset_root = expand(root) if root is not None else root_parent / name
    dataset_repo_id = repo_id or f"local/{name}"

    if dataset_root.exists() and not allow_existing:
        raise FileExistsError(
            f"dataset root already exists: {dataset_root}\n"
            "Use --allow-existing only when you intentionally want to resume/append."
        )

    config = load_config(config_path)
    old_dataset = dict(config.get("dataset", {}))
    if "dataset" not in config or not isinstance(config["dataset"], dict):
        raise KeyError("config does not contain a dataset object")

    config["dataset"]["repo_id"] = dataset_repo_id
    config["dataset"]["root"] = str(dataset_root)

    result = {
        "config_path": str(config_path),
        "backup_path": None,
        "old_repo_id": old_dataset.get("repo_id"),
        "old_root": old_dataset.get("root"),
        "new_repo_id": dataset_repo_id,
        "new_root": str(dataset_root),
        "dry_run": dry_run,
    }

    if dry_run:
        return result

    root_parent.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or time.strftime("%Y%m%d_%H%M%S")
    backup_path = config_path.with_name(f"{config_path.name}.bak.{stamp}")
    shutil.copy2(config_path, backup_path)
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    result["backup_path"] = str(backup_path)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create/switch a LeRobot workbench collection dataset."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("~/lerobot_workbench/config/workbench_config.json"),
        help="Path to workbench_config.json.",
    )
    parser.add_argument("--name", required=True, help="New dataset name, e.g. openarm_cookie_0610_v1.")
    parser.add_argument(
        "--root-parent",
        type=Path,
        default=Path("/home/robot/data"),
        help="Parent directory where the dataset directory will be placed.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Full dataset root. Overrides --root-parent/--name for the filesystem path.",
    )
    parser.add_argument(
        "--repo-id",
        default=None,
        help="LeRobot repo_id. Defaults to local/<name>.",
    )
    parser.add_argument(
        "--allow-existing",
        action="store_true",
        help="Allow switching to an existing dataset root to resume/append.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned change without writing the config.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = configure_dataset(
        config_path=args.config,
        name=args.name,
        root_parent=args.root_parent,
        root=args.root,
        repo_id=args.repo_id,
        allow_existing=args.allow_existing,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.dry_run:
        print("\nDry run only: config was not changed.")
    else:
        print("\nDataset config updated. Start the workbench with:")
        print("~/lerobot_workbench/scripts/start_with_can.sh")


if __name__ == "__main__":
    main()
