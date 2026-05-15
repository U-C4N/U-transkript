from ai_translator import AITranscriptTranslator
from exceptions import (
    CookiePathInvalid,
    CookiesInvalid,
    FailedToCreateConsentCookie,
    NoTranscriptAvailable,
    NoTranscriptFound,
    NotTranslatable,
    TooManyRequests,
    TranscriptDisabled,
    TranscriptNotFound,
    TranscriptRetrievalError,
    TranslationLanguageNotAvailable,
    VideoUnavailable,
)
from fetched_transcript import FetchedTranscript
from formatters import (
    Formatter,
    JSONFormatter,
    PrettyPrintFormatter,
    SRTFormatter,
    TextFormatter,
    VTTFormatter,
)
from transcript_list import TranscriptList
from youtube_transcript import YouTubeTranscriptApi

__version__ = "3.2.0"
__author__ = "U-C4N"
__email__ = "noreply@deuz.ai"
__url__ = "https://github.com/U-C4N/u-transkript"

__all__ = [
    "AITranscriptTranslator",
    "YouTubeTranscriptApi",
    "TranscriptList",
    "FetchedTranscript",
    "TranscriptRetrievalError",
    "VideoUnavailable",
    "TranscriptNotFound",
    "TranscriptDisabled",
    "NoTranscriptFound",
    "NotTranslatable",
    "TranslationLanguageNotAvailable",
    "CookiePathInvalid",
    "CookiesInvalid",
    "FailedToCreateConsentCookie",
    "NoTranscriptAvailable",
    "TooManyRequests",
    "Formatter",
    "PrettyPrintFormatter",
    "JSONFormatter",
    "TextFormatter",
    "SRTFormatter",
    "VTTFormatter",
    "quick_translate",
]


def quick_translate(
    video_id: str,
    api_key: str,
    target_language: str = "Turkish",
    output_type: str = "txt",
) -> str:
    translator = AITranscriptTranslator(api_key)
    return (
        translator.set_lang(target_language)
        .set_type(output_type)
        .translate_transcript(video_id)
    )
