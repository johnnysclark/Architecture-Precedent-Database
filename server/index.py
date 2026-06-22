"""The rebuildable index — a disposable cache, never the source of truth.

Built entirely by scanning the archive for markdown notes that carry an ``id``.
Resolves stable IDs to current file locations, powers list/filter/search, and
tracks relations. Delete the SQLite file anytime; :meth:`Index.rebuild`
regenerates it from disk.

Full-text search uses SQLite FTS5 when available, and degrades to ``LIKE`` over
the same shadow table when it is not.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Optional

from . import config, notesio, schema


def _fts5_available() -> bool:
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        c.close()
        return True
    except sqlite3.OperationalError:
        return False


def _posix(p: Path) -> str:
    return p.as_posix()


class Index:
    def __init__(self, db_path: Path | str, archive_dir: Path | str):
        self.db_path = str(db_path)
        self.archive_dir = Path(archive_dir)
        self.fts = _fts5_available()
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    # -- schema -----------------------------------------------------------
    def _init_db(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS entries(
                id TEXT PRIMARY KEY,
                rel_path TEXT,
                note_dir TEXT,
                title TEXT,
                type TEXT,
                created TEXT,
                updated TEXT,
                mtime REAL,
                size INTEGER,
                primary_image TEXT,
                primary_alt TEXT,
                image_count INTEGER,
                missing_alt INTEGER
            );
            CREATE TABLE IF NOT EXISTS entry_tags(id TEXT, tag TEXT);
            CREATE INDEX IF NOT EXISTS ix_entry_tags_tag ON entry_tags(tag);
            CREATE INDEX IF NOT EXISTS ix_entry_tags_id ON entry_tags(id);
            CREATE TABLE IF NOT EXISTS relations(src TEXT, dst TEXT);
            CREATE INDEX IF NOT EXISTS ix_relations_src ON relations(src);
            CREATE INDEX IF NOT EXISTS ix_relations_dst ON relations(dst);
            """
        )
        if self.fts:
            cur.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS search "
                "USING fts5(id UNINDEXED, title, tags, alt, body)"
            )
        else:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS search("
                "id TEXT, title TEXT, tags TEXT, alt TEXT, body TEXT)"
            )
        self.conn.commit()

    # -- write ------------------------------------------------------------
    def _delete_rows(self, cur: sqlite3.Cursor, entry_id: str) -> None:
        cur.execute("DELETE FROM entries WHERE id=?", (entry_id,))
        cur.execute("DELETE FROM entry_tags WHERE id=?", (entry_id,))
        cur.execute("DELETE FROM relations WHERE src=?", (entry_id,))
        cur.execute("DELETE FROM search WHERE id=?", (entry_id,))

    def _insert(self, cur: sqlite3.Cursor, entry: schema.Entry, path: Path) -> None:
        rel = path.relative_to(self.archive_dir)
        note_dir = rel.parent
        st = path.stat()
        primary = next((i for i in entry.images if i.primary), None)
        if primary is None and entry.images:
            primary = entry.images[0]
        primary_image = primary.path if primary else ""
        primary_alt = primary.alt if primary else ""
        missing_alt = 1 if any(not i.alt.strip() for i in entry.images) else 0

        cur.execute(
            "INSERT INTO entries(id, rel_path, note_dir, title, type, created, "
            "updated, mtime, size, primary_image, primary_alt, image_count, missing_alt) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                entry.id,
                _posix(rel),
                _posix(note_dir),
                entry.title,
                entry.type,
                entry.created,
                entry.updated,
                st.st_mtime,
                st.st_size,
                primary_image,
                primary_alt,
                len(entry.images),
                missing_alt,
            ),
        )
        for tag in entry.tags:
            cur.execute("INSERT INTO entry_tags(id, tag) VALUES(?,?)", (entry.id, tag))
        for dst in entry.related:
            cur.execute("INSERT INTO relations(src, dst) VALUES(?,?)", (entry.id, dst))
        cur.execute(
            "INSERT INTO search(id, title, tags, alt, body) VALUES(?,?,?,?,?)",
            (
                entry.id,
                entry.title,
                " ".join(entry.tags),
                " ".join(i.alt for i in entry.images),
                entry.notes,
            ),
        )

    def upsert_file(self, path: Path | str) -> Optional[str]:
        """Index (or re-index) a single note file. Returns its id, or None."""
        path = Path(path)
        entry = notesio.read_note(path)
        if entry is None:
            return None
        with self._lock:
            cur = self.conn.cursor()
            self._delete_rows(cur, entry.id)
            self._insert(cur, entry, path)
            self.conn.commit()
        return entry.id

    def remove(self, entry_id: str) -> None:
        with self._lock:
            cur = self.conn.cursor()
            self._delete_rows(cur, entry_id)
            self.conn.commit()

    def rebuild(self) -> dict:
        """Scan the whole archive and rebuild the index from scratch."""
        with self._lock:
            cur = self.conn.cursor()
            for t in ("entries", "entry_tags", "relations", "search"):
                cur.execute(f"DELETE FROM {t}")
            count = 0
            for path in self._walk_notes():
                entry = notesio.read_note(path)
                if entry is None:
                    continue
                self._delete_rows(cur, entry.id)  # last-writer-wins on dup ids
                self._insert(cur, entry, path)
                count += 1
            self.conn.commit()
        return {"count": count, "fts5": self.fts}

    def _walk_notes(self) -> Iterable[Path]:
        for p in self.archive_dir.rglob("*.md"):
            if any(part in config.IGNORE_DIRS for part in p.parts):
                continue
            yield p

    # -- read -------------------------------------------------------------
    def resolve_path(self, entry_id: str) -> Optional[Path]:
        row = self.conn.execute(
            "SELECT rel_path FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
        if not row:
            return None
        return self.archive_dir / row["rel_path"]

    def _summary(self, row: sqlite3.Row) -> dict:
        tags = [
            r["tag"]
            for r in self.conn.execute(
                "SELECT tag FROM entry_tags WHERE id=? ORDER BY tag", (row["id"],)
            )
        ]
        note_dir = row["note_dir"] or ""
        primary = row["primary_image"] or ""
        primary_rel = _join_rel(note_dir, primary) if primary else ""
        return {
            "id": row["id"],
            "title": row["title"],
            "type": row["type"],
            "tags": tags,
            "updated": row["updated"],
            "imageCount": row["image_count"],
            "missingAlt": bool(row["missing_alt"]),
            "primaryImage": primary_rel,
            "primaryAlt": row["primary_alt"] or "",
        }

    def list_entries(
        self,
        *,
        type: Optional[str] = None,
        tag: Optional[str] = None,
        q: Optional[str] = None,
        sort: str = "updated",
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        where = []
        params: list = []
        joins = ""
        if q:
            ids = self._search_ids(q)
            if not ids:
                return []
            where.append(f"e.id IN ({','.join('?' for _ in ids)})")
            params.extend(ids)
        if type:
            where.append("e.type = ?")
            params.append(type)
        if tag:
            joins += " JOIN entry_tags t ON t.id = e.id AND t.tag = ?"
            params.insert(0, tag)  # join param comes first
        order = {
            "updated": "e.updated DESC",
            "created": "e.created DESC",
            "title": "e.title COLLATE NOCASE ASC",
        }.get(sort, "e.updated DESC")
        sql = f"SELECT e.* FROM entries e{joins}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {order} LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self.conn.execute(sql, params).fetchall()
        return [self._summary(r) for r in rows]

    def _search_ids(self, q: str) -> list[str]:
        if self.fts:
            try:
                rows = self.conn.execute(
                    "SELECT id FROM search WHERE search MATCH ?", (_fts_query(q),)
                ).fetchall()
                return [r["id"] for r in rows]
            except sqlite3.OperationalError:
                pass  # malformed query -> fall through to LIKE
        like = f"%{q}%"
        rows = self.conn.execute(
            "SELECT id FROM search WHERE title LIKE ? OR tags LIKE ? "
            "OR alt LIKE ? OR body LIKE ?",
            (like, like, like, like),
        ).fetchall()
        return [r["id"] for r in rows]

    def all_types(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT type FROM entries WHERE type<>'' ORDER BY type"
        ).fetchall()
        return [r["type"] for r in rows]

    def all_tags(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT tag, COUNT(*) n FROM entry_tags GROUP BY tag ORDER BY tag"
        ).fetchall()
        return [{"tag": r["tag"], "count": r["n"]} for r in rows]

    def title_of(self, entry_id: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT title FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
        return row["title"] if row else None

    def backlinks(self, entry_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT src FROM relations WHERE dst=?", (entry_id,)
        ).fetchall()
        return [r["src"] for r in rows]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) n FROM entries").fetchone()["n"]


def _join_rel(note_dir: str, image_rel: str) -> str:
    """Combine a note's dir (archive-relative) with an image path relative to the
    note, yielding an archive-relative posix path used to build image URLs."""
    image_rel = image_rel.lstrip("./")
    base = Path(note_dir) if note_dir else Path("")
    return (base / image_rel).as_posix()


def _fts_query(q: str) -> str:
    """Turn free text into a forgiving FTS5 prefix query (term* AND term*)."""
    terms = [t for t in "".join(c if c.isalnum() else " " for c in q).split() if t]
    if not terms:
        return '""'
    return " AND ".join(f"{t}*" for t in terms)
