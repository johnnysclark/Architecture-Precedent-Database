"""Per-machine settings, the portable archive config, and cache locations.

Three kinds of state, deliberately kept apart:

* **Per-machine, never synced** — which folder is the archive, and the API key.
  Resolved from environment first, else a small app-config file in the OS config
  dir. Never hardcoded.
* **Portable, travels with the archive** — ``.precedents/config.yaml`` at the
  archive root holds the editable ``type`` controlled list. Safe to sync.
* **Disposable cache** — the SQLite index lives in the OS cache dir, keyed by a
  hash of the archive path, so it never pollutes or syncs the archive.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional

import yaml
from platformdirs import user_cache_dir, user_config_dir

APP_NAME = "precedent-db"

PRECEDENTS_DIRNAME = ".precedents"
CONFIG_FILENAME = "config.yaml"

# Directories the scanner should never treat as archive content.
IGNORE_DIRS = {
    ".git",
    ".obsidian",
    PRECEDENTS_DIRNAME,
    ".venv",
    "node_modules",
    "__pycache__",
    ".trash",
    ".Trash",
}

DEFAULT_TYPES = [
    "building",
    "interior",
    "detail",
    "urban",
    "landscape",
    "plan",
    "section",
    "diagram",
    "drawing",
    "model",
    "material",
    "reference",
]


# ---------------------------------------------------------------------------
# Per-machine archive location
# ---------------------------------------------------------------------------

def _app_config_path() -> Path:
    return Path(user_config_dir(APP_NAME)) / "app.json"


def get_saved_archive_dir() -> Optional[Path]:
    """Environment variable wins; otherwise the last folder chosen in the UI."""
    env = os.environ.get("PRECEDENTS_ARCHIVE_DIR")
    if env:
        return Path(env).expanduser()
    p = _app_config_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            d = data.get("archive_dir")
            if d:
                return Path(d).expanduser()
        except Exception:
            return None
    return None


def save_archive_dir(path: Path) -> None:
    cfg = _app_config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"archive_dir": str(path)}, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Portable archive config (.precedents/config.yaml)
# ---------------------------------------------------------------------------

def archive_config_path(archive_dir: Path) -> Path:
    return Path(archive_dir) / PRECEDENTS_DIRNAME / CONFIG_FILENAME


def load_archive_config(archive_dir: Path) -> dict:
    """Load (creating with defaults if absent) the archive's portable config."""
    p = archive_config_path(archive_dir)
    data: dict = {}
    if p.exists():
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    changed = False
    if not data.get("types"):
        data["types"] = list(DEFAULT_TYPES)
        changed = True
    if "schemaVersion" not in data:
        data["schemaVersion"] = 1
        changed = True
    if changed:
        save_archive_config(archive_dir, data)
    return data


def save_archive_config(archive_dir: Path, data: dict) -> None:
    p = archive_config_path(archive_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Disposable index cache location
# ---------------------------------------------------------------------------

def index_db_path(archive_dir: Path) -> Path:
    key = hashlib.sha1(str(Path(archive_dir).resolve()).encode("utf-8")).hexdigest()[:16]
    d = Path(user_cache_dir(APP_NAME)) / key
    d.mkdir(parents=True, exist_ok=True)
    return d / "index.sqlite"


# ---------------------------------------------------------------------------
# Secrets / runtime settings
# ---------------------------------------------------------------------------

class Settings:
    """Runtime secrets and model config, read from the environment."""

    def __init__(self) -> None:
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        self.anthropic_base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
        self.alt_model = os.environ.get("PRECEDENTS_ALT_MODEL", "claude-sonnet-4-6").strip()

    @property
    def has_api_key(self) -> bool:
        return bool(self.anthropic_api_key)
