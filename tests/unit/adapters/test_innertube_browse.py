"""Tests for the InnerTube browse and resolve_url requests."""

from __future__ import annotations

import json

import pytest

from tests.helpers.fake_transport import FakeTransport, json_response, text_response
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.clients import ANDROID_VR, WEB
from utmax.errors import IpBlocked, YouTubeDataUnparsable, YouTubeRequestFailed

API = "https://www.youtube.com/youtubei/v1"
PAGE = {"contents": {"singleColumnBrowseResultsRenderer": {}}}


def test_browse_asks_for_the_first_page_of_a_playlist() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/browse", json_response(PAGE))
    answer = InnerTubeClient(transport).browse(ANDROID_VR, browse_id="VLPLtest")
    assert answer == PAGE
    (request,) = transport.requests
    assert request.url == f"{API}/browse?prettyPrint=false"
    assert request.headers["X-YouTube-Client-Name"] == "28"
    body = json.loads(request.body or b"{}")
    assert body == {"context": ANDROID_VR.context_payload(), "browseId": "VLPLtest"}


def test_browse_follows_a_continuation_token() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/browse", json_response(PAGE))
    InnerTubeClient(transport).browse(WEB, continuation="token-2")
    (request,) = transport.requests
    assert request.headers["X-YouTube-Client-Name"] == "1"
    body = json.loads(request.body or b"{}")
    assert body == {"context": WEB.context_payload(), "continuation": "token-2"}


def test_resolve_url_asks_about_one_url() -> None:
    answer = {"endpoint": {"browseEndpoint": {"browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"}}}
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/navigation/resolve_url", json_response(answer))
    url = "https://www.youtube.com/@RickAstleyYT"
    assert InnerTubeClient(transport).resolve_url(ANDROID_VR, url) == answer
    (request,) = transport.requests
    assert request.url == f"{API}/navigation/resolve_url?prettyPrint=false"
    body = json.loads(request.body or b"{}")
    assert body == {"context": ANDROID_VR.context_payload(), "url": url}


def test_rate_limits_are_retried_only_with_block_retries() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/browse", json_response({}, status=429))
    with pytest.raises(IpBlocked, match="HTTP 429") as caught:
        InnerTubeClient(transport).browse(ANDROID_VR, browse_id="VLPLtest")
    assert caught.value.video_id is None
    retried = FakeTransport()
    retried.add(
        "POST",
        "/youtubei/v1/navigation/resolve_url",
        json_response({}, status=429),
        json_response({"endpoint": {}}),
    )
    client = InnerTubeClient(retried, block_retries=1)
    assert client.resolve_url(WEB, "https://www.youtube.com/@x") == {"endpoint": {}}
    assert len(retried.requests) == 2


def test_http_errors_and_unreadable_answers() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        "/youtubei/v1/browse",
        json_response({"error": {"code": 404}}, status=404),
        text_response("<html>not json</html>"),
        json_response(["not", "an", "object"]),
    )
    client = InnerTubeClient(transport)
    with pytest.raises(YouTubeRequestFailed, match="HTTP 404") as caught:
        client.browse(ANDROID_VR, browse_id="VLUULVx")
    assert caught.value.status_code == 404
    with pytest.raises(YouTubeDataUnparsable, match="not JSON"):
        client.browse(ANDROID_VR, continuation="t")
    with pytest.raises(YouTubeDataUnparsable, match="unexpected JSON value"):
        client.browse(WEB, continuation="t")
