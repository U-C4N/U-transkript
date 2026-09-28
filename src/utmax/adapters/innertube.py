"""InnerTube (YouTube's internal API): player requests with client fallback, and captions."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from functools import partial
from typing import Any, TypeVar

from utmax.adapters.watch_page import fetch_api_key
from utmax.core.captions import caption_url, check_caption_url
from utmax.core.clients import ANDROID, DESKTOP_USER_AGENT, ORDER, ClientProfile, Purpose
from utmax.core.playability import check_playability
from utmax.core.player import PlayerData, parse_player_response
from utmax.errors import (
    IpBlocked,
    RequestBlocked,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeError,
    YouTubeRequestFailed,
)
from utmax.transport import HttpRequest, HttpResponse, Transport

__all__ = ["API_BASE", "InnerTubeClient"]

API_BASE = "https://www.youtube.com/youtubei/v1"
log = logging.getLogger("utmax.youtube")
T = TypeVar("T")

_HTTP_LEVEL_FAILURES = (YouTubeRequestFailed, YouTubeDataUnparsable)


class InnerTubeClient:
    """Talks to InnerTube with a chain of client profiles (see ``utmax.core.clients``)."""

    def __init__(self, transport: Transport, *, block_retries: int = 0) -> None:
        self._transport = transport
        self._block_retries = block_retries

    def player(self, video_id: str, *, purpose: Purpose = "captions") -> PlayerData:
        """A playable player response, trying each profile for ``purpose`` in order.

        For ``"streams"``, a response without a direct MP4 stream URL counts as a failed profile.
        """
        profiles = ORDER[purpose]
        failures: list[YouTubeError] = []
        http_failures = 0
        for profile in profiles:
            try:
                return self._with_block_retries(
                    partial(self._playable, profile, video_id, None, purpose=purpose)
                )
            except _HTTP_LEVEL_FAILURES as error:
                http_failures += 1
                failures.append(error)
            except (VideoUnplayable, RequestBlocked) as error:
                if isinstance(error, IpBlocked):
                    raise
                failures.append(error)
            log.info("InnerTube client %s failed for %s: %s", profile.name, video_id, failures[-1])
        if http_failures == len(profiles):
            log.info("every InnerTube client failed at the HTTP level; trying the watch page")
            api_key = fetch_api_key(self._transport, video_id)
            return self._with_block_retries(
                partial(self._playable, ANDROID, video_id, api_key, purpose=purpose)
            )
        raise failures[0]

    def player_json(
        self, profile: ClientProfile, video_id: str, *, api_key: str | None = None
    ) -> dict[str, Any]:
        """The raw player response of one profile (low level; used by the fixture recorder)."""
        url = f"{API_BASE}/player?prettyPrint=false"
        if api_key is not None:
            url += f"&key={api_key}"
        payload = {
            "context": profile.context_payload(),
            "videoId": video_id,
            "contentCheckOk": True,
            "racyCheckOk": True,
        }
        body = json.dumps(payload).encode("utf-8")
        response = self._transport.send(HttpRequest("POST", url, profile.request_headers(), body))
        return _json_object(response, video_id=video_id)

    def fetch_captions(self, base_url: str, *, video_id: str) -> HttpResponse:
        """Download a caption track as json3."""
        check_caption_url(base_url, video_id=video_id)
        url = caption_url(base_url, fmt="json3")
        return self._with_block_retries(partial(self._caption_response, url, video_id))

    def _playable(
        self, profile: ClientProfile, video_id: str, api_key: str | None, *, purpose: Purpose
    ) -> PlayerData:
        data = self.player_json(profile, video_id, api_key=api_key)
        player = parse_player_response(data, video_id=video_id)
        check_playability(player.playability, video_id=video_id)
        if purpose == "streams" and not any(
            stream.url and stream.format.container == "mp4" and not stream.drm
            for stream in player.streams
        ):
            raise YouTubeDataUnparsable(
                f"The {profile.name} client returned no direct MP4 stream URLs for {video_id}.",
                video_id=video_id,
            )
        return player

    def _caption_response(self, url: str, video_id: str) -> HttpResponse:
        headers = {
            "User-Agent": DESKTOP_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip",
        }
        response = self._transport.send(HttpRequest("GET", url, headers))
        if response.status == 429:
            hint = (
                "YouTube's own translation is heavily rate-limited; use AI translation or a proxy."
                if "tlang=" in url
                else None
            )
            raise IpBlocked(
                "YouTube rate-limited the caption download (HTTP 429).",
                video_id=video_id,
                suggestion=hint,
            )
        if response.status != 200:
            raise YouTubeRequestFailed(
                f"The caption download answered HTTP {response.status}.",
                status_code=response.status,
                video_id=video_id,
            )
        return response

    def _with_block_retries(self, action: Callable[[], T]) -> T:
        attempt = 0
        while True:
            try:
                return action()
            except RequestBlocked as error:
                if attempt >= self._block_retries:
                    raise
                attempt += 1
                log.info(
                    "blocked by YouTube (%s); retry %d/%d", error, attempt, self._block_retries
                )


def _json_object(response: HttpResponse, *, video_id: str) -> dict[str, Any]:
    if response.status == 429:
        raise IpBlocked("YouTube rate-limited this IP address (HTTP 429).", video_id=video_id)
    if response.status != 200:
        raise YouTubeRequestFailed(
            f"InnerTube answered HTTP {response.status}.",
            status_code=response.status,
            video_id=video_id,
        )
    try:
        data = response.json()
    except ValueError:
        raise YouTubeDataUnparsable(
            "InnerTube returned a response that is not JSON.", video_id=video_id
        ) from None
    if not isinstance(data, dict):
        raise YouTubeDataUnparsable(
            "InnerTube returned an unexpected JSON value.", video_id=video_id
        )
    return data
