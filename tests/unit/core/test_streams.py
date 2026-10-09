"""Tests for stream parsing and selection."""

from __future__ import annotations

from typing import Any

import pytest

from tests.helpers.youtube import streaming_data
from utmax.core.clients import ANDROID_VR, DESKTOP_USER_AGENT, IOS
from utmax.core.streams import (
    Stream,
    choose_streams,
    describe_stream,
    file_types,
    parse_streams,
    pick_video,
)
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
    found: tuple[Stream, ...],
    container: Container = "mp4",
    quality: Quality = "best",
    resolution: int | None = None,
) -> tuple[int | None, int]:
    picked, sound = choose_streams(
        found, container=container, quality=quality, resolution=resolution, video_id="v"
    )
    return (picked.format.itag if picked else None, sound.format.itag)


def track_url(itag: int, xtags: str) -> str:
    """A stream URL with YouTube's ``xtags`` (percent-encoded, as YouTube sends it)."""
    return f"https://rr1.googlevideo.com/videoplayback?itag={itag}&c=VISIONOS&xtags={xtags}"


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
        ("mp4", "best", (401, 140)),
        ("mov", "compat", (137, 140)),
        ("mov", "best", (137, 140)),
        ("m4a", "best", (None, 140)),
        ("mp3", "compat", (None, 140)),
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
        (video(248, "vp9", 1920, 1080), None),
        (video(337, "vp09.02.51.10.01.09.16.09.00", 3840, 2160), None),
        (video(701, "av01.0.12M.10.0.110.09.16.09.0", 3840, 2160), None),
        (audio(328, "ec-3"), "other codec"),
        (audio(251, "opus"), None),
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


def test_best_prefers_size_then_frame_rate_then_av1_then_bitrate() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080, bitrate=4_000_000),
        video(399, "av01.0.08M.08", 1920, 1080, bitrate=1_600_000),
        video(136, "avc1.4d401f", 1280, 720, fps=50, bitrate=3_000_000),
        audio(140),
    )
    assert choose(found) == (399, 140)
    assert choose(found, quality="compat") == (137, 140)
    faster = streams(
        video(299, "avc1.64002a", 1920, 1080, fps=50, bitrate=5_000_000),
        video(399, "av01.0.08M.08", 1920, 1080, bitrate=1_600_000),
        audio(140),
    )
    assert choose(faster) == (299, 140)


def test_best_has_no_size_limit_and_resolution_caps_it() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080),
        video(138, "avc1.640033", 7680, 4320),
        video(401, "av01.0.12M.08", 3840, 2160),
        video(571, "av01.0.16M.08", 7680, 4320),
        audio(140),
    )
    assert choose(found) == (571, 140)
    assert choose(found, resolution=2160) == (401, 140)
    assert choose(found, resolution=1440) == (137, 140)
    assert choose(found, quality="compat") == (137, 140)
    assert choose(found, quality="compat", resolution=4320) == (137, 140)
    with pytest.raises(FormatNotAvailable, match=r"has no H\.264 or AV1 video up to 720p in MP4"):
        choose(found, resolution=720)
    with pytest.raises(FormatNotAvailable, match=r"has no H\.264 video up to 720p"):
        choose(found, quality="compat", resolution=720)


def test_hdr_is_chosen_only_where_it_is_bigger_and_never_for_compat() -> None:
    hdr = {"qualityLabel": "HDR", "fps": 60}
    found = streams(
        video(701, "av01.0.12M.10.0.110.09.16.09.0", 3840, 2160, **hdr),
        video(699, "av01.0.08M.10.0.110.09.16.09.0", 1920, 1080, **hdr),
        video(399, "av01.0.08M.08", 1920, 1080, fps=60),
        video(299, "avc1.64002a", 1920, 1080, fps=60),
        audio(140),
    )
    assert choose(found) == (701, 140)
    assert choose(found, resolution=1080) == (399, 140)
    assert choose(found, quality="compat") == (299, 140)


def test_mov_takes_h264_only() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080),
        video(401, "av01.0.12M.08", 3840, 2160),
        audio(140),
    )
    assert choose(found, "mov") == (137, 140)
    with pytest.raises(FormatNotAvailable, match=r"has no H\.264 video\."):
        choose(streams(video(401, "av01.0.12M.08", 3840, 2160), audio(140)), "mov")


def test_webm_streams_do_not_fit_mp4_files() -> None:
    found = streams(video(313, "vp9", 3840, 2160), video(137, "avc1.640028", 1920, 1080))
    with pytest.raises(FormatNotAvailable, match="has no AAC audio in MP4"):
        choose((*found, *streams(audio(251, "opus"))))
    assert choose((*found, *streams(audio(140)))) == (137, 140)


