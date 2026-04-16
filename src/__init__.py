from youtube_transcript import YouTubeTranscriptApi
from transcript_list import TranscriptList
from fetched_transcript import FetchedTranscript
from ai_translator import AITranscriptTranslator
from exceptions import (
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
    TooManyRequests
)
from formatters import (
    Formatter,
    PrettyPrintFormatter,
    JSONFormatter,
    TextFormatter,
    SRTFormatter,
    VTTFormatter
)

__version__ = "3.0.0"
__author__ = "U-Transkript Team"
__email__ = "contact@u-transkript.com"
__description__ = "Extract YouTube transcripts and translate them with AI — standalone alternative to youtube-transcript-api"
__url__ = "https://github.com/U-C4N/u-transkript"

# Ana sınıf ve fonksiyonları dışa aktar
__all__ = [
    # Ana AI çeviri sınıfı
    'AITranscriptTranslator',
    
    # YouTube transcript API sınıfları
    'YouTubeTranscriptApi',
    'TranscriptList',
    'FetchedTranscript',
    
    # Hata sınıfları
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
    
    # Formatter sınıfları
    'Formatter',
    'PrettyPrintFormatter',
    'JSONFormatter',
    'TextFormatter',
    'SRTFormatter',
    'VTTFormatter'
]

# Paket bilgileri
__package_info__ = {
    "name": "u-transkript",
    "version": __version__,
    "description": __description__,
    "author": __author__,
    "email": __email__,
    "url": __url__,
    "license": "MIT",
    "python_requires": ">=3.10",
    "keywords": [
        "youtube", "transcript", "translation", "ai", "gemini",
        "subtitle", "video", "nlp", "machine-learning", "automation"
    ]
}

def get_version():
    """Paket versiyonunu döndür."""
    return __version__

def get_info():
    """Paket bilgilerini döndür."""
    return __package_info__

# Hızlı başlangıç fonksiyonu
def quick_translate(video_id: str, api_key: str, target_language: str = "Turkish", output_type: str = "txt"):
    """
    Hızlı çeviri fonksiyonu.
    
    Args:
        video_id: YouTube video ID
        api_key: Google Gemini API anahtarı
        target_language: Hedef dil (varsayılan: "Turkish")
        output_type: Çıktı formatı (varsayılan: "txt")
    
    Returns:
        Çevrilmiş transcript
    
    Example:
        result = quick_translate("dQw4w9WgXcQ", "YOUR_API_KEY", "Turkish")
    """
    translator = AITranscriptTranslator(api_key)
    return translator.set_lang(target_language).set_type(output_type).translate_transcript(video_id)

# Paket yüklendiğinde bilgi mesajı (opsiyonel)
def _show_welcome_message():
    """Paket yüklendiğinde hoş geldin mesajı göster."""
    try:
        import sys
        if hasattr(sys, 'ps1'):  # Etkileşimli modda çalışıyorsa
            print(f"🎬 U-Transkript v{__version__} yüklendi!")
            print("📖 Kullanım: from u_transkript import AITranscriptTranslator")
            print("🔗 Dokümantasyon: https://github.com/U-C4N/u-transkript")
    except:
        pass  # Hata durumunda sessizce geç

# Paket import edildiğinde hoş geldin mesajını göster (opsiyonel)
# _show_welcome_message()
