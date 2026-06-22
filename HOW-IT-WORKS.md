# How the Precedent Database Works

This explains what the system *is*, where it keeps things, and what actually
happens when you use it. The [README](README.md) is the quick start and feature
list; this is the mental model underneath it.

The whole design follows one rule: **your files on disk are the truth, and the
app only ever adds to them.** Everything below is a consequence of that rule.

---

## 1. The big idea

This is **a lens over a folder of your files**, not a place you put files *into*.

You point the app at a folder (your "archive"). It reads what's there, and for
each image you want to track it writes a small **markdown note next to that
image**. The note holds the title, tags, alt text, sources, and links to other
entries. Your original images are never moved, renamed, or altered.

Because the notes are plain markdown and live beside your files:

- There is **no database to export from** — the folder *is* the data. Copy it,
  zip it, put it in iCloud/Dropbox/git; it's all there.
- You can open the **same folder in Obsidian** for graph/links/search and edit
  the very same notes. This app and Obsidian are just two windows onto one pile
  of files.
- If you stop using the app entirely, you're left with images and readable text
  notes — nothing locked up.

---

## 2. Where everything lives

Four distinct places, deliberately kept apart:

```
YOUR ARCHIVE  (the truth — syncable, portable, yours)
└── /Users/you/Pictures/Precedents/
    ├── stair.png                 ← your original image (untouched)
    ├── stair.md                  ← note the app wrote *beside* it
    ├── therme-vals-study/        ← a "project" entry (a folder)
    │   ├── index.md              ← the project's note
    │   ├── floor-plan.png
    │   ├── exterior.png
    │   └── floor-plan.piaf.png   ← a generated derivative (new file)
    └── .precedents/
        └── config.yaml           ← portable settings (your editable type list)

THE INDEX CACHE  (disposable — never in your archive, never synced)
└── ~/Library/Caches/precedent-db/<hash-of-archive-path>/index.sqlite

THE APP CODE  (this repo — the program, not your data)
└── server/  web/  run.sh  ...

YOUR SECRETS  (per-machine, gitignored, never synced)
└── .env      ← ANTHROPIC_API_KEY, optional archive path
```

Why split this way:

- **Index in the OS cache, not the archive.** The index is just a fast lookup
  rebuilt from your notes. Keeping it out of the archive means it never causes
  sync conflicts and never clutters your folder. Delete it anytime — "Rebuild
  index" recreates it from the notes on disk.
- **Settings in `.precedents/config.yaml`** travel *with* the archive (so your
  custom type list moves between machines), but the **API key and archive path
  stay in `.env`** and never sync.

---

## 3. Anatomy of an entry

An **entry** is one markdown note. Its YAML frontmatter is structured data; its
body is your freeform notes. Only four fields are mandatory — everything else is
optional.

```markdown
---
id: 0b9c1e2a-7d4f-4a1b-9c0e-2a3b4c5d6e7f   # mandatory — the durable handle
schemaVersion: 1                            # mandatory
created: '2026-06-22T15:48:00Z'             # mandatory
updated: '2026-06-22T15:48:00Z'             # mandatory — bumped on every save
title: Spiral stair, board-formed concrete  # optional
type: detail                                 # optional (from your type list)
tags: [concrete, stair, top-light]           # optional
sources:                                     # optional
- url: https://example.com/project
  label: ArchDaily
related:                                      # optional — IDs of other entries
- 7a1c…  
images:                                       # usually ≥1
- path: ./stair.png        # relative to THIS note
  alt: Concrete spiral stair coiling around a top-lit circular void…
  altSource: human         # "ai" | "human" | ""  (protects your edits)
  caption: ''
  primary: true            # the thumbnail for lists/gallery
  tactilePrepped: true     # only present once you make a PIAF version
  derivatives:             # only present when generated files exist
  - kind: piaf
    path: ./stair.piaf.png
    created: '2026-06-22T16:00:00Z'
---

Free text notes go here, in markdown. This body is the entry's `notes`.
```

The **smallest valid entry** is just the four mandatory fields plus one image
with empty alt — which is exactly what a single dropped screenshot produces. You
enrich it later, or never; both are fine.

---

## 4. Two on-disk shapes (and why nothing moves)

| You did this | The app writes | Result |
|---|---|---|
| Dropped/added one loose image `stair.png` | `stair.md` **beside it** | Sibling note. Image stays put. |
| Grouped several images as one "project" | A folder with `index.md` + the images | Folder entry. |
| Ran PIAF or Edit on an image | A new file `stair.piaf.png` / `stair.edit.png` beside the source | Derivative, recorded in frontmatter. Original untouched. |

