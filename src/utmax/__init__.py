"""u-transcript max: YouTube transcripts, AI translation and downloads with zero dependencies."""

from __future__ import annotations

import logging

from utmax._version import __version__

__all__ = ["__version__"]

logging.getLogger("utmax").addHandler(logging.NullHandler())
