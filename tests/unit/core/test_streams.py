"""Tests for stream parsing and selection."""

from __future__ import annotations

from typing import Any

import pytest

from tests.helpers.youtube import streaming_data
from utmax.core.clients import ANDROID_VR, DESKTOP_USER_AGENT, IOS
from utmax.core.streams import Stream, choose_streams, describe_stream, parse_streams
from utmax.errors import FormatNotAvailable
from utmax.models import Container, Format, Quality

URL = "https://rr1.googlevideo.com/videoplayback?expire=1790604050&itag={itag}&c=IOS"


def raw(itag: int, mime: str, **fields: Any) -> dict[str, Any]:
    """One ``adaptiveFormats`` entry with a direct URL."""
    return {"itag": itag, "mimeType": mime, "url": URL.format(itag=itag), **fields}


def video(itag: int, codecs: str, width: int, height: int, **fields: Any) -> dict[str, Any]:
    container = "webm" if codecs.startswith(("vp9", "vp09")) else "mp4"
    fields.setdefault("fps", 25)
    fields.setdefault("bitrate", 1000)
    mime = f'video/{container}; codecs="{codecs}"'
    return raw(itag, mime, width=width, height=height, **fields)


def audio(itag: int, codecs: str = "mp4a.40.2", **fields: Any) -> dict[str, Any]:
    container = "webm" if codecs == "opus" else "mp4"
    fields.setdefault("audioSampleRate", "44100")
    fields.setdefault("audioChannels", 2)
    fields.setdefault("bitrate", 128000)
    return raw(itag, f'audio/{container}; codecs="{codecs}"', **fields)


def streams(*entries: dict[str, Any]) -> tuple[Stream, ...]:
    return parse_streams({"adaptiveFormats": list(entries)})


def choose(
    found: tuple[Stream, ...], container: Container = "mp4", quality: Quality = "compat"
) -> tuple[int | None, int]:
    picked, sound = choose_streams(found, container=container, quality=quality, video_id="v")
    return (picked.format.itag if picked else None, sound.format.itag)


def test_the_recorded_android_vr_streams_parse() -> None:
    found = parse_streams(streaming_data())
    assert len(found) == 27
    assert [stream.format.itag for stream in found][:3] == [18, 313, 401]
    by_itag = {stream.format.itag: stream for stream in found}
    assert by_itag[137].format == Format(
        itag=137,
        kind="video",
        container="mp4",
        codec="h264",
        codecs="avc1.640028",
        width=1920,
        height=1080,
        fps=25,
        bitrate=4334157,
        content_length=80911999,
        last_modified="1766957926174250",
    )
    assert by_itag[140].format == Format(
        itag=140,
        kind="audio",
        container="mp4",
        codec="aac",
        codecs="mp4a.40.2",
        bitrate=130677,
        content_length=3449447,
        audio_sample_rate=44100,
        audio_channels=2,
        last_modified="1766955925572207",
    )
    assert by_itag[137].user_agent == ANDROID_VR.user_agent
    assert by_itag[137].expires_at is None  # the recorded URLs carry expire=REDACTED
    assert by_itag[18].progressive
    assert by_itag[18].format.content_length is None


@pytest.mark.parametrize(
    ("container", "quality", "expected"),
    [
        ("mp4", "compat", (137, 140)),
        ("mp4", "max", (401, 140)),
        ("mov", "compat", (137, 140)),
        ("m4a", "compat", (None, 140)),
        ("mp3", "max", (None, 140)),
    ],
)
def test_the_recorded_streams_pick_the_expected_itags(
    container: Container, quality: Quality, expected: tuple[int | None, int]
) -> None:
    assert choose(parse_streams(streaming_data()), container, quality) == expected


@pytest.mark.parametrize(
    ("entry", "problem"),
    [
        (video(137, "avc1.640028", 1920, 1080), None),
        (video(137, "avc1.640028", 1920, 1080, drmFamilies=["WIDEVINE"]), "DRM-protected"),
        (video(137, "avc1.640028", 1920, 1080, targetDurationSec=5), "part of a live stream"),
        (
            {**video(137, "avc1.640028", 1920, 1080), "url": None, "signatureCipher": "s=1"},
            "needs a signature utmax cannot compute",
        ),
        (raw(18, 'video/mp4; codecs="avc1.42001E, mp4a.40.2"'), "audio and video combined"),
        (video(248, "vp9", 1920, 1080), "WebM"),
        (video(337, "vp09.02.51.10.01.09.16.09.00", 3840, 2160), "WebM"),
        (video(701, "av01.0.12M.10.0.110.09.16.09.0", 3840, 2160), "HDR or more than 8 bits"),
        (
            video(
                399,
                "av01.0.08M.08",
                1920,
                1080,
                colorInfo={"transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_SMPTEST2084"},
            ),
            "HDR or more than 8 bits",
        ),
        (
            video(400, "av01.0.12M.08", 2560, 1440, qualityLabel="1440p60 HDR"),
            "HDR or more than 8 bits",
        ),
        (audio(328, "ec-3"), "other codec"),
        (audio(251, "opus"), "WebM"),
    ],
)
def test_problems_explain_why_a_stream_is_skipped(
    entry: dict[str, Any], problem: str | None
) -> None:
    (stream,) = streams(entry)
    assert stream.problem == problem


