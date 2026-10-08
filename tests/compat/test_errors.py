"""The exceptions of utmax.compat: youtube-transcript-api 1.2.4's hierarchy and messages."""

from __future__ import annotations

from pathlib import Path

import pytest

from utmax.compat import _errors
from utmax.compat._errors import (
    AgeRestricted,
    CookieError,
    CookieInvalid,
    CookiePathInvalid,
    CouldNotRetrieveTranscript,
    FailedToCreateConsentCookie,
    InvalidVideoId,
    IpBlocked,
    NotTranslatable,
    PoTokenRequired,
    RequestBlocked,
    TranscriptsDisabled,
    TranslationLanguageNotAvailable,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeRequestFailed,
    YouTubeTranscriptApiException,
)
from utmax.compat.proxies import GenericProxyConfig, WebshareProxyConfig

INTRO = "\nCould not retrieve a transcript for the video https://www.youtube.com/watch?v=abc!"
REFERRAL = (
    "\n\nIf you are sure that the described cause is not responsible for this error and that "
    "a transcript should be retrievable, please create an issue at "
    "https://github.com/jdepoix/youtube-transcript-api/issues. Please add which version of "
    "youtube_transcript_api you are using and provide the information needed to replicate "
    "the error. Also make sure that there are no open issues which already describe your "
    "problem!"
)
SIMPLE = [
    (YouTubeDataUnparsable, "The data required to fetch the transcript is not parsable."),
    (VideoUnavailable, "The video is no longer available"),
    (InvalidVideoId, "You provided an invalid video id."),
    (RequestBlocked, "YouTube is blocking requests from your IP."),
    (IpBlocked, "YouTube is blocking requests from your IP."),
    (TranscriptsDisabled, "Subtitles are disabled for this video"),
    (AgeRestricted, "This video is age-restricted."),
    (NotTranslatable, "The requested language is not translatable"),
    (TranslationLanguageNotAvailable, "The requested translation language is not available"),
    (FailedToCreateConsentCookie, "Failed to automatically give consent to saving cookies"),
    (PoTokenRequired, "The requested video cannot be retrieved without a PO Token."),
]


def test_the_message_is_built_like_youtube_transcript_api() -> None:
    error = TranscriptsDisabled("abc")

    assert error.video_id == "abc"
    assert error.args == ()
    assert str(error) == (
        f"{INTRO} This is most likely caused by:\n\nSubtitles are disabled for this video{REFERRAL}"
    )


@pytest.mark.parametrize(("error_class", "cause"), SIMPLE)
def test_every_cause_follows_the_intro(
    error_class: type[CouldNotRetrieveTranscript], cause: str
) -> None:
    message = str(error_class("abc"))

    assert message.startswith(f"{INTRO} This is most likely caused by:\n\n{cause}")
    assert message.endswith(REFERRAL)
    assert issubclass(error_class, CouldNotRetrieveTranscript)


def test_a_transcript_error_without_a_cause_has_only_the_intro() -> None:
    assert str(CouldNotRetrieveTranscript("abc")) == INTRO


def test_request_failures_quote_the_http_error() -> None:
    error = YouTubeRequestFailed("abc", "500 Server Error: Internal Server Error")

    assert error.reason == "500 Server Error: Internal Server Error"
    assert "Request to YouTube failed: 500 Server Error: Internal Server Error" in str(error)


def test_unplayable_videos_list_the_reason_and_details() -> None:
    error = VideoUnplayable("abc", "Custom Reason", ["Sub Reason 1", "Sub Reason 2"])

    assert (error.reason, error.sub_reasons) == ("Custom Reason", ["Sub Reason 1", "Sub Reason 2"])
    assert (
        "The video is unplayable for the following reason: Custom Reason\n\n"
        "Additional Details:\n - Sub Reason 1\n - Sub Reason 2"
    ) in str(error)
    assert "No reason specified!" in str(VideoUnplayable("abc", None, []))


def test_blocks_explain_the_proxy_in_use() -> None:
    webshare = WebshareProxyConfig("user", "password")
    generic = GenericProxyConfig(http_url="http://localhost:8080")

    plain = RequestBlocked("abc")
    with_webshare = RequestBlocked("abc").with_proxy_config(webshare)
    with_generic = IpBlocked("abc").with_proxy_config(generic)

    assert plain.with_proxy_config(None) is plain
    assert "There are two things you can do to work around this" in str(plain)
    assert with_webshare._proxy_config is webshare
    assert "despite you using Webshare proxies" in str(with_webshare)
    assert "YouTube is blocking your requests, despite you using proxies" in str(with_generic)
    assert "Ways to work around this are explained" in str(IpBlocked("abc"))
    assert isinstance(with_generic, RequestBlocked)


def test_cookie_errors_name_the_file() -> None:
    assert str(CookiePathInvalid(Path("cookies.txt"))) == (
        "Can't load the provided cookie file: cookies.txt"
    )
    assert str(CookieInvalid("cookies.txt")) == (
        "The cookies provided are not valid (may have expired): cookies.txt"
    )
    assert issubclass(CookieError, YouTubeTranscriptApiException)
    assert not issubclass(CookieError, CouldNotRetrieveTranscript)


def test_the_names_of_version_0_6_still_work() -> None:
    assert _errors.TooManyRequests is IpBlocked
    assert _errors.NoTranscriptAvailable is TranscriptsDisabled
    assert _errors.CookiesInvalid is CookieInvalid
