from server import schema
from server.index import Index
from server.notesio import write_note


def _entry(title, type="", tags=None, alt="", related=None):
    e = schema.new_entry(title=title)
    e.type = type
    e.tags = tags or []
    e.related = related or []
    if alt:
        e.images = [schema.EntryImage(path="./x.png", alt=alt, primary=True)]
    return e


def test_rebuild_list_search_filter(tmp_path, make_png):
    archive = tmp_path
    make_png(archive / "x.png")
    a = _entry("Therme Vals", type="building", tags=["stone", "bath"], alt="layered gneiss bath")
    write_note(a, archive / "vals.md")
    b = _entry("Glass Pavilion", type="building", tags=["glass"])
    write_note(b, archive / "glass.md")

    idx = Index(tmp_path / "i.sqlite", archive)
    res = idx.rebuild()
    assert res["count"] == 2

    assert idx.count() == 2
    assert {x["title"] for x in idx.list_entries()} == {"Therme Vals", "Glass Pavilion"}

    # full-text search hits title, tags, and alt
    assert [x["title"] for x in idx.list_entries(q="gneiss")] == ["Therme Vals"]
    assert [x["title"] for x in idx.list_entries(q="glass")] == ["Glass Pavilion"]

    # filter by tag and type
    assert [x["title"] for x in idx.list_entries(tag="stone")] == ["Therme Vals"]
    assert len(idx.list_entries(type="building")) == 2

    # resolve id -> path survives
    assert idx.resolve_path(a.id).name == "vals.md"


def test_missing_alt_flag(tmp_path, make_png):
    archive = tmp_path
    make_png(archive / "x.png")
    e = schema.new_entry(title="No alt")
    e.images = [schema.EntryImage(path="./x.png", primary=True)]
    write_note(e, archive / "n.md")
    idx = Index(tmp_path / "i.sqlite", archive)
    idx.rebuild()
    assert idx.list_entries()[0]["missingAlt"] is True


def test_relations_backlinks(tmp_path):
    archive = tmp_path
    a = _entry("A", related=[])
    b = _entry("B")
    a.related = [b.id]
    write_note(a, archive / "a.md")
    write_note(b, archive / "b.md")
    idx = Index(tmp_path / "i.sqlite", archive)
    idx.rebuild()
    assert idx.backlinks(b.id) == [a.id]
    assert idx.title_of(b.id) == "B"
