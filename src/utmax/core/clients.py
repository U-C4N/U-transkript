"""InnerTube client profiles: the single place to update when YouTube changes its apps.

Verified on 2026-09-27: ANDROID, IOS and ANDROID_VR return captions and direct stream URLs
without an API key or proof-of-origin token; ANDROID_VR returns no ``translationLanguages``.

Verified on 2026-10-09: the stream URLs of ANDROID and IOS serve only the start of a stream
without a proof-of-origin token, and ANDROID_VR mostly answers with a bot check. VISIONOS, sent
with a ``visitorData`` that YouTube issued, serves whole streams of every quality (H.264, AV1
and VP9 up to 2160p and HDR, AAC and Opus) without JavaScript or a token.
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
    "PROFILES",
    "VISIONOS",
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
    """How utmax introduces itself to InnerTube as one of YouTube's apps.

    ``needs_visitor``: YouTube answers this app with a bot check unless the request carries a
    ``visitorData`` that it issued (``POST /youtubei/v1/visitor_id``).
    """

    name: str
    client_id: int
    version: str
    user_agent: str
    extra: tuple[tuple[str, str | int], ...] = ()
    needs_visitor: bool = False

    def context_payload(self, visitor_data: str | None = None) -> dict[str, Any]:
        """The ``context`` object of an InnerTube request body."""
        client: dict[str, Any] = {"clientName": self.name, "clientVersion": self.version}
        client.update(self.extra)
        client.update({"hl": "en", "gl": "US"})
        if visitor_data is not None:
            client["visitorData"] = visitor_data
        return {"client": client}

    def request_headers(self, visitor_data: str | None = None) -> dict[str, str]:
        """HTTP headers for an InnerTube request made as this app."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
            "X-YouTube-Client-Name": str(self.client_id),
            "X-YouTube-Client-Version": self.version,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip",
        }
        if visitor_data is not None:
            headers["X-Goog-Visitor-Id"] = visitor_data
        return headers


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
VISIONOS = ClientProfile(
    name="VISIONOS",
    client_id=101,
    version="1.02",
    user_agent=(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_7_3) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/26.0 Safari/605.1.15"
    ),
    extra=(
        ("deviceMake", "Apple"),
        ("deviceModel", "RealityDevice17,1"),
        ("osName", "visionOS"),
        ("osVersion", "26.5.23O471"),
    ),
    needs_visitor=True,
)
WEB = ClientProfile(
    name="WEB", client_id=1, version="2.20260925.01.00", user_agent=DESKTOP_USER_AGENT
)

ORDER: Mapping[Purpose, tuple[ClientProfile, ...]] = MappingProxyType(
    {
        "captions": (ANDROID, IOS, ANDROID_VR),
        "streams": (VISIONOS, ANDROID_VR),
        "browse": (ANDROID_VR, WEB),
        "resolve": (ANDROID_VR, WEB),
    }
)

PROFILES: Mapping[str, ClientProfile] = MappingProxyType(
    {profile.name: profile for profile in (ANDROID, IOS, ANDROID_VR, VISIONOS, WEB)}
)
