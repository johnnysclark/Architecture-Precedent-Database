"""The write/business layer: create, read, update entry notes and relations.

Every mutation writes the markdown note atomically and re-indexes it. Originals
are never touched; new notes are written *beside* the images they describe
(sibling note) or inside a deliberately-grouped folder (``index.md``).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from . import schema
from .images import ensure_within
from .index import Index
from .notesio import read_note, write_note

IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".heif",
    ".tif", ".tiff", ".bmp", ".avif",
}


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------

def humanize(stem: str) -> str:
    s = re.sub(r"[_]+", " ", stem).strip()
    s = re.sub(r"\s{2,}", " ", s)
    return s or stem


def slugify(text: str, fallback: str = "entry") -> str:
    s = re.sub(r"[^\w\s-]", "", (text or "").lower()).strip()
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or fallback


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not cand.exists():
            return cand
        n += 1


def _sibling_note_path(image_path: Path) -> Path:
    return _unique(image_path.with_name(image_path.stem + ".md"))


def _rel_to_note(target_abs: Path, note_path: Path) -> str:
    rel = Path(os.path.relpath(target_abs, note_path.parent)).as_posix()
    return rel if rel.startswith((".", "/")) else "./" + rel


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load(archive_dir: Path, index: Index, entry_id: str) -> tuple[schema.Entry, Path]:
    note_path = index.resolve_path(entry_id)
    if not note_path or not note_path.exists():
        raise KeyError(entry_id)
    entry = read_note(note_path)
    if entry is None:
        raise KeyError(entry_id)
    return entry, note_path


def _save(index: Index, entry: schema.Entry, note_path: Path) -> schema.Entry:
    entry.updated = schema.now_iso()
    write_note(entry, note_path)
    index.upsert_file(note_path)
    return entry


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------

def create_sibling_entry(
    archive_dir: Path,
    index: Index,
    image_path: Path,
    *,
    title: Optional[str] = None,
    sources: Optional[list[schema.Source]] = None,
    added_from: str = "",
) -> tuple[schema.Entry, Path]:
    """Write a sibling note next to an image already on disk. Image is not moved."""
    image_path = ensure_within(archive_dir, image_path)
    note_path = _sibling_note_path(image_path)
    img = schema.EntryImage(path="./" + image_path.name, primary=True, addedFrom=added_from)
    entry = schema.new_entry(title=title or humanize(image_path.stem))
    entry.images = [img]
    entry.sources = sources or []
    write_note(entry, note_path)
    index.upsert_file(note_path)
    return entry, note_path


def add_existing_image(
    archive_dir: Path, index: Index, image_path: Path | str
) -> tuple[schema.Entry, Path, bool]:
    """Make (or return) an entry for an image that already lives in the archive.

    Returns (entry, note_path, created) where ``created`` is False if a sibling
    note already existed.
    """
    image_path = ensure_within(archive_dir, image_path)
    if image_path.suffix.lower() not in IMAGE_EXTS or not image_path.is_file():
        raise ValueError("not an image file in the archive")
    sibling = image_path.with_name(image_path.stem + ".md")
    if sibling.exists():
        existing = read_note(sibling)
        if existing is not None:
            index.upsert_file(sibling)
            return existing, sibling, False
    entry, note_path = create_sibling_entry(archive_dir, index, image_path)
    return entry, note_path, True


def save_upload_bytes(
    archive_dir: Path, filename: str, data: bytes, subdir: str = ""
) -> Path:
    """Persist uploaded/pasted bytes into the archive (loose, or into ``subdir``)."""
    safe_name = Path(filename or "pasted.png").name
    if not safe_name:
        safe_name = "pasted.png"
    target_dir = ensure_within(archive_dir, Path(subdir)) if subdir else Path(archive_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique(target_dir / safe_name)
    dest = ensure_within(archive_dir, dest)
    dest.write_bytes(data)
    return dest


def create_folder_entry(
    archive_dir: Path,
    index: Index,
    folder: Path,
    image_names: list[str],
    *,
    title: str,
) -> tuple[schema.Entry, Path]:
    """Create a folder-per-entry note (``index.md``) referencing images inside it."""
    folder = ensure_within(archive_dir, folder)
    note_path = folder / "index.md"
    entry = schema.new_entry(title=title or humanize(folder.name))
    entry.images = [
        schema.EntryImage(path="./" + n, primary=(i == 0))
        for i, n in enumerate(image_names)
    ]
    write_note(entry, note_path)
    index.upsert_file(note_path)
    return entry, note_path


# ---------------------------------------------------------------------------
# Mutation
# ---------------------------------------------------------------------------

_ALLOWED_PATCH = {"title", "type", "tags", "notes", "sources"}


def update_entry(archive_dir: Path, index: Index, entry_id: str, patch: dict) -> schema.Entry:
    entry, note_path = load(archive_dir, index, entry_id)
    if "title" in patch:
        entry.title = str(patch["title"] or "")
    if "type" in patch:
        entry.type = str(patch["type"] or "")
    if "tags" in patch:
        entry.tags = [str(t).strip() for t in (patch["tags"] or []) if str(t).strip()]
    if "notes" in patch:
        entry.notes = str(patch["notes"] or "")
    if "sources" in patch:
        entry.sources = [
            schema.Source(url=str(s.get("url", "")).strip(), label=str(s.get("label", "")).strip())
            for s in (patch["sources"] or [])
            if str(s.get("url", "")).strip()
        ]
    return _save(index, entry, note_path)


def set_image_alt(
    archive_dir: Path,
    index: Index,
    entry_id: str,
    image_index: int,
    alt: str,
    source: str,
) -> schema.Entry:
    entry, note_path = load(archive_dir, index, entry_id)
    img = entry.images[image_index]
    img.alt = alt or ""
    img.altSource = source
    return _save(index, entry, note_path)


def update_image(
    archive_dir: Path,
    index: Index,
    entry_id: str,
    image_index: int,
    *,
    caption: Optional[str] = None,
    primary: Optional[bool] = None,
) -> schema.Entry:
    entry, note_path = load(archive_dir, index, entry_id)
    img = entry.images[image_index]
    if caption is not None:
        img.caption = str(caption)
    if primary:
        for i, other in enumerate(entry.images):
            other.primary = i == image_index
    return _save(index, entry, note_path)


def add_image_derivative(
    archive_dir: Path,
    index: Index,
    entry_id: str,
    image_index: int,
    kind: str,
    out_abs: Path,
    *,
    set_tactile: bool = False,
) -> tuple[schema.Entry, str]:
    entry, note_path = load(archive_dir, index, entry_id)
    rel = _rel_to_note(Path(out_abs), note_path)
    img = entry.images[image_index]
    img.derivatives.append(
        schema.Derivative(kind=kind, path=rel, created=schema.now_iso())
    )
    if set_tactile:
        img.tactilePrepped = True
    _save(index, entry, note_path)
    return entry, rel


# ---------------------------------------------------------------------------
# Relations (bidirectional)
# ---------------------------------------------------------------------------

def add_relation(archive_dir: Path, index: Index, a: str, b: str) -> None:
    if a == b:
        raise ValueError("cannot relate an entry to itself")
    ea, pa = load(archive_dir, index, a)
    eb, pb = load(archive_dir, index, b)
    changed = False
    if b not in ea.related:
        ea.related.append(b)
        _save(index, ea, pa)
        changed = True
    if a not in eb.related:
        eb.related.append(a)
        _save(index, eb, pb)
        changed = True
    if not changed:
        return


def remove_relation(archive_dir: Path, index: Index, a: str, b: str) -> None:
    for x, y in ((a, b), (b, a)):
        try:
            e, p = load(archive_dir, index, x)
        except KeyError:
            continue
        if y in e.related:
            e.related = [r for r in e.related if r != y]
            _save(index, e, p)


# ---------------------------------------------------------------------------
# Path resolution for serving images
# ---------------------------------------------------------------------------

def image_abs(archive_dir: Path, note_path: Path, image_rel: str) -> Path:
    return ensure_within(archive_dir, (Path(note_path).parent / image_rel))
