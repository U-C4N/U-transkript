"""Tests for utmax.list_videos, fetch_many, translate_many and download_many."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
        "resolution",
        "subtitles",
        "subtitle_mode",
        "concurrency",
        "skip_existing",
        "filename",
        "ffmpeg",
        "progress",
    ],
}
# The Client attribute that holds the service behind each call.
SERVICES = {
    "list_videos": "_collections",
    "fetch_many": "_bulk",
    "translate_many": "_bulk",
    "download_many": "_bulk",
}


class Spy:
    """Stands in for a service: records every call and answers each with the same object."""

    def __init__(self) -> None:
        self.answer = object()
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Callable[..., object]:
        def record(*args: Any, **kwargs: Any) -> object:
            self.calls.append((name, args, kwargs))
            return self.answer

        return record


def contract(function: Callable[..., object]) -> tuple[list[inspect.Parameter], object]:
    """Name, kind, default and annotation of every parameter, then the result's annotation.

    The annotations are evaluated, so it is the types that are compared, not how they are spelled.
    """
    signature = inspect.signature(function, eval_str=True)
    return list(signature.parameters.values()), signature.return_annotation


@pytest.mark.parametrize("name", sorted(PARAMETERS))
def test_the_facade_and_the_client_take_the_arguments_of_the_service(name: str) -> None:
    client = Client(transport=FakeTransport())
    service = contract(getattr(getattr(client, SERVICES[name]), name))
    assert [parameter.name for parameter in service[0]] == PARAMETERS[name]
    assert contract(getattr(client, name)) == service
    assert contract(getattr(utmax, name)) == service
    assert name in utmax.__all__


@pytest.mark.parametrize("layer", ["facade", "client"])
@pytest.mark.parametrize("name", sorted(PARAMETERS))
def test_every_argument_reaches_the_service_under_its_own_name(
    name: str, layer: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each layer hands every argument on, unchanged and under its own name, and the result back."""
    client = Client(transport=FakeTransport())
    call = getattr(utmax if layer == "facade" else client, name)
    signature = inspect.signature(getattr(getattr(client, SERVICES[name]), name))
    spy = Spy()
    monkeypatch.setattr(client, SERVICES[name], spy)
    monkeypatch.setattr(utmax, "_default_client", client)
    # Every parameter gets a value of its own, and **options two more keys.
    values = {parameter: f"<{parameter}>" for parameter in PARAMETERS[name]}
    if "options" in values:
        del values["options"]
        values |= {"first_option": "<first_option>", "second_option": "<second_option>"}
    given = inspect.signature(call).bind(**values)
    assert call(*given.args, **given.kwargs) is spy.answer
    assert [method for method, _, _ in spy.calls] == [name]
    _, args, kwargs = spy.calls[0]
    assert signature.bind(*args, **kwargs).arguments == given.arguments


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
