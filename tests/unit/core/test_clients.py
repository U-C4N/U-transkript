"""Tests for the InnerTube client profiles."""

from __future__ import annotations

from utmax.core.clients import ANDROID, ANDROID_VR, IOS, ORDER, WEB


def test_context_payload_introduces_the_app_in_english() -> None:
    client = ANDROID.context_payload()["client"]
    assert client["clientName"] == "ANDROID"
    assert client["clientVersion"] == "20.10.38"
    assert client["androidSdkVersion"] == 30
    assert (client["hl"], client["gl"]) == ("en", "US")


def test_request_headers_match_the_profile() -> None:
    headers = ANDROID_VR.request_headers()
    assert headers["X-YouTube-Client-Name"] == "28"
    assert headers["X-YouTube-Client-Version"] == "1.62.27"
    assert headers["User-Agent"].startswith("com.google.android.apps.youtube.vr.oculus/")
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept-Encoding"] == "gzip"


def test_fallback_orders() -> None:
    assert ORDER["captions"] == (ANDROID, IOS, ANDROID_VR)
    assert ORDER["streams"] == (ANDROID_VR, ANDROID, IOS)
    assert ORDER["browse"] == (ANDROID_VR, WEB)
    assert ORDER["resolve"] == (ANDROID_VR, WEB)
    assert len({profile.name for profile in (ANDROID, IOS, ANDROID_VR, WEB)}) == 4
