"""Tests for the visitorData that VISIONOS player requests carry.

Without one, YouTube answered VISIONOS with "Sign in to confirm you're not a bot" for 8 of 10
test videos on 2026-10-09; with one issued by ``visitor_id``, every one played.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import pytest

from tests.helpers.fake_transport import FakeTransport, json_response, text_response
from tests.helpers.youtube import (
    VIDEO_ID,
    VISITOR_DATA,
    player_payload,
    streaming_data,
    visitor_payload,
)
from utmax.adapters.innertube import InnerTubeClient
from utmax.errors import IpBlocked
from utmax.transport import HttpRequest

BOT_CHECK = player_payload(status="LOGIN_REQUIRED", reason="Sign in to confirm you're not a bot")


def playable() -> dict[str, Any]:
    return player_payload(streaming_data=streaming_data())


def players(transport: FakeTransport) -> list[HttpRequest]:
    return [request for request in transport.requests if "/youtubei/v1/player" in request.url]


def sent(request: HttpRequest) -> tuple[str, str | None, str | None]:
    """(client name, visitorData in the body, X-Goog-Visitor-Id header) of a player request."""
    client = json.loads(request.body or b"{}")["context"]["client"]
    return client["clientName"], client.get("visitorData"), request.headers.get("X-Goog-Visitor-Id")


def visitor_requests(transport: FakeTransport) -> int:
    return sum("/youtubei/v1/visitor_id" in url for url in transport.urls("POST"))


def test_visionos_asks_once_for_a_visitor_data_and_sends_it() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/visitor_id", json_response(visitor_payload()))
    transport.add("POST", "/youtubei/v1/player", json_response(playable()), repeat=True)
    innertube = InnerTubeClient(transport)
    innertube.player(VIDEO_ID, purpose="streams")
    innertube.player(VIDEO_ID, purpose="streams")
    assert transport.urls("POST")[0] == (
        "https://www.youtube.com/youtubei/v1/visitor_id?prettyPrint=false"
    )
    visitor_body = json.loads(transport.requests[0].body or b"{}")
    assert visitor_body["context"]["client"]["clientName"] == "VISIONOS"
    assert "visitorData" not in visitor_body["context"]["client"]
    assert [sent(request) for request in players(transport)] == [
        ("VISIONOS", VISITOR_DATA, VISITOR_DATA)
    ] * 2
    assert players(transport)[0].headers["X-YouTube-Client-Name"] == "101"
    assert innertube.visitor_data() == VISITOR_DATA
    assert visitor_requests(transport) == 1


def test_a_bot_check_renews_the_visitor_data_once() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        "/youtubei/v1/visitor_id",
        json_response(visitor_payload("first")),
        json_response(visitor_payload("second")),
    )
    transport.add(
        "POST", "/youtubei/v1/player", json_response(BOT_CHECK), json_response(playable())
    )
    player = InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert player.playability.status == "OK"
    assert [sent(request)[:2] for request in players(transport)] == [
        ("VISIONOS", "first"),
        ("VISIONOS", "second"),
    ]


def test_a_second_bot_check_moves_on_to_android_vr_without_a_visitor_data() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        "/youtubei/v1/visitor_id",
        json_response(visitor_payload("first")),
        json_response(visitor_payload("second")),
    )
    transport.add(
        "POST",
        "/youtubei/v1/player",
        json_response(BOT_CHECK),
        json_response(BOT_CHECK),
        json_response(playable()),
    )
    InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert [sent(request) for request in players(transport)] == [
        ("VISIONOS", "first", "first"),
        ("VISIONOS", "second", "second"),
        ("ANDROID_VR", None, None),
    ]


@pytest.mark.parametrize(
    "answer",
    [
        text_response("server error", status=503),
        text_response("<html>not json</html>"),
        json_response({"responseContext": {}}),
        json_response({"responseContext": {"visitorData": ""}}),
    ],
)
def test_without_a_visitor_data_the_request_goes_out_without_one(answer: Any) -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/visitor_id", answer, repeat=True)
    transport.add("POST", "/youtubei/v1/player", json_response(playable()), repeat=True)
    innertube = InnerTubeClient(transport)
    innertube.player(VIDEO_ID, purpose="streams")
    innertube.player(VIDEO_ID, purpose="streams")
    assert [sent(request) for request in players(transport)] == [("VISIONOS", None, None)] * 2
    assert visitor_requests(transport) == 2


def test_a_rate_limit_while_asking_for_a_visitor_data_is_final() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/visitor_id", json_response({}, status=429))
    with pytest.raises(IpBlocked):
        InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert players(transport) == []


def test_threads_share_one_visitor_data() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/visitor_id", json_response(visitor_payload()), repeat=True)
    transport.add("POST", "/youtubei/v1/player", json_response(playable()), repeat=True)
    innertube = InnerTubeClient(transport)
    barrier = threading.Barrier(8, timeout=5)
    errors: list[BaseException] = []

    def work() -> None:
        try:
            barrier.wait()
            innertube.player(VIDEO_ID, purpose="streams")
        except BaseException as error:  # pragma: no cover - reported below
            errors.append(error)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert visitor_requests(transport) == 1
    assert len(players(transport)) == 8


def test_renew_visitor_asks_for_a_new_visitor_data_first() -> None:
    """YouTube restricts the streams of some visitors (about one in six on 2026-10-09: their
    URLs serve only the start), so a download that meets 403s refreshes as a new visitor."""
    transport = FakeTransport()
    transport.add(
        "POST",
        "/youtubei/v1/visitor_id",
        json_response(visitor_payload("first")),
        json_response(visitor_payload("second")),
    )
    transport.add("POST", "/youtubei/v1/player", json_response(playable()), repeat=True)
    innertube = InnerTubeClient(transport)
    innertube.player(VIDEO_ID, purpose="streams")
    innertube.player(VIDEO_ID, purpose="streams", renew_visitor=True)
    assert [sent(request)[1] for request in players(transport)] == ["first", "second"]
    assert innertube.visitor_data() == "second"


def test_caption_requests_need_no_visitor_data() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(player_payload()))
    InnerTubeClient(transport).player(VIDEO_ID)
    assert [sent(request) for request in transport.requests] == [("ANDROID", None, None)]


class FirstVisitorBlocked:
    """Issues visitor-1, visitor-2, ...; answers players sent as visitor-1 with a bot check, once
    ``threads`` of them are waiting, so that every thread meets it before any renews."""

    def __init__(self, threads: int) -> None:
        self.issued = 0
        self._lock = threading.Lock()
        self._all_blocked = threading.Barrier(threads, timeout=5)

    def send(self, request: HttpRequest) -> Any:
        if "/youtubei/v1/visitor_id" in request.url:
            with self._lock:
                self.issued += 1
                return json_response(visitor_payload(f"visitor-{self.issued}"))
        client = json.loads(request.body or b"{}")["context"]["client"]
        if client.get("visitorData") == "visitor-1":
            self._all_blocked.wait()
            return json_response(BOT_CHECK)
        return json_response(playable())


def test_threads_that_meet_a_bot_check_renew_the_visitor_data_once() -> None:
    transport = FirstVisitorBlocked(threads=8)
    innertube = InnerTubeClient(transport)
    barrier = threading.Barrier(8, timeout=5)
    errors: list[BaseException] = []

    def work() -> None:
        try:
            barrier.wait()
            innertube.player(VIDEO_ID, purpose="streams")
        except BaseException as error:  # pragma: no cover - reported below
            errors.append(error)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert transport.issued == 2
    assert innertube.visitor_data() == "visitor-2"
