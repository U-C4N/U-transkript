"""The MCP tools through the SDK's in-memory client, over a faked YouTube."""

from __future__ import annotations

import itertools
import json
import threading
from typing import Any

import anyio
import pytest
from mcp import Client as MCPClient
from mcp.types import CallToolResult, Tool

from tests.helpers.browse import CHANNEL_ID, vr_page
from tests.helpers.bulk import IDS, TITLES, ManyVideos
from tests.helpers.fake_translator import FakeTranslator, Script, echo
from tests.helpers.fake_transport import FakeTransport, json_response
from tests.helpers.youtube import ASR_JSON3, VIDEO_ID, player_payload, standard_youtube
from utmax import Client
from utmax.adapters.providers.base import Translator
from utmax.mcp import server as mcp_server
from utmax.mcp.config import Config
from utmax.mcp.server import build_server
from utmax.transport import Transport

TOOLS = ["list_tracks", "get_transcript", "translate_transcript", "list_videos", "download"]
PLAYLIST = "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"


class RecordingClient(Client):
    """A real Client whose translators are fakes; records the models it was asked for."""

    def __init__(self, transport: Transport, script: Script = echo) -> None:
        super().__init__(transport=transport)
        self.models: list[tuple[str, dict[str, Any]]] = []
        self.translators: list[FakeTranslator] = []
        self._script = script

    def translator(self, model: str, **options: Any) -> Translator:
        self.models.append((model, options))
        self.translators.append(FakeTranslator(self._script))
        return self.translators[-1]

    @property
    def model_requests(self) -> int:
        """How many times the models were asked, however many translators were made."""
        return sum(len(translator.requests) for translator in self.translators)


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


def test_the_server_offers_five_tools() -> None:
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
    offset = transcript["properties"]["offset"]
    assert (offset["type"], offset["minimum"], offset["default"]) == ("integer", 0, 0)
    max_chars = transcript["properties"]["max_chars"]
    assert max_chars["anyOf"] == [{"type": "integer", "minimum": 1}, {"type": "null"}]
    assert max_chars["default"] is None
    translation = offered["translate_transcript"].input_schema["properties"]
    assert (translation["offset"], translation["max_chars"]) == (offset, max_chars)
    limit = offered["list_videos"].input_schema["properties"]["limit"]
    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 5000, 50)
    download = offered["download"].input_schema["properties"]
    assert list(download) == ["video", "format", "quality", "subtitles", "subtitle_mode"]
    assert download["format"]["enum"] == ["mp4", "mov", "m4a", "mp3"]


def test_only_download_changes_anything() -> None:
    offered = tools(build_server(Client(transport=FakeTransport()), Config()))

    hints = {
        name: tool.annotations.read_only_hint for name, tool in offered.items() if tool.annotations
    }
    assert hints == {
        "list_tracks": True,
        "get_transcript": True,
        "translate_transcript": True,
        "list_videos": True,
        "download": False,
    }


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
    empty = error_text(call(server, "get_transcript", {"video": VIDEO_ID, "max_chars": 0}))
    negative = error_text(call(server, "get_transcript", {"video": VIDEO_ID, "offset": -1}))

    assert "Could not find a YouTube video ID in 'not a video'." in invalid
    assert "Suggestion: Pass a YouTube URL or an 11-character video ID." in invalid
    assert "No subtitles in xx match" in missing
    assert "Suggestion: Pick one of the available languages" in missing
    assert "limit" in bounded
    assert "max_chars" in empty
    assert "offset" in negative


def test_translation_needs_a_model() -> None:
    server = build_server(RecordingClient(standard_youtube()), Config())

    message = error_text(call(server, "translate_transcript", {"video": VIDEO_ID, "to": "tr"}))

    assert "No translation model is configured." in message
    assert "UTMAX_MODEL" in message


def test_a_model_that_cannot_be_used_fails_before_any_request() -> None:
    transport = FakeTransport()
    server = build_server(Client(transport=transport), Config())

    malformed = error_text(
        call(server, "translate_transcript", {"video": VIDEO_ID, "to": "tr", "model": "nonsense"})
    )
    unknown = error_text(
        call(server, "translate_transcript", {"video": VIDEO_ID, "to": "tr", "model": "acme=foo"})
    )

    assert "The model 'nonsense' is not \"provider=model-id\"" in malformed
    assert "Unknown provider 'acme' in 'acme=foo'" in unknown
    for message in (malformed, unknown):
        assert 'Suggestion: Pass model="provider=model-id", where provider is claude' in message
    assert transport.requests == []


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


def test_a_translation_is_made_once_and_read_in_parts() -> None:
    answers = itertools.count(1)

    def moody(request: dict[str, Any]) -> str:
        mood = "!" * next(answers)  # a real model words every answer differently
        items = [
            {"id": item["id"], "text": item["text"].upper() + mood} for item in request["items"]
        ]
        return json.dumps({"items": items})

    client = RecordingClient(standard_youtube(repeat=True), moody)
    server = build_server(client, Config(model="claude=claude-opus-5"))
    arguments = {"video": VIDEO_ID, "to": "tr", "format": "srt"}
    whole = output(call(server, "translate_transcript", arguments))
    parts: list[str] = []
    offset: int | None = 0

    while offset is not None:
        page = output(
            call(
                server,
                "translate_transcript",
                {**arguments, "offset": offset, "max_chars": 40},
            )
        )
        assert page["total_chars"] == whole["total_chars"]
        parts.append(page["content"])
        offset = page["next_offset"]

    assert len(parts) > 2
    assert "".join(parts) == whole["content"]
    assert (len(client.translators), client.model_requests) == (1, 1)


