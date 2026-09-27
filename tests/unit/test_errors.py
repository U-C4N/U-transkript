"""Tests for the exception hierarchy."""

from __future__ import annotations

import pickle

import pytest

import utmax
from utmax import errors


def test_every_public_error_has_a_real_suggestion() -> None:
    for name in errors.__all__:
        cls = getattr(errors, name)
        assert issubclass(cls, errors.UTMaxError)
        assert cls.suggestion.endswith(".")
        assert len(cls.suggestion) > 20


@pytest.mark.parametrize(
    ("child", "parent"),
    [
        (errors.InvalidVideoId, ValueError),
        (errors.InvalidOption, ValueError),
        (errors.UnsupportedFormat, ValueError),
        (errors.NetworkError, errors.UTMaxError),
        (errors.YouTubeError, errors.UTMaxError),
        (errors.RequestBlocked, errors.YouTubeError),
        (errors.IpBlocked, errors.RequestBlocked),
        (errors.NoTranscriptFound, errors.YouTubeError),
        (errors.TranscriptsDisabled, errors.YouTubeError),
    ],
)
def test_hierarchy(child: type[Exception], parent: type[Exception]) -> None:
    assert issubclass(child, parent)


def test_message_video_id_and_suggestion_override() -> None:
    error = errors.VideoUnavailable("gone", video_id="abc")
    assert str(error) == "gone"
    assert error.message == "gone"
    assert error.video_id == "abc"
    assert error.suggestion == errors.VideoUnavailable.suggestion
    custom = errors.VideoUnavailable("gone", suggestion="Try another video.")
    assert custom.suggestion == "Try another video."
    assert errors.VideoUnavailable.suggestion != "Try another video."


def test_specific_fields_are_stored_as_tuples() -> None:
    unplayable = errors.VideoUnplayable("no", reason="Private video", sub_reasons=["Sign in"])
    assert unplayable.reason == "Private video"
    assert unplayable.sub_reasons == ("Sign in",)
    assert errors.YouTubeRequestFailed("bad", status_code=403).status_code == 403
    missing = errors.NoTranscriptFound("none", requested=["tr"], available=["en (English, manual)"])
    assert missing.requested == ("tr",)
    assert missing.available == ("en (English, manual)",)
    assert errors.TranslationLanguageNotAvailable("no", available=["de"]).available == ("de",)


@pytest.mark.parametrize(
    "error",
    [
        errors.InvalidVideoId("bad id"),
        errors.VideoUnplayable("no", reason="r", sub_reasons=["s"], video_id="v"),
        errors.YouTubeRequestFailed("bad", status_code=500, video_id="v"),
        errors.NoTranscriptFound("none", requested=["tr"], available=["en"], video_id="v"),
        errors.IpBlocked("slow down", suggestion="Wait a minute."),
    ],
)
def test_errors_survive_pickling(error: errors.UTMaxError) -> None:
    clone = pickle.loads(pickle.dumps(error))
    assert type(clone) is type(error)
    assert str(clone) == str(error)
    assert clone.__dict__ == error.__dict__


@pytest.mark.parametrize(
    ("child", "parents"),
    [
        (errors.InvalidModelSpec, (errors.UTMaxError, ValueError)),
        (errors.MissingExtra, (errors.UTMaxError, ImportError)),
        (errors.TranslationError, (errors.UTMaxError,)),
        (errors.ProviderNotInstalled, (errors.TranslationError, errors.MissingExtra, ImportError)),
        (errors.ProviderAuthError, (errors.TranslationError,)),
        (errors.ProviderRateLimited, (errors.TranslationError,)),
        (errors.ProviderError, (errors.TranslationError,)),
        (errors.TranslationRefused, (errors.TranslationError,)),
        (errors.TranslationMismatch, (errors.TranslationError,)),
        (errors.DownloadError, (errors.UTMaxError,)),
        (errors.MuxError, (errors.DownloadError,)),
    ],
)
def test_translation_and_download_hierarchy(
    child: type[Exception], parents: tuple[type[Exception], ...]
) -> None:
    for parent in parents:
        assert issubclass(child, parent)


