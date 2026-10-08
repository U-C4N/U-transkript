"""``python -m utmax.mcp`` speaks MCP over stdio: a real client starts it and calls a tool."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters, stdio_client


def test_a_stdio_client_lists_the_tools_and_gets_errors_as_text(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COV_", "COVERAGE_"))}
    env["UTMAX_DOWNLOAD_DIR"] = str(tmp_path)
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "utmax.mcp"], env=env)

    async def main() -> tuple[list[str], str, bool]:
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as session,
        ):
            initialized = await session.initialize()
            assert initialized.server_info.name == "utmax"
            names = [tool.name for tool in (await session.list_tools()).tools]
            result = await session.call_tool("get_transcript", {"video": "not a video ♪"})
            text = " ".join(block.text for block in result.content if block.type == "text")
            return names, text, result.is_error

    names, text, is_error = anyio.run(main)

    assert names == [
        "list_tracks",
        "get_transcript",
        "translate_transcript",
        "list_videos",
        "download",
    ]
    assert is_error is True
    assert "Could not find a YouTube video ID in 'not a video ♪'." in text
