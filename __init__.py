import importlib

_prefix = '.' if __package__ else ''

youtube_transcript = importlib.import_module(f"{_prefix}youtube_transcript")
transcript_list = importlib.import_module(f"{_prefix}transcript_list")
fetched_transcript = importlib.import_module(f"{_prefix}fetched_transcript")
ai_translator = importlib.import_module(f"{_prefix}ai_translator")
exceptions = importlib.import_module(f"{_prefix}exceptions")
formatters = importlib.import_module(f"{_prefix}formatters")

YouTubeTranscriptApi = youtube_transcript.YouTubeTranscriptApi
TranscriptList = transcript_list.TranscriptList
FetchedTranscript = fetched_transcript.FetchedTranscript
AITranscriptTranslator = ai_translator.AITranscriptTranslator
(
    TranscriptRetrievalError,
    VideoUnavailable,
    TranscriptNotFound,
    TranscriptDisabled,
    NoTranscriptFound,
    NotTranslatable,
    TranslationLanguageNotAvailable,
    CookiePathInvalid,
    CookiesInvalid,
    FailedToCreateConsentCookie,
    NoTranscriptAvailable,
    TooManyRequests,
) = (
    exceptions.TranscriptRetrievalError,
    exceptions.VideoUnavailable,
    exceptions.TranscriptNotFound,
    exceptions.TranscriptDisabled,
    exceptions.NoTranscriptFound,
    exceptions.NotTranslatable,
    exceptions.TranslationLanguageNotAvailable,
    exceptions.CookiePathInvalid,
    exceptions.CookiesInvalid,
    exceptions.FailedToCreateConsentCookie,
    exceptions.NoTranscriptAvailable,
    exceptions.TooManyRequests,
)
(
    Formatter,
    PrettyPrintFormatter,
    JSONFormatter,
    TextFormatter,
    SRTFormatter,
    VTTFormatter,
) = (
    formatters.Formatter,
    formatters.PrettyPrintFormatter,
    formatters.JSONFormatter,
    formatters.TextFormatter,
    formatters.SRTFormatter,
    formatters.VTTFormatter,
)

__version__ = "1.0.0"
__author__ = "U-Transkript Team"
__email__ = "contact@u-transkript.com"
__description__ = "YouTube videolarını otomatik olarak çıkarıp AI ile çeviren güçlü Python kütüphanesi"
__url__ = "https://github.com/username/u-transkript"

__all__ = [
    'AITranscriptTranslator',
    'YouTubeTranscriptApi',
    'TranscriptList',
    'FetchedTranscript',
    'TranscriptRetrievalError',
    'VideoUnavailable',
    'TranscriptNotFound',
    'TranscriptDisabled',
    'NoTranscriptFound',
    'NotTranslatable',
    'TranslationLanguageNotAvailable',
    'CookiePathInvalid',
    'CookiesInvalid',
    'FailedToCreateConsentCookie',
    'NoTranscriptAvailable',
    'TooManyRequests',
    'Formatter',
    'PrettyPrintFormatter',
    'JSONFormatter',
    'TextFormatter',
    'SRTFormatter',
    'VTTFormatter'
]

__package_info__ = {
    "name": "u-transkript",
    "version": __version__,
    "description": __description__,
    "author": __author__,
    "email": __email__,
    "url": __url__,
    "license": "MIT",
    "python_requires": ">=3.7",
    "keywords": [
        "youtube", "transcript", "translation", "ai", "gemini",
        "subtitle", "video", "nlp", "machine-learning", "automation"
    ]
}

def get_version():
    """
    Returns the current version of the package as a string.
    """
    return __version__

def get_info():
    """
    Returns the package information dictionary containing metadata such as name, version, description, author, license, Python version requirement, and keywords.
    """
    return __package_info__

def quick_translate(video_id: str, api_key: str, target_language: str = "Turkish", output_type: str = "txt"):
    """
    Translates the transcript of a YouTube video to a specified language and format.
    
    Args:
        video_id: The YouTube video identifier.
        api_key: API key for the transcript translation service.
        target_language: The language to translate the transcript into. Defaults to "Turkish".
        output_type: The desired output format (e.g., "txt", "json", "srt"). Defaults to "txt".
    
    Returns:
        The translated transcript in the specified format.
    """
    translator = AITranscriptTranslator(api_key)
    return translator.set_lang(target_language).set_type(output_type).translate_transcript(video_id)

# def _show_welcome_message():
#     try:
#         import sys
#         if hasattr(sys, 'ps1'):
#             print(f"🎬 U-Transkript v{__version__} yüklendi!")
#             print("📖 Kullanım: from u_transkript import AITranscriptTranslator")
#             print("🔗 Dokümantasyon: https://github.com/username/u-transkript")
#     except:
#         pass
# _show_welcome_message()
