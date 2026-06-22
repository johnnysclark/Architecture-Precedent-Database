"""Internet add: build an entry from a URL's Open Graph / oEmbed metadata.

Honest about its limits. Arbitrary-page scraping is best-effort and often returns
thin metadata; Instagram and similar login-walled sites are flagged as a
manual-screenshot path rather than pretended-to-be-fetched. Server-side fetches
are guarded against SSRF (no localhost / private addresses).
"""
from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import schema
from .entries import create_sibling_entry, slugify, _unique
from .index import Index
from .notesio import write_note

USER_AGENT = "PrecedentDB/0.1 (+local archive tool)"
MAX_HTML_BYTES = 2_000_000
MAX_IMAGE_BYTES = 25_000_000
TIMEOUT = 12

# Hosts where reliable fetching is unrealistic; recommend a manual screenshot.
MANUAL_HOSTS = ("instagram.com", "instagr.am", "threads.net", "facebook.com")


# ---------------------------------------------------------------------------
# Pure parsing (unit-testable without network)
# ---------------------------------------------------------------------------

def parse_metadata(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    def meta(prop: str) -> str:
        el = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        return (el.get("content") or "").strip() if el else ""

    title = meta("og:title") or meta("twitter:title")
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    description = meta("og:description") or meta("twitter:description") or meta("description")
    image = meta("og:image") or meta("og:image:url") or meta("twitter:image")
    site_name = meta("og:site_name")
    canonical = meta("og:url")

    link_canon = soup.find("link", rel="canonical")
    if link_canon and link_canon.get("href"):
        canonical = canonical or link_canon["href"].strip()

    oembed = soup.find("link", attrs={"type": "application/json+oembed"})
    oembed_url = oembed["href"].strip() if oembed and oembed.get("href") else ""

    if image:
        image = urljoin(base_url, image)
    if canonical:
        canonical = urljoin(base_url, canonical)
    if oembed_url:
        oembed_url = urljoin(base_url, oembed_url)

    return {
        "title": title,
        "description": description,
        "image": image,
        "site_name": site_name,
        "canonical": canonical,
        "oembed_url": oembed_url,
    }


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------

def is_safe_url(url: str) -> bool:
    try:
        parts = urlparse(url)
    except Exception:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, None)
    except Exception:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Network fetch
# ---------------------------------------------------------------------------

def fetch_url(url: str) -> dict:
    """Fetch + parse a URL's metadata. Returns a dict with ``ok`` and a ``note``."""
    host = _host(url)
    manual = any(host == h or host.endswith("." + h) for h in MANUAL_HOSTS)
    if not is_safe_url(url):
        return {"ok": False, "reason": "unsafe_or_unresolvable_url", "manualRecommended": manual}
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"},
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text[:MAX_HTML_BYTES]
    except Exception as e:
        return {"ok": False, "reason": f"{type(e).__name__}: {e}", "manualRecommended": manual}

    meta = parse_metadata(html, resp.url)

    # Optional oEmbed enrichment.
    if meta.get("oembed_url") and is_safe_url(meta["oembed_url"]):
        try:
            o = requests.get(meta["oembed_url"], headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT).json()
            meta["title"] = meta["title"] or str(o.get("title", ""))
            meta["site_name"] = meta["site_name"] or str(o.get("provider_name", ""))
            meta["image"] = meta["image"] or str(o.get("thumbnail_url", ""))
        except Exception:
            pass

    meta.update({"ok": True, "url": url, "manualRecommended": manual})
    if manual:
        meta["note"] = (
            "This site usually blocks automated fetching. If the details look thin, "
            "take a screenshot and add it as a local image instead."
        )
    return meta


def download_image(url: str, dest_dir: Path, base_name: str) -> Optional[Path]:
    if not is_safe_url(url):
        return None
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, stream=True)
        resp.raise_for_status()
        ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if not ctype.startswith("image/"):
            return None
        ext = {
            "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
            "image/webp": ".webp", "image/avif": ".avif", "image/svg+xml": ".svg",
        }.get(ctype) or (Path(urlparse(url).path).suffix or ".img")
        data = b""
        for chunk in resp.iter_content(64 * 1024):
            data += chunk
            if len(data) > MAX_IMAGE_BYTES:
                return None
    except Exception:
        return None
    dest = _unique(Path(dest_dir) / f"{slugify(base_name, 'web-image')}{ext}")
    dest.write_bytes(data)
    return dest


def create_entry_from_url(
    archive_dir: Path, index: Index, url: str
) -> dict:
    """Fetch a URL and create an entry from its metadata + primary image."""
    meta = fetch_url(url)
    if not meta.get("ok"):
        return {"ok": False, "reason": meta.get("reason", "fetch_failed"),
                "manualRecommended": meta.get("manualRecommended", False)}

    domain = _host(meta.get("canonical") or url)
    title = meta.get("title") or domain or "Untitled"
    sources = [schema.Source(url=meta.get("canonical") or url, label=meta.get("site_name") or domain)]
    description = meta.get("description") or ""

    had_image = False
    if meta.get("image"):
        img_path = download_image(meta["image"], Path(archive_dir), title)
        if img_path is not None:
            entry, note_path = create_sibling_entry(
                Path(archive_dir), index, img_path, title=title, sources=sources, added_from=url
            )
            if description:
                entry.notes = description
                entry.updated = schema.now_iso()
                write_note(entry, note_path)
                index.upsert_file(note_path)
            had_image = True
            return {
                "ok": True, "id": entry.id, "title": entry.title, "hadImage": True,
                "manualRecommended": meta.get("manualRecommended", False), "note": meta.get("note", ""),
            }

    # No usable image — create a note-only entry at the archive root.
    note_path = _unique(Path(archive_dir) / f"{slugify(title)}.md")
    entry = schema.new_entry(title=title)
    entry.sources = sources
    entry.notes = description
    write_note(entry, note_path)
    index.upsert_file(note_path)
    return {
        "ok": True, "id": entry.id, "title": entry.title, "hadImage": had_image,
        "manualRecommended": meta.get("manualRecommended", False),
        "note": meta.get("note", "") or ("No image found on the page; created a text entry." ),
    }
