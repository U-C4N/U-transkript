from __future__ import annotations


class TranscriptRetrievalError(Exception):
    """
    Base exception for transcript retrieval errors.
    """
    def __init__(self, video_id: str | None, message: str | None = None) -> None:
        self.video_id = video_id
        self._message = message or f"Could not retrieve transcript for video: {video_id}"
        super().__init__(self._message)

    @property
    def suggestion(self) -> str:
        """Return an actionable suggestion for resolving this error."""
        return "Check the video URL and your network connection, then try again."


class VideoUnavailable(TranscriptRetrievalError):
    """
    Raised when the requested video is unavailable.
    """
    def __init__(self, video_id: str) -> None:
        super().__init__(
            video_id,
            f"The video {video_id} is unavailable (private, deleted, or restricted)"
        )

    @property
    def suggestion(self) -> str:
        return "Check if the video URL is correct and the video is public."


class TranscriptNotFound(TranscriptRetrievalError):
    """
    Raised when no transcript is found for the requested video.
    """
    def __init__(self, video_id: str, language_codes: list[str] | None = None) -> None:
        if language_codes:
            message = f"No transcript found for video {video_id} in languages: {language_codes}"
        else:
            message = f"No transcript found for video {video_id}"
        super().__init__(video_id, message)

    @property
    def suggestion(self) -> str:
        return (
            "This video may not have transcripts. "
            "Try --list-transcripts to see available options."
        )


class TranscriptDisabled(TranscriptRetrievalError):
    """
    Raised when transcripts are disabled for the video.
    """
    def __init__(self, video_id: str) -> None:
        super().__init__(
            video_id,
            f"Transcript is disabled for video {video_id}"
        )

    @property
    def suggestion(self) -> str:
        return (
            "The video owner has disabled transcripts for this video. "
            "There is no workaround for this restriction."
        )


class NoTranscriptFound(TranscriptRetrievalError):
    """
    Raised when no transcript could be found for any of the requested languages.
    """
    def __init__(
        self,
        video_id: str,
        requested_language_codes: list[str],
        transcript_data: dict,
    ) -> None:
        self.requested_language_codes = requested_language_codes
        self.transcript_data = transcript_data
        available_languages = [t['language_code'] for t in transcript_data] if isinstance(transcript_data, list) else list(transcript_data.keys())
        super().__init__(
            video_id,
            f"No transcript found for video {video_id} in requested languages: {requested_language_codes}. "
            f"Available languages: {available_languages}"
        )

    @property
    def suggestion(self) -> str:
        return (
            "Try a different language code, or use --list-transcripts "
            "to see all available languages for this video."
        )


class NotTranslatable(TranscriptRetrievalError):
    """
    Raised when the requested transcript cannot be translated.
    """
    def __init__(self, video_id: str, language_code: str) -> None:
        super().__init__(
            video_id,
            f"The transcript for video {video_id} in language {language_code} is not translatable"
        )

    @property
    def suggestion(self) -> str:
        return (
            "Not all transcripts support translation. "
            "Try using a different source language or use AI translation instead."
        )


class TranslationLanguageNotAvailable(TranscriptRetrievalError):
    """
    Raised when the requested translation language is not available.
    """
    def __init__(self, video_id: str, language_code: str, available_languages: list) -> None:
        self.available_languages = available_languages
        super().__init__(
            video_id,
            f"Translation language {language_code} not available for video {video_id}. "
            f"Available languages: {available_languages}"
        )

    @property
    def suggestion(self) -> str:
        return (
            "Choose one of the available translation languages listed above, "
            "or use AI translation for unsupported languages."
        )


class CookiePathInvalid(TranscriptRetrievalError):
    """
    Raised when the provided cookie path is invalid.
    """
    def __init__(self, cookie_path: str) -> None:
        self.cookie_path = cookie_path
        super().__init__(None, f"Invalid cookie path: {cookie_path}")

    @property
    def suggestion(self) -> str:
        return (
            "Verify the cookie file path exists and is readable. "
            "Export cookies from your browser using a cookie export extension."
        )


class CookiesInvalid(TranscriptRetrievalError):
    """
    Raised when the provided cookies are invalid.
    """
    def __init__(self, video_id: str) -> None:
        super().__init__(
            video_id,
            f"The provided cookies are invalid for accessing video {video_id}"
        )

    @property
    def suggestion(self) -> str:
        return (
            "Your cookies may have expired. "
            "Re-export fresh cookies from your browser and try again."
        )


class FailedToCreateConsentCookie(TranscriptRetrievalError):
    """
    Raised when failing to create consent cookie.
    """
    def __init__(self, video_id: str) -> None:
        super().__init__(
            video_id,
            f"Failed to create consent cookie for video {video_id}"
        )

    @property
    def suggestion(self) -> str:
        return (
            "This usually happens with EU consent requirements. "
            "Try providing your own cookies via the `cookies` parameter."
        )


class NoTranscriptAvailable(TranscriptRetrievalError):
    """
    Raised when no transcript is available for the video.
    """
    def __init__(self, video_id: str) -> None:
        super().__init__(
            video_id,
            f"No transcript available for video {video_id}"
        )

    @property
    def suggestion(self) -> str:
        return (
            "This video does not have any transcripts. "
            "It may be a live stream, a very new upload, or a video without speech."
        )


class TooManyRequests(TranscriptRetrievalError):
    """
    Raised when too many requests have been made and IP is temporarily blocked.
    """
    def __init__(self, video_id: str | None = None) -> None:
        super().__init__(
            video_id,
            "Too many requests. Your IP may be temporarily blocked. Please try again later."
        )

    @property
    def suggestion(self) -> str:
        return (
            "YouTube rate limit reached. Wait a few minutes and try again, "
            "or route requests through a proxy."
        )
