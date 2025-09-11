class TranscriptRetrievalError(Exception):
    """
    Base exception for transcript retrieval errors.
    """
    def __init__(self, video_id, message=None):
        self.video_id = video_id
        super().__init__(message or f"Could not retrieve transcript for video: {video_id}")


class VideoUnavailable(TranscriptRetrievalError):
    """
    Raised when the requested video is unavailable.
    """
    def __init__(self, video_id):
        super().__init__(
            video_id,
            f"The video {video_id} is unavailable (private, deleted, or restricted)"
        )


class TranscriptNotFound(TranscriptRetrievalError):
    """
    Raised when no transcript is found for the requested video.
    """
    def __init__(self, video_id, language_codes=None):
        if language_codes:
            message = f"No transcript found for video {video_id} in languages: {language_codes}"
        else:
            message = f"No transcript found for video {video_id}"
        super().__init__(video_id, message)


class TranscriptDisabled(TranscriptRetrievalError):
    """
    Raised when transcripts are disabled for the video.
    """
    def __init__(self, video_id):
        super().__init__(
            video_id,
            f"Transcript is disabled for video {video_id}"
        )


class NoTranscriptFound(TranscriptRetrievalError):
    """
    Raised when no transcript could be found for any of the requested languages.
    """
    def __init__(self, video_id, requested_language_codes, transcript_data):
        self.requested_language_codes = requested_language_codes
        self.transcript_data = transcript_data
        available_languages = [t['language_code'] for t in transcript_data]
        super().__init__(
            video_id,
            f"No transcript found for video {video_id} in requested languages: {requested_language_codes}. "
            f"Available languages: {available_languages}"
        )


class NotTranslatable(TranscriptRetrievalError):
    """
    Raised when the requested transcript cannot be translated.
    """
    def __init__(self, video_id, language_code):
        super().__init__(
            video_id,
            f"The transcript for video {video_id} in language {language_code} is not translatable"
        )


class TranslationLanguageNotAvailable(TranscriptRetrievalError):
    """
    Raised when the requested translation language is not available.
    """
    def __init__(self, video_id, language_code, available_languages):
        self.available_languages = available_languages
        super().__init__(
            video_id,
            f"Translation language {language_code} not available for video {video_id}. "
            f"Available languages: {available_languages}"
        )


class CookiePathInvalid(TranscriptRetrievalError):
    """
    Raised when the provided cookie path is invalid.
    """
    def __init__(self, cookie_path):
        self.cookie_path = cookie_path
        super().__init__(None, f"Invalid cookie path: {cookie_path}")


class CookiesInvalid(TranscriptRetrievalError):
    """
    Raised when the provided cookies are invalid.
    """
    def __init__(self, video_id):
        super().__init__(
            video_id,
            f"The provided cookies are invalid for accessing video {video_id}"
        )


class FailedToCreateConsentCookie(TranscriptRetrievalError):
    """
    Raised when failing to create consent cookie.
    """
    def __init__(self, video_id):
        super().__init__(
            video_id,
            f"Failed to create consent cookie for video {video_id}"
        )


class NoTranscriptAvailable(TranscriptRetrievalError):
    """
    Raised when no transcript is available for the video.
    """
    def __init__(self, video_id):
        super().__init__(
            video_id,
            f"No transcript available for video {video_id}"
        )


class TooManyRequests(TranscriptRetrievalError):
    """
    Raised when too many requests have been made and IP is temporarily blocked.
    """
    def __init__(self, video_id=None):
        super().__init__(
            video_id,
            "Too many requests. Your IP may be temporarily blocked. Please try again later."
        )
