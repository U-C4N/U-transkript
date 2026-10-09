"""Tests for the InnerTube client profiles."""

from __future__ import annotations

from utmax.core.clients import ANDROID, ANDROID_VR, IOS, ORDER, PROFILES, VISIONOS, WEB


def test_context_payload_introduces_the_app_in_english() -> None:
    client = ANDROID.context_payload()["client"]
    assert client["clientName"] == "ANDROID"
    assert client["clientVersion"] == "20.10.38"
    assert client["androidSdkVersion"] == 30
    assert (client["hl"], client["gl"]) == ("en", "US")
    assert "visitorData" not in client


def test_request_headers_match_the_profile() -> None:
    headers = ANDROID_VR.request_headers()
    assert headers["X-YouTube-Client-Name"] == "28"
    assert headers["X-YouTube-Client-Version"] == "1.62.27"
    assert headers["User-Agent"].startswith("com.google.android.apps.youtube.vr.oculus/")
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept-Encoding"] == "gzip"
    assert "X-Goog-Visitor-Id" not in headers


def test_visionos_introduces_itself_as_the_vision_pro_app_with_a_visitor() -> None:
    client = VISIONOS.context_payload("visitor-1")["client"]
    assert (client["clientName"], client["clientVersion"]) == ("VISIONOS", "1.02")
    assert (client["deviceMake"], client["deviceModel"]) == ("Apple", "RealityDevice17,1")
    assert (client["osName"], client["hl"]) == ("visionOS", "en")
    assert client["visitorData"] == "visitor-1"
    headers = VISIONOS.request_headers("visitor-1")
    assert headers["X-YouTube-Client-Name"] == "101"
    assert headers["X-Goog-Visitor-Id"] == "visitor-1"
    assert "Safari/" in headers["User-Agent"]
    assert VISIONOS.needs_visitor
    assert not any(profile.needs_visitor for profile in (ANDROID, IOS, ANDROID_VR, WEB))


def test_fallback_orders() -> None:
    assert ORDER["captions"] == (ANDROID, IOS, ANDROID_VR)
    assert ORDER["streams"] == (VISIONOS, ANDROID_VR)
    assert ORDER["browse"] == (ANDROID_VR, WEB)
    assert ORDER["resolve"] == (ANDROID_VR, WEB)
    assert len({profile.name for profile in (ANDROID, IOS, ANDROID_VR, VISIONOS, WEB)}) == 5
    assert PROFILES["VISIONOS"] is VISIONOS
