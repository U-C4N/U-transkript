from __future__ import annotations

import os
import sys

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.append(_SRC_DIR)

from .main import main  # noqa: E402

__all__ = ["main"]
