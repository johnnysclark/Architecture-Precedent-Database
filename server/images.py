"""Server-side image work: safe path resolution, PIAF prep, and basic edits.

All operations are non-destructive — the original image is opened read-only and
results are written as *new* derivative files beside it. Heavier vectorization
(and any external image-MCP handoff) is intentionally left as a deferred hook:
:func:`prep_for_piaf` accepts ``mode`` so a future ``"vector"`` path can be added
without reworking callers.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

# Register HEIC/HEIF so iPhone photos open like any other image.
try:  # pragma: no cover - depends on optional native lib
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover
    pass

# Media types the Anthropic API accepts directly; anything else we convert.
API_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def ensure_within(archive_dir: Path | str, candidate: Path | str) -> Path:
    """Resolve ``candidate`` and guarantee it stays inside ``archive_dir``.

    Guards every filesystem-facing endpoint against path traversal.
    """
    root = Path(archive_dir).resolve()
    p = Path(candidate)
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    if p != root and root not in p.parents:
        raise ValueError("path escapes archive")
    return p


def _load(src: Path) -> Image.Image:
    img = Image.open(src)
    # Honor EXIF orientation so rotated phone shots are processed upright.
    return ImageOps.exif_transpose(img)


def _free_path(base_dir: Path, stem: str, suffix: str) -> Path:
    """Return base_dir/<stem><suffix>, bumping a numeric counter to avoid
    overwriting an existing file (used for repeatable edit derivatives)."""
    candidate = base_dir / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        candidate = base_dir / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


# ---------------------------------------------------------------------------
# PIAF prep (tactile / swell paper): high-contrast black-on-white
# ---------------------------------------------------------------------------

def prep_for_piaf(
    src: Path,
    *,
    threshold: int = 128,
    edge: bool = False,
    invert: bool = False,
    mode: str = "raster",
) -> Path:
    """Produce a bold 1-bit black/white image suited to swell-paper printing.

    PIAF raises black regions on heating, so we want minimal mid-tones. Default
    is grayscale -> auto-contrast -> threshold (dark areas become raised black).
    ``edge=True`` runs edge detection first (good for line drawings/plans).
    """
    if mode != "raster":
        # Deferred hook — vectorized output via model/MCP handoff (Phase 2).
        raise NotImplementedError(f"PIAF mode '{mode}' is not available in v1")

    src = Path(src)
    gray = _load(src).convert("L")
    if edge:
        base = gray.filter(ImageFilter.FIND_EDGES)  # white edges on black
        base = base.filter(ImageFilter.MaxFilter(3))  # thicken slightly
        base = ImageOps.invert(base)  # -> black edges on white
    else:
        base = ImageOps.autocontrast(gray)

    th = max(0, min(255, int(threshold)))
    # Below threshold -> black (raised); at/above -> white.
    binary = base.point(lambda p: 0 if p < th else 255, mode="L").convert("1")
    if invert:
        binary = binary.point(lambda p: 0 if p else 255).convert("1")

    out = src.with_name(src.stem + ".piaf.png")
    binary.save(out, format="PNG")
    return out


# ---------------------------------------------------------------------------
# Basic edits (crop / rotate / resize / contrast) — not a full editor
# ---------------------------------------------------------------------------

_ROTATE = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}


def edit_image(
    src: Path,
    *,
    crop: Optional[dict] = None,  # {x, y, w, h} in pixels
    rotate: int = 0,  # clockwise degrees: 0/90/180/270
    resize: Optional[dict] = None,  # {w, h} or {maxDim}
    contrast: Optional[float] = None,  # 1.0 = unchanged
) -> Path:
    """Apply simple, reversible-by-discarding edits and save a new derivative."""
    src = Path(src)
    img = _load(src)

    if crop:
        x, y = int(crop.get("x", 0)), int(crop.get("y", 0))
        w, h = int(crop.get("w", 0)), int(crop.get("h", 0))
        if w > 0 and h > 0:
            img = img.crop((x, y, x + w, y + h))

    if rotate:
        r = int(rotate) % 360
        if r in _ROTATE:
            img = img.transpose(_ROTATE[r])

    if resize:
        if resize.get("maxDim"):
            m = int(resize["maxDim"])
            img.thumbnail((m, m), Image.LANCZOS)
        elif resize.get("w") and resize.get("h"):
            img = img.resize((int(resize["w"]), int(resize["h"])), Image.LANCZOS)

    if contrast is not None and float(contrast) != 1.0:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img = ImageEnhance.Contrast(img).enhance(float(contrast))

    out = _free_path(src.parent, src.stem, ".edit.png")
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGBA")
    elif img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.save(out, format="PNG")
    return out
