import json
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "new_collection_dataset.py"


def load_module():
    spec = importlib.util.spec_from_file_location("new_collection_dataset", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "workspace_root": "/home/robot/lerobot_workbench",
                "session_root": "/home/robot/lerobot_workbench/sessions",
                "dataset": {
                    "repo_id": "local/old_dataset",
                    "root": "/home/robot/data/old_dataset",
                    "fps": 30,
                },
            }
        )
        + "\n"
    )


def test_updates_dataset_config_and_writes_backup(tmp_path):
    module = load_module()
    config = tmp_path / "workbench_config.json"
    write_config(config)

    result = module.configure_dataset(
        config_path=config,
        name="official_0610_v1",
        root_parent=tmp_path / "data",
        root=None,
        repo_id=None,
        allow_existing=False,
        dry_run=False,
        timestamp="20260610_161200",
    )

    updated = json.loads(config.read_text())
    assert updated["dataset"]["repo_id"] == "local/official_0610_v1"
    assert updated["dataset"]["root"] == str(tmp_path / "data" / "official_0610_v1")
    assert result["backup_path"] == str(config.with_name("workbench_config.json.bak.20260610_161200"))
    assert Path(result["backup_path"]).exists()


def test_dry_run_does_not_modify_config_or_write_backup(tmp_path):
    module = load_module()
    config = tmp_path / "workbench_config.json"
    write_config(config)
    before = config.read_text()

    result = module.configure_dataset(
        config_path=config,
        name="official_0610_v1",
        root_parent=tmp_path / "data",
        root=None,
        repo_id=None,
        allow_existing=False,
        dry_run=True,
        timestamp="20260610_161200",
    )

    assert config.read_text() == before
    assert result["backup_path"] is None
    assert not config.with_name("workbench_config.json.bak.20260610_161200").exists()


def test_rejects_existing_dataset_root_without_allow_existing(tmp_path):
    module = load_module()
    config = tmp_path / "workbench_config.json"
    write_config(config)
    existing_root = tmp_path / "data" / "official_0610_v1"
    existing_root.mkdir(parents=True)

    with pytest.raises(FileExistsError):
        module.configure_dataset(
            config_path=config,
            name="official_0610_v1",
            root_parent=tmp_path / "data",
            root=None,
            repo_id=None,
            allow_existing=False,
            dry_run=False,
            timestamp="20260610_161200",
        )


def test_rejects_dataset_names_with_slashes(tmp_path):
    module = load_module()
    config = tmp_path / "workbench_config.json"
    write_config(config)

    with pytest.raises(ValueError):
        module.configure_dataset(
            config_path=config,
            name="bad/name",
            root_parent=tmp_path / "data",
            root=None,
            repo_id=None,
            allow_existing=False,
            dry_run=True,
            timestamp="20260610_161200",
        )
