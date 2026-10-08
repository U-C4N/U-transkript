"""The download tool: files land in the download folder, progress reaches the client, an
existing file is not downloaded again, and a cancelled call stops the download."""

from __future__ import annotations

import itertools
import logging
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


def assert_rising(updates: list[Update]) -> None:
    """MCP clients expect the progress of a call to grow with every notification."""
    progress = [value for value, _, _ in updates]
    assert all(before < after for before, after in itertools.pairwise(progress)), updates


class ScriptedClient:
    """Reports the progress it is given as utmax does (every phase counts from zero), then stops."""

    def __init__(self, updates: list[tuple[str, int, int | None]]) -> None:
        self.updates = updates

    def download(self, video: str, path: Path, **options: Any) -> Any:
        for phase, done, total in self.updates:
            options["progress"](Progress(video, phase, done, total))
        raise DownloadCancelled("Stopped.")


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


@pytest.mark.parametrize("container", ["m4a", "mp4", "mov"])
def test_progress_only_rises_from_the_first_byte_to_the_finished_file(
    tmp_path: Path, container: str
) -> None:
    server = build_server(Client(transport=ManyVideos()), Config(download_dir=tmp_path))
    updates: list[Update] = []

    result = call(server, {"video": VIDEO, "format": container}, updates)

    assert result.is_error is False, result.content
    messages = [message for _, _, message in updates]
    assert "muxing" in messages
    assert messages[-1] == "finished"
    assert_rising(updates)
    assert all(total is None or progress <= total for progress, total, _ in updates)
    filled = [progress / total for progress, total, _ in updates if total]
    assert filled == sorted(filled)  # one bar for the whole call: it never empties again
    assert filled[-1] == 1


@pytest.mark.parametrize(
    ("given", "sent"),
    [
        pytest.param(
            [
                ("downloading", 0, 56005),
                ("downloading", 56005, 56005),
                ("muxing", 1318, 53602),
                ("finished", 53602, 53602),
            ],
            [
                (0, 112010, "downloading: 0.0 of 0.1 MB"),
                (56005, 112010, "downloading: 0.1 of 0.1 MB"),
                (57382, 112010, "muxing"),
                (112010, 112010, "finished"),
            ],
            id="the download fills the first half and muxing the second",
        ),
        pytest.param(
            [
                ("downloading", 0, 900),
                ("downloading", 900, 900),
                ("converting", 0, None),
                ("finished", 700, 700),
            ],
            [
                (0, 1800, "downloading: 0.0 of 0.0 MB"),
                (900, 1800, "downloading: 0.0 of 0.0 MB"),
                (901, 1800, "converting"),
                (1800, 1800, "finished"),
            ],
            id="a conversion that cannot count waits at half",
        ),
        pytest.param(
            [
                ("downloading", 100, 100),
                ("muxing", 0, 90),
                ("muxing", 0, 90),
                ("muxing", 90, 90),
                ("finished", 90, 90),
            ],
            [
                (100, 200, "downloading: 0.0 of 0.0 MB"),
                (101, 200, "muxing"),
                (200, 200, "muxing"),
                (201, 201, "finished"),
            ],
            id="every phase is announced even when it adds nothing",
        ),
        pytest.param(
            [
                ("downloading", 10, 100),
                ("downloading", 10, 100),
                ("downloading", 5, 100),
                ("downloading", 20, 100),
            ],
            [
                (10, 200, "downloading: 0.0 of 0.0 MB"),
                (20, 200, "downloading: 0.0 of 0.0 MB"),
            ],
            id="a repeat or a step back is left out",
        ),
        pytest.param(
            [("downloading", 5, None), ("downloading", 50, 100), ("finished", 90, 90)],
            [
                (5, None, "downloading: 0.0 MB"),
                (50, 200, "downloading: 0.0 of 0.0 MB"),
                (200, 200, "finished"),
            ],
            id="the total is sent once the size is known",
        ),
    ],
)
def test_one_bar_fills_through_the_phases_of_a_download(
    tmp_path: Path,
    given: list[tuple[str, int, int | None]],
    sent: list[tuple[int, int | None, str]],
) -> None:
    seen: list[tuple[float, float | None, str | None]] = []

    async def report(progress: float, total: float | None, message: str | None) -> None:
        seen.append((progress, total, message))

    async def main() -> Any:
        return await download_file(ScriptedClient(given), tmp_path, VIDEO, report=report)

    with pytest.raises(ToolError):
        anyio.run(main)

    assert seen == sent


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


def test_a_download_named_after_its_id_is_skipped_too(tmp_path: Path) -> None:
    youtube = ManyVideos({VIDEO: " . "})  # nothing of this title is left for a file name
    server = build_server(Client(transport=youtube), Config(download_dir=tmp_path))
    first = call(server, {"video": VIDEO, "format": "m4a"})
    players = list(youtube.players)

    again = call(server, {"video": VIDEO, "format": "m4a"})

    assert first.structured_content is not None
    assert first.structured_content["path"] == str(tmp_path / f"{VIDEO}.m4a")
    assert again.structured_content is not None
    assert again.structured_content["skipped"] is True
    assert again.structured_content["path"] == first.structured_content["path"]
    assert again.structured_content["title"] == VIDEO  # the file name is all there is
    assert youtube.players == players


