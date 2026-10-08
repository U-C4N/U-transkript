"""The MCP tools through the SDK's in-memory client, over a faked YouTube."""

from __future__ import annotations

from typing import Any

import anyio
import pytest
from mcp import Client as MCPClient
from mcp.types import CallToolResult, Tool

from tests.helpers.browse import vr_page
from tests.helpers.fake_translator import FakeTranslator
from tests.helpers.fake_transport import FakeTransport, json_response
from tests.helpers.youtube import VIDEO_ID, standard_youtube
from utmax import Client
from utmax.adapters.providers.base import Translator
from utmax.mcp import server as mcp_server
from utmax.mcp.config import Config
from utmax.mcp.server import build_server
from utmax.transport import Transport

TOOLS = ["list_tracks", "get_transcript", "translate_transcript", "list_videos"]


class RecordingClient(Client):
    """A real Client whose translators are fakes; records the models it was asked for."""

    def __init__(self, transport: Transport) -> None:
        super().__init__(transport=transport)
        self.models: list[tuple[str, dict[str, Any]]] = []
        self.translators: list[FakeTranslator] = []

    def translator(self, model: str, **options: Any) -> Translator:
        self.models.append((model, options))
        self.translators.append(FakeTranslator())
        return self.translators[-1]


def call(server: Any, name: str, arguments: dict[str, Any]) -> CallToolResult:
    async def main() -> CallToolResult:
        async with MCPClient(server, raise_exceptions=True) as client:
            return await client.call_tool(name, arguments)

    return anyio.run(main)


def tools(server: Any) -> dict[str, Tool]:
    async def main() -> dict[str, Tool]:
        async with MCPClient(server, raise_exceptions=True) as client:
            return {tool.name: tool for tool in (await client.list_tools()).tools}

    return anyio.run(main)


def output(result: CallToolResult) -> dict[str, Any]:
    assert result.is_error is False, result.content
    assert result.structured_content is not None
    return result.structured_content


def error_text(result: CallToolResult) -> str:
    assert result.is_error is True
    return " ".join(block.text for block in result.content if block.type == "text")


def test_the_server_offers_four_tools() -> None:
    offered = tools(build_server(Client(transport=FakeTransport()), Config()))

    assert list(offered) == TOOLS
    assert all(tool.description for tool in offered.values())
    assert all(tool.output_schema for tool in offered.values())


def test_tool_arguments_are_described_and_bounded() -> None:
    offered = tools(build_server(Client(transport=FakeTransport()), Config()))

    transcript = offered["get_transcript"].input_schema
    assert transcript["required"] == ["video"]
    assert transcript["properties"]["video"]["description"].startswith("A YouTube video URL")
    assert transcript["properties"]["format"]["enum"] == ["txt", "srt", "vtt", "json", "pretty"]
    assert transcript["properties"]["source"]["enum"] == ["any", "manual", "generated"]
    assert offered["translate_transcript"].input_schema["required"] == ["video", "to"]
    limit = offered["list_videos"].input_schema["properties"]["limit"]
    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 5000, 50)


def test_the_tools_only_read() -> None:
    offered = tools(build_server(Client(transport=FakeTransport()), Config()))

    assert all(tool.annotations and tool.annotations.read_only_hint for tool in offered.values())


def test_list_tracks() -> None:
    server = build_server(Client(transport=standard_youtube()), Config())

    result = output(call(server, "list_tracks", {"video": f"https://youtu.be/{VIDEO_ID}"}))

    assert result["video"] == {
        "video_id": VIDEO_ID,
        "title": "Rick Astley - Never Gonna Give You Up (Official Video)",
        "channel": "Rick Astley",
        "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw",
        "duration_seconds": 213.0,
        "url": f"https://www.youtube.com/watch?v={VIDEO_ID}",
    }
    assert [(t["language_code"], t["is_generated"]) for t in result["tracks"]] == [
        ("en", False),
        ("en", True),
        ("de-DE", False),
        ("ja", False),
        ("pt-BR", False),
        ("es-419", False),
    ]


def test_get_transcript_in_every_format() -> None:
    server = build_server(Client(transport=standard_youtube(repeat=True)), Config())

    text = output(call(server, "get_transcript", {"video": VIDEO_ID}))
    srt = output(call(server, "get_transcript", {"video": VIDEO_ID, "format": "srt"}))
    auto = output(call(server, "get_transcript", {"video": VIDEO_ID, "source": "generated"}))
    german = output(call(server, "get_transcript", {"video": VIDEO_ID, "languages": ["de"]}))

    assert text["content"].startswith("[♪♪♪] ♪ We're no strangers to love")
    assert (text["language_code"], text["is_generated"], text["format"]) == ("en", False, "txt")
    assert text["title"].startswith("Rick Astley")
    assert (text["offset"], text["next_offset"], text["total_chars"]) == (
        0,
        None,
        len(text["content"]),
    )
    assert srt["content"].startswith("1\n00:00:01,360 --> 00:00:03,040\n")
    assert (auto["language"], auto["is_generated"]) == ("English (auto-generated)", True)
    assert german["language_code"] == "de-DE"


