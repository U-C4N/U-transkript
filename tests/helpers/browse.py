"""Browse answers for collection tests: the recorded fixtures and small synthetic pages.

The synthetic shapes copy what InnerTube answered on 2026-09-28 (see the M5 plan's verified
facts); only the fields utmax reads are filled in.
"""

from __future__ import annotations

import json
from typing import Any

from tests.helpers.youtube import FIXTURES

CHANNEL_ID = "UCuAXFkgsw1L7xaCfnd5JJOw"
VIDEOS_LIST = "UULFuAXFkgsw1L7xaCfnd5JJOw"
VR_PAGE_1 = ["PXC_PYeB6F8", "LaOUkDBDjW8", "wvr7-pDJUOA"]
VR_PAGE_2 = ["1hCm58jzquQ", "QJjrf9RkzGo"]
WEB_LAST_PAGE = ["CdI9nxxXe4U", "nDoU231XCqs", "dQw4w9WgXcQ"]


def browse_fixture(name: str) -> dict[str, Any]:
    """A recorded answer from tests/fixtures/youtube, such as ``"browse_web_1"``."""
    return dict(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))


def alert_page(text: str) -> dict[str, Any]:
    """A WEB answer that holds only an alert."""
    return {"alerts": [{"alertRenderer": {"type": "ERROR", "text": {"runs": [{"text": text}]}}}]}


def error_body(code: int) -> dict[str, Any]:
    """InnerTube's JSON body for HTTP 400 and 404 answers."""
    status = {400: "INVALID_ARGUMENT", 404: "NOT_FOUND"}[code]
    return {"error": {"code": code, "message": "Request failed.", "status": status}}


def lockup(
    video_id: str, *, badge: str = "3:51", title: str = "A video", channel_id: str = ""
) -> dict[str, Any]:
    """A WEB ``lockupViewModel`` item; with ``channel_id`` its metadata links to a channel."""
    parts = []
    if channel_id:
        command = {"onTap": {"innertubeCommand": {"browseEndpoint": {"browseId": channel_id}}}}
        parts.append({"text": {"content": "Some Channel", "commandRuns": [command]}})
    badges = [{"thumbnailBadgeViewModel": {"text": badge}}]
    return {
        "lockupViewModel": {
            "contentId": video_id,
            "contentImage": {
                "thumbnailViewModel": {
                    "overlays": [{"thumbnailBottomOverlayViewModel": {"badges": badges}}]
                }
            },
            "metadata": {
                "lockupMetadataViewModel": {
                    "title": {"content": title},
                    "metadata": {
                        "contentMetadataViewModel": {"metadataRows": [{"metadataParts": parts}]}
                    },
                }
            },
        }
    }


def web_page(*items: dict[str, Any], header: dict[str, Any] | None = None) -> dict[str, Any]:
    """A WEB first page listing ``items`` under ``header`` (a whole ``header`` object)."""
    section = {"itemSectionRenderer": {"contents": list(items)}}
    tab = {"tabRenderer": {"content": {"sectionListRenderer": {"contents": [section]}}}}
    page: dict[str, Any] = {"contents": {"twoColumnBrowseResultsRenderer": {"tabs": [tab]}}}
    if header is not None:
        page["header"] = header
    return page


def shorts_page(*video_ids: str, count: str = "") -> dict[str, Any]:
    """A WEB page of a channel's Shorts: a ``richGridRenderer`` with one ``richItemRenderer``
    per video and no continuation, as WEB answers (live on 2026-09-29: 100 items whatever the
    header counts). With ``count`` set the page has a playlist header that says so."""
    grid = [
        {
            "richItemRenderer": {
                "content": {
                    "shortsLockupViewModel": {
                        "onTap": {"innertubeCommand": {"reelWatchEndpoint": {"videoId": video_id}}},
                        "overlayMetadata": {"primaryText": {"content": f"Short {video_id}"}},
                    }
                }
            }
        }
        for video_id in video_ids
    ]
    header = None
    if count:
        title = {"simpleText": "Short videos"}
        numbers = {"runs": [{"text": count}]}
        header = {"playlistHeaderRenderer": {"title": title, "numVideosText": numbers}}
    return web_page({"richGridRenderer": {"contents": grid}}, header=header)


def vr_page(*video_ids: str, token: str | None = None, count: str = "") -> dict[str, Any]:
    """An ANDROID_VR page of playable videos, with a playlist header when ``count`` is set."""
    videos = [
        {"playlistVideoRenderer": {"videoId": video_id, "title": {"runs": [{"text": video_id}]}}}
        for video_id in video_ids
    ]
    renderer: dict[str, Any] = {"contents": videos}
    if token is not None:
        renderer["continuations"] = [{"nextContinuationData": {"continuation": token}}]
    page: dict[str, Any] = {"continuationContents": {"playlistVideoListContinuation": renderer}}
    if count:
        title = {"runs": [{"text": "A playlist"}]}
        numbers = {"runs": [{"text": count}]}
        page["header"] = {"playlistHeaderRenderer": {"title": title, "numVideosText": numbers}}
    return page
