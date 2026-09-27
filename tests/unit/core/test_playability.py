"""Tests for the playabilityStatus → error table."""

from __future__ import annotations

from typing import Any

import pytest

from utmax.core.playability import Playability, check_playability, parse_playability
from utmax.errors import (
    AgeRestricted,
    RequestBlocked,
    UTMaxError,
    VideoUnavailable,
    VideoUnplayable,
)


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (
            {"status": "LOGIN_REQUIRED", "reason": "Sign in to confirm you're not a bot"},
            RequestBlocked,
        ),
        ({"status": "LOGIN_REQUIRED", "reason": "Sign in to confirm your age"}, AgeRestricted),
        (
            {
                "status": "LOGIN_REQUIRED",
                "reason": "This video may be inappropriate for some users.",
            },
            AgeRestricted,
        ),
        ({"status": "LOGIN_REQUIRED", "reason": "Please sign in"}, VideoUnplayable),
        ({"status": "ERROR", "reason": "This video is unavailable"}, VideoUnavailable),
        (
            {"status": "UNPLAYABLE", "reason": "This live stream recording is not available."},
            VideoUnplayable,
        ),
        ({"status": "ERROR", "reason": "Something else"}, VideoUnplayable),
        ({"status": "CONTENT_CHECK_REQUIRED"}, VideoUnplayable),
    ],
)
def test_every_non_ok_status_maps_to_a_typed_error(
    status: dict[str, Any], error: type[UTMaxError]
) -> None:
    with pytest.raises(error) as caught:
        check_playability(parse_playability({"playabilityStatus": status}), video_id="v")
    assert type(caught.value) is error
    assert caught.value.video_id == "v"


@pytest.mark.parametrize(
    "player", [{"playabilityStatus": {"status": "OK"}}, {}, {"playabilityStatus": "odd"}]
)
def test_ok_or_missing_status_passes(player: dict[str, Any]) -> None:
    check_playability(parse_playability(player), video_id="v")


def test_reason_and_sub_reasons_come_from_the_error_screen() -> None:
    playability = parse_playability(
        {
            "playabilityStatus": {
                "status": "UNPLAYABLE",
                "errorScreen": {
                    "playerErrorMessageRenderer": {
                        "reason": {"simpleText": "Video unavailable"},
                        "subreason": {
                            "runs": [
                                {"text": "The uploader has not made this video "},
                                {"text": "available in your country"},
                            ]
                        },
                    }
                },
            }
        }
    )
    assert playability == Playability(
        "UNPLAYABLE",
        "Video unavailable",
        ("The uploader has not made this video ", "available in your country"),
    )
    with pytest.raises(VideoUnplayable) as caught:
        check_playability(playability, video_id="v")
    assert caught.value.sub_reasons == playability.sub_reasons
    assert caught.value.reason == "Video unavailable"


def test_private_videos_explain_that_sign_in_is_unsupported() -> None:
    with pytest.raises(VideoUnplayable) as caught:
        check_playability(Playability("LOGIN_REQUIRED", "Please sign in"), video_id="v")
    assert "signed-in" in caught.value.suggestion