def test_a_translation_is_reused_only_for_the_same_request() -> None:
    client = RecordingClient(ManyVideos())
    server = build_server(client, Config(model="claude=claude-opus-5"))

    def translate(**changes: Any) -> int:
        output(call(server, "translate_transcript", {"video": VIDEO_ID, "to": "tr", **changes}))
        return client.model_requests

    assert translate() == 1
    assert translate(video=f"https://youtu.be/{VIDEO_ID}", format="vtt", bilingual=True) == 1
    assert translate(video=IDS[1]) == 2
    assert translate(to="de") == 3
    assert translate(instructions="Keep song titles in English.") == 4
    assert translate(languages=["de"]) == 5
    assert translate(model="gemini=gemini-3-pro") == 6
    assert translate(to="de") == 6
    german = output(
        call(server, "translate_transcript", {"video": VIDEO_ID, "to": "tr", "languages": ["de"]})
    )
    assert (german["translated_from"], client.model_requests) == ("de-DE", 6)
    assert [model for model, _ in client.models] == ["claude=claude-opus-5", "gemini=gemini-3-pro"]


def test_reading_in_parts_fetches_the_captions_once() -> None:
    youtube = ManyVideos()
    server = build_server(RecordingClient(youtube), Config(model="claude=claude-opus-5"))
    arguments = {"video": VIDEO_ID, "format": "srt", "max_chars": 40}

    link = f"https://youtu.be/{VIDEO_ID}"
    first = output(call(server, "get_transcript", arguments))
    second = output(
        call(server, "get_transcript", {**arguments, "video": link, "offset": first["next_offset"]})
    )
    translated = output(call(server, "translate_transcript", {"video": VIDEO_ID, "to": "tr"}))
    other = output(call(server, "get_transcript", {"video": IDS[1]}))

    assert second["offset"] == first["next_offset"] > 0
    assert translated["translated_from"] == "en"
    assert other["title"] == TITLES[IDS[1]]
    assert youtube.players == [VIDEO_ID, IDS[1]]


def test_the_memory_forgets_the_value_used_longest_ago() -> None:
    read = mcp_server._Memory[str](2)
    read.put("a", "first")
    read.put("b", "second")
    read.get("a")  # a was used last, so b goes first
    read.put("c", "third")
    written = mcp_server._Memory[str](2)
    written.put("a", "first")
    written.put("b", "second")
    written.put("a", "newer")  # replaces the value and counts as used
    written.put("c", "third")

    assert [read.get(key) for key in "abc"] == ["first", None, "third"]
    assert [written.get(key) for key in "abc"] == ["newer", None, "third"]


def test_the_memory_is_safe_to_share_between_threads() -> None:
    memory = mcp_server._Memory[str](2)
    memory.put("a", "first")
    workers = [
        threading.Thread(target=lambda: memory.get("a")),
        threading.Thread(target=lambda: memory.put("b", "second")),
    ]

    with memory._lock:  # a reader and a writer wait for whoever is using the memory
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(0.2)
        waiting = [worker.is_alive() for worker in workers]
    for worker in workers:
        worker.join()

    assert waiting == [True, True]
    assert memory.get("b") == "second"


def test_a_transcript_is_not_reused_for_another_kind_of_track() -> None:
    transport = FakeTransport()
    tracks = (("en", "English (auto-generated)", True),)
    player = json_response(player_payload(tracks=tracks))
    transport.add("POST", "/youtubei/v1/player", player, repeat=True)
    transport.add("GET", "kind=asr", json_response(ASR_JSON3), repeat=True)
    server = build_server(Client(transport=transport), Config())

    anything = output(call(server, "get_transcript", {"video": VIDEO_ID}))
    manual = error_text(call(server, "get_transcript", {"video": VIDEO_ID, "source": "manual"}))

    assert anything["is_generated"] is True
    assert "No subtitles match the filters" in manual


def test_list_videos() -> None:
    transport = FakeTransport()
    page = vr_page("aaaaaaaaaaa", "bbbbbbbbbbb", count="2 videos")
    transport.add("POST", "/youtubei/v1/browse", json_response(page))
    server = build_server(Client(transport=transport), Config())

    result = output(call(server, "list_videos", {"source": PLAYLIST}))

    assert {key: value for key, value in result.items() if key != "videos"} == {
        "title": "A playlist",
        "source_id": PLAYLIST,
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


def test_list_videos_stops_at_the_limit() -> None:
    transport = FakeTransport()
    page = vr_page("aaaaaaaaaaa", "bbbbbbbbbbb", count="2 videos")
    transport.add("POST", "/youtubei/v1/browse", json_response(page))
    server = build_server(Client(transport=transport), Config())

    result = output(call(server, "list_videos", {"source": PLAYLIST, "limit": 1}))

    assert [video["video_id"] for video in result["videos"]] == ["aaaaaaaaaaa"]
    assert result["count"] == 2


def test_list_videos_takes_the_kind_of_a_channel_and_refuses_it_for_a_playlist() -> None:
    transport = FakeTransport()
    page = vr_page("aaaaaaaaaaa", count="1 video")
    transport.add("POST", "/youtubei/v1/browse", json_response(page))
    server = build_server(Client(transport=transport), Config())

    shorts = output(call(server, "list_videos", {"source": CHANNEL_ID, "kind": "shorts"}))
    refused = error_text(call(server, "list_videos", {"source": PLAYLIST, "kind": "videos"}))

    assert (shorts["kind"], shorts["source_id"]) == ("shorts", f"UUSH{CHANNEL_ID[2:]}")
    assert refused.endswith("Suggestion: Leave kind out for playlists.")
    assert len(transport.requests) == 1  # the refusal came before any request


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
