"""Tests for the exception hierarchy."""

from __future__ import annotations

import pickle

import pytest

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
