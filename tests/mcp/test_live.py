"""Live checks of the MCP tools (spec §4.7) on dQw4w9WgXcQ and Rick Astley's channel.

The last tests run offline: they pin how ``call`` tells YouTube blocking this IP address (a skip)
from a real failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client as MCPClient
from mcp.types import CallToolResult

from tests.helpers.fake_transport import FakeTransport
from utmax import Client
from utmax.errors import IpBlocked, RequestBlocked, UTMaxError, VideoUnavailable
from utmax.mcp.config import Config
from utmax.mcp.server import build_server

VIDEO = "dQw4w9WgXcQ"
# A block reaches the model as "<message> Suggestion: <suggestion>". The message varies (HTTP 429,
# a CAPTCHA page, the bot check) but the suggestion comes from the error class, so it tells a
# RequestBlocked or IpBlocked from any other error, as tests/live/conftest.py does by type.
BLOCKED = (RequestBlocked.suggestion, IpBlocked.suggestion)


def call(server: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async def main() -> CallToolResult:
        async with MCPClient(server, raise_exceptions=True) as client:
            return await client.call_tool(name, arguments)

    result = anyio.run(main)
    if result.is_error:
        text = " ".join(block.text for block in result.content if block.type == "text")
        if any(suggestion in text for suggestion in BLOCKED):
            pytest.skip(f"YouTube is blocking this IP address: {text}")
        pytest.fail(text)
    assert result.structured_content is not None
    return result.structured_content


@pytest.mark.live
def test_tracks_and_a_transcript_in_parts(tmp_path: Path) -> None:
    server = build_server(Client(), Config(download_dir=tmp_path))

    tracks = call(server, "list_tracks", {"video": VIDEO})
    page = call(server, "get_transcript", {"video": VIDEO, "max_chars": 200})

    assert ("en", False) in [(t["language_code"], t["is_generated"]) for t in tracks["tracks"]]
    assert page["content"].startswith("[♪♪♪] ♪ We're no strangers to love ♪")
    assert page["next_offset"] is not None
    assert page["total_chars"] > 200


@pytest.mark.live
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


class Refused(Client):
    """A client whose YouTube refuses every transcript request with ``error``."""

    def __init__(self, error: UTMaxError) -> None:
        super().__init__(transport=FakeTransport())
        self.error = error

    def fetch(self, *args: Any, **options: Any) -> Any:
        raise self.error


def tool_error(name: str, error: UTMaxError) -> str:
    return f"Error executing tool {name}: {error} Suggestion: {error.suggestion}"


BLOCKS = [
    pytest.param(
        RequestBlocked("Sign in to confirm you\U00002019re not a bot", video_id=VIDEO),
        id="the bot check",
    ),
    pytest.param(IpBlocked("YouTube answered with a CAPTCHA page.", video_id=VIDEO), id="CAPTCHA"),
    pytest.param(
        IpBlocked("YouTube rate-limited the caption download (HTTP 429).", video_id=VIDEO),
        id="HTTP 429",
    ),
]


@pytest.mark.parametrize("error", BLOCKS)
def test_a_blocked_ip_address_skips_the_check(error: UTMaxError) -> None:
    server = build_server(Refused(error), Config())

    with pytest.raises(pytest.skip.Exception) as skipped:
        call(server, "get_transcript", {"video": VIDEO})

    assert str(skipped.value) == (
        f"YouTube is blocking this IP address: {tool_error('get_transcript', error)}"
    )


def test_any_other_error_still_fails_the_check() -> None:
    error = VideoUnavailable("This video is unavailable.", video_id=VIDEO)
    server = build_server(Refused(error), Config())

    with pytest.raises((pytest.fail.Exception, pytest.skip.Exception)) as outcome:
        call(server, "get_transcript", {"video": VIDEO})

    assert outcome.type is pytest.fail.Exception
    assert str(outcome.value) == tool_error("get_transcript", error)
