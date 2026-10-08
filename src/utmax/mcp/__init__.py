"""An MCP server that gives AI assistants utmax's tools: transcripts, AI translation,
playlists and channels, and downloads.

Install it with ``pip install "u-transcript-max[mcp]"`` and register the ``utmax-mcp`` command
(or ``python -m utmax.mcp``) as a stdio server in your MCP client, for example Claude Code::

    claude mcp add utmax -e UTMAX_MODEL=claude=claude-opus-5 -- utmax-mcp

Settings come from environment variables; see :mod:`utmax.mcp.config`.
"""
