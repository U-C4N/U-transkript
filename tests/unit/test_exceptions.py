import pytest

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
    TooManyRequests,
)


class TestTranscriptRetrievalError:
    def test_base_exception_with_default_message(self):
        exc = TranscriptRetrievalError("test_video")
        assert "test_video" in str(exc)
        assert exc.video_id == "test_video"

    def test_base_exception_with_custom_message(self):
        exc = TranscriptRetrievalError("test_video", "Custom error message")
        assert str(exc) == "Custom error message"
        assert exc.video_id == "test_video"

    def test_is_exception_subclass(self):
        exc = TranscriptRetrievalError("test_video")
        assert isinstance(exc, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(TranscriptRetrievalError):
            raise TranscriptRetrievalError("test_video")


class TestVideoUnavailable:
    def test_message(self):
        exc = VideoUnavailable("abc123")
        assert "abc123" in str(exc)
        assert "unavailable" in str(exc).lower()

    def test_inherits_from_base(self):
        exc = VideoUnavailable("abc123")
        assert isinstance(exc, TranscriptRetrievalError)

    def test_video_id_attribute(self):
        exc = VideoUnavailable("abc123")
        assert exc.video_id == "abc123"

    def test_can_be_caught_as_base(self):
        with pytest.raises(TranscriptRetrievalError):
            raise VideoUnavailable("abc123")


class TestTranscriptNotFound:
    def test_message_without_languages(self):
        exc = TranscriptNotFound("abc123")
        assert "abc123" in str(exc)

    def test_message_with_languages(self):
        exc = TranscriptNotFound("abc123", language_codes=["en", "fr"])
        assert "abc123" in str(exc)
        assert "en" in str(exc)
        assert "fr" in str(exc)

    def test_inherits_from_base(self):
        assert issubclass(TranscriptNotFound, TranscriptRetrievalError)


class TestTranscriptDisabled:
    def test_message(self):
        exc = TranscriptDisabled("abc123")
        assert "abc123" in str(exc)
        assert "disabled" in str(exc).lower()

    def test_inherits_from_base(self):
        assert issubclass(TranscriptDisabled, TranscriptRetrievalError)


class TestNoTranscriptFound:
    def test_message(self):
        transcript_data = [
            {"language_code": "en"},
            {"language_code": "fr"},
        ]
        exc = NoTranscriptFound("abc123", ["de", "es"], transcript_data)
        assert "abc123" in str(exc)
        assert "de" in str(exc)
        assert "es" in str(exc)

    def test_stores_requested_languages(self):
        transcript_data = [{"language_code": "en"}]
        exc = NoTranscriptFound("abc123", ["de"], transcript_data)
        assert exc.requested_language_codes == ["de"]

    def test_stores_transcript_data(self):
        transcript_data = [{"language_code": "en"}]
        exc = NoTranscriptFound("abc123", ["de"], transcript_data)
        assert exc.transcript_data == transcript_data

    def test_inherits_from_base(self):
        assert issubclass(NoTranscriptFound, TranscriptRetrievalError)


class TestNotTranslatable:
    def test_message(self):
        exc = NotTranslatable("abc123", "en")
        assert "abc123" in str(exc)
        assert "en" in str(exc)
        assert "not translatable" in str(exc).lower()

    def test_inherits_from_base(self):
        assert issubclass(NotTranslatable, TranscriptRetrievalError)


class TestTranslationLanguageNotAvailable:
    def test_message(self):
        exc = TranslationLanguageNotAvailable("abc123", "de", ["en", "fr"])
        assert "abc123" in str(exc)
        assert "de" in str(exc)

    def test_stores_available_languages(self):
        exc = TranslationLanguageNotAvailable("abc123", "de", ["en", "fr"])
        assert exc.available_languages == ["en", "fr"]

    def test_inherits_from_base(self):
        assert issubclass(TranslationLanguageNotAvailable, TranscriptRetrievalError)


class TestCookiePathInvalid:
    def test_message(self):
        exc = CookiePathInvalid("/invalid/path")
        assert "/invalid/path" in str(exc)

    def test_cookie_path_attribute(self):
        exc = CookiePathInvalid("/invalid/path")
        assert exc.cookie_path == "/invalid/path"

    def test_video_id_is_none(self):
        exc = CookiePathInvalid("/invalid/path")
        assert exc.video_id is None

    def test_inherits_from_base(self):
        assert issubclass(CookiePathInvalid, TranscriptRetrievalError)


class TestCookiesInvalid:
    def test_message(self):
        exc = CookiesInvalid("abc123")
        assert "abc123" in str(exc)
        assert "invalid" in str(exc).lower()

    def test_inherits_from_base(self):
        assert issubclass(CookiesInvalid, TranscriptRetrievalError)


class TestFailedToCreateConsentCookie:
    def test_message(self):
        exc = FailedToCreateConsentCookie("abc123")
        assert "abc123" in str(exc)
        assert "consent cookie" in str(exc).lower()

    def test_inherits_from_base(self):
        assert issubclass(FailedToCreateConsentCookie, TranscriptRetrievalError)


class TestNoTranscriptAvailable:
    def test_message(self):
        exc = NoTranscriptAvailable("abc123")
        assert "abc123" in str(exc)

    def test_inherits_from_base(self):
        assert issubclass(NoTranscriptAvailable, TranscriptRetrievalError)


class TestTooManyRequests:
    def test_message_with_video_id(self):
        exc = TooManyRequests("abc123")
        assert "Too many requests" in str(exc)

    def test_message_without_video_id(self):
        exc = TooManyRequests()
        assert "Too many requests" in str(exc)

    def test_inherits_from_base(self):
        assert issubclass(TooManyRequests, TranscriptRetrievalError)


class TestAllExceptionsInheritFromBase:
    """Verify every exception class inherits from TranscriptRetrievalError."""

    @pytest.mark.parametrize(
        "exc_class",
        [
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
        ],
    )
    def test_inherits_from_transcript_retrieval_error(self, exc_class):
        assert issubclass(exc_class, TranscriptRetrievalError)

    @pytest.mark.parametrize(
        "exc_class",
        [
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
        ],
    )
    def test_inherits_from_exception(self, exc_class):
        assert issubclass(exc_class, Exception)
