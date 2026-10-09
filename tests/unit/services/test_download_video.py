"""Tests for video downloads with subtitles (fake YouTube, real files and muxer)."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

import pytest

from tests.helpers.builders import VIDEO, make_transcript
from tests.helpers.downloads import FakeYouTube, codec_of, read_movie
from tests.helpers.youtube import VIDEO_ID
from utmax.errors import InvalidOption, NoTranscriptFound, OutputExists
from utmax.models import Segment
from utmax.services.download import DownloadOptions

TURKISH = replace(
    make_transcript(
        Segment(1.0, 2.0, "Merhaba"), language_code="tr", language="Turkish", is_generated=True
    ),
    translated_from="en",
    translator="claude=claude-opus-5",
)


def test_mp4_downloads_embed_the_spoken_language_by_default(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    result = youtube.service().download(VIDEO_ID, tmp_path / "rick.mp4", DownloadOptions())
    assert result.video_format is not None
    assert (result.video_format.itag, result.audio_format.itag) == (399, 140)
    assert result.embedded_subtitles == ("en",)
    movie = read_movie(result.path)
    assert [track.handler for track in movie.tracks] == ["vide", "soun", "sbtl"]
    assert [codec_of(track) for track in movie.tracks] == [b"av01", b"mp4a", b"tx3g"]
    assert [len(track.samples) for track in movie.tracks[:2]] == [100, 172]
    subtitle = movie.tracks[2]
    assert (subtitle.extended_language, subtitle.name, subtitle.flags & 1) == ("en", "English", 1)
    players = [url for url in youtube.api.urls("POST") if "/youtubei/v1/player" in url]
    assert len(players) == 1  # one player response serves streams and captions


def test_an_empty_subtitle_list_embeds_nothing(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    options = DownloadOptions(subtitles=[])
    result = youtube.service().download(VIDEO_ID, tmp_path / "rick.mp4", options)
    assert result.embedded_subtitles == ()
    assert [track.handler for track in read_movie(result.path).tracks] == ["vide", "soun"]
    assert youtube.api.urls("GET") == []


def test_unknown_subtitle_languages_fail_before_any_media_byte(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    with pytest.raises(NoTranscriptFound):
        youtube.service().download(
            VIDEO_ID, tmp_path / "rick.mp4", DownloadOptions(subtitles=["xx"])
        )
    assert youtube.media.requests == []


def test_codes_and_transcripts_mix_and_default_subtitle_picks_the_enabled_track(
    tmp_path: Path,
) -> None:
    options = DownloadOptions(subtitles=["en", TURKISH], default_subtitle="tr")
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.mp4", options)
    assert result.embedded_subtitles == ("en", "tr")
    english, turkish = read_movie(result.path).tracks[2:]
    assert (english.flags & 1, turkish.flags & 1) == (0, 1)
    assert turkish.name == "Turkish (AI: claude=claude-opus-5)"


def test_sidecar_mode_writes_srt_files_instead(tmp_path: Path) -> None:
    options = DownloadOptions(subtitle_mode="sidecar")
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.mp4", options)
    assert result.embedded_subtitles == ()
    assert result.sidecars == (tmp_path / "rick.en.srt",)
    assert "We're no strangers to love" in result.sidecars[0].read_text(encoding="utf-8")
    assert [track.handler for track in read_movie(result.path).tracks] == ["vide", "soun"]


def test_both_mode_embeds_and_writes(tmp_path: Path) -> None:
    options = DownloadOptions(subtitles=["en", "de"], subtitle_mode="both")
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.mp4", options)
    assert result.embedded_subtitles == ("en", "de-DE")
    assert result.sidecars == (tmp_path / "rick.en.srt", tmp_path / "rick.de-DE.srt")


def test_default_subtitle_must_name_an_embedded_track_before_download(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    service = youtube.service()
    with pytest.raises(InvalidOption, match="matches no embedded subtitle track"):
        service.download(
            VIDEO_ID,
            tmp_path / "rick.mp4",
            DownloadOptions(subtitles=["en"], default_subtitle="de"),
        )
    with pytest.raises(InvalidOption, match="no subtitles are embedded"):
        service.download(
            VIDEO_ID,
            tmp_path / "rick.mp4",
            DownloadOptions(subtitle_mode="sidecar", default_subtitle="en"),
        )
    assert youtube.media.requests == []


def test_videos_without_captions_download_without_subtitles(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    youtube = FakeYouTube(captions=False)
    with caplog.at_level(logging.INFO, logger="utmax.download"):
        result = youtube.service().download(VIDEO_ID, tmp_path / "rick.mp4", DownloadOptions())
    assert result.embedded_subtitles == ()
    assert "has no subtitles" in caplog.text


def test_mov_downloads_use_the_quicktime_flavor(tmp_path: Path) -> None:
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.mov", DownloadOptions())
    assert result.container == "mov"
    assert read_movie(result.path).major_brand == "qt  "


def test_compat_quality_keeps_h264(tmp_path: Path) -> None:
    options = DownloadOptions(quality="compat")
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.mp4", options)
    assert result.video_format is not None
    assert result.video_format.itag == 137
    assert codec_of(read_movie(result.path).tracks[0]) == b"avc1"


def test_transcripts_of_other_videos_are_refused(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    other = replace(TURKISH, video=replace(VIDEO, video_id="aaaaaaaaaaa"))
    with pytest.raises(InvalidOption, match="belongs to video aaaaaaaaaaa"):
        youtube.service().download(
            VIDEO_ID, tmp_path / "rick.mp4", DownloadOptions(subtitles=[other])
        )
    assert youtube.media.requests == []


def test_duplicate_subtitle_languages_are_refused(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    with pytest.raises(InvalidOption, match="own language code"):
        youtube.service().download(
            VIDEO_ID, tmp_path / "rick.mp4", DownloadOptions(subtitles=["en", "EN"])
        )
    assert youtube.media.requests == []


def test_existing_sidecars_are_refused_before_download(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    (tmp_path / "rick.en.srt").write_text("old", encoding="utf-8")
    with pytest.raises(OutputExists, match=r"rick\.en\.srt"):
        youtube.service().download(
            VIDEO_ID, tmp_path / "rick.mp4", DownloadOptions(subtitle_mode="sidecar")
        )
    assert youtube.media.requests == []
