from server import schema


def test_new_entry_has_mandatory_fields():
    e = schema.new_entry(title="X")
    assert e.id and e.created and e.updated
    assert e.schemaVersion == schema.SCHEMA_VERSION


def test_roundtrip_minimal():
    e = schema.new_entry(title="Foo")
    e.images = [schema.EntryImage(path="./Foo.png", alt="bold stair", altSource="ai", primary=True)]
    md = schema.entry_to_metadata(e)
    back = schema.entry_from_metadata(md, "")
    assert back.id == e.id
    assert back.images[0].path == "./Foo.png"
    assert back.images[0].altSource == "ai"
    assert back.images[0].primary is True


def test_roundtrip_full():
    e = schema.new_entry(title="Project")
    e.type = "building"
    e.tags = ["stone", "bath"]
    e.sources = [schema.Source(url="https://x.com", label="X")]
    e.related = ["abc", "def"]
    e.images = [
        schema.EntryImage(path="./a.jpg", alt="a", altSource="human", caption="cap", primary=True,
                          tactilePrepped=True,
                          derivatives=[schema.Derivative(kind="piaf", path="./a.piaf.png", created="t")]),
        schema.EntryImage(path="./b.jpg"),
    ]
    e.notes = "# heading\n\nbody"
    back = schema.entry_from_metadata(schema.entry_to_metadata(e), e.notes)
    assert back.type == "building"
    assert back.tags == ["stone", "bath"]
    assert back.sources[0].url == "https://x.com"
    assert back.related == ["abc", "def"]
    assert back.images[0].tactilePrepped is True
    assert back.images[0].derivatives[0].kind == "piaf"
    assert back.notes.startswith("# heading")


def test_is_entry_metadata():
    assert schema.is_entry_metadata({"id": "x"})
    assert not schema.is_entry_metadata({"title": "no id"})


def test_missing_schema_version_defaults():
    e = schema.entry_from_metadata({"id": "x"}, "")
    assert e.schemaVersion == schema.SCHEMA_VERSION
