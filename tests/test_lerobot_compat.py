from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "src" / "workbench" / "lerobot_compat.py"


def _load_compat(monkeypatch, *, legacy_exports: bool):
    modules = {
        "lerobot": types.ModuleType("lerobot"),
        "lerobot.datasets": types.ModuleType("lerobot.datasets"),
        "lerobot.datasets.lerobot_dataset": types.ModuleType("lerobot.datasets.lerobot_dataset"),
        "lerobot.datasets.pipeline_features": types.ModuleType("lerobot.datasets.pipeline_features"),
        "lerobot.datasets.utils": types.ModuleType("lerobot.datasets.utils"),
        "lerobot.datasets.video_utils": types.ModuleType("lerobot.datasets.video_utils"),
        "lerobot.utils": types.ModuleType("lerobot.utils"),
        "lerobot.utils.feature_utils": types.ModuleType("lerobot.utils.feature_utils"),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    class Dataset:
        def __init__(self, repo_id, **kwargs):
            self.repo_id = repo_id
            self.kwargs = kwargs

    class LegacyDataset(Dataset):
        @classmethod
        def resume(cls, repo_id, **kwargs):
            result = cls(repo_id, **kwargs)
            result.used_resume = True
            return result

    dataset_type = LegacyDataset if legacy_exports else Dataset
    marker = object()
    if legacy_exports:
        modules["lerobot.datasets"].LeRobotDataset = dataset_type
        modules["lerobot.datasets"].VideoEncodingManager = marker
        modules["lerobot.datasets"].aggregate_pipeline_dataset_features = marker
        modules["lerobot.datasets"].create_initial_features = marker
        modules["lerobot.utils.feature_utils"].build_dataset_frame = marker
        modules["lerobot.utils.feature_utils"].combine_feature_dicts = marker
    else:
        modules["lerobot.datasets.lerobot_dataset"].LeRobotDataset = dataset_type
        modules["lerobot.datasets.video_utils"].VideoEncodingManager = marker
        modules["lerobot.datasets.pipeline_features"].aggregate_pipeline_dataset_features = marker
        modules["lerobot.datasets.pipeline_features"].create_initial_features = marker
        modules["lerobot.datasets.utils"].build_dataset_frame = marker
        modules["lerobot.datasets.utils"].combine_feature_dicts = marker

    spec = importlib.util.spec_from_file_location("workbench_test_lerobot_compat", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, dataset_type


def test_imports_lerobot_04_module_locations(monkeypatch) -> None:
    compat, dataset_type = _load_compat(monkeypatch, legacy_exports=False)

    assert compat.LeRobotDataset is dataset_type


def test_resume_uses_constructor_when_classmethod_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    compat, _ = _load_compat(monkeypatch, legacy_exports=False)

    dataset = compat.resume_lerobot_dataset("local/test", root=tmp_path, vcodec="h264")

    assert dataset.repo_id == "local/test"
    assert dataset.kwargs == {"root": tmp_path, "vcodec": "h264"}


def test_resume_uses_classmethod_when_available(monkeypatch, tmp_path: Path) -> None:
    compat, _ = _load_compat(monkeypatch, legacy_exports=True)

    dataset = compat.resume_lerobot_dataset("local/test", root=tmp_path)

    assert dataset.used_resume is True