def test_long_transcripts_are_read_in_parts() -> None:
    server = build_server(Client(transport=standard_youtube(repeat=True)), Config())
    whole = output(call(server, "get_transcript", {"video": VIDEO_ID, "format": "srt"}))
    parts: list[str] = []
    offset: int | None = 0

    while offset is not None:
        page = output(
            call(
                server,
                "get_transcript",
                {"video": VIDEO_ID, "format": "srt", "offset": offset, "max_chars": 40},
            )
        )
        assert len(page["content"]) <= 40
        assert page["total_chars"] == whole["total_chars"]
        parts.append(page["content"])
        offset = page["next_offset"]

    assert "".join(parts) == whole["content"]
    assert all(part.endswith(("\n", " ")) for part in parts[:-1])


def test_a_part_without_a_line_or_word_end_is_cut_where_it_must() -> None:
    assert mcp_server._page("abcdefghij", 0, 4) == ("abcd", 4)
    assert mcp_server._page("ab cd ef", 2, 4) == (" cd ", 6)
    assert mcp_server._page("abc", 5, 10) == ("", None)


def test_errors_carry_a_suggestion() -> None:
    server = build_server(Client(transport=standard_youtube(repeat=True)), Config())

    invalid = error_text(call(server, "get_transcript", {"video": "not a video"}))
    missing = error_text(call(server, "get_transcript", {"video": VIDEO_ID, "languages": ["xx"]}))
    bounded = error_text(call(server, "list_videos", {"source": "PL" + "x" * 16, "limit": 0}))

    assert "Could not find a YouTube video ID in 'not a video'." in invalid
    assert "Suggestion: Pass a YouTube URL or an 11-character video ID." in invalid
    assert "No subtitles in xx match" in missing
    assert "Suggestion: Pick one of the available languages" in missing
    assert "limit" in bounded


def test_translation_needs_a_model() -> None:
    server = build_server(RecordingClient(standard_youtube()), Config())

    message = error_text(call(server, "translate_transcript", {"video": VIDEO_ID, "to": "tr"}))

    assert "No translation model is configured." in message
    assert "UTMAX_MODEL" in message


def test_translation_uses_the_model_and_its_base_url() -> None:
    client = RecordingClient(standard_youtube(repeat=True))
    config = Config(model="openai=llama3.1:8b", base_url="http://localhost:11434/v1")
    server = build_server(client, config)

    default = output(call(server, "translate_transcript", {"video": VIDEO_ID, "to": "tr"}))
    chosen = output(
        call(
            server,
            "translate_transcript",
            {"video": VIDEO_ID, "to": "tr", "model": "claude=claude-opus-5", "bilingual": True},
        )
    )

    assert client.models == [
        ("openai=llama3.1:8b", {"base_url": "http://localhost:11434/v1"}),
        ("claude=claude-opus-5", {}),
    ]
    assert default["content"].startswith("[♪♪♪] ♪ WE'RE NO STRANGERS TO LOVE")
    assert (default["language_code"], default["language"]) == ("tr", "Turkish")
    assert (default["translated_from"], default["translator"]) == ("en", "fake=echo-1")
    assert chosen["language_code"] == "en+tr"
    assert "♪ We're no strangers to love ♪\n♪ WE'RE NO STRANGERS" in chosen["content"]


def test_translation_instructions_reach_the_model() -> None:
    client = RecordingClient(standard_youtube(repeat=True))
    server = build_server(client, Config(model="claude=claude-opus-5"))

    output(
        call(
            server,
            "translate_transcript",
            {"video": VIDEO_ID, "to": "tr", "instructions": "Keep song titles in English."},
        )
    )

    assert client.models == [("claude=claude-opus-5", {})]
    assert [request["instructions"] for request in client.translators[0].requests] == [
        "Keep song titles in English."
    ]


def test_list_videos() -> None:
    transport = FakeTransport()
    page = vr_page("aaaaaaaaaaa", "bbbbbbbbbbb", count="2 videos")
    transport.add("POST", "/youtubei/v1/browse", json_response(page))
    server = build_server(Client(transport=transport), Config())

    result = output(call(server, "list_videos", {"source": "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"}))

    assert {key: value for key, value in result.items() if key != "videos"} == {
        "title": "A playlist",
        "source_id": "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI",
        "kind": "all",
        "count": 2,
    }
    assert result["videos"][1] == {
        "video_id": "bbbbbbbbbbb",
        "title": "bbbbbbbbbbb",
        "duration_seconds": None,
        "channel": "",
        "channel_id": "",
        "index": 2,
        "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb",
    }


def test_the_server_reads_the_environment_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str | None] = []

    def fake_client(*, proxy: str | None) -> RecordingClient:
        created.append(proxy)
        return RecordingClient(standard_youtube())

    monkeypatch.setattr(mcp_server, "Client", fake_client)
    monkeypatch.setenv("UTMAX_PROXY", "http://proxy.test:8080")
    monkeypatch.setenv("UTMAX_MODEL", "gemini=gemini-3-pro")

    server = build_server()

    assert created == ["http://proxy.test:8080"]
    assert list(tools(server)) == TOOLS


def test_tools_print_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    server = build_server(Client(transport=standard_youtube(repeat=True)), Config())

    call(server, "get_transcript", {"video": VIDEO_ID})
    call(server, "get_transcript", {"video": "not a video"})

    assert capsys.readouterr().out == ""
