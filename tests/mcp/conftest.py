"""Without the MCP SDK (the core CI job), only the tests that do not need it run."""

from __future__ import annotations

import importlib.util

collect_ignore = (
    []
    if importlib.util.find_spec("mcp") is not None
    else ["test_download.py", "test_flow.py", "test_live.py", "test_server.py", "test_stdio.py"]
)
