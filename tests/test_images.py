import pytest
from PIL import Image

from server import images


def test_ensure_within_blocks_traversal(tmp_path):
    inside = images.ensure_within(tmp_path, "a/b.png")
    assert str(inside).startswith(str(tmp_path.resolve()))
    with pytest.raises(ValueError):
        images.ensure_within(tmp_path, "../escape.png")


def test_piaf_produces_bilevel(tmp_path, make_png):
    src = make_png(tmp_path / "a.png", size=(80, 60), color=(40, 40, 40))
    out = images.prep_for_piaf(src, threshold=128)
    assert out.exists() and out.name == "a.piaf.png"
    assert Image.open(out).mode == "1"


def test_piaf_edge_mode(tmp_path, make_png):
    src = make_png(tmp_path / "b.png", size=(80, 60))
    out = images.prep_for_piaf(src, edge=True)
    assert out.exists()
    assert Image.open(out).mode == "1"


def test_piaf_vector_mode_is_deferred(tmp_path, make_png):
    src = make_png(tmp_path / "c.png")
    with pytest.raises(NotImplementedError):
        images.prep_for_piaf(src, mode="vector")


def test_edit_rotate_and_resize(tmp_path, make_png):
    src = make_png(tmp_path / "d.png", size=(64, 48))
    rotated = images.edit_image(src, rotate=90)
    assert Image.open(rotated).size == (48, 64)

    resized = images.edit_image(src, resize={"maxDim": 32})
    w, h = Image.open(resized).size
    assert max(w, h) == 32


def test_edit_writes_new_file_not_overwrite(tmp_path, make_png):
    src = make_png(tmp_path / "e.png")
    o1 = images.edit_image(src, rotate=90)
    o2 = images.edit_image(src, rotate=180)
    assert o1 != o2
    assert src.exists()  # original untouched
