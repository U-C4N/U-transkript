"""The utmax exception hierarchy.

Every error carries a one-sentence English ``suggestion`` telling the caller what to do next
and, when known, the ``video_id`` it concerns. Names mirror youtube-transcript-api where the
meaning is the same, which keeps migrations simple.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

__all__ = [
    "AgeRestricted",
    "FailedToCreateConsentCookie",
    "InvalidOption",
    "InvalidVideoId",
    "IpBlocked",
    "NetworkError",
    "NoTranscriptFound",
    "NotTranslatable",
    "PoTokenRequired",
    "RequestBlocked",
    "TranscriptsDisabled",
    "TranslationLanguageNotAvailable",
    "UTMaxError",
    "UnsupportedFormat",
    "VideoUnavailable",
    "VideoUnplayable",
    "YouTubeDataUnparsable",
    "YouTubeError",
    "YouTubeRequestFailed",
]


def _restore(cls: type[UTMaxError], message: str, state: dict[str, Any]) -> UTMaxError:
    error = cls.__new__(cls)
    Exception.__init__(error, message)
    error.__dict__.update(state)
    return error


class UTMaxError(Exception):
    """Base class of every error raised by utmax."""

    suggestion: str = "Read the error message for details."

    def __init__(
        self, message: str, *, video_id: str | None = None, suggestion: str | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.video_id = video_id
        if suggestion is not None:
            self.suggestion = suggestion

    def __str__(self) -> str:
        return self.message

    def __reduce__(self) -> tuple[Any, ...]:
        return (_restore, (type(self), self.message, dict(self.__dict__)))


class InvalidVideoId(UTMaxError, ValueError):
    """The input does not contain a YouTube video ID."""

    suggestion = "Pass a YouTube URL or an 11-character video ID."


class InvalidOption(UTMaxError, ValueError):
    """An option value, or a combination of options, is not supported."""

    suggestion = "Check the options passed to this call against the documentation."


class UnsupportedFormat(UTMaxError, ValueError):
    """The requested output format is unknown."""

    suggestion = "Use a .srt, .vtt, .json or .txt file name, or pass format=... explicitly."


class NetworkError(UTMaxError):
    """The network failed and retries did not help."""

    suggestion = "Check your internet connection, proxy settings and firewall, then try again."


class YouTubeError(UTMaxError):
    """YouTube refused or could not serve the request."""

    suggestion = "YouTube could not serve this request; try again later."


class VideoUnavailable(YouTubeError):
    """The video does not exist or was removed."""

    suggestion = "Check that the video ID is correct and that the video is still public."


class VideoUnplayable(YouTubeError):
    """YouTube will not play the video for this client."""

    suggestion = "Private, members-only and region-locked videos are not supported."

    def __init__(
        self,
        message: str,
        *,
        reason: str = "",
        sub_reasons: Sequence[str] = (),
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.reason = reason
        self.sub_reasons = tuple(sub_reasons)


class AgeRestricted(YouTubeError):
    """The video is age-restricted."""

    suggestion = "Age-restricted videos need a signed-in session, which utmax does not support."


class RequestBlocked(YouTubeError):
    """YouTube is blocking requests from this IP address."""

    suggestion = (
        "Use a proxy (Client(proxy=...)) with block_retries, and avoid cloud-provider IP addresses."
    )


class IpBlocked(RequestBlocked):
    """YouTube rate-limited this IP address (HTTP 429 or a CAPTCHA)."""

    suggestion = "Wait before retrying, or use a rotating residential proxy with block_retries."


class PoTokenRequired(YouTubeError):
    """YouTube requires a proof-of-origin token that utmax cannot produce."""

    suggestion = (
        "YouTube changed how captions are served; please report it at "
        "https://github.com/U-C4N/U-transkript/issues."
    )


class FailedToCreateConsentCookie(YouTubeError):
    """YouTube kept showing its cookie-consent page."""

    suggestion = "Try again later, or from a different region or proxy."


class YouTubeRequestFailed(YouTubeError):
    """YouTube answered with an unexpected HTTP status."""

    suggestion = "YouTube answered with an unexpected HTTP status; try again later."

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.status_code = status_code


class YouTubeDataUnparsable(YouTubeError):
    """YouTube returned data utmax could not understand."""

    suggestion = "YouTube may have changed its responses; please report it with the video ID."


class TranscriptsDisabled(YouTubeError):
    """The video has no subtitles at all."""

    suggestion = "The uploader disabled subtitles for this video, so there is nothing to fetch."


class NoTranscriptFound(YouTubeError):
    """No track matches the requested languages or filters."""

    suggestion = "Pick one of the available languages, or call utmax.list_tracks() to see them."

    def __init__(
        self,
        message: str,
        *,
        requested: Sequence[str] = (),
        available: Sequence[str] = (),
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.requested = tuple(requested)
        self.available = tuple(available)


class NotTranslatable(YouTubeError):
    """YouTube cannot translate this track."""

    suggestion = "YouTube cannot translate this track; use AI translation instead."


class TranslationLanguageNotAvailable(YouTubeError):
    """YouTube cannot translate into the requested language."""

    suggestion = "Use a language from TrackList.translation_languages, or use AI translation."

    def __init__(
        self,
        message: str,
        *,
        available: Sequence[str] = (),
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.available = tuple(available)
