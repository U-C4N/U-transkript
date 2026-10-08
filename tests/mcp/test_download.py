"""The download tool: files land in the download folder, progress reaches the client, an
existing file is not downloaded again, and a cancelled call stops the download."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client as MCPClient
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult

from tests.helpers.bulk import IDS, TITLES, ManyVideos
from utmax import Client
from utmax.errors import DownloadCancelled
from utmax.mcp import server as mcp_server
from utmax.mcp.config import Config
from utmax.mcp.server import build_server, download_file
from utmax.models import Progress

VIDEO = IDS[0]
NAME = f"{TITLES[VIDEO]} [{VIDEO}]"
Update = tuple[float, float | None, str | None]


def call(
    server: Any, arguments: dict[str, Any], updates: list[Update] | None = None
) -> CallToolResult:
    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        if updates is not None:
            updates.append((progress, total, message))

    async def main() -> CallToolResult:
        async with MCPClient(server, raise_exceptions=True) as client:
            return await client.call_tool("download", arguments, progress_callback=on_progress)

    return anyio.run(main)


class SlowClient:
    """Downloads until the call is cancelled, then stops like utmax does."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.cancel: threading.Event | None = None

    def download(self, video: str, path: Path, **options: Any) -> Any:
        self.cancel = options["cancel"]
        self.started.set()
        if not self.cancel.wait(10):
            raise AssertionError("the download was never cancelled")
        raise DownloadCancelled("Stopped.")


def test_audio_lands_in_the_download_folder_with_progress(tmp_path: Path) -> None:
    folder = tmp_path / "downloads"
    server = build_server(Client(transport=ManyVideos()), Config(download_dir=folder))
    updates: list[Update] = []

    result = call(server, {"video": f"https://youtu.be/{VIDEO}", "format": "m4a"}, updates)

    assert result.is_error is False, result.content
    assert result.structured_content == {
        "path": str(folder / f"{NAME}.m4a"),
        "size_bytes": (folder / f"{NAME}.m4a").stat().st_size,
        "video_id": VIDEO,
        "title": TITLES[VIDEO],
        "container": "m4a",
        "embedded_subtitles": [],
        "sidecars": [],
        "skipped": False,
    }
    assert updates
    assert updates[-1][2] == "finished"
    assert all(total is None or progress <= total for progress, total, _ in updates)


def test_videos_embed_or_add_the_requested_subtitles(tmp_path: Path) -> None:
    server = build_server(Client(transport=ManyVideos()), Config(download_dir=tmp_path))

    embedded = call(server, {"video": VIDEO})
    sidecars = call(
        server,
        {
            "video": IDS[1],
            "format": "mov",
            "subtitles": ["en", "de"],
            "subtitle_mode": "sidecar",
        },
    )

    assert embedded.structured_content is not None
    assert embedded.structured_content["embedded_subtitles"] == ["en"]
    assert embedded.structured_content["path"] == str(tmp_path / f"{NAME}.mp4")
    assert sidecars.structured_content is not None
    stem = f"{TITLES[IDS[1]]} [{IDS[1]}]"
    assert sidecars.structured_content["sidecars"] == [
        str(tmp_path / f"{stem}.en.srt"),
        str(tmp_path / f"{stem}.de-DE.srt"),
    ]


def test_a_file_already_downloaded_is_skipped_without_a_request(tmp_path: Path) -> None:
    youtube = ManyVideos()
    server = build_server(Client(transport=youtube), Config(download_dir=tmp_path))
    first = call(server, {"video": VIDEO, "format": "m4a"})
    players = list(youtube.players)

    again = call(server, {"video": VIDEO, "format": "m4a"})

    assert youtube.players == players
    assert first.structured_content is not None
    assert again.structured_content == {
        **first.structured_content,
        "embedded_subtitles": [],
        "sidecars": [],
        "skipped": True,
    }


def test_other_formats_of_the_same_video_are_still_downloaded(tmp_path: Path) -> None:
    (tmp_path / f"{NAME}.m4a").write_bytes(b"audio")
    server = build_server(Client(transport=ManyVideos()), Config(download_dir=tmp_path))

    result = call(server, {"video": VIDEO})

    assert result.structured_content is not None
    assert result.structured_content["skipped"] is False


def test_bad_requests_fail_before_any_request(tmp_path: Path) -> None:
    youtube = ManyVideos()
    server = build_server(Client(transport=youtube), Config(download_dir=tmp_path))

    invalid = call(server, {"video": "not a video"})
    unknown = call(server, {"video": VIDEO, "format": "webm"})

    assert invalid.is_error is True
    assert "Suggestion: Pass a YouTube URL" in invalid.content[0].text
    assert unknown.is_error is True
    assert youtube.players == []


def test_a_download_folder_that_cannot_be_created_is_a_tool_error(tmp_path: Path) -> None:
    blocked = tmp_path / "file.txt"
    blocked.write_text("not a folder", encoding="utf-8")
    server = build_server(Client(transport=ManyVideos()), Config(download_dir=blocked))

    result = call(server, {"video": VIDEO, "format": "m4a"})

    assert result.is_error is True


def test_progress_that_cannot_be_reported_does_not_stop_the_download(tmp_path: Path) -> None:
    async def broken(update: Progress) -> None:
        raise RuntimeError("the client went away")

    async def main() -> Any:
        return await download_file(
            Client(transport=ManyVideos()), tmp_path, VIDEO, format="m4a", report=broken
        )

    result = anyio.run(main)

    assert result.skipped is False
    assert Path(result.path).exists()


def test_cancelling_the_call_stops_the_download(tmp_path: Path) -> None:
    client = SlowClient()

    async def main() -> None:
        async with anyio.create_task_group() as group:
            group.start_soon(lambda: download_file(client, tmp_path, VIDEO))
            await anyio.to_thread.run_sync(client.started.wait)
            group.cancel_scope.cancel()

    anyio.run(main)

    assert client.cancel is not None
    assert client.cancel.is_set()


def test_utmax_errors_become_tool_errors(tmp_path: Path) -> None:
    class FailingClient:
        def download(self, video: str, path: Path, **options: Any) -> Any:
            raise DownloadCancelled("Stopped.")

    async def main() -> Any:
        return await download_file(FailingClient(), tmp_path, VIDEO)

    with pytest.raises(ToolError, match=r"Stopped\. Suggestion: Run the same download again"):
        anyio.run(main)


def test_progress_is_optional_and_reads_well(tmp_path: Path) -> None:
    class ReportingClient:
        def download(self, video: str, path: Path, **options: Any) -> Any:
            options["progress"](Progress(video, "downloading", 5, None))
            raise DownloadCancelled("Stopped.")

    async def main() -> Any:
        return await download_file(ReportingClient(), tmp_path, VIDEO)

    with pytest.raises(ToolError):
        anyio.run(main)
    assert mcp_server._progress_message(Progress(VIDEO, "downloading", 1_500_000, None)) == (
        "downloading: 1.5 MB"
    )
    assert mcp_server._progress_message(Progress(VIDEO, "downloading", 0, 2_000_000)) == (
        "downloading: 0.0 of 2.0 MB"
    )
    assert mcp_server._progress_message(Progress(VIDEO, "muxing", 9, 9)) == "muxing"
