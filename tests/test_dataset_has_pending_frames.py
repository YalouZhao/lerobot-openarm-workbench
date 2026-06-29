import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from workbench.lerobot_compat import dataset_has_pending_frames


class NativeDataset:
    """Older LeRobot API that still exposes has_pending_frames()."""

    def __init__(self, pending: bool) -> None:
        self._pending = pending

    def has_pending_frames(self) -> bool:
        return self._pending


class BufferDataset:
    """LeRobot 0.4.x: pending state lives in episode_buffer["size"]."""

    def __init__(self, episode_buffer) -> None:
        self.episode_buffer = episode_buffer


def test_prefers_native_method_true():
    assert dataset_has_pending_frames(NativeDataset(True)) is True


def test_prefers_native_method_false():
    assert dataset_has_pending_frames(NativeDataset(False)) is False


def test_buffer_with_frames_is_pending():
    assert dataset_has_pending_frames(BufferDataset({"size": 3})) is True


def test_empty_buffer_is_not_pending():
    assert dataset_has_pending_frames(BufferDataset({"size": 0})) is False


def test_none_buffer_is_not_pending():
    # State right after dataset construction, before the first add_frame/create.
    assert dataset_has_pending_frames(BufferDataset(None)) is False


def test_missing_buffer_attr_is_not_pending():
    assert dataset_has_pending_frames(object()) is False
