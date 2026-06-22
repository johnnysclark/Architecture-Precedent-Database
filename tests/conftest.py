import pytest
from PIL import Image


@pytest.fixture
def make_png():
    """Factory: write a small PNG and return its path."""
    def _make(path, size=(64, 48), color=(100, 110, 120)):
        Image.new("RGB", size, color).save(str(path))
        return path
    return _make
