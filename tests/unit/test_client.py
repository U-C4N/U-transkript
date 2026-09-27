"""Tests for utmax.Client."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.helpers.fake_transport import FakeTransport, json_response, text_response
from tests.helpers.youtube import MANUAL_JSON3, VIDEO_ID, player_payload, standard_youtube
from utmax import Client
from utmax.errors import InvalidOption


@pytest.mark.parametrize(
    "options",
    [
        {"timeout": 0},
        {"retries": -1},
        {"block_retries": -1},
        {"proxy": "http://proxy.example:8080", "transport": FakeTransport()},
        {"proxy": "socks5://127.0.0.1:1080"},
    ],
)
def test_bad_options_are_rejected(options: dict[str, object]) -> None:
    with pytest.raises(InvalidOption):
        Client(**options)  # type: ignore[arg-type]


def test_client_fetches_and_is_a_context_manager() -> None:
    with Client(transport=standard_youtube(repeat=True)) as client:
        assert client.fetch(VIDEO_ID).segments[1].text == "♪ We're no strangers to love ♪"
        assert client.list_tracks(VIDEO_ID).video.video_id == VIDEO_ID
        assert client.video_info(VIDEO_ID).title.startswith("Rick Astley")


def test_one_client_is_safe_to_share_between_threads() -> None:
    client = Client(transport=standard_youtube(repeat=True))
    with ThreadPoolExecutor(max_workers=8) as pool:
        texts = list(pool.map(lambda _: client.fetch(VIDEO_ID).text, range(32)))
    assert len(texts) == 32
    assert len(set(texts)) == 1


def test_block_retries_reach_innertube() -> None:
    transport = FakeTransport()
    transport.add("POST", "/player", text_response("", status=429), json_response(player_payload()))
    transport.add("GET", "lang=en&fmt=json3", json_response(MANUAL_JSON3))
    assert Client(transport=transport, block_retries=1).fetch(VIDEO_ID).language_code == "en"
