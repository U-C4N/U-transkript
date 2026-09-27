"""InnerTube client profiles: the single place to update when YouTube changes its apps.

Verified on 2026-09-27: ANDROID, IOS and ANDROID_VR return captions and direct stream URLs
without an API key or proof-of-origin token; ANDROID_VR returns no ``translationLanguages``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

__all__ = [
    "ANDROID",
    "ANDROID_VR",
    "DESKTOP_USER_AGENT",
    "IOS",
    "ORDER",
    "WEB",
    "ClientProfile",
    "Purpose",
]

Purpose = Literal["captions", "streams", "browse", "resolve"]

DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


@dataclass(frozen=True, slots=True)
class ClientProfile:
    """How utmax introduces itself to InnerTube as one of YouTube's apps."""

    name: str
    client_id: int
    version: str
    user_agent: str
    extra: tuple[tuple[str, str | int], ...] = ()

    def context_payload(self) -> dict[str, Any]:
        """The ``context`` object of an InnerTube request body."""
        client: dict[str, Any] = {"clientName": self.name, "clientVersion": self.version}
        client.update(self.extra)
        client.update({"hl": "en", "gl": "US"})
        return {"client": client}

    def request_headers(self) -> dict[str, str]:
        """HTTP headers for an InnerTube request made as this app."""
        return {
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
            "X-YouTube-Client-Name": str(self.client_id),
            "X-YouTube-Client-Version": self.version,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip",
        }


ANDROID = ClientProfile(
    name="ANDROID",
    client_id=3,
    version="20.10.38",
    user_agent="com.google.android.youtube/20.10.38 (Linux; U; Android 11) gzip",
    extra=(("androidSdkVersion", 30), ("osName", "Android"), ("osVersion", "11")),
)
IOS = ClientProfile(
    name="IOS",
    client_id=5,
    version="20.10.4",
    user_agent="com.google.ios.youtube/20.10.4 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)",
    extra=(
        ("deviceMake", "Apple"),
        ("deviceModel", "iPhone16,2"),
        ("osName", "iPhone"),
        ("osVersion", "18.3.2.22D82"),
    ),
)
ANDROID_VR = ClientProfile(
    name="ANDROID_VR",
    client_id=28,
    version="1.62.27",
    user_agent=(
        "com.google.android.apps.youtube.vr.oculus/1.62.27 "
        "(Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip"
    ),
    extra=(
        ("deviceMake", "Oculus"),
        ("deviceModel", "Quest 3"),
        ("androidSdkVersion", 32),
        ("osName", "Android"),
        ("osVersion", "12L"),
    ),
)
WEB = ClientProfile(
    name="WEB", client_id=1, version="2.20260925.01.00", user_agent=DESKTOP_USER_AGENT
)

ORDER: Mapping[Purpose, tuple[ClientProfile, ...]] = MappingProxyType(
    {
        "captions": (ANDROID, IOS, ANDROID_VR),
        "streams": (ANDROID_VR, ANDROID, IOS),
        "browse": (ANDROID_VR, WEB),
        "resolve": (ANDROID_VR, WEB),
    }
)
