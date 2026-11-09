"""Downloads into .mkv and .webm: VP9 and Opus streams, and subtitles as tracks or files."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.downloads import FakeYouTube
from tests.helpers.webm_factory import frame_bytes
from tests.helpers.youtube import VIDEO_ID
from utmax.adapters.files import FileByteSource
from utmax.core.media.webm import WebmTrack, index_webm
from utmax.errors import FormatNotAvailable, InvalidOption
from utmax.services.download import DownloadOptions


def read(path: Path) -> tuple[list[WebmTrack], bytes]:
    with FileByteSource(path) as source:
        return index_webm(source), path.read_bytes()


def test_mkv_takes_the_4k_vp9_picture_and_opus_and_embeds_text_subtitles(tmp_path: Path) -> None:
    result = (
        FakeYouTube(webm=True).service().download(VIDEO_ID, tmp_path / "v.mkv", DownloadOptions())
    )

    assert result.container == "mkv"
    assert (
        result.video_format.itag if result.video_format else None,
        result.audio_format.itag,
    ) == (313, 251)
    assert result.embedded_subtitles == ("en",)
    tracks, data = read(result.path)
    assert [track.codec_id for track in tracks] == ["V_VP9", "A_OPUS", "S_TEXT/UTF8"]
    video = tracks[0]
    assert [
        data[o : o + s] for o, s in zip(video.frames.offsets, video.frames.sizes, strict=True)
    ] == [frame_bytes(1, index, 700 + index % 50) for index in range(100)]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["v.mkv"]  # the parts are gone


def test_mkv_without_webm_streams_holds_av1_and_aac(tmp_path: Path) -> None:
    options = DownloadOptions(subtitles=[])
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "v.mkv", options)
    assert (
        result.video_format.itag if result.video_format else None,
        result.audio_format.itag,
    ) == (399, 140)
    tracks, _ = read(result.path)
    assert [track.codec_id for track in tracks] == ["V_AV1", "A_AAC"]


def test_webm_writes_subtitles_next_to_it_and_only_when_asked(tmp_path: Path) -> None:
    youtube = FakeYouTube(webm=True)
    plain = youtube.service().download(VIDEO_ID, tmp_path / "plain.webm", DownloadOptions())
    assert (plain.container, plain.embedded_subtitles, plain.sidecars) == ("webm", (), ())
    asked = youtube.service().download(
        VIDEO_ID, tmp_path / "asked.webm", DownloadOptions(subtitles=["en"])
    )
    assert asked.sidecars == (tmp_path / "asked.en.srt",)
    assert asked.sidecars[0].read_text(encoding="utf-8").startswith("1\n")
    tracks, _ = read(asked.path)
    assert [track.codec_id for track in tracks] == ["V_VP9", "A_OPUS"]


def test_webm_cannot_show_a_default_subtitle(tmp_path: Path) -> None:
    with pytest.raises(InvalidOption, match="cannot embed subtitles") as caught:
        FakeYouTube(webm=True).service().download(
            VIDEO_ID, tmp_path / "v.webm", DownloadOptions(default_subtitle="en")
        )
    assert ".mkv" in caught.value.suggestion


def test_webm_needs_opus_audio(tmp_path: Path) -> None:
    with pytest.raises(FormatNotAvailable, match="has no Opus audio"):
        FakeYouTube().service().download(VIDEO_ID, tmp_path / "v.webm", DownloadOptions())
