"""The entry data model and its (de)serialization to YAML frontmatter.

This module is pure: dataclasses plus dict<->Entry conversion, no file I/O. The
four mandatory fields are id / schemaVersion / created / updated; everything else
is optional and defaults to empty. The markdown body of a note is the entry's
``notes``.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1

# Alt-text provenance. "human" edits are protected from being silently
# overwritten by regeneration.
ALT_AI = "ai"
ALT_HUMAN = "human"
ALT_NONE = ""


def now_iso() -> str:
    """UTC timestamp, second precision, ``...Z`` form (sorts and diffs cleanly)."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class Source:
    url: str
    label: str = ""


@dataclass
class Derivative:
    kind: str  # "piaf" | "edit"
    path: str  # relative to the note
    created: str


@dataclass
class EntryImage:
    path: str  # relative to the note, e.g. "./Foo.png"
    alt: str = ""
    altSource: str = ALT_NONE  # "ai" | "human" | ""
    caption: str = ""
    primary: bool = False
    tactilePrepped: bool = False
    addedFrom: str = ""  # provenance, e.g. a fetched URL
    derivatives: list[Derivative] = field(default_factory=list)


@dataclass
class Entry:
    id: str
    schemaVersion: int
    created: str
    updated: str
    title: str = ""
    type: str = ""
    tags: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    images: list[EntryImage] = field(default_factory=list)
    notes: str = ""  # markdown body


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def new_entry(title: str = "", **kwargs: Any) -> Entry:
    ts = now_iso()
    return Entry(
        id=new_id(),
        schemaVersion=SCHEMA_VERSION,
        created=ts,
        updated=ts,
        title=title,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Entry -> frontmatter metadata dict (ordered, minimal noise)
# ---------------------------------------------------------------------------

def _source_to_dict(s: Source) -> dict:
    d: dict[str, Any] = {"url": s.url}
    if s.label:
        d["label"] = s.label
    return d


def _derivative_to_dict(d: Derivative) -> dict:
    return {"kind": d.kind, "path": d.path, "created": d.created}


def _image_to_dict(i: EntryImage) -> dict:
    d: dict[str, Any] = {
        "path": i.path,
        "alt": i.alt,
        "altSource": i.altSource,
        "caption": i.caption,
        "primary": i.primary,
    }
    # Only emit optional flags when meaningful, to keep minimal entries clean.
    if i.tactilePrepped:
        d["tactilePrepped"] = True
    if i.addedFrom:
        d["addedFrom"] = i.addedFrom
    if i.derivatives:
        d["derivatives"] = [_derivative_to_dict(x) for x in i.derivatives]
    return d


def entry_to_metadata(e: Entry) -> dict:
    """Ordered frontmatter dict. Insertion order is the on-disk field order."""
    return {
        "id": e.id,
        "schemaVersion": e.schemaVersion,
        "created": e.created,
        "updated": e.updated,
        "title": e.title,
        "type": e.type,
        "tags": list(e.tags),
        "sources": [_source_to_dict(s) for s in e.sources],
        "related": list(e.related),
        "images": [_image_to_dict(i) for i in e.images],
    }


# ---------------------------------------------------------------------------
# frontmatter metadata dict -> Entry (tolerant; fills defaults / light migration)
# ---------------------------------------------------------------------------

def _coerce_str(v: Any) -> str:
    return "" if v is None else str(v)


def _source_from(v: Any) -> Source:
    if isinstance(v, dict):
        return Source(url=_coerce_str(v.get("url")), label=_coerce_str(v.get("label")))
    return Source(url=_coerce_str(v))


def _derivative_from(v: Any) -> Derivative:
    v = v or {}
    return Derivative(
        kind=_coerce_str(v.get("kind")),
        path=_coerce_str(v.get("path")),
        created=_coerce_str(v.get("created")),
    )


def _image_from(v: Any) -> EntryImage:
    v = v or {}
    return EntryImage(
        path=_coerce_str(v.get("path")),
        alt=_coerce_str(v.get("alt")),
        altSource=_coerce_str(v.get("altSource")),
        caption=_coerce_str(v.get("caption")),
        primary=bool(v.get("primary", False)),
        tactilePrepped=bool(v.get("tactilePrepped", False)),
        addedFrom=_coerce_str(v.get("addedFrom")),
        derivatives=[_derivative_from(d) for d in (v.get("derivatives") or [])],
    )


def is_entry_metadata(md: dict) -> bool:
    """A markdown file is an entry iff its frontmatter carries an ``id``."""
    return isinstance(md, dict) and bool(md.get("id"))


def entry_from_metadata(md: dict, body: str = "") -> Entry:
    md = md or {}
    try:
        sv = int(md.get("schemaVersion", SCHEMA_VERSION))
    except (TypeError, ValueError):
        sv = SCHEMA_VERSION
    return Entry(
        id=_coerce_str(md.get("id")) or new_id(),
        schemaVersion=sv,
        created=_coerce_str(md.get("created")) or now_iso(),
        updated=_coerce_str(md.get("updated")) or now_iso(),
        title=_coerce_str(md.get("title")),
        type=_coerce_str(md.get("type")),
        tags=[_coerce_str(t) for t in (md.get("tags") or [])],
        sources=[_source_from(s) for s in (md.get("sources") or [])],
        related=[_coerce_str(r) for r in (md.get("related") or [])],
        images=[_image_from(i) for i in (md.get("images") or [])],
        notes=body or "",
    )
