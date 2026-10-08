"""An MCP server that gives AI assistants utmax's tools: subtitle tracks and transcripts,
playlists and channels, and downloads.

Install it with ``pip install "u-transcript-max[mcp]"`` and register the ``utmax-mcp`` command
(or ``python -m utmax.mcp``) as a stdio server in your MCP client, for example Claude Code::

    claude mcp add utmax -- utmax-mcp

It needs no API key: the assistant translates transcripts itself. Settings (the download folder
and a proxy) come from environment variables; see :mod:`utmax.mcp.config`.
"""

from __future__ import annotations

__all__ = ["main"]

_SDK_MODULES = frozenset({"anyio", "mcp", "mcp_types", "pydantic", "pydantic_core"})


def main() -> None:
    """Run the MCP server over stdio until the client disconnects."""
    try:
        from utmax.mcp.server import run
    except ModuleNotFoundError as error:
        if (error.name or "").partition(".")[0] not in _SDK_MODULES:
            raise
        raise SystemExit(
            'utmax-mcp needs the MCP SDK: pip install "u-transcript-max[mcp]"'
        ) from error
    run()
