"""Read and write entry notes as markdown + YAML frontmatter.

Kept separate from both the index and the write/business layer so it has no
circular dependencies: it depends only on :mod:`schema` and the ``frontmatter``
library. Writes are atomic (temp file + ``os.replace``) so a sync client never
observes a half-written note.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

import frontmatter

from . import schema


def read_note(path: os.PathLike | str) -> Optional[schema.Entry]:
    """Parse a note file into an Entry, or return None if it is not an entry
    (no ``id`` in frontmatter) or cannot be parsed."""
    try:
        post = frontmatter.load(str(path))
    except Exception:
        return None
    md = dict(post.metadata or {})
    if not schema.is_entry_metadata(md):
        return None
    return schema.entry_from_metadata(md, post.content or "")


def dumps_note(entry: schema.Entry) -> str:
    """Serialize an Entry to the full markdown text (frontmatter + body)."""
    md = schema.entry_to_metadata(entry)
    post = frontmatter.Post(entry.notes or "", **md)
    # sort_keys=False preserves our field order; width is large so long alt-text
    # lines are never wrapped (wrapping makes diffs and screen-reading worse).
    text = frontmatter.dumps(post, sort_keys=False, allow_unicode=True, width=4096)
    if not text.endswith("\n"):
        text += "\n"
    return text


def write_note(entry: schema.Entry, path: os.PathLike | str) -> Path:
    """Atomically write an Entry to ``path``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = dumps_note(entry)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".md.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path
