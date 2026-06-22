"""FastAPI app: the localhost backend and JSON API for the Precedent Database.

Holds a single in-process AppState (archive dir + index + settings). Truth is
always read from the note files on disk; the index only accelerates list/search.
Static UI is served from ../web.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import entries, fetchurl, images, schema
from .alttext import generate_alt_text, suggest_metadata
from .config import (
    Settings,
    get_saved_archive_dir,
    index_db_path,
    load_archive_config,
    save_archive_config,
    save_archive_dir,
)
from .index import Index

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class AppState:
    def __init__(self) -> None:
        self.settings = Settings()
        self.archive_dir: Optional[Path] = None
        self.index: Optional[Index] = None
        self.config: dict = {}

    @property
    def ready(self) -> bool:
        return self.archive_dir is not None and self.index is not None

    def bind(self, archive_dir: Path, build: bool = True) -> None:
        archive_dir = Path(archive_dir).expanduser().resolve()
        if not archive_dir.is_dir():
            raise ValueError(f"Not a folder: {archive_dir}")
        self.archive_dir = archive_dir
        self.config = load_archive_config(archive_dir)
        self.index = Index(index_db_path(archive_dir), archive_dir)
        if build:
            self.index.rebuild()


state = AppState()


def require() -> tuple[Path, Index]:
    if not state.ready:
        raise HTTPException(status_code=409, detail="No archive selected yet.")
    assert state.archive_dir is not None and state.index is not None
    return state.archive_dir, state.index


@asynccontextmanager
async def lifespan(app: FastAPI):
    saved = get_saved_archive_dir()
    if saved and saved.is_dir():
        try:
            state.bind(saved)
        except Exception:
            pass
    yield


app = FastAPI(title="Precedent Database", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _archive_rel(abs_path: Path) -> str:
    return Path(abs_path).resolve().relative_to(state.archive_dir.resolve()).as_posix()


def image_url(abs_path: Path, download: bool = False) -> str:
    rel = _archive_rel(abs_path)
    return f"/api/{'download' if download else 'image'}?{urlencode({'path': rel})}"


def _image_payload(note_path: Path, idx: int, im: schema.EntryImage) -> dict:
    archive = state.archive_dir
    url, exists = "", False
    try:
        abs_p = entries.image_abs(archive, note_path, im.path)
        url, exists = image_url(abs_p), abs_p.exists()
    except Exception:
        pass
    derivs = []
    for d in im.derivatives:
        try:
            dabs = entries.image_abs(archive, note_path, d.path)
            derivs.append({
                "kind": d.kind,
                "created": d.created,
                "url": image_url(dabs),
                "download": image_url(dabs, download=True),
                "exists": dabs.exists(),
            })
        except Exception:
            continue
    return {
        "index": idx,
        "path": im.path,
        "url": url,
        "exists": exists,
        "alt": im.alt,
        "altSource": im.altSource,
        "caption": im.caption,
        "primary": im.primary,
        "tactilePrepped": im.tactilePrepped,
        "addedFrom": im.addedFrom,
        "derivatives": derivs,
    }


def entry_detail(entry: schema.Entry, note_path: Path) -> dict:
    _, index = require()
    related = [{"id": r, "title": index.title_of(r) or "(missing entry)"} for r in entry.related]
    extra = [b for b in index.backlinks(entry.id) if b not in entry.related]
    backlinks = [{"id": b, "title": index.title_of(b) or "(missing entry)"} for b in extra]
    return {
        "id": entry.id,
        "schemaVersion": entry.schemaVersion,
        "created": entry.created,
        "updated": entry.updated,
        "title": entry.title,
        "type": entry.type,
        "tags": entry.tags,
        "sources": [{"url": s.url, "label": s.label} for s in entry.sources],
        "related": related,
        "backlinks": backlinks,
        "notes": entry.notes,
        "notePath": _archive_rel(note_path),
        "images": [_image_payload(note_path, i, im) for i, im in enumerate(entry.images)],
    }


async def _bg_alt(entry_id: str, image_index: int) -> None:
    """Background: fill AI alt text for a freshly added image (if a key exists)."""
    if not state.ready or not state.settings.has_api_key:
        return
    try:
        entry, note_path = entries.load(state.archive_dir, state.index, entry_id)
        im = entry.images[image_index]
        if im.alt.strip() or im.altSource == schema.ALT_HUMAN:
            return
        abs_p = entries.image_abs(state.archive_dir, note_path, im.path)
        res = await generate_alt_text(abs_p, state.settings)
        if res.ok:
            entries.set_image_alt(state.archive_dir, state.index, entry_id, image_index, res.text, schema.ALT_AI)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ArchiveBody(BaseModel):
    path: str


class EntryPatch(BaseModel):
    title: Optional[str] = None
    type: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    sources: Optional[list[dict]] = None


class RelationBody(BaseModel):
    target: str


class AltBody(BaseModel):
    alt: str


class ImageMetaBody(BaseModel):
    caption: Optional[str] = None
    primary: Optional[bool] = None


class PiafBody(BaseModel):
    threshold: int = 128
    edge: bool = False
    invert: bool = False


class EditBody(BaseModel):
    crop: Optional[dict] = None
    rotate: int = 0
    resize: Optional[dict] = None
    contrast: Optional[float] = None


class UrlBody(BaseModel):
    url: str


class ExistingBody(BaseModel):
    path: str


class TypeBody(BaseModel):
    type: str


# ---------------------------------------------------------------------------
# Status / settings / config
# ---------------------------------------------------------------------------

@app.get("/api/status")
def status() -> dict:
    return {
        "archiveSet": state.ready,
        "archiveDir": str(state.archive_dir) if state.archive_dir else "",
        "fts5": state.index.fts if state.index else False,
        "hasApiKey": state.settings.has_api_key,
        "count": state.index.count() if state.index else 0,
        "version": "0.1.0",
    }


@app.post("/api/settings/archive")
def set_archive(body: ArchiveBody) -> dict:
    path = Path(body.path).expanduser()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a folder: {path}")
    state.bind(path)
    save_archive_dir(path.resolve())
    return status()


@app.post("/api/index/rebuild")
def rebuild() -> dict:
    _, index = require()
    return index.rebuild()


@app.get("/api/config")
def get_config() -> dict:
    _, index = require()
    return {
        "types": state.config.get("types", []),
        "usedTypes": index.all_types(),
        "tags": index.all_tags(),
        "hasApiKey": state.settings.has_api_key,
        "archiveDir": str(state.archive_dir),
    }


@app.post("/api/config/types")
def add_type(body: TypeBody) -> dict:
    require()
    t = body.type.strip()
    types = state.config.setdefault("types", [])
    if t and t not in types:
        types.append(t)
        save_archive_config(state.archive_dir, state.config)
    return {"types": types}


# ---------------------------------------------------------------------------
# Browse
# ---------------------------------------------------------------------------

@app.get("/api/entries")
def list_entries(
    type: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    sort: str = "updated",
) -> dict:
    _, index = require()
    items = index.list_entries(type=type, tag=tag, q=q, sort=sort)
    for it in items:
        if it["primaryImage"]:
            it["primaryImageUrl"] = f"/api/image?{urlencode({'path': it['primaryImage']})}"
        else:
            it["primaryImageUrl"] = ""
    return {"entries": items, "total": len(items)}


@app.get("/api/entries/{entry_id}")
def get_entry(entry_id: str) -> dict:
    archive, index = require()
    try:
        entry, note_path = entries.load(archive, index, entry_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry_detail(entry, note_path)


@app.patch("/api/entries/{entry_id}")
def patch_entry(entry_id: str, body: EntryPatch) -> dict:
    archive, index = require()
    patch = body.model_dump(exclude_unset=True)
    try:
        entries.update_entry(archive, index, entry_id, patch)
        entry, note_path = entries.load(archive, index, entry_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry_detail(entry, note_path)


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------

@app.post("/api/entries/{entry_id}/relations")
def add_relation(entry_id: str, body: RelationBody) -> dict:
    archive, index = require()
    try:
        entries.add_relation(archive, index, entry_id, body.target)
        entry, note_path = entries.load(archive, index, entry_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Entry not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return entry_detail(entry, note_path)


@app.delete("/api/entries/{entry_id}/relations/{target}")
def remove_relation(entry_id: str, target: str) -> dict:
    archive, index = require()
    entries.remove_relation(archive, index, entry_id, target)
    try:
        entry, note_path = entries.load(archive, index, entry_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry_detail(entry, note_path)


# ---------------------------------------------------------------------------
# Alt text & image metadata
# ---------------------------------------------------------------------------

@app.post("/api/entries/{entry_id}/images/{idx}/alt")
def set_alt(entry_id: str, idx: int, body: AltBody) -> dict:
    archive, index = require()
    try:
        entries.set_image_alt(archive, index, entry_id, idx, body.alt, schema.ALT_HUMAN)
        entry, note_path = entries.load(archive, index, entry_id)
    except (KeyError, IndexError):
        raise HTTPException(status_code=404, detail="Entry or image not found")
    return entry_detail(entry, note_path)


@app.post("/api/entries/{entry_id}/images/{idx}/alt/generate")
async def generate_alt(entry_id: str, idx: int, confirm: bool = False) -> dict:
    archive, index = require()
    try:
        entry, note_path = entries.load(archive, index, entry_id)
        im = entry.images[idx]
    except (KeyError, IndexError):
        raise HTTPException(status_code=404, detail="Entry or image not found")
    if im.altSource == schema.ALT_HUMAN and not confirm:
        return {"ok": False, "needsConfirm": True,
                "reason": "Human-edited alt text — confirm to overwrite."}
    abs_p = entries.image_abs(archive, note_path, im.path)
    if not abs_p.exists():
        return {"ok": False, "reason": "image_missing"}
    res = await generate_alt_text(abs_p, state.settings)
    if not res.ok:
        return {"ok": False, "reason": res.reason}
    entries.set_image_alt(archive, index, entry_id, idx, res.text, schema.ALT_AI)
    return {"ok": True, "alt": res.text}


@app.post("/api/entries/{entry_id}/images/{idx}/meta")
def patch_image(entry_id: str, idx: int, body: ImageMetaBody) -> dict:
    archive, index = require()
    try:
        entries.update_image(archive, index, entry_id, idx, caption=body.caption, primary=body.primary)
        entry, note_path = entries.load(archive, index, entry_id)
    except (KeyError, IndexError):
        raise HTTPException(status_code=404, detail="Entry or image not found")
    return entry_detail(entry, note_path)


@app.post("/api/entries/{entry_id}/images/{idx}/suggest")
async def suggest(entry_id: str, idx: int) -> dict:
    archive, index = require()
    try:
        entry, note_path = entries.load(archive, index, entry_id)
        im = entry.images[idx]
    except (KeyError, IndexError):
        raise HTTPException(status_code=404, detail="Entry or image not found")
    if not state.settings.has_api_key:
        return {"ok": False, "reason": "no_api_key"}
    abs_p = entries.image_abs(archive, note_path, im.path)
    data = await suggest_metadata(abs_p, state.settings, state.config.get("types", []))
    if not data:
        return {"ok": False, "reason": "unavailable"}
    return {"ok": True, "suggestions": data}


@app.post("/api/alt/generate-missing")
async def generate_missing() -> dict:
    archive, index = require()
    if not state.settings.has_api_key:
        return {"ok": False, "reason": "no_api_key", "updated": 0, "failed": 0, "skipped": 0}
    updated = failed = skipped = 0
    for summ in index.list_entries(limit=1_000_000):
        try:
            entry, note_path = entries.load(archive, index, summ["id"])
        except KeyError:
            continue
        for i, im in enumerate(entry.images):
            if im.alt.strip() or im.altSource == schema.ALT_HUMAN:
                skipped += 1
                continue
            abs_p = entries.image_abs(archive, note_path, im.path)
            if not abs_p.exists():
                failed += 1
                continue
            res = await generate_alt_text(abs_p, state.settings)
            if res.ok:
                entries.set_image_alt(archive, index, summ["id"], i, res.text, schema.ALT_AI)
                updated += 1
            else:
                failed += 1
    return {"ok": True, "updated": updated, "failed": failed, "skipped": skipped}


# ---------------------------------------------------------------------------
# Add: existing file / upload / url
# ---------------------------------------------------------------------------

@app.post("/api/add/existing")
def add_existing(body: ExistingBody, background: BackgroundTasks) -> dict:
    archive, index = require()
    try:
        entry, note_path, created = entries.add_existing_image(archive, index, body.path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if created and state.settings.has_api_key:
        background.add_task(_bg_alt, entry.id, 0)
    return {"id": entry.id, "title": entry.title, "created": created,
            "altScheduled": created and state.settings.has_api_key}


@app.post("/api/add/upload")
async def add_upload(
    background: BackgroundTasks,
    files: list[UploadFile] = File(...),
    group: bool = Form(False),
    groupTitle: str = Form(""),
) -> dict:
    archive, index = require()
    created: list[dict] = []

    if group and len(files) >= 1:
        title = groupTitle.strip() or "Untitled project"
        folder = entries._unique(archive / entries.slugify(title, "project"))
        folder.mkdir(parents=True, exist_ok=True)
        names: list[str] = []
        for f in files:
            data = await f.read()
            dest = entries.save_upload_bytes(archive, f.filename or "image.png", data, subdir=folder.name)
            names.append(dest.name)
        entry, _ = entries.create_folder_entry(archive, index, folder, names, title=title)
        created.append({"id": entry.id, "title": entry.title})
        if state.settings.has_api_key:
            for i in range(len(names)):
                background.add_task(_bg_alt, entry.id, i)
    else:
        for f in files:
            data = await f.read()
            dest = entries.save_upload_bytes(archive, f.filename or "image.png", data)
            entry, _ = entries.create_sibling_entry(archive, index, dest)
            created.append({"id": entry.id, "title": entry.title})
            if state.settings.has_api_key:
                background.add_task(_bg_alt, entry.id, 0)

    return {"created": created, "count": len(created),
            "altScheduled": state.settings.has_api_key}


@app.post("/api/add/url")
async def add_url(body: UrlBody, background: BackgroundTasks) -> dict:
    archive, index = require()
    result = await run_in_threadpool(fetchurl.create_entry_from_url, archive, index, body.url.strip())
    if result.get("ok") and result.get("hadImage") and state.settings.has_api_key:
        background.add_task(_bg_alt, result["id"], 0)
        result["altScheduled"] = True
    return result


# ---------------------------------------------------------------------------
# Image actions: PIAF prep / edit
# ---------------------------------------------------------------------------

def _src_for(entry_id: str, idx: int):
    archive, index = require()
    entry, note_path = entries.load(archive, index, entry_id)
    im = entry.images[idx]
    src = entries.image_abs(archive, note_path, im.path)
    if not src.exists():
        raise HTTPException(status_code=404, detail="Source image missing on disk")
    return archive, index, entry, note_path, im, src


@app.post("/api/entries/{entry_id}/images/{idx}/piaf")
async def piaf(entry_id: str, idx: int, body: PiafBody) -> dict:
    try:
        archive, index, entry, note_path, im, src = _src_for(entry_id, idx)
    except (KeyError, IndexError):
        raise HTTPException(status_code=404, detail="Entry or image not found")
    out = await run_in_threadpool(
        images.prep_for_piaf, src, threshold=body.threshold, edge=body.edge, invert=body.invert
    )
    _, rel = entries.add_image_derivative(archive, index, entry_id, idx, "piaf", out, set_tactile=True)
    return {"ok": True, "url": image_url(out), "download": image_url(out, download=True), "path": rel}


@app.post("/api/entries/{entry_id}/images/{idx}/edit")
async def edit(entry_id: str, idx: int, body: EditBody) -> dict:
    try:
        archive, index, entry, note_path, im, src = _src_for(entry_id, idx)
    except (KeyError, IndexError):
        raise HTTPException(status_code=404, detail="Entry or image not found")
    out = await run_in_threadpool(
        images.edit_image, src,
        crop=body.crop, rotate=body.rotate, resize=body.resize, contrast=body.contrast,
    )
    _, rel = entries.add_image_derivative(archive, index, entry_id, idx, "edit", out)
    return {"ok": True, "url": image_url(out), "download": image_url(out, download=True), "path": rel}


# ---------------------------------------------------------------------------
# Serve image bytes (path-traversal guarded)
# ---------------------------------------------------------------------------

@app.get("/api/image")
def serve_image(path: str):
    archive, _ = require()
    try:
        abs_p = images.ensure_within(archive, path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not abs_p.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(abs_p)


@app.get("/api/download")
def download_image(path: str):
    archive, _ = require()
    try:
        abs_p = images.ensure_within(archive, path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not abs_p.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(abs_p, filename=abs_p.name, media_type="application/octet-stream")


# Static UI last, so /api/* always wins. html=True serves index.html at "/".
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