def test_file_types_name_where_a_format_fits() -> None:
    h264, av1, vp9, aac, opus = (
        stream.format
        for stream in streams(
            video(137, "avc1.640028", 1920, 1080),
            video(401, "av01.0.12M.08", 3840, 2160),
            video(313, "vp9", 3840, 2160),
            audio(140),
            audio(251, "opus"),
        )
    )
    assert file_types(h264) == ("mp4", "mov")
    assert file_types(av1) == ("mp4",)
    assert file_types(vp9) == ()
    assert file_types(aac) == ("mp4", "mov", "m4a", "mp3")
    assert file_types(opus) == ()


def test_audio_tracks_hdr_and_bit_depth_are_parsed() -> None:
    dub, original, tagged, picture = streams(
        audio(
            140,
            url=track_url(140, "acont%3Ddubbed-auto%3Alang%3Dar"),
            audioTrack={"id": "ar.10", "displayName": "Arabic", "audioIsDefault": True},
        ),
        audio(
            140,
            url=track_url(140, "acont%3Doriginal%3Adrc%3D1%3Alang%3Den-US"),
            audioTrack={"id": "en-US.4", "displayName": "English (US) original"},
        ),
        audio(251, "opus", url=track_url(251, "acont%3Doriginal%3Alang%3Dde")),
        video(701, "av01.0.12M.10.0.110.09.16.09.0", 3840, 2160, qualityLabel="2160p60 HDR"),
    )
    assert (dub.format.language, dub.format.is_original) == ("ar", False)
    assert (original.format.language, original.format.is_original) == ("en-US", True)
    assert (tagged.format.language, tagged.format.is_original) == ("de", True)
    assert (picture.format.hdr, picture.format.bit_depth) == (True, 10)
    assert original.format.label == "140 mp4 aac 44.1kHz en-US original"
    assert picture.format.label == "701 mp4 av1 2160p25 hdr"


def test_audio_prefers_the_original_track_of_a_dubbed_video() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080),
        audio(
            140,
            bitrate=140_000,
            url=track_url(140, "acont%3Ddubbed-auto%3Alang%3Dar"),
            audioTrack={"id": "ar.10", "displayName": "Arabic", "audioIsDefault": True},
        ),
        audio(
            140,
            bitrate=129_000,
            url=track_url(140, "acont%3Doriginal%3Alang%3Den-US"),
            audioTrack={"id": "en-US.4", "displayName": "English (US) original"},
        ),
    )
    _, chosen = choose_streams(found, container="m4a", quality="best", video_id="v")
    assert (chosen.format.language, chosen.format.is_original) == ("en-US", True)


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
    _, chosen = choose_streams(found, container="mp4", quality="best", video_id="v")
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
        choose_streams(found, container="mp4", quality="best", video_id="abc")
    assert caught.value.available == ("248 webm vp9 1080p25", "251 webm opus 44.1kHz")
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
    (protected,) = streams(video(137, "avc1.640028", 1920, 1080, drmFamilies=["WIDEVINE"]))
    assert describe_stream(protected) == "137 mp4 h264 1080p25 (DRM-protected)"
    (usable,) = streams(audio(140))
    assert describe_stream(usable) == "140 mp4 aac 44.1kHz"


def test_stream_reprs_hide_the_ip_bound_url() -> None:
    (stream,) = streams(video(137, "avc1.640028", 1920, 1080))
    assert "googlevideo" in stream.url
    assert "googlevideo" not in repr(stream)
    assert "itag=137" in repr(stream)


def test_pick_video_is_the_choice_of_choose_streams() -> None:
    found = streams(
        video(699, "av01.0.08M.10.0.110.09.16.09.0", 1920, 1080, fps=60, qualityLabel="HDR"),
        video(399, "av01.0.08M.08", 1920, 1080, fps=60),
        video(299, "avc1.64002a", 1920, 1080, fps=60),
        audio(140),
    )
    formats = [stream.format for stream in found]
    picked = pick_video(formats, container="mp4")
    assert picked is not None
    assert picked.itag == choose(found)[0] == 399
    assert [
        getattr(pick_video(formats, container=container, quality=quality), "itag", None)
        for container, quality in (("mov", "best"), ("mp4", "compat"), ("m4a", "best"))
    ] == [299, 299, None]
    assert pick_video(formats, container="mp4", resolution=720) is None
