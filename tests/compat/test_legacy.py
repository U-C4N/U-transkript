"""The class methods of youtube-transcript-api 0.6, as the 1.1 releases tested them."""

from __future__ import annotations

from typing import Any

import pytest

from tests.helpers.compat import RAW_DATA, VIDEO, compat_youtube
from tests.helpers.fake_transport import FakeTransport
from utmax.compat import _bridge
from utmax.compat._api import YouTubeTranscriptApi
from utmax.compat._errors import InvalidVideoId, NoTranscriptFound, VideoUnavailable
from utmax.compat.proxies import GenericProxyConfig, WebshareProxyConfig

FORMATTED = [dict(line) for line in RAW_DATA]
FORMATTED[1]["text"] = 'today we <i>really</i> build "it"'


@pytest.fixture
def youtube(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """Fake YouTube behind utmax's own transport; returns the proxies each instance used."""
    proxies: list[str | None] = []

    def fake_urllib(*, proxy: str | None, timeout: float) -> FakeTransport:
        proxies.append(proxy)
        return compat_youtube()

    monkeypatch.setattr(_bridge, "UrllibTransport", fake_urllib)
    return proxies


@pytest.mark.usefixtures("youtube")
def test_get_transcript__deprecated() -> None:
    with pytest.deprecated_call() as warnings:
        transcript = YouTubeTranscriptApi.get_transcript(VIDEO)

    assert transcript == RAW_DATA
    assert str(warnings[0].message).startswith("`get_transcript` is deprecated")


@pytest.mark.usefixtures("youtube")
def test_get_transcript_formatted__deprecated() -> None:
    with pytest.deprecated_call():
        transcript = YouTubeTranscriptApi.get_transcript(VIDEO, preserve_formatting=True)

    assert transcript == FORMATTED


@pytest.mark.usefixtures("youtube")
def test_list_transcripts__deprecated() -> None:
    with pytest.deprecated_call(match="Use the `list` method instead!"):
        transcript_list = YouTubeTranscriptApi.list_transcripts(VIDEO)

    assert transcript_list.find_manually_created_transcript(["cs"]).is_generated is False
    assert transcript_list.find_generated_transcript(["en"]).is_generated is True
    with pytest.raises(NoTranscriptFound):
        transcript_list.find_generated_transcript(["cs"])


@pytest.mark.usefixtures("youtube")
def test_list_transcripts__url_as_video_id__deprecated() -> None:
    with pytest.deprecated_call(), pytest.raises(InvalidVideoId):
        YouTubeTranscriptApi.list_transcripts(
            f"https://www.youtube.com/youtubei/v1/player?v={VIDEO}"
        )


@pytest.mark.usefixtures("youtube")
def test_get_transcript__exception_if_language_unavailable__deprecated() -> None:
    with pytest.deprecated_call(), pytest.raises(NoTranscriptFound):
        YouTubeTranscriptApi.get_transcript(VIDEO, languages=["cz"])


def test_get_transcript__with_proxy__deprecated(youtube: list[str | None]) -> None:
    proxies = {"http": "http://localhost:8080", "https": "http://localhost:8080"}

    with pytest.deprecated_call():
        transcript = YouTubeTranscriptApi.get_transcript(VIDEO, proxies=proxies)

    assert transcript == RAW_DATA
    assert youtube == ["http://localhost:8080"]


def test_get_transcript__with_proxy_config__deprecated(youtube: list[str | None]) -> None:
    proxy_config = WebshareProxyConfig("user", "password")

    with pytest.deprecated_call():
        transcript = YouTubeTranscriptApi.get_transcript(VIDEO, proxies=proxy_config)

    assert transcript == RAW_DATA
    assert youtube == ["http://user-rotate:password@p.webshare.io:80/"]


def test_get_transcript__cookies_are_ignored_with_a_warning(youtube: list[str | None]) -> None:
    with (
        pytest.deprecated_call(),
        pytest.warns(UserWarning, match="Cookie authentication is not supported"),
    ):
        transcript = YouTubeTranscriptApi.get_transcript(VIDEO, cookies="cookies.txt")

    assert transcript == RAW_DATA
    assert youtube == [None]


def test_get_transcript__video_id_must_be_a_string() -> None:
    with pytest.deprecated_call(), pytest.raises(AssertionError, match="must be a string"):
        YouTubeTranscriptApi.get_transcript(["abc"])  # type: ignore[arg-type]


def test_get_transcripts__assertionerror_if_input_not_list__deprecated() -> None:
    with pytest.deprecated_call(), pytest.raises(AssertionError):
        YouTubeTranscriptApi.get_transcripts("video_id_1")  # type: ignore[arg-type]


def mock_get_transcript(
    monkeypatch: pytest.MonkeyPatch, *, fail: frozenset[str] = frozenset()
) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    def get_transcript(*args: Any) -> list[dict[str, Any]]:
        calls.append(args)
        if args[0] in fail:
            raise VideoUnavailable(args[0])
        return [{"text": args[0], "start": 0.0, "duration": 1.0}]

    monkeypatch.setattr(YouTubeTranscriptApi, "get_transcript", get_transcript)
    return calls


def test_get_transcripts__deprecated(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = mock_get_transcript(monkeypatch)
    languages = ["de", "en"]

    with pytest.deprecated_call(match="`get_transcripts` is deprecated"):
        data, failed = YouTubeTranscriptApi.get_transcripts(
            ["video_id_1", "video_id_2"], languages=languages
        )

    assert calls == [
        ("video_id_1", languages, None, None, False),
        ("video_id_2", languages, None, None, False),
    ]
    assert list(data) == ["video_id_1", "video_id_2"]
    assert failed == []


def test_get_transcripts__stop_on_error__deprecated(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = mock_get_transcript(monkeypatch, fail={"video_id_1"})

    with pytest.deprecated_call(), pytest.raises(VideoUnavailable):
        YouTubeTranscriptApi.get_transcripts(["video_id_1", "video_id_2"])

    assert len(calls) == 1


def test_get_transcripts__continue_on_error__deprecated(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = mock_get_transcript(monkeypatch, fail={"video_id_1"})

    with pytest.deprecated_call():
        data, failed = YouTubeTranscriptApi.get_transcripts(
            ["video_id_1", "video_id_2"], continue_after_error=True
        )

    assert calls == [
        ("video_id_1", ("en",), None, None, False),
        ("video_id_2", ("en",), None, None, False),
    ]
    assert list(data) == ["video_id_2"]
    assert failed == ["video_id_1"]


def test_get_transcripts__with_cookies_and_proxies__deprecated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = mock_get_transcript(monkeypatch)
    proxies = GenericProxyConfig(http_url="http://localhost:8080")

    with pytest.deprecated_call():
        YouTubeTranscriptApi.get_transcripts(
            [VIDEO], proxies=proxies, cookies="cookies.txt", preserve_formatting=True
        )

    assert calls == [(VIDEO, ("en",), proxies, "cookies.txt", True)]
