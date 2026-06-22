"""AI alt text — one pluggable async function, called when an image is added.

Sends the image to the Anthropic Messages API with a system prompt tuned for
architectural precedents. The API key comes from the environment, never
hardcoded. With no key the function degrades cleanly (``ok=False,
reason="no_api_key"``) so the rest of the app keeps working; the UI surfaces the
missing-key state and alt text stays editable.

The same model optionally suggests a title/type/tags — returned as *suggestions*
for the human to accept or reject, never applied silently.
"""
from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import Settings

# Tuned, verbatim. Written to be read aloud by a screen reader.
ALT_SYSTEM_PROMPT = """\
You write alt text for an architecture precedent library. Each image is an \
architectural precedent saved for study — a building, space, drawing, diagram, \
detail, model, or urban condition. Produce one concise description written to be \
read aloud by a screen reader.

Name the kind of representation only when it's evident (photograph, plan, \
section, elevation, axonometric, diagram, model, render). Then describe, in \
order of importance: (1) spatial organization and composition — massing, \
proportion, symmetry, circulation, figure-ground, how space is bounded, opened, \
or layered; (2) materials, structure, and light — what things are made of, \
tectonic expression, surface, how light enters; (3) any notable formal or \
experiential quality a designer would care about.

Be information-dense but economical: roughly one to three sentences, no filler. \
Do not begin with "an image of", "a picture of", "this shows", or similar — \
state the content directly. Do not guess architect, project name, location, or \
date unless legible in the image. Ignore watermarks, browser/UI chrome, and \
screenshot borders; if it's a screenshot of a page, describe the architecture \
depicted, not the webpage. If the image is primarily a diagram or text, \
summarize the key labeled information. Use plain, concrete spatial language; \
avoid marketing adjectives. Output only the alt text — no quotation marks, no \
preamble."""

SUGGEST_SYSTEM_PROMPT = """\
You help catalog architectural precedents. Look at the image and propose concise \
catalog metadata. Reply with ONLY a JSON object of the form \
{"title": string, "type": string, "tags": [string, ...]}. The title is a short \
human label (max ~6 words). Choose type from this list if one clearly fits, else \
empty string: %s. Tags are 3-6 lowercase keywords (materials, building type, \
spatial idea, architect if legible). No prose, no code fence."""

MAX_TOKENS = 400


@dataclass
class AltResult:
    ok: bool
    text: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return {"ok": self.ok, "text": self.text, "reason": self.reason}


def _image_block(path: Path) -> dict:
    """Return an Anthropic image content block, converting unsupported formats
    (e.g. HEIC, TIFF) to PNG in memory first."""
    from .images import API_IMAGE_TYPES, _load  # local import avoids cycle at load

    path = Path(path)
    media_type = API_IMAGE_TYPES.get(path.suffix.lower())
    if media_type:
        data = path.read_bytes()
    else:
        buf = io.BytesIO()
        _load(path).convert("RGB").save(buf, format="PNG")
        data = buf.getvalue()
        media_type = "image/png"
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
    }


def _client(settings: Settings):
    import anthropic  # imported lazily so the app runs without a key/SDK call

    kwargs = {"api_key": settings.anthropic_api_key}
    if settings.anthropic_base_url:
        kwargs["base_url"] = settings.anthropic_base_url
    return anthropic.AsyncAnthropic(**kwargs)


async def generate_alt_text(image_path: Path | str, settings: Settings) -> AltResult:
    """The pluggable alt-text function. Always returns an AltResult; never raises."""
    if not settings.has_api_key:
        return AltResult(ok=False, reason="no_api_key")
    try:
        block = _image_block(Path(image_path))
        client = _client(settings)
        resp = await client.messages.create(
            model=settings.alt_model,
            max_tokens=MAX_TOKENS,
            system=ALT_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        block,
                        {"type": "text", "text": "Write the alt text for this architectural precedent."},
                    ],
                }
            ],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        if not text:
            return AltResult(ok=False, reason="empty_response")
        return AltResult(ok=True, text=text)
    except ImportError:
        return AltResult(ok=False, reason="anthropic_not_installed")
    except Exception as e:  # network, auth, rate limit, etc. — keep app alive
        return AltResult(ok=False, reason=f"{type(e).__name__}: {e}")


async def suggest_metadata(
    image_path: Path | str, settings: Settings, types: list[str]
) -> Optional[dict]:
    """Best-effort title/type/tags suggestion. Returns None if unavailable."""
    if not settings.has_api_key:
        return None
    try:
        block = _image_block(Path(image_path))
        client = _client(settings)
        resp = await client.messages.create(
            model=settings.alt_model,
            max_tokens=300,
            system=SUGGEST_SYSTEM_PROMPT % ", ".join(types),
            messages=[{"role": "user", "content": [block, {"type": "text", "text": "Suggest catalog metadata as JSON."}]}],
        )
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        data = _loose_json(raw)
        if not isinstance(data, dict):
            return None
        return {
            "title": str(data.get("title", ""))[:120],
            "type": str(data.get("type", "")) if data.get("type") in types else "",
            "tags": [str(t).lower() for t in (data.get("tags") or [])][:8],
        }
    except Exception:
        return None


def _loose_json(raw: str):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):]
    try:
        return json.loads(raw)
    except Exception:
        start, end = raw.find("{"), raw.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(raw[start : end + 1])
            except Exception:
                return None
        return None
