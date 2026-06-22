from server import schema
from server.notesio import read_note, write_note, dumps_note


def test_write_then_read(tmp_path):
    e = schema.new_entry(title="Therme Vals")
    e.tags = ["stone"]
    e.images = [schema.EntryImage(path="./v.png", alt="layered stone bath", altSource="ai", primary=True)]
    e.notes = "Quarried gneiss, compressed thresholds."
    p = tmp_path / "v.md"
    write_note(e, p)
    back = read_note(p)
    assert back is not None
    assert back.id == e.id
    assert back.title == "Therme Vals"
    assert back.images[0].alt == "layered stone bath"
    assert back.notes.strip() == "Quarried gneiss, compressed thresholds."


def test_long_alt_is_not_wrapped(tmp_path):
    long_alt = "concrete " * 60
    e = schema.new_entry(title="L")
    e.images = [schema.EntryImage(path="./l.png", alt=long_alt.strip(), primary=True)]
    text = dumps_note(e)
    # The alt value should live on a single line (no YAML folding mid-value).
    alt_lines = [ln for ln in text.splitlines() if ln.strip().startswith("alt:")]
    assert len(alt_lines) == 1


def test_non_entry_returns_none(tmp_path):
    p = tmp_path / "plain.md"
    p.write_text("---\ntitle: no id here\n---\nbody\n", encoding="utf-8")
    assert read_note(p) is None