@pytest.mark.parametrize(
    ("codecs", "codec"),
    [
        ("avc1.640028", "h264"),
        ("avc1.4D401F", "h264"),
        ("av01.0.08M.08", "av1"),
        ("vp9", "vp9"),
        ("vp09.00.51.08", "vp9"),
        ("mp4a.40.2", "aac"),
        ("mp4a.40.5", "he-aac"),
        ("mp4a.40.29", "he-aac"),
        ("opus", "opus"),
        ("ec-3", "other"),
        ("mp4a.a5", "other"),
    ],
)
def test_codec_families(codecs: str, codec: str) -> None:
    (stream,) = parse_streams({"adaptiveFormats": [raw(1, f'audio/mp4; codecs="{codecs}"')]})
    assert stream.format.codec == codec


def test_max_prefers_av1_at_equal_size_then_frame_rate_and_bitrate() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080, bitrate=4_000_000),
        video(399, "av01.0.08M.08", 1920, 1080, bitrate=1_600_000),
        video(299, "avc1.64002a", 1920, 1080, fps=50, bitrate=5_000_000),
        audio(140),
    )
    assert choose(found, quality="compat") == (299, 140)
    assert choose(found, quality="max") == (399, 140)


def test_quality_caps_the_size() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080),
        video(138, "avc1.640033", 7680, 4320),
        video(401, "av01.0.12M.08", 3840, 2160),
        video(571, "av01.0.16M.08", 7680, 4320),
        audio(140),
    )
    assert choose(found) == (137, 140)
    assert choose(found, quality="max") == (401, 140)


def test_vertical_videos_are_measured_on_the_short_side() -> None:
    found = streams(
        video(137, "avc1.640028", 1080, 1920),
        video(136, "avc1.4d401f", 720, 1280),
        audio(140),
    )
    assert choose(found) == (137, 140)


def test_audio_prefers_the_default_track_then_no_drc_then_bitrate() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080),
        audio(140, bitrate=130_000, isDrc=True),
        audio(140, bitrate=129_000),
        audio(139, "mp4a.40.5", bitrate=50_000),
        audio(141, bitrate=260_000, audioTrack={"audioIsDefault": False, "displayName": "Spanish"}),
    )
    _, chosen = choose_streams(found, container="mp4", quality="compat", video_id="v")
    assert (chosen.format.itag, chosen.format.is_drc, chosen.format.bitrate) == (
        140,
        False,
        129_000,
    )


def test_mov_needs_stereo_audio() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080),
        audio(256, "mp4a.40.5", audioChannels=6, bitrate=192_000),
        audio(140, bitrate=128_000),
        audio(327, audioSampleRate="96000", bitrate=300_000),
    )
    assert choose(found, "mp4") == (137, 327)
    assert choose(found, "mov") == (137, 140)


def test_nothing_suitable_lists_every_stream() -> None:
    found = streams(video(248, "vp9", 1920, 1080), audio(251, "opus"))
    with pytest.raises(FormatNotAvailable, match="has no AAC audio in MP4") as caught:
        choose_streams(found, container="mp4", quality="compat", video_id="abc")
    assert caught.value.available == (
        "248 webm vp9 1080p25 (WebM)",
        "251 webm opus 44.1kHz (WebM)",
    )
    assert caught.value.video_id == "abc"
    only_av1 = streams(video(399, "av01.0.08M.08", 1920, 1080), audio(140))
    with pytest.raises(FormatNotAvailable, match=r"has no H\.264 video up to 1080p"):
        choose_streams(only_av1, container="mp4", quality="compat", video_id="abc")


def test_live_streams_and_empty_lists_have_their_own_message() -> None:
    live = streams(
        video(137, "avc1.640028", 1920, 1080, targetDurationSec=5),
        audio(140, targetDurationSec=5),
    )
    with pytest.raises(FormatNotAvailable, match="is a live stream"):
        choose_streams(live, container="mp4", quality="compat", video_id="abc")
    with pytest.raises(FormatNotAvailable, match="offered no streams"):
        choose_streams((), container="m4a", quality="compat", video_id="abc")


def test_expiry_and_user_agent_come_from_the_url() -> None:
    (stream,) = streams(video(137, "avc1.640028", 1920, 1080))
    assert stream.expires_at == 1790604050
    assert stream.user_agent == IOS.user_agent
    unknown_client = {
        **video(137, "avc1.640028", 1920, 1080),
        "url": "https://rr1.googlevideo.com/videoplayback?c=TVHTML5",
    }
    (other,) = streams(unknown_client)
    assert (other.expires_at, other.user_agent) == (None, DESKTOP_USER_AGENT)


def test_malformed_entries_are_skipped() -> None:
    found = parse_streams(
        {
            "formats": "not a list",
            "adaptiveFormats": [
                {"itag": 1},
                {"mimeType": 'video/mp4; codecs="avc1"'},
                {"itag": True, "mimeType": 'video/mp4; codecs="avc1"'},
                {"itag": 2, "mimeType": "text/plain"},
                "not a dict",
                {
                    "itag": "3",
                    "mimeType": 'audio/mp4; codecs="mp4a.40.2"',
                    "bitrate": "fast",
                    "width": 1.5,
                },
            ],
        }
    )
    assert [stream.format.itag for stream in found] == [3]
    assert (found[0].format.bitrate, found[0].format.width) == (0, None)


def test_describe_stream() -> None:
    (webm,) = streams(video(248, "vp9", 1920, 1080))
    assert describe_stream(webm) == "248 webm vp9 1080p25 (WebM)"
    (usable,) = streams(audio(140))
    assert describe_stream(usable) == "140 mp4 aac 44.1kHz"


def test_stream_reprs_hide_the_ip_bound_url() -> None:
    (stream,) = streams(video(137, "avc1.640028", 1920, 1080))
    assert "googlevideo" in stream.url
    assert "googlevideo" not in repr(stream)
    assert "itag=137" in repr(stream)
