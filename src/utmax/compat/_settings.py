"""URL templates and the InnerTube context of youtube-transcript-api 1.2.4.

utmax builds its own requests (see ``utmax.core.clients``); these values only keep code that
reads them working.
"""

from __future__ import annotations

__all__ = ["INNERTUBE_API_URL", "INNERTUBE_CONTEXT", "WATCH_URL"]

WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
INNERTUBE_API_URL = "https://www.youtube.com/youtubei/v1/player?key={api_key}"
INNERTUBE_CONTEXT = {"client": {"clientName": "ANDROID", "clientVersion": "20.10.38"}}