def test_other_formats_of_the_same_video_are_still_downloaded(tmp_path: Path) -> None:
    (tmp_path / f"{NAME}.m4a").write_bytes(b"audio")
    server = build_server(Client(transport=ManyVideos()), Config(download_dir=tmp_path))

    result = call(server, {"video": VIDEO})

    assert result.structured_content is not None
    assert result.structured_content["skipped"] is False


def test_a_subtitle_file_from_an_earlier_download_does_not_block_a_later_one(
    tmp_path: Path,
) -> None:
    server = build_server(Client(transport=ManyVideos()), Config(download_dir=tmp_path))

    audio = call(server, {"video": VIDEO, "format": "m4a", "subtitles": ["en"]})
    video = call(
        server,
        {"video": VIDEO, "format": "mp4", "subtitles": ["en"], "subtitle_mode": "sidecar"},
    )

    sidecar = str(tmp_path / f"{NAME}.en.srt")
    assert audio.structured_content is not None
    assert audio.structured_content["sidecars"] == [sidecar]
    assert video.is_error is False, video.content
    assert video.structured_content is not None
    assert video.structured_content["skipped"] is False
    assert video.structured_content["sidecars"] == [sidecar]


def test_a_subtitle_file_left_behind_without_its_video_is_replaced(tmp_path: Path) -> None:
    sidecar = tmp_path / f"{NAME}.en.srt"
    sidecar.write_text("left behind", encoding="utf-8")
    server = build_server(Client(transport=ManyVideos()), Config(download_dir=tmp_path))

    result = call(server, {"video": VIDEO, "format": "m4a", "subtitles": ["en"]})

    assert result.is_error is False, result.content
    assert sidecar.read_text(encoding="utf-8") != "left behind"


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
    text = result.content[0].text
    assert text.startswith("Error executing tool download: ")
    assert "file.txt" in text
    assert text.endswith(
        "Suggestion: check that UTMAX_DOWNLOAD_DIR names a folder the MCP server can create and "
        "write to."
    )


def test_a_download_folder_that_cannot_be_searched_is_a_tool_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_is_dir = Path.is_dir

    def is_dir(self: Path, *args: Any, **kwargs: Any) -> bool:
        if self == tmp_path:
            raise PermissionError("the download folder cannot be searched")
        return real_is_dir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    youtube = ManyVideos()
    server = build_server(Client(transport=youtube), Config(download_dir=tmp_path))

    result = call(server, {"video": VIDEO, "format": "m4a"})

    assert result.is_error is True
    assert "the download folder cannot be searched" in result.content[0].text
    assert youtube.players == []


def test_a_file_that_vanishes_before_it_is_measured_is_a_tool_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = tmp_path / f"{NAME}.m4a"
    existing.write_bytes(b"audio")
    real_stat = Path.stat

    def stat(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == existing:
            raise FileNotFoundError("the file vanished")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    youtube = ManyVideos()
    server = build_server(Client(transport=youtube), Config(download_dir=tmp_path))

    result = call(server, {"video": VIDEO, "format": "m4a"})

    assert result.is_error is True
    assert "the file vanished" in result.content[0].text
    assert youtube.players == []


def test_progress_that_cannot_be_reported_does_not_stop_the_download(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def broken(progress: float, total: float | None, message: str | None) -> None:
        raise RuntimeError("the client went away")

    async def main() -> Any:
        return await download_file(
            Client(transport=ManyVideos()), tmp_path, VIDEO, format="m4a", report=broken
        )

    with caplog.at_level(logging.DEBUG, logger="utmax.mcp"):
        result = anyio.run(main)

    assert result.skipped is False
    assert Path(result.path).exists()
    failures = [r for r in caplog.records if "report download progress" in r.getMessage()]
    assert len(failures) > 1
    assert failures[0].levelno == logging.WARNING
    assert failures[0].exc_info is not None
    assert failures[0].exc_info[0] is RuntimeError
    assert {record.levelno for record in failures[1:]} == {logging.DEBUG}


def test_progress_after_the_call_was_cancelled_is_not_reported(tmp_path: Path) -> None:
    class LateClient:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.finished = threading.Event()

        def download(self, video: str, path: Path, **options: Any) -> Any:
            self.started.set()
            options["cancel"].wait(10)
            options["progress"](Progress(video, "downloading", 5, None))
            self.finished.set()
            raise DownloadCancelled("Stopped.")

    client = LateClient()
    reported: list[float] = []

    async def report(progress: float, total: float | None, message: str | None) -> None:
        reported.append(progress)

    async def main() -> None:
        async with anyio.create_task_group() as group:
            group.start_soon(lambda: download_file(client, tmp_path, VIDEO, report=report))
            assert await anyio.to_thread.run_sync(client.started.wait, 10)
            group.cancel_scope.cancel()
        await anyio.to_thread.run_sync(client.finished.wait, 10)

    anyio.run(main)

    assert client.finished.is_set()
    assert reported == []


def test_cancelling_the_call_stops_the_download(tmp_path: Path) -> None:
    client = SlowClient()

    async def main() -> None:
        async with anyio.create_task_group() as group:
            group.start_soon(lambda: download_file(client, tmp_path, VIDEO))
            assert await anyio.to_thread.run_sync(client.started.wait, 10)
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
