"""Tests for the HTTP value types."""

from __future__ import annotations

import pytest

from utmax.transport import HttpRequest, HttpResponse


def test_response_headers_are_case_insensitive() -> None:
    response = HttpResponse(
        status=200, url="u", headers={"Content-Type": "application/json", "X-A": "1"}
    )
    assert response.header("content-type") == "application/json"
    assert response.header("CONTENT-TYPE") == "application/json"
    assert response.content_type == "application/json"
    assert response.header("missing") is None
    assert dict(response.headers) == {"content-type": "application/json", "x-a": "1"}


def test_response_text_and_json() -> None:
    response = HttpResponse(status=200, url="u", body='{"ok": "♪"}'.encode())
    assert response.text == '{"ok": "♪"}'
    assert response.json() == {"ok": "♪"}
    assert HttpResponse(status=200, url="u").content_type == ""
    with pytest.raises(ValueError, match="Expecting value"):
        HttpResponse(status=200, url="u", body=b"<html>").json()


def test_request_defaults() -> None:
    request = HttpRequest("GET", "https://www.youtube.com/")
    assert (request.headers, request.body) == ({}, None)