Loose images get a **sibling note** because that requires **moving nothing** —
the note simply appears next to the image. Folder entries are only created when
*you* deliberately group files (e.g. a multi-image project), because grouping is
your intent, not the app reorganizing you. The app never turns your loose
screenshots into folders on its own.

---

## 5. Stable IDs, relations, and the rebuildable index

**Links are by `id`, not by path.** Every note has a uuid. When you relate two
entries, each note stores the *other's* id (the link is **bidirectional** —
both notes are updated). So when you later rename `stair.png` to
`vals-stair.png`, or drag it into a folder, **the links don't break** — they
never pointed at the path in the first place.

**The index turns ids back into locations.** On startup (and on "Rebuild
index") the app scans the archive for every `*.md` that has an `id`, and records
in SQLite: where each note currently lives, its title/type/tags, its images and
alt text, and its relations. That's what powers the gallery, filters, and
full-text search (SQLite **FTS5**, with a plain `LIKE` fallback if your SQLite
lacks FTS5).

The index is **a cache, never the truth.** If it's deleted or stale, rebuilding
re-derives everything from the notes. (When a referenced image goes missing, the
rescan makes a best-effort attempt to re-locate it by remembered filename/size;
full content-hash relocation is a Phase 2 hook.)

```
ids in notes ──scan──▶ index.sqlite ──▶ fast lists / search / "what links here"
     ▲                                          │
     └────────────── rebuild from disk ◀────────┘   (truth flows one way: disk → index)
```

---

## 6. What happens when you…

**…add a loose image** (drag-drop, paste, or "point at a file already in the
archive"). The app saves the bytes into the archive if needed, writes a sibling
`Foo.md` with a fresh id and the image marked `primary`, and indexes it. If an
API key is set, it kicks off alt-text generation **in the background** — the
entry is usable immediately; the alt text fills in shortly after.

**…add a project** (tick "Group these into one project entry"). The app makes a
folder from your title, saves the images inside it, and writes one `index.md`
referencing them all (`./floor-plan.png`, `./exterior.png`, …) with the first
image `primary`. Background alt text runs per image.

**…add from a URL.** The backend fetches the page, reads its Open Graph / oEmbed
metadata, downloads the primary image into the archive, and creates an entry
with the canonical URL saved under `sources`. It refuses to fetch internal/
localhost addresses (SSRF guard). Login-walled sites like Instagram are flagged
as a **manual-screenshot** path rather than pretending to fetch them — and if a
page has no usable image, you still get a text entry.

**…generate or edit alt text.** "Generate alt (AI)" sends the image to the
Anthropic Messages API (`claude-sonnet-4-6`) with a prompt tuned for
architecture (spatial organization, materials, composition; screen-reader-first;
no "an image of"). When you type your own alt text it's stored with
`altSource: human`, and a later regenerate **won't overwrite it without asking**.
"Generate all missing alt text" walks the whole archive and fills only the
images that have none. With no API key, every alt path returns a clear
"no API key" message instead of failing silently.

**…Prep for PIAF.** Server-side Pillow converts the image to grayscale and
thresholds it to bold black-on-white (optionally running edge detection first,
good for plans). It writes `Foo.piaf.png` beside the original, records it as a
derivative, flags the image `tactilePrepped`, and gives you a download link. The
original is never modified.

**…Edit image.** Basic crop / rotate / resize / contrast via Pillow, written as
a new `Foo.edit.png` derivative you can download. Not a full editor by design.

**…add a relation.** Search for another entry, click to link. Both notes get the
other's id, both are re-indexed, and the detail view shows it under "Related"
(and "Linked from" for any one-directional backlinks).

**…rebuild the index.** The app rescans every note and regenerates the SQLite
cache. Use it after editing notes outside the app (e.g. in Obsidian) or moving
files around.

---

## 7. The pieces of the program

```
Browser (web/app.js)
   │  fetch() JSON + multipart
   ▼
FastAPI app (server/main.py)  ── AppState: archive dir + index + settings
   │
   ├─ entries.py   create/update notes, relations, derivatives  ─┐
   ├─ index.py     SQLite/FTS5 cache: list, search, resolve id   │ writes/reads
   ├─ images.py    PIAF prep, edits, path-traversal guard        │ the archive
   ├─ alttext.py   pluggable async Anthropic call (+ suggestions)│ on disk
   ├─ fetchurl.py  Open Graph/oEmbed intake, SSRF guard          │
   └─ notesio.py   atomic markdown read/write  ◀─────────────────┘
        │
        └─ schema.py   the Entry model + frontmatter (de)serialization
           config.py   secrets, archive-dir resolution, .precedents/config.yaml
```

| File | Responsibility |
|---|---|
| `server/main.py` | FastAPI routes, static UI serving, safe image serving, background alt-text task |
| `server/schema.py` | `Entry`/`EntryImage`/`Source`/`Derivative` dataclasses; ↔ frontmatter dict |
| `server/notesio.py` | `read_note` / `write_note` (atomic temp-file + replace) |
| `server/index.py` | `Index`: scan → SQLite/FTS5, `list_entries`, search, `resolve_path`, backlinks |
| `server/entries.py` | sibling/folder creation, `update_entry`, relations, alt, derivatives |
| `server/images.py` | `ensure_within` (traversal guard), `prep_for_piaf`, `edit_image` |
| `server/alttext.py` | `generate_alt_text`, `suggest_metadata`, the tuned system prompt |
| `server/config.py` | `Settings` (env), archive-dir + cache-path resolution, archive config |
| `server/fetchurl.py` | `parse_metadata`, `is_safe_url`, `fetch_url`, `create_entry_from_url` |
| `web/index.html` · `app.js` · `styles.css` | the accessible, no-build front end |

**Key principle in the code:** the **detail view reads truth from the note on
disk** (via `notesio.read_note`), while **lists and search read the index**. The
index can never silently disagree with a note, because the note is always
re-read for the thing you're actually looking at.

---

## 8. HTTP API reference

Everything the UI does goes through these. Useful if you ever script against it.

| Method & path | Does |
|---|---|
| `GET /api/status` | archive set? FTS5? API key present? entry count |
| `POST /api/settings/archive` | choose the archive folder, build the index |
| `POST /api/index/rebuild` | rescan archive, rebuild the cache |
| `GET /api/config` | type list, used types, tag counts |
| `POST /api/config/types` | add a new type to the controlled list |
| `GET /api/entries` | list/search/filter (`?q=&type=&tag=&sort=`) |
| `GET /api/entries/{id}` | full entry detail (read from disk) |
| `PATCH /api/entries/{id}` | update title/type/tags/notes/sources |
| `POST /api/entries/{id}/relations` · `DELETE …/relations/{target}` | link / unlink (bidirectional) |
| `POST /api/entries/{id}/images/{i}/alt` | save human alt text |
| `POST /api/entries/{id}/images/{i}/alt/generate` | AI alt (`?confirm=true` to overwrite a human edit) |
| `POST /api/entries/{id}/images/{i}/meta` | set caption / make primary |
| `POST /api/entries/{id}/images/{i}/suggest` | AI title/type/tags suggestions |
| `POST /api/alt/generate-missing` | bulk-fill all empty alt text |
| `POST /api/add/existing` | make an entry for a file already in the archive |
| `POST /api/add/upload` | upload one/many files (`group=true` → project folder) |
| `POST /api/add/url` | create an entry from a web link |
| `POST /api/entries/{id}/images/{i}/piaf` | render a PIAF derivative |
| `POST /api/entries/{id}/images/{i}/edit` | render a crop/rotate/resize/contrast derivative |
| `GET /api/image?path=` · `GET /api/download?path=` | serve / download a file (both guarded to stay inside the archive) |

---

## 9. Accessibility model

Built to read as a reference example for non-visual design:

- Stored `alt` is rendered into the **real DOM `alt` attribute**, and a visible
  "Show/Hide alt text" toggle exposes it as on-screen text too.
- Semantic landmarks and headings; every action is a real `<button>`; labels on
  every control; **focus rings are never removed**.
- **Color is never the only signal** — alt status, primary, and tactile-prepped
  all carry text badges, not just color.
- Drag-and-drop always has a file-picker equivalent; status messages announce
  via an ARIA live region.

---

## 10. Honest limits & how to extend

**Limits, stated plainly.** URL intake depends on a page exposing Open Graph/
oEmbed data — arbitrary pages can return thin results, and Instagram/Threads/
Facebook stay a manual-screenshot path. AI features need `ANTHROPIC_API_KEY`;
without it they're cleanly disabled, not broken. The image editor is intentionally
minimal.

**Extension points (Phase 2 hooks already seamed in).**

- **Vectorized PIAF** — `images.prep_for_piaf(..., mode=)` already branches on
  `mode`; a `"vector"` mode can hand off to a vectorizer (e.g. an external image
  MCP) without touching callers.
- **Dedupe / robust relocation by image hash**, a **fuller editor**, and a
  **custom graph view** (deferred to Obsidian) are the other planned hooks.
- The **alt-text function is pluggable** (`alttext.generate_alt_text`) — swap the
  model or provider in one place.

The schema carries `schemaVersion`, so future format changes can migrate old
notes forward without breaking what's already on disk.
```
