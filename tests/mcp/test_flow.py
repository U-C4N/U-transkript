"""The conversation the server is built for: list the formats, download one with the
subtitles the user wants (YouTube's own or the assistant's translation), or save subtitles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
from mcp import Client as MCPClient
from mcp.types import CallToolResult

from tests.helpers.bulk import IDS, TITLES, ManyVideos
from tests.helpers.downloads import FakeYouTube, read_movie
from tests.helpers.youtube import VIDEO_ID
from utmax import Client
from utmax.mcp.config import Config
from utmax.mcp.server import build_server, formats_out
from utmax.models import Format, FormatList, VideoInfo

VIDEO = IDS[0]
NAME = f"{TITLES[VIDEO]} [{VIDEO}]"
RICK = "Rick Astley - Never Gonna Give You Up (Official Video)"
TURKISH = "1\n00:00:01,000 --> 00:00:02,000\nMerhaba\n\n2\n00:00:02,000 --> 00:00:03,500\nDunya\n"


def call(server: Any, name: str, arguments: dict[str, Any]) -> CallToolResult:
    async def main() -> CallToolResult:
        async with MCPClient(server, raise_exceptions=True) as client:
            return await client.call_tool(name, arguments)

    return anyio.run(main)


def output(result: CallToolResult) -> dict[str, Any]:
    assert result.is_error is False, result.content
    assert result.structured_content is not None
    return result.structured_content


def error_text(result: CallToolResult) -> str:
    assert result.is_error is True
    return " ".join(block.text for block in result.content if block.type == "text")


def video(itag: int, codec: str, height: int, *, fps: int = 25, hdr: bool = False) -> Format:
    return Format(
        itag, "video", "mp4", codec, codec, width=height * 16 // 9, height=height, fps=fps, hdr=hdr
    )


def test_list_formats_offers_file_types_and_resolutions() -> None:
    server = build_server(Client(transport=FakeYouTube()), Config())

    result = output(call(server, "list_formats", {"video": f"https://youtu.be/{VIDEO_ID}"}))

    assert result["video"]["title"] == RICK
    assert result["file_types"] == ["mp4", "mov", "m4a", "mp3"]
    assert result["resolutions"] == [
        {
            "resolution": "1080p",
            "height": 1080,
            "fps": 25,
            "hdr": False,
            "file_types": ["mp4", "mov"],
        }
    ]


def test_resolutions_are_grouped_labelled_and_largest_first() -> None:
    info = VideoInfo("abcdefghijk", "Clip", "Channel", "UC", 60.0, False)
    formats = FormatList(
        info,
        (
            video(299, "h264", 1080, fps=60),
            video(701, "av1", 2160, fps=60, hdr=True),
            video(315, "vp9", 2160, fps=60),
            video(399, "av1", 1080, fps=60),
            video(136, "h264", 720, fps=30),
            Format(140, "audio", "mp4", "aac", "mp4a.40.2"),
            Format(251, "audio", "webm", "opus", "opus"),
        ),
    )

    result = formats_out(formats).model_dump()

    assert result["file_types"] == ["mp4", "mov", "m4a", "mp3"]
    assert [(r["resolution"], r["file_types"]) for r in result["resolutions"]] == [
        ("2160p60 HDR", ["mp4"]),
        ("1080p60", ["mp4", "mov"]),
        ("720p", ["mp4", "mov"]),
    ]
    without_aac = formats_out(FormatList(info, (video(399, "av1", 1080), formats[6])))
    assert (without_aac.file_types, without_aac.resolutions) == ([], [])


def test_a_translation_is_embedded_and_shown_by_default(tmp_path: Path) -> None:
    server = build_server(Client(transport=FakeYouTube()), Config(download_dir=tmp_path))

    result = output(
        call(
            server,
            "download",
            {"video": VIDEO_ID, "translated_subtitles": [{"language": "tr", "srt": TURKISH}]},
        )
    )

    assert result["embedded_subtitles"] == ["tr"]
    subtitle = read_movie(Path(result["path"])).tracks[2]
    assert (subtitle.extended_language, subtitle.name, subtitle.flags & 1) == (
        "tr",
        "Turkish (AI: assistant)",
        1,
    )


def test_youtube_tracks_and_a_translation_together(tmp_path: Path) -> None:
    server = build_server(Client(transport=FakeYouTube()), Config(download_dir=tmp_path))

    result = output(
        call(
            server,
            "download",
            {
                "video": VIDEO_ID,
                "subtitles": ["en"],
                "translated_subtitles": [{"language": "tr", "srt": TURKISH}],
            },
        )
    )

    assert result["embedded_subtitles"] == ["en", "tr"]
    tracks = read_movie(Path(result["path"])).tracks[2:]
    assert [(track.extended_language, track.flags & 1) for track in tracks] == [
        ("en", 0),
        ("tr", 1),
    ]


def test_a_translation_that_is_not_subtitles_is_refused_before_any_download(
    tmp_path: Path,
) -> None:
    youtube = FakeYouTube()
    server = build_server(Client(transport=youtube), Config(download_dir=tmp_path))

    result = call(
        server,
        "download",
        {"video": VIDEO_ID, "translated_subtitles": [{"language": "tr", "srt": "Merhaba"}]},
    )

    assert "no subtitle cue" in error_text(result)
    assert youtube.media.requests == []


def test_resolution_reaches_the_download(tmp_path: Path) -> None:
    server = build_server(Client(transport=FakeYouTube()), Config(download_dir=tmp_path))

    smaller = call(server, "download", {"video": VIDEO_ID, "resolution": 720})
    fitting = output(call(server, "download", {"video": VIDEO_ID, "resolution": 1080}))

    assert "up to 720p" in error_text(smaller)
    assert fitting["skipped"] is False


def test_overwrite_downloads_a_file_that_is_already_there(tmp_path: Path) -> None:
    youtube = ManyVideos()
    server = build_server(Client(transport=youtube), Config(download_dir=tmp_path))
    output(call(server, "download", {"video": VIDEO, "format": "m4a"}))
    players = len(youtube.players)

    again = output(call(server, "download", {"video": VIDEO, "format": "m4a", "overwrite": True}))

    assert again["skipped"] is False
    assert again["path"] == str(tmp_path / f"{NAME}.m4a")
    assert len(youtube.players) > players


def test_save_subtitles_writes_youtubes_track(tmp_path: Path) -> None:
    server = build_server(Client(transport=FakeYouTube()), Config(download_dir=tmp_path / "subs"))

    result = output(call(server, "save_subtitles", {"video": VIDEO_ID}))

    path = tmp_path / "subs" / f"{RICK} [{VIDEO_ID}].en.srt"
    assert result == {
        "path": str(path),
        "video_id": VIDEO_ID,
        "title": RICK,
        "language_code": "en",
        "language": "English",
        "format": "srt",
        "cues": 3,
    }
    assert "We're no strangers to love" in path.read_text(encoding="utf-8")


def test_save_subtitles_writes_the_assistants_translation(tmp_path: Path) -> None:
    server = build_server(Client(transport=FakeYouTube()), Config(download_dir=tmp_path))

    result = output(
        call(
            server,
            "save_subtitles",
            {
                "video": VIDEO_ID,
                "translated_srt": TURKISH,
                "translated_language": "tr",
                "format": "vtt",
            },
        )
    )

    path = tmp_path / f"{RICK} [{VIDEO_ID}].tr.vtt"
    assert (result["path"], result["language"], result["cues"]) == (str(path), "Turkish", 2)
    assert path.read_text(encoding="utf-8") == (
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nMerhaba\n\n00:00:02.000 --> 00:00:03.500\nDunya\n"
    )


def test_save_subtitles_needs_the_language_of_a_translation(tmp_path: Path) -> None:
    server = build_server(Client(transport=FakeYouTube()), Config(download_dir=tmp_path))

    result = call(server, "save_subtitles", {"video": VIDEO_ID, "translated_srt": TURKISH})

    assert "translated_language" in error_text(result)
    assert list(tmp_path.iterdir()) == []


def test_language_codes_cannot_steer_files_out_of_the_download_folder(tmp_path: Path) -> None:
    folder = tmp_path / "downloads"
    server = build_server(Client(transport=FakeYouTube()), Config(download_dir=folder))
    escape = "tr/../../escaped"

    saved = call(
        server,
        "save_subtitles",
        {"video": VIDEO_ID, "translated_srt": TURKISH, "translated_language": escape},
    )
    embedded = call(
        server,
        "download",
        {"video": VIDEO_ID, "translated_subtitles": [{"language": escape, "srt": TURKISH}]},
    )

    assert saved.is_error is True
    assert embedded.is_error is True
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


def test_regional_language_codes_name_the_file(tmp_path: Path) -> None:
    server = build_server(Client(transport=FakeYouTube()), Config(download_dir=tmp_path))

    result = output(
        call(
            server,
            "save_subtitles",
            {"video": VIDEO_ID, "translated_srt": TURKISH, "translated_language": "pt-BR"},
        )
    )

    assert result["path"] == str(tmp_path / f"{RICK} [{VIDEO_ID}].pt-BR.srt")


def test_translations_become_files_next_to_audio_and_in_sidecar_mode(tmp_path: Path) -> None:
    server = build_server(Client(transport=FakeYouTube()), Config(download_dir=tmp_path))
    translated = [{"language": "tr", "srt": TURKISH}]
    sidecar = str(tmp_path / f"{RICK} [{VIDEO_ID}].tr.srt")

    audio = output(
        call(
            server,
            "download",
            {"video": VIDEO_ID, "format": "m4a", "translated_subtitles": translated},
        )
    )
    video = output(
        call(
            server,
            "download",
            {"video": VIDEO_ID, "subtitle_mode": "sidecar", "translated_subtitles": translated},
        )
    )

    assert (audio["embedded_subtitles"], audio["sidecars"]) == ([], [sidecar])
    assert (video["embedded_subtitles"], video["sidecars"]) == ([], [sidecar])


def test_a_resolution_lists_the_picture_download_takes_for_each_file_type() -> None:
    info = VideoInfo("abcdefghijk", "Clip", "Channel", "UC", 60.0, False)
    same_height = FormatList(
        info,
        (
            video(699, "av1", 1080, fps=60, hdr=True),
            video(399, "av1", 1080, fps=60),
            video(299, "h264", 1080, fps=60),
            Format(140, "audio", "mp4", "aac", "mp4a.40.2"),
        ),
    )
    differing = FormatList(
        info,
        (
            video(399, "av1", 1080, fps=60),
            video(137, "h264", 1080, fps=30),
            Format(140, "audio", "mp4", "aac", "mp4a.40.2"),
        ),
    )

    assert [(r.resolution, r.file_types) for r in formats_out(same_height).resolutions] == [
        ("1080p60", ["mp4", "mov"])
    ]
    assert [(r.resolution, r.file_types) for r in formats_out(differing).resolutions] == [
        ("1080p60", ["mp4"]),
        ("1080p", ["mov"]),
    ]
