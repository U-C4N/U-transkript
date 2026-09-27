"""Tests for the module-level facade."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

import utmax
from tests.helpers.fake_transport import FakeTransport
from tests.helpers.youtube import VIDEO_ID, standard_youtube


def test_every_public_name_exists() -> None:
    for name in utmax.__all__:
        assert hasattr(utmax, name), name
    assert {
        "fetch",
        "list_tracks",
        "video_info",
        "Client",
        "Transcript",
        "NoTranscriptFound",
    } <= set(utmax.__all__)


def test_module_functions_use_the_default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        utmax, "_default_client", utmax.Client(transport=standard_youtube(repeat=True))
    )
    assert (
        utmax.fetch(f"https://youtu.be/{VIDEO_ID}").segments[1].text
        == "♪ We're no strangers to love ♪"
    )
    assert len(utmax.list_tracks(VIDEO_ID)) == 6
    assert utmax.video_info(VIDEO_ID).channel == "Rick Astley"


def test_the_default_client_is_created_once_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[utmax.Client] = []

    class CountingClient(utmax.Client):
        def __init__(self) -> None:
            created.append(self)
            super().__init__(transport=FakeTransport())

    monkeypatch.setattr(utmax, "_default_client", None)
    monkeypatch.setattr(utmax, "Client", CountingClient)
    with ThreadPoolExecutor(max_workers=8) as pool:
        clients = list(pool.map(lambda _: utmax._client(), range(32)))
    assert len(created) == 1
    assert all(client is created[0] for client in clients)