def test_missing_extra_names_the_pip_extra_and_stays_an_import_error() -> None:
    error = errors.MissingExtra("The mcp package is not installed.", extra="mcp", video_id="v")
    assert (error.extra, error.video_id) == ("mcp", "v")
    assert error.suggestion == 'Install it with pip install "u-transcript-max[mcp]".'
    assert error.msg == "The mcp package is not installed."
    assert str(error) == "The mcp package is not installed."
    custom = errors.MissingExtra("missing", extra="mcp", suggestion="Install mcp yourself.")
    assert custom.suggestion == "Install mcp yourself."


def test_provider_not_installed_is_a_translation_error_and_a_missing_extra() -> None:
    error = errors.ProviderNotInstalled("anthropic is missing", provider="claude", extra="claude")
    assert (error.provider, error.extra, error.video_id) == ("claude", "claude", None)
    assert error.suggestion == 'Install it with pip install "u-transcript-max[claude]".'
    assert error.msg == "anthropic is missing"
    with pytest.raises(ImportError, match="anthropic is missing"):
        raise error


def test_translation_error_fields() -> None:
    assert errors.ProviderAuthError("bad key", provider="openai").provider == "openai"
    assert errors.ProviderRateLimited("slow down", provider="gemini").provider == "gemini"
    failed = errors.ProviderError("server error", provider="gemini", status_code=503)
    assert (failed.provider, failed.status_code) == ("gemini", 503)
    assert errors.ProviderError("no status", provider="openrouter").status_code is None
    mismatch = errors.TranslationMismatch(
        "ids differ", provider="claude", ids=[3, 1], raw_excerpt='{"items": [', video_id="v"
    )
    assert (mismatch.ids, mismatch.raw_excerpt, mismatch.video_id) == ((3, 1), '{"items": [', "v")
    assert errors.TranslationRefused("no", provider="claude").provider == "claude"


@pytest.mark.parametrize(
    "error",
    [
        errors.InvalidModelSpec("claude-opus-5"),
        errors.MissingExtra("no mcp", extra="mcp", video_id="v"),
        errors.TranslationError("failed", provider="openai"),
        errors.ProviderNotInstalled("no sdk", provider="gemini", extra="gemini"),
        errors.ProviderAuthError("bad key", provider="claude", suggestion="Set the key."),
        errors.ProviderRateLimited("429", provider="openai"),
        errors.ProviderError("500", provider="openrouter", status_code=500),
        errors.TranslationRefused("refused", provider="claude"),
        errors.TranslationMismatch("bad ids", provider="claude", ids=(2,), raw_excerpt="[]"),
        errors.DownloadError("failed", video_id="v"),
        errors.MuxError("bad stream", video_id="v"),
    ],
)
def test_translation_and_download_errors_survive_pickling(error: errors.UTMaxError) -> None:
    clone = pickle.loads(pickle.dumps(error))
    assert type(clone) is type(error)
    assert str(clone) == str(error)
    assert clone.args == error.args
    assert clone.__dict__ == error.__dict__
    if isinstance(error, ImportError):
        assert isinstance(clone, ImportError)
        assert clone.msg == error.msg


def test_translation_and_download_errors_are_exported_from_utmax() -> None:
    for name in (
        "DownloadError",
        "InvalidModelSpec",
        "MissingExtra",
        "MuxError",
        "ProviderAuthError",
        "ProviderError",
        "ProviderNotInstalled",
        "ProviderRateLimited",
        "TranslationError",
        "TranslationMismatch",
        "TranslationRefused",
    ):
        assert name in errors.__all__
        assert name in utmax.__all__
        assert getattr(utmax, name) is getattr(errors, name)
