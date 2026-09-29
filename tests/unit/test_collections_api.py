"""Tests for utmax.list_videos, fetch_many, translate_many and download_many."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import utmax
from tests.helpers.browse import vr_page
from tests.helpers.bulk import IDS, TITLES, ManyVideos
from tests.helpers.fake_translator import FakeTranslator
from tests.helpers.fake_transport import FakeTransport, json_response
from utmax import Client
from utmax.models import VideoEntry, VideoList

PARAMETERS = {
    "list_videos": ["source", "kind", "limit"],
    "fetch_many": [
        "videos",
        "out_dir",
        "format",
        "languages",
        "include_manual",
        "include_generated",
        "concurrency",
        "skip_existing",
        "filename",
        "progress",
    ],
    "translate_many": [
        "videos",
        "to",
        "model",
        "out_dir",
        "format",
        "languages",
        "bilingual",
        "instructions",
        "resegment",
        "concurrency",
        "skip_existing",
        "filename",
        "progress",
        "options",
    ],
    "download_many": [
        "videos",
        "out_dir",
        "format",
        "quality",
        "subtitles",
        "subtitle_mode",
        "concurrency",
        "skip_existing",
        "filename",
        "ffmpeg",
        "progress",
    ],
}


@pytest.mark.parametrize("name", sorted(PARAMETERS))
def test_the_facade_and_the_client_take_the_same_arguments(name: str) -> None:
    facade = inspect.signature(getattr(utmax, name))
    method = inspect.signature(getattr(Client, name))
    assert list(facade.parameters) == PARAMETERS[name]
    assert list(method.parameters) == ["self", *PARAMETERS[name]]
    for parameter in facade.parameters.values():
        twin = method.parameters[parameter.name]
        assert (twin.kind, twin.default) == (parameter.kind, parameter.default)
    assert name in utmax.__all__


def test_list_videos_uses_the_default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeTransport()
    transport.add(
        "POST", "/youtubei/v1/browse", json_response(vr_page("aaaaaaaaaaa", count="1 video"))
    )
    monkeypatch.setattr(utmax, "_default_client", Client(transport=transport))
    videos = utmax.list_videos("PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI", limit=5)
    assert [(entry.video_id, entry.index) for entry in videos] == [("aaaaaaaaaaa", 1)]
    assert (videos.title, videos.video_count) == ("A playlist", 1)


def test_bulk_calls_use_the_default_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(utmax, "_default_client", Client(transport=ManyVideos()))
    fetched = utmax.fetch_many(IDS[:2], out_dir=tmp_path, format="vtt")
    assert [result.path for result in fetched] == [tmp_path / f"{i}.en.vtt" for i in IDS[:2]]
    translated = utmax.translate_many(IDS[:1], "tr", model=FakeTranslator(), bilingual=True)
    assert translated[0].value is not None
    assert translated[0].value.language_code == "en+tr"
    downloaded = utmax.download_many(IDS[:1], tmp_path, format="m4a")
    assert downloaded[0].path == tmp_path / f"{TITLES[IDS[0]]} [{IDS[0]}].m4a"


def test_video_lists_feed_the_bulk_calls(tmp_path: Path) -> None:
    entries = tuple(
        VideoEntry(video_id, TITLES[video_id], 60.0, "Rick Astley", "UC" + "x" * 22, index)
        for index, video_id in enumerate(IDS, start=1)
    )
    videos = VideoList("Uploads from Rick Astley", "UU" + "x" * 22, "all", 3, entries)
    client = Client(transport=ManyVideos())
    report = client.fetch_many(videos, out_dir=tmp_path, filename="{index:02d} {video_id}.{ext}")
    assert [result.path for result in report] == [
        tmp_path / f"{index:02d} {video_id}.srt" for index, video_id in enumerate(IDS, start=1)
    ]
