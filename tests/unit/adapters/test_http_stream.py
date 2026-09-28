"""Tests for streamed responses and IPv4-only connections."""

from __future__ import annotations

import socket

import pytest

from tests.helpers.fake_transport import FakeTransport, text_response
from tests.helpers.http_server import MEDIA, ipv6_loopback_available, local_server
from utmax import Client
from utmax.adapters.http import BufferedStream, RetryingTransport, UrllibTransport, open_stream
from utmax.errors import InvalidOption, NetworkError
from utmax.transport import HttpRequest, HttpStream, StreamingTransport


def read_all(stream: HttpStream, piece: int = 1000) -> bytes:
    parts = []
    while data := stream.read(piece):
        parts.append(data)
    return b"".join(parts)


def test_streams_read_a_byte_range_in_pieces() -> None:
    with local_server() as base:
        request = HttpRequest("GET", f"{base}/media", {"Range": "bytes=10-4009"})
        stream = UrllibTransport().stream(request)
        try:
            assert stream.status == 206
            assert stream.header("Content-Range") == f"bytes 10-4009/{len(MEDIA)}"
            assert read_all(stream) == MEDIA[10:4010]
            assert stream.read(10) == b""
        finally:
            stream.close()


def test_streams_return_error_statuses_with_their_body() -> None:
    with local_server() as base:
        stream = UrllibTransport().stream(HttpRequest("GET", f"{base}/missing"))
        try:
            assert stream.status == 404
            assert read_all(stream) == b"nope"
        finally:
            stream.close()


def test_connection_failures_are_network_errors() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    request = HttpRequest("GET", f"http://127.0.0.1:{port}/media")
    with pytest.raises(NetworkError, match="Could not complete GET"):
        UrllibTransport(timeout=2).stream(request)


def test_bodies_that_end_early_come_back_short() -> None:
    with local_server() as base:
        stream = UrllibTransport().stream(HttpRequest("GET", f"{base}/truncated"))
        try:
            assert read_all(stream) == b"x" * 10
        finally:
            stream.close()


def test_connections_that_stall_mid_body_are_network_errors() -> None:
    with local_server() as base:
        stream = UrllibTransport(timeout=0.3).stream(HttpRequest("GET", f"{base}/stall"))
        try:
            with pytest.raises(NetworkError):
                read_all(stream)
        finally:
            stream.close()


def test_retrying_transport_streams_through_its_inner_transport() -> None:
    with local_server() as base:
        request = HttpRequest("GET", f"{base}/media", {"Range": "bytes=0-99"})
        stream = RetryingTransport(UrllibTransport()).stream(request)
        try:
            assert read_all(stream) == MEDIA[:100]
        finally:
            stream.close()


def test_open_stream_buffers_transports_that_cannot_stream() -> None:
    transport = FakeTransport()
    transport.add("GET", "/media", text_response("abcdef", status=206, content_type="video/mp4"))
    assert not isinstance(transport, StreamingTransport)
    stream = open_stream(transport, HttpRequest("GET", "https://media.test/media"))
    assert isinstance(stream, BufferedStream)
    assert (stream.status, stream.header("content-type")) == (206, "video/mp4")
    assert stream.read(4) + stream.read(4) + stream.read(4) == b"abcdef"
    stream.close()


def test_the_built_in_transports_can_stream() -> None:
    assert isinstance(UrllibTransport(), StreamingTransport)
    assert isinstance(RetryingTransport(FakeTransport()), StreamingTransport)


def test_force_ipv4_still_reaches_ipv4_servers() -> None:
    with local_server() as base:
        response = UrllibTransport(force_ipv4=True).send(HttpRequest("GET", f"{base}/json"))
    assert response.json() == {"ok": True}


def test_force_ipv4_refuses_ipv6_only_servers() -> None:
    if not ipv6_loopback_available():
        pytest.skip("this machine cannot listen on ::1")
    with local_server(ipv6=True) as base:
        request = HttpRequest("GET", f"{base}/json")
        assert UrllibTransport().send(request).status == 200
        ipv4_only = RetryingTransport(UrllibTransport(force_ipv4=True, timeout=2), retries=0)
        with pytest.raises(NetworkError):
            ipv4_only.send(request)


def test_client_force_ipv4_option() -> None:
    Client(force_ipv4=True)
    with pytest.raises(InvalidOption, match="force_ipv4"):
        Client(transport=FakeTransport(), force_ipv4=True)
