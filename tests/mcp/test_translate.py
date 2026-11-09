"""Translation on the server: UTMAX_TRANSLATOR, translate_to, and what the assistant is told."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client as MCPClient
from mcp.types import CallToolResult

from tests.helpers.downloads import FakeYouTube, read_movie
from tests.helpers.fake_translator import FakeTranslator
from tests.helpers.youtube import VIDEO_ID
from utmax import Client
from utmax.errors import (
    InvalidModelSpec,
    InvalidOption,
    ProviderAuthError,
    ProviderNotInstalled,
)
from utmax.mcp import server as mcp_server
from utmax.mcp.config import Config
from utmax.mcp.server import build_server

MODEL = "gemini=gemini-3.8-flash"


def call(server: Any, name: str, arguments: dict[str, Any]) -> CallToolResult:
    async def main() -> CallToolResult:
        async with MCPClient(server, raise_exceptions=True) as client:
            return await client.call_tool(name, arguments)

    return anyio.run(main)


def output(result: CallToolResult) -> dict[str, Any]:
    assert result.is_error is False, result.content
    assert result.structured_content is not None
    return result.structured_content


def error_text(result: CallToolResult) -> str:
    assert result.is_error is True
    return " ".join(block.text for block in result.content if block.type == "text")


class Translating:
    """A client whose translator is a FakeTranslator named like the configured model."""

    def __init__(self, youtube: FakeYouTube) -> None:
        self.client = Client(transport=youtube)
        self.made: list[tuple[str, dict[str, Any]]] = []
        self.fake = FakeTranslator(name=MODEL)

        def translator(model: str, **options: Any) -> FakeTranslator:
            self.made.append((model, options))
            return self.fake

        self.client.translator = translator  # type: ignore[method-assign]


def test_the_settings_name_a_model_and_a_fast_effort() -> None:
    config = Config.from_env({"UTMAX_TRANSLATOR": " Gemini = gemini-3.8-flash "})
    assert (config.translator, config.translator_effort) == (MODEL, "low")
    config = Config.from_env(
        {"UTMAX_TRANSLATOR": "grok=grok-4.7", "UTMAX_TRANSLATOR_EFFORT": "xhigh"}
    )
    assert (config.translator, config.translator_effort) == ("grok=grok-4.7", "xhigh")
    config = Config.from_env({"UTMAX_TRANSLATOR": MODEL, "UTMAX_TRANSLATOR_EFFORT": "default"})
    assert config.translator_effort is None
    assert Config.from_env({}).translator is None


def test_bad_settings_stop_the_server_at_startup() -> None:
    with pytest.raises(InvalidModelSpec, match="choose one of"):
        Config.from_env({"UTMAX_TRANSLATOR": "deepl=pro"})
    with pytest.raises(InvalidOption, match="low, medium, high, not 'xhigh'"):
        Config.from_env({"UTMAX_TRANSLATOR": MODEL, "UTMAX_TRANSLATOR_EFFORT": "xhigh"})


def test_the_assistant_is_told_to_let_the_server_translate_only_when_it_can() -> None:
    assert mcp_server.instructions(None) == mcp_server.INSTRUCTIONS
    told = mcp_server.instructions(MODEL)
    assert told.startswith(mcp_server.INSTRUCTIONS)
    assert f"translates subtitles itself with {MODEL}" in told
    assert "pass translate_to" in told


def test_download_embeds_the_servers_translations_first_shown(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    translating = Translating(youtube)
    server = build_server(translating.client, Config(download_dir=tmp_path, translator=MODEL))

    result = output(call(server, "download", {"video": VIDEO_ID, "translate_to": ["tr", "de"]}))

    assert result["embedded_subtitles"] == ["tr", "de"]
    tracks = read_movie(Path(result["path"])).tracks[2:]
    assert [(track.extended_language, track.name, track.flags & 1) for track in tracks] == [
        ("tr", f"Turkish (AI: {MODEL})", 1),
        ("de", f"German (AI: {MODEL})", 0),
    ]
    assert translating.made == [(MODEL, {"effort": "low"})]
    assert translating.fake.requests  # the server, not the assistant, translated


def test_the_translator_is_made_once_and_kept(tmp_path: Path) -> None:
    translating = Translating(FakeYouTube())
    server = build_server(translating.client, Config(download_dir=tmp_path, translator=MODEL))
    output(call(server, "save_subtitles", {"video": VIDEO_ID, "translate_to": "tr"}))
    output(call(server, "save_subtitles", {"video": VIDEO_ID, "translate_to": "de"}))
    assert len(translating.made) == 1


def test_save_subtitles_saves_the_servers_translation(tmp_path: Path) -> None:
    translating = Translating(FakeYouTube())
    server = build_server(translating.client, Config(download_dir=tmp_path, translator=MODEL))

    result = output(call(server, "save_subtitles", {"video": VIDEO_ID, "translate_to": "tr"}))

    assert (result["language_code"], result["path"].endswith(".tr.srt")) == ("tr", True)
    text = Path(result["path"]).read_text(encoding="utf-8")
    assert text.isupper() or any(line.isupper() for line in text.splitlines() if line.strip())


def test_without_a_translator_translate_to_is_a_clear_tool_error(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    server = build_server(Client(transport=youtube), Config(download_dir=tmp_path))

    message = error_text(call(server, "download", {"video": VIDEO_ID, "translate_to": ["tr"]}))

    assert "no translator" in message
    assert "UTMAX_TRANSLATOR" in message
    assert youtube.media.requests == []


def test_translated_srt_and_translate_to_together_are_refused(tmp_path: Path) -> None:
    translating = Translating(FakeYouTube())
    server = build_server(translating.client, Config(download_dir=tmp_path, translator=MODEL))
    srt = "1\n00:00:01,000 --> 00:00:02,000\nMerhaba\n"
    arguments = {
        "video": VIDEO_ID,
        "translated_srt": srt,
        "translated_language": "tr",
        "translate_to": "tr",
    }
    assert "not both" in error_text(call(server, "save_subtitles", arguments))


def test_a_missing_provider_extra_names_the_uvx_command(tmp_path: Path) -> None:
    client = Client(transport=FakeYouTube())

    def missing(model: str, **options: Any) -> Any:
        raise ProviderNotInstalled(
            "The gemini translator needs google.genai.", provider="gemini", extra="gemini"
        )

    client.translator = missing  # type: ignore[method-assign]
    server = build_server(client, Config(download_dir=tmp_path, translator=MODEL))

    message = error_text(call(server, "save_subtitles", {"video": VIDEO_ID, "translate_to": "tr"}))

    assert 'uvx --from "u-transcript-max[mcp,gemini]@latest" utmax-mcp' in message


def test_a_missing_key_says_where_the_server_reads_it(tmp_path: Path) -> None:
    client = Client(transport=FakeYouTube())

    def keyless(model: str, **options: Any) -> Any:
        raise ProviderAuthError(
            "No Gemini API key was found.",
            provider="gemini",
            suggestion="Pass api_key=... or set the GEMINI_API_KEY environment variable.",
        )

    client.translator = keyless  # type: ignore[method-assign]
    server = build_server(client, Config(download_dir=tmp_path, translator=MODEL))

    message = error_text(call(server, "save_subtitles", {"video": VIDEO_ID, "translate_to": "tr"}))

    assert "GEMINI_API_KEY" in message
    assert "MCP server's environment" in message
