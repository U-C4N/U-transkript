"""Folder checks that hold on every platform."""

from __future__ import annotations

from pathlib import Path


def folder_names(folder: Path) -> list[str]:
    """The sorted names in ``folder``, without the ones some Windows security software shows
    for a moment after a file was deleted: the old name in capitals plus ``.tmp`` (such as
    ``RICK.M4A.140.PART.JSON.tmp``). utmax's own temporary files start with a dot, so they
    still show up."""
    return sorted(name for name in (path.name for path in folder.iterdir()) if not _ghost(name))


def _ghost(name: str) -> bool:
    stem = name.removesuffix(".tmp")
    return stem != name and not name.startswith(".") and stem == stem.upper()
