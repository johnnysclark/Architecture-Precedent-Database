import hashlib

from server import entries, schema
from server.index import Index
from server.notesio import read_note


def _idx(tmp_path, archive):
    return Index(tmp_path / "i.sqlite", archive)


def test_sibling_entry_is_non_destructive(tmp_path, make_png):
    archive = tmp_path
    img = make_png(archive / "Foo.png")
    before = hashlib.sha256(img.read_bytes()).hexdigest()
    idx = _idx(tmp_path, archive)

    entry, note_path = entries.create_sibling_entry(archive, idx, img)
    # Note sits beside the image; image is untouched and unmoved.
    assert note_path == archive / "Foo.md"
    assert img.exists()
    assert hashlib.sha256(img.read_bytes()).hexdigest() == before
    assert entry.images[0].path == "./Foo.png"
    assert entry.images[0].primary is True
    # And it is a complete, valid, indexed entry.
    assert idx.resolve_path(entry.id) == note_path


def test_add_existing_dedupes(tmp_path, make_png):
    archive = tmp_path
    make_png(archive / "a.png")
    idx = _idx(tmp_path, archive)
    e1, _, created1 = entries.add_existing_image(archive, idx, "a.png")
    e2, _, created2 = entries.add_existing_image(archive, idx, "a.png")
    assert created1 is True and created2 is False
    assert e1.id == e2.id


def test_update_and_relations_bidirectional(tmp_path, make_png):
    archive = tmp_path
    make_png(archive / "a.png")
    make_png(archive / "b.png")
    idx = _idx(tmp_path, archive)
    ea, _ = entries.create_sibling_entry(archive, idx, archive / "a.png")
    eb, _ = entries.create_sibling_entry(archive, idx, archive / "b.png")

    entries.update_entry(archive, idx, ea.id, {"type": "building", "tags": ["stone"], "notes": "hi"})
    reloaded, _ = entries.load(archive, idx, ea.id)
    assert reloaded.type == "building" and reloaded.tags == ["stone"]

    entries.add_relation(archive, idx, ea.id, eb.id)
    ra, _ = entries.load(archive, idx, ea.id)
    rb, _ = entries.load(archive, idx, eb.id)
    assert eb.id in ra.related and ea.id in rb.related

    entries.remove_relation(archive, idx, ea.id, eb.id)
    ra2, _ = entries.load(archive, idx, ea.id)
    rb2, _ = entries.load(archive, idx, eb.id)
    assert eb.id not in ra2.related and ea.id not in rb2.related


def test_alt_source_protection_and_derivative(tmp_path, make_png):
    archive = tmp_path
    make_png(archive / "a.png")
    idx = _idx(tmp_path, archive)
    e, note_path = entries.create_sibling_entry(archive, idx, archive / "a.png")

    entries.set_image_alt(archive, idx, e.id, 0, "human-written alt", schema.ALT_HUMAN)
    r, _ = entries.load(archive, idx, e.id)
    assert r.images[0].altSource == "human"
    assert idx.list_entries()[0]["missingAlt"] is False

    out = archive / "a.piaf.png"
    out.write_bytes(b"\x89PNG\r\n")  # stand-in derivative file
    entries.add_image_derivative(archive, idx, e.id, 0, "piaf", out, set_tactile=True)
    r2 = read_note(note_path)
    assert r2.images[0].tactilePrepped is True
    assert r2.images[0].derivatives[0].kind == "piaf"
    assert r2.images[0].derivatives[0].path == "./a.piaf.png"


def test_folder_entry(tmp_path, make_png):
    archive = tmp_path
    folder = archive / "project"
    folder.mkdir()
    make_png(folder / "one.png")
    make_png(folder / "two.png")
    idx = _idx(tmp_path, archive)
    e, note_path = entries.create_folder_entry(archive, idx, folder, ["one.png", "two.png"], title="Project")
    assert note_path == folder / "index.md"
    assert [i.path for i in e.images] == ["./one.png", "./two.png"]
    assert e.images[0].primary is True and e.images[1].primary is False
