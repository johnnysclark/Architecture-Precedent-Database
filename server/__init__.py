"""Precedent Database — a non-destructive lens over a folder of files.

Truth lives on disk as markdown notes (YAML frontmatter) beside the images they
describe. This package is the local backend: it scans the archive, builds a
disposable SQLite index, and writes metadata *alongside* your files. It never
moves, renames, or rewrites the original images.
"""

__version__ = "0.1.0"
