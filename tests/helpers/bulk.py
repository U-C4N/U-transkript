"""A fake YouTube with several videos for bulk tests: the player answer depends on the video.

Every video has the default caption tracks: manual English (``MANUAL_JSON3``), auto English
and German (``de-DE``). Its streams are the synthetic ones of ``tests.helpers.downloads``.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Collection, Mapping
from typing import Any

from tests.helpers.downloads import streaming_data_for
from tests.helpers.fake_media import FakeBody, FakeMedia
from tests.helpers.fake_transport import json_response
from tests.helpers.youtube import MANUAL_JSON3, json3_payload, player_payload
from utmax.adapters.innertube import InnerTubeClient
from utmax.services.bulk import BulkService
from utmax.services.download import DownloadService
from utmax.services.transcripts import TranscriptService
from utmax.transport import HttpRequest, HttpResponse

TITLES = {
    "dQw4w9WgXcQ": "Never Gonna Give You Up",
    "jNQXAC9IVRw": "Me at the zoo",
    "9bZkp7q19f0": "Gangnam Style",
}
IDS = list(TITLES)


class ManyVideos:
    """InnerTube, captions and googlevideo for every video in ``titles``.

    Videos in ``blocked`` answer HTTP 429 and videos in ``missing`` are unavailable.
    ``players`` lists the video ID of every player request, in order.
    """

    def __init__(
        self,
        titles: Mapping[str, str] = TITLES,
        *,
        blocked: Collection[str] = (),
        missing: Collection[str] = (),
    ) -> None:
        self.titles = dict(titles)
        self.blocked = set(blocked)
        self.missing = set(missing)
        self.media = FakeMedia()
        self.players: list[str] = []
        self._streaming = streaming_data_for(self.media)
        self._lock = threading.Lock()

    def send(self, request: HttpRequest) -> HttpResponse:
        if "/youtubei/v1/player" in request.url:
            video_id = json.loads(request.body or b"{}")["videoId"]
            with self._lock:
                self.players.append(video_id)
            if video_id in self.blocked:
                return json_response({}, status=429)
            if video_id in self.missing:
                reason = "This video is unavailable"
                return json_response(
                    player_payload(video_id=video_id, status="ERROR", reason=reason)
                )
            title = self.titles[video_id]
            payload = player_payload(video_id=video_id, title=title, streaming_data=self._streaming)
            return json_response(payload)
        if "lang=de-DE" in request.url:
            return json_response(json3_payload((1000, 2000, "Wir sind keine Fremden")))
        if "/api/timedtext" in request.url:
            return json_response(MANUAL_JSON3)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    def stream(self, request: HttpRequest) -> FakeBody:
        return self.media.stream(request)

    def bulk(self, **options: Any) -> BulkService:
        """A BulkService over this fake; ``options`` go to the DownloadService."""
        innertube = InnerTubeClient(self)
        transcripts = TranscriptService(innertube)
        downloads = DownloadService(innertube, transcripts, self.stream, **options)
        return BulkService(transcripts, downloads)
