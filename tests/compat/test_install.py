"""utmax.compat.install(): code that imports youtube_transcript_api runs on utmax."""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import utmax.compat
from tests.helpers.compat import RAW_DATA, VIDEO, compat_youtube
from tests.helpers.fake_transport import FakeTransport
from utmax.compat import _bridge, formatters, proxies

MODULES = ("", "._api", "._errors", "._settings", "._transcripts", ".formatters", ".proxies")
LOADER = '''
def load(video_id):
    """Like LangChain's YouTube loader: import youtube_transcript_api when needed."""
    from youtube_transcript_api import NoTranscriptFound, YouTubeTranscriptApi
    from youtube_transcript_api.formatters import TextFormatter

    try:
        transcript = YouTubeTranscriptApi().fetch(video_id, languages=["en"])
    except NoTranscriptFound:
        return None
    return TextFormatter().format_transcript(transcript)
'''


def registered() -> dict[str, Any]:
    return {
        name: module
        for name, module in sys.modules.items()
        if name.partition(".")[0] == "youtube_transcript_api"
    }


@pytest.fixture(autouse=True)
def restore_sys_modules() -> Iterator[None]:
    before = registered()
    yield
    for name in registered():
        del sys.modules[name]
    sys.modules.update(before)


def test_install_registers_every_module() -> None:
    utmax.compat.install()

    assert set(registered()) == {f"youtube_transcript_api{suffix}" for suffix in MODULES}
    assert importlib.import_module("youtube_transcript_api") is utmax.compat
    assert importlib.import_module("youtube_transcript_api.formatters") is formatters
    assert importlib.import_module("youtube_transcript_api.proxies") is proxies


def test_imports_give_utmax_compat_classes() -> None:
    utmax.compat.install()

    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import NoTranscriptFound
    from youtube_transcript_api.proxies import WebshareProxyConfig

    assert YouTubeTranscriptApi is utmax.compat.YouTubeTranscriptApi
    assert NoTranscriptFound is utmax.compat.NoTranscriptFound
    assert WebshareProxyConfig is proxies.WebshareProxyConfig


def test_install_again_changes_nothing() -> None:
    utmax.compat.install()
    first = registered()

    utmax.compat.install()

    assert registered() == first


def test_install_replaces_a_youtube_transcript_api_imported_before() -> None:
    sys.modules["youtube_transcript_api"] = types.ModuleType("youtube_transcript_api")

    utmax.compat.install()

    assert sys.modules["youtube_transcript_api"] is utmax.compat


def test_a_library_that_imports_youtube_transcript_api_runs_on_utmax(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "fake_loader.py"
    path.write_text(LOADER, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("fake_loader", path)
    assert spec is not None
    assert spec.loader is not None
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)

    def fake_urllib(*, proxy: str | None, timeout: float) -> FakeTransport:
        return compat_youtube()

    monkeypatch.setattr(_bridge, "UrllibTransport", fake_urllib)
    utmax.compat.install()

    assert loader.load(VIDEO) == "\n".join(line["text"] for line in RAW_DATA)
