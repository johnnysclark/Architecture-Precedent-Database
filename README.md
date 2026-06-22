# Precedent Database

A personal **architectural precedent database** that works as a *lens and
enrichment layer over a folder of your own files* — not a new silo that ingests
and hides them. Point it at a folder of screenshots/images/notes; it reads that
folder, builds a rebuildable index, and writes metadata **alongside** your files.
It never moves, renames, or alters your originals.

A single dropped screenshot is a complete, valid entry. A fully documented
project — multiple images, notes, source links, relations to other entries — is
the same model, scaled up.

## Principles (the architecture is deliberately boring and durable)

- **Filesystem is the truth; the app is additive and non-destructive.** Truth is
  markdown notes (YAML frontmatter) plus your image files on disk. There is no
  proprietary export — *the archive is the export*.
- **Stable IDs, not paths, are the durable link.** Every note carries a uuid
  `id`; relations are lists of IDs. The index resolves IDs to current locations
  and is a disposable cache you can delete and rebuild anytime.
- **Obsidian-friendly.** Because notes are markdown + frontmatter, you can point
  Obsidian at the same folder for graph/links/search. This app is the primary UI
  for intake, alt text, and image actions; Obsidian is optional for browsing.
- **Syncable.** The archive can live in iCloud/Dropbox/git; the app runs
  per-machine and rebuilds its index from disk. No path is hardcoded; the index
  cache lives in the OS cache dir, never in the archive.

## Quick start

Requires Python 3.10+.

```bash
cp .env.example .env          # optional: add ANTHROPIC_API_KEY for AI alt text
./run.sh                      # creates .venv, installs deps, starts the server
# open http://127.0.0.1:8765  → choose your folder on first run
```

Without an API key the app runs fine; AI alt text is simply disabled and clearly
marked until you add a key.

## What it does (v1)

- **Index + browse.** Gallery and list views, filter by type/tag, full-text
  search (SQLite FTS5). Entry detail shows images with a visible alt-text toggle,
  sources, notes, tags, and clickable related entries. Adding a relation updates
  **both** entries.
- **Local add.** Drag-and-drop one or many files, paste from the clipboard, or
  point at a file already in the archive. Each becomes a stub entry immediately;
  enrich later. "Group into one project" creates a folder entry.
- **Internet add.** Paste a URL; the backend builds an entry from Open Graph /
  oEmbed metadata and the primary image, storing the canonical URL as a source.
  *Honest limits:* arbitrary pages are best-effort, and login-walled sites
  (e.g. Instagram) are flagged as a manual-screenshot path, not a reliable fetch.
- **AI alt text** tuned for architectural precedents (spatial organization,
  materials, composition; screen-reader-first; no "an image of"). Editable and
  stored; a human edit is never overwritten on regeneration without confirming.
  Includes a bulk **"generate all missing alt text"** action for migration.
- **Prep for PIAF** (tactile/swell paper): real server-side Pillow processing —
  grayscale → adjustable threshold to bold black/white, with optional edge
  detection. Download the result; the entry image is flagged tactile-prepped.
- **Edit image**: basic crop / rotate / resize / contrast, downloadable. Not a
  full editor by design.

## Data model

One markdown note per entry. Mandatory frontmatter: `id`, `schemaVersion`,
`created`, `updated`. Optional: `title`, `type` (from an editable list in
`.precedents/config.yaml`), `tags`, `sources` (`{url, label}`), `related` (entry
IDs), and `images` (each with `path`, `alt`, `altSource`, `caption`, `primary`,
optional `tactilePrepped` / `derivatives`). The markdown **body is the notes**.

On disk:

- **Loose image → sibling note** (`Foo.png` → `Foo.md`). Zero-move; the common
  case for a pile of screenshots.
- **Project → folder** with `index.md` and its images inside. Used only when you
  deliberately group files.
- **Derivatives** (PIAF/edit output) are written *beside* the source
  (`Foo.piaf.png`), recorded in frontmatter; originals are never overwritten.

## Accessibility

Built as a reference example for non-visual design: semantic landmarks and
headings, every control keyboard-reachable and labeled, always-visible focus
states, stored alt text present in the real DOM, and color never used as the
only signal (badges carry text too).

## Configuration

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Enables AI alt text + suggestions (`claude-sonnet-4-6`). |
| `PRECEDENTS_ARCHIVE_DIR` | Optional: pin the archive folder instead of choosing in the UI. |
| `PRECEDENTS_ALT_MODEL` | Optional: override the vision model. |
| `ANTHROPIC_BASE_URL` | Optional: override the Anthropic endpoint. |
| `PORT` | Optional: server port (default 8765). |

## Deferred (Phase 2 hooks, not built in v1)

Vectorized PIAF via a model/MCP handoff (the `prep_for_piaf(mode=…)` seam is in
place); a full image editor; dedupe-by-image-hash; a custom graph view (use
Obsidian); any hosting/multi-user; Tauri/Electron packaging.

## Develop / test

```bash
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

## Project layout

```
server/   FastAPI backend
  main.py     routes + static serving        index.py    rebuildable SQLite/FTS index
  schema.py   entry model + frontmatter I/O   entries.py  create/update notes, relations
  notesio.py  atomic note read/write          images.py   PIAF prep + edits (Pillow)
  config.py   settings, archive config        alttext.py  pluggable Anthropic alt text
                                              fetchurl.py OG/oEmbed URL intake
web/        plain HTML/CSS/JS UI (no build step)
tests/      pytest suite
```
