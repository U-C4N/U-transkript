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
    "DownloadCancelled",
    "DownloadError",
    "DownloadIncomplete",
    "FFmpegError",
    "FFmpegFailed",
    "FFmpegNotFound",
    "FailedToCreateConsentCookie",
    "FormatNotAvailable",
    "InvalidModelSpec",
    "InvalidOption",
    "InvalidVideoId",
    "IpBlocked",
    "MissingExtra",
    "MuxError",
    "NetworkError",
    "NoTranscriptFound",
    "NotTranslatable",
    "OutputExists",
    "PoTokenRequired",
    "ProviderAuthError",
    "ProviderError",
    "ProviderNotInstalled",
    "ProviderRateLimited",
    "RequestBlocked",
    "StreamForbidden",
    "TranscriptsDisabled",
    "TranslationError",
    "TranslationLanguageNotAvailable",
    "TranslationMismatch",
    "TranslationRefused",
    "UTMaxError",
    "UnsupportedFormat",
    "VideoUnavailable",
    "VideoUnplayable",
    "YouTubeDataUnparsable",
    "YouTubeError",
    "YouTubeRequestFailed",
]


def _install_hint(extra: str) -> str:
    return f'Install it with pip install "u-transcript-max[{extra}]".'


def _restore(cls: type[UTMaxError], message: str, state: dict[str, Any]) -> UTMaxError:
    error = cls.__new__(cls)
    super(UTMaxError, error).__init__(message)  # also sets ImportError.msg for MissingExtra
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


class InvalidModelSpec(UTMaxError, ValueError):
    """A translator model string is not ``"provider=model-id"``."""

    suggestion = (
        'Pass model="provider=model-id", where provider is claude, openai, gemini or openrouter.'
    )


class InvalidOption(UTMaxError, ValueError):
    """An option value, or a combination of options, is not supported."""

    suggestion = "Check the options passed to this call against the documentation."


class UnsupportedFormat(UTMaxError, ValueError):
    """The requested output format is unknown."""

    suggestion = "Use a .srt, .vtt, .json or .txt file name, or pass format=... explicitly."


class MissingExtra(UTMaxError, ImportError):
    """An optional dependency (a pip "extra") is not installed."""

    suggestion = 'Install the optional dependency with pip install "u-transcript-max[<extra>]".'

    def __init__(
        self,
        message: str,
        *,
        extra: str,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion or _install_hint(extra))
        self.extra = extra


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


class DownloadError(UTMaxError):
    """Downloading or assembling a video or audio file failed."""

    suggestion = "The download failed; check your connection and disk space, then try again."


class MuxError(DownloadError):
    """The downloaded streams could not be combined into the requested file."""

    suggestion = (
        "The streams could not be combined; try another format, or report it with the video ID."
    )


class FormatNotAvailable(DownloadError):
    """No stream of the video fits the requested file type and quality."""

    suggestion = (
        'Try quality="compat" or another file type; live streams can be downloaded after they end.'
    )

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


class StreamForbidden(DownloadError):
    """YouTube kept refusing a stream (HTTP 403) even with fresh URLs."""

    suggestion = (
        "Stream URLs only work from the IP address that requested them: avoid rotating proxies "
        "and VPN switches during a download, and try Client(force_ipv4=True)."
    )

    def __init__(
        self,
        message: str,
        *,
        itag: int,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.itag = itag


class DownloadIncomplete(DownloadError):
    """A stream could not be downloaded completely."""

    suggestion = "Run the same download again; finished parts are kept and it resumes."


class DownloadCancelled(DownloadError):
    """The download was stopped through its ``cancel`` event."""

    suggestion = "Run the same download again to resume where it stopped."


class OutputExists(DownloadError):
    """The target file (or a subtitle file next to it) already exists."""

    suggestion = "Pass overwrite=True to replace it, or choose another file name."


class FFmpegError(DownloadError):
    """ffmpeg, which utmax needs only for MP3 files, failed."""

    suggestion = "Check your ffmpeg installation, or download .m4a audio, which needs no ffmpeg."


class FFmpegNotFound(FFmpegError):
    """No usable ffmpeg executable was found."""

    suggestion = (
        "Install ffmpeg (winget install Gyan.FFmpeg | brew install ffmpeg | apt install ffmpeg), "
        'or pass ffmpeg="/path/to/ffmpeg".'
    )


class FFmpegFailed(FFmpegError):
    """ffmpeg exited with an error."""

    suggestion = "ffmpeg could not convert the audio; see stderr_tail, or download .m4a instead."

    def __init__(
        self,
        message: str,
        *,
        returncode: int,
        stderr_tail: str,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.returncode = returncode
        self.stderr_tail = stderr_tail


class TranslationError(UTMaxError):
    """AI translation failed."""

    suggestion = "Check the provider, the model ID and your API key, then try again."

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.provider = provider


class ProviderNotInstalled(TranslationError, MissingExtra):
    """The official SDK of the chosen translation provider is not installed."""

    suggestion = 'Install the provider SDK with pip install "u-transcript-max[<extra>]".'

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        extra: str,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        # The two parents take different keyword arguments, so skip their constructors.
        UTMaxError.__init__(
            self, message, video_id=video_id, suggestion=suggestion or _install_hint(extra)
        )
        self.provider = provider
        self.extra = extra


class ProviderAuthError(TranslationError):
    """The provider rejected the API key."""

    suggestion = "Check the API key passed to the translator or set in the environment."


class ProviderRateLimited(TranslationError):
    """The provider rate-limited the request or the account ran out of quota."""

    suggestion = "Wait and retry with lower concurrency, or check the provider account's quota."


class ProviderError(TranslationError):
    """The provider answered with an error."""

    suggestion = "The provider reported an error; check the model ID and try again later."

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, provider=provider, video_id=video_id, suggestion=suggestion)
        self.status_code = status_code


class TranslationRefused(TranslationError):
    """The model refused to translate the text."""

    suggestion = "The model declined this text; try another model or provider."


class TranslationMismatch(TranslationError):
    """The model kept returning output that does not match the requested lines."""

    suggestion = "The model returned unusable output; retry, or use a more capable model."

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        ids: Sequence[int],
        raw_excerpt: str,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, provider=provider, video_id=video_id, suggestion=suggestion)
        self.ids = tuple(ids)
        self.raw_excerpt = raw_excerpt
