"""Live checks of the MCP tools (spec §4.7) on dQw4w9WgXcQ and Rick Astley's channel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client as MCPClient
from mcp.types import CallToolResult

from utmax import Client
from utmax.mcp.config import Config
from utmax.mcp.server import build_server

pytestmark = pytest.mark.live

VIDEO = "dQw4w9WgXcQ"


def call(server: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async def main() -> CallToolResult:
        async with MCPClient(server, raise_exceptions=True) as client:
            return await client.call_tool(name, arguments)

    result = anyio.run(main)
    if result.is_error:
        text = " ".join(block.text for block in result.content if block.type == "text")
        if "rate-limited" in text or "blocking" in text:
            pytest.skip(f"YouTube is blocking this IP address: {text}")
        pytest.fail(text)
    assert result.structured_content is not None
    return result.structured_content


def test_tracks_and_a_transcript_in_parts(tmp_path: Path) -> None:
    server = build_server(Client(), Config(download_dir=tmp_path))

    tracks = call(server, "list_tracks", {"video": VIDEO})
    page = call(server, "get_transcript", {"video": VIDEO, "max_chars": 200})

    assert ("en", False) in [(t["language_code"], t["is_generated"]) for t in tracks["tracks"]]
    assert page["content"].startswith("[♪♪♪] ♪ We're no strangers to love ♪")
    assert page["next_offset"] is not None
    assert page["total_chars"] > 200


def test_a_channel_tab_and_an_audio_download(tmp_path: Path) -> None:
    server = build_server(Client(), Config(download_dir=tmp_path))

    videos = call(
        server,
        "list_videos",
        {"source": "https://www.youtube.com/@RickAstleyYT/videos", "limit": 5},
    )
    first = call(server, "download", {"video": VIDEO, "format": "m4a"})
    again = call(server, "download", {"video": VIDEO, "format": "m4a"})

    assert (videos["kind"], len(videos["videos"])) == ("videos", 5)
    assert videos["count"] >= 139
    assert Path(first["path"]).parent == tmp_path
    assert first["size_bytes"] > 3_000_000
    assert (first["skipped"], again["skipped"]) == (False, True)
