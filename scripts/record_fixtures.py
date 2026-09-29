"""Record trimmed, redacted real YouTube responses into tests/fixtures/youtube/.

Run from the repository root (needs network access):

    uv run python scripts/record_fixtures.py

Re-run when YouTube changes its responses, then review the diff before committing.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from utmax.adapters.http import RetryingTransport, UrllibTransport
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.captions import caption_url
from utmax.core.clients import ANDROID, ANDROID_VR, IOS, WEB
from utmax.transport import HttpRequest

VIDEO_ID = "dQw4w9WgXcQ"
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "youtube"
SECRET_PARAMS = frozenset({"ei", "expire", "ip", "key", "lsig", "sig", "signature"})
KEPT_DETAILS = ("videoId", "title", "lengthSeconds", "channelId", "author", "isLiveContent")
KEPT_FORMAT_FIELDS = (
    "itag",
    "mimeType",
    "bitrate",
    "width",
    "height",
    "fps",
    "qualityLabel",
    "contentLength",
    "lastModified",
    "audioQuality",
    "audioSampleRate",
    "audioChannels",
    "isDrc",
    "audioTrack",
    "colorInfo",
    "drmFamilies",
    "targetDurationSec",
)
CHANNEL_ID = "UCuAXFkgsw1L7xaCfnd5JJOw"  # Rick Astley
VIDEOS_LIST = f"UULF{CHANNEL_ID[2:]}"  # his long-form uploads
SHORTS_LIST = f"UUSH{CHANNEL_ID[2:]}"  # his Shorts
HANDLE_URL = "https://www.youtube.com/@RickAstleyYT"
UNKNOWN_HANDLE_URL = "https://www.youtube.com/@thishandledoesnotexist20260928x"
# What the browse fixtures keep of each renderer (True keeps a whole value).
OWNER_KEEP = {"runs": {"text": True, "navigationEndpoint": {"browseEndpoint": {"browseId": True}}}}
HEADER_KEEP = {"playlistId": True, "title": True, "numVideosText": True, "ownerText": OWNER_KEEP}
PLAYLIST_VIDEO_KEEP = {
    "videoId": True,
    "title": True,
    "index": True,
    "shortBylineText": OWNER_KEEP,
    "lengthSeconds": True,
    "isPlayable": True,
}
CHANNEL_RUN_KEEP = {
    "content": True,
    "commandRuns": {"onTap": {"innertubeCommand": {"browseEndpoint": {"browseId": True}}}},
}
BADGE_KEEP = {
    "thumbnailBottomOverlayViewModel": {"badges": {"thumbnailBadgeViewModel": {"text": True}}}
}
LOCKUP_KEEP = {
    "contentId": True,
    "contentType": True,
    "contentImage": {"thumbnailViewModel": {"overlays": BADGE_KEEP}},
    "metadata": {
        "lockupMetadataViewModel": {
            "title": True,
            "metadata": {
                "contentMetadataViewModel": {
                    "metadataRows": {"metadataParts": {"text": CHANNEL_RUN_KEEP}}
                }
            },
        }
    },
}
SHORTS_KEEP = {
    "onTap": {"innertubeCommand": {"reelWatchEndpoint": {"videoId": True}}},
    "overlayMetadata": {"primaryText": True},
}
CONTINUATION_KEEP = {
    "continuationCommand": {"innertubeCommand": {"continuationCommand": {"token": True}}}
}


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    query = [
        (key, "REDACTED" if key in SECRET_PARAMS else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


def trim_player(data: dict[str, Any]) -> dict[str, Any]:
    status = data.get("playabilityStatus", {})
    details = data.get("videoDetails", {})
    trimmed: dict[str, Any] = {
        "playabilityStatus": {k: status[k] for k in ("status", "reason") if k in status},
        "videoDetails": {k: details[k] for k in KEPT_DETAILS if k in details},
    }
    renderer = data.get("captions", {}).get("playerCaptionsTracklistRenderer")
    if renderer:
        renderer = json.loads(json.dumps(renderer))
        for track in renderer.get("captionTracks", []):
            track["baseUrl"] = redact_url(track["baseUrl"])
        trimmed["captions"] = {"playerCaptionsTracklistRenderer": renderer}
    return trimmed


def trim_format(raw: dict[str, Any]) -> dict[str, Any]:
    """The fields utmax reads; the URL becomes a placeholder keeping only the itag and client."""
    trimmed = {key: raw[key] for key in KEPT_FORMAT_FIELDS if key in raw}
    if "url" in raw:
        client = dict(parse_qsl(urlsplit(raw["url"]).query)).get("c", "")
        trimmed["url"] = (
            "https://redacted.googlevideo.com/videoplayback"
            f"?expire=REDACTED&itag={raw['itag']}&c={client}"
        )
    if "signatureCipher" in raw or "cipher" in raw:
        trimmed["signatureCipher"] = "REDACTED"
    return trimmed


def streams_fixture(data: dict[str, Any]) -> str:
    """``streamingData`` with one format per line (``serverAbrStreamingUrl`` is dropped)."""
    streaming = data.get("streamingData", {})
    expires = json.dumps(streaming.get("expiresInSeconds", ""))
    lines = ["{", ' "streamingData": {', f'  "expiresInSeconds": {expires},']
    for key in ("formats", "adaptiveFormats"):
        entries = [
            json.dumps(trim_format(raw), ensure_ascii=False) for raw in streaming.get(key, [])
        ]
        lines.append(f'  "{key}": [')
        lines.extend(f"   {entry}," for entry in entries[:-1])
        lines.extend(f"   {entry}" for entry in entries[-1:])
        lines.append("  ]," if key == "formats" else "  ]")
    lines += [" }", "}"]
    return "\n".join(lines) + "\n"


def prune(node: Any, keep: Any) -> Any:
    """Only the keys named in ``keep`` (``True`` keeps a whole value); lists are pruned per item."""
    if keep is True:
        return node
    if isinstance(node, list):
        return [prune(item, keep) for item in node]
    if isinstance(node, dict):
        return {key: prune(node[key], sub) for key, sub in keep.items() if key in node}
    return node


def playlist_page(renderer: dict[str, Any], count: int, token: str) -> dict[str, Any]:
    """An ANDROID_VR video list with its first ``count`` videos and a continuation token."""
    return {
        "contents": [
            {"playlistVideoRenderer": prune(item["playlistVideoRenderer"], PLAYLIST_VIDEO_KEEP)}
            for item in renderer["contents"][:count]
        ],
        "continuations": [{"nextContinuationData": {"continuation": token}}],
    }


def android_vr_pages(innertube: InnerTubeClient) -> tuple[dict[str, Any], dict[str, Any]]:
    """The first two ANDROID_VR pages of VIDEOS_LIST: three and two videos."""
    first = innertube.browse(ANDROID_VR, browse_id=f"VL{VIDEOS_LIST}")
    tab = first["contents"]["singleColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]
    renderer = next(
        item["playlistVideoListRenderer"]
        for item in tab["content"]["sectionListRenderer"]["contents"]
        if "playlistVideoListRenderer" in item
    )
    token = renderer["continuations"][0]["nextContinuationData"]["continuation"]
    second = innertube.browse(ANDROID_VR, continuation=token)
    following = second["continuationContents"]["playlistVideoListContinuation"]
    next_token = following["continuations"][0]["nextContinuationData"]["continuation"]
    section = {"playlistVideoListRenderer": playlist_page(renderer, 3, token)}
    header = prune(first["header"]["playlistHeaderRenderer"], HEADER_KEEP)
    first_page = {
        "header": {"playlistHeaderRenderer": header},
        "contents": {
            "singleColumnBrowseResultsRenderer": {
                "tabs": [
                    {"tabRenderer": {"content": {"sectionListRenderer": {"contents": [section]}}}}
                ]
            }
        },
    }
    continuation = playlist_page(following, 2, next_token)
    second_page = {"continuationContents": {"playlistVideoListContinuation": continuation}}
    return first_page, second_page


def web_items(items: list[Any]) -> list[Any]:
    """WEB list items with only the fields utmax reads."""
    kept: list[Any] = []
    for item in items:
        if "lockupViewModel" in item:
            kept.append({"lockupViewModel": prune(item["lockupViewModel"], LOCKUP_KEEP)})
        elif "continuationItemViewModel" in item:
            view = prune(item["continuationItemViewModel"], CONTINUATION_KEEP)
            kept.append({"continuationItemViewModel": view})
        elif "richItemRenderer" in item:
            short = prune(item["richItemRenderer"]["content"]["shortsLockupViewModel"], SHORTS_KEEP)
            kept.append({"richItemRenderer": {"content": {"shortsLockupViewModel": short}}})
    return kept


def web_page(items: list[Any], header: dict[str, Any]) -> dict[str, Any]:
    """A WEB first page holding ``items`` under a playlist header."""
    section = {"itemSectionRenderer": {"contents": items}}
    return {
        "header": {"playlistHeaderRenderer": prune(header, HEADER_KEEP)},
        "contents": {
            "twoColumnBrowseResultsRenderer": {
                "tabs": [
                    {"tabRenderer": {"content": {"sectionListRenderer": {"contents": [section]}}}}
                ]
            }
        },
    }


def web_pages(innertube: InnerTubeClient) -> tuple[dict[str, Any], ...]:
    """WEB pages: the first page of VIDEOS_LIST (three videos) and its last page (the first
    two and the last video), and the first page of SHORTS_LIST (two Shorts)."""
    first = innertube.browse(WEB, browse_id=f"VL{VIDEOS_LIST}")
    tab = first["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]
    items = tab["content"]["sectionListRenderer"]["contents"][0]["itemSectionRenderer"]["contents"]
    command = items[-1]["continuationItemViewModel"]["continuationCommand"]
    second = innertube.browse(
        WEB, continuation=command["innertubeCommand"]["continuationCommand"]["token"]
    )
    action = second["onResponseReceivedActions"][0]["appendContinuationItemsAction"]
    appended = action["continuationItems"]
    shorts = innertube.browse(WEB, browse_id=f"VL{SHORTS_LIST}")
    shorts_tab = shorts["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]
    shorts_section = shorts_tab["content"]["sectionListRenderer"]["contents"][0]
    grid = shorts_section["itemSectionRenderer"]["contents"][0]["richGridRenderer"]
    header = first["header"]["playlistHeaderRenderer"]
    first_page = web_page(web_items([*items[:3], items[-1]]), header)
    last_items = web_items([*appended[:2], appended[-1]])
    second_page = {
        "onResponseReceivedActions": [
            {"appendContinuationItemsAction": {"continuationItems": last_items}}
        ]
    }
    shorts_page = web_page(
        [{"richGridRenderer": {"contents": web_items(grid["contents"][:2])}}],
        shorts["header"]["playlistHeaderRenderer"],
    )
    return first_page, second_page, shorts_page


def resolved(innertube: InnerTubeClient, url: str) -> dict[str, Any]:
    """The ``endpoint`` of the ANDROID_VR ``navigation/resolve_url`` answer for ``url``."""
    endpoint = innertube.resolve_url(ANDROID_VR, url)["endpoint"]
    kept = {key: endpoint[key] for key in ("browseEndpoint", "urlEndpoint") if key in endpoint}
    return {"endpoint": kept}


def first_elements(xml: str, tag: str, count: int, *, head_end: str, tail: str) -> str:
    head = xml[: xml.index(head_end) + len(head_end)]
    elements = re.findall(rf"<{tag}\b.*?</{tag}>", xml, flags=re.DOTALL)[:count]
    return head + "\n".join(elements) + tail


def write(name: str, content: str) -> None:
    path = OUT / name
    path.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {path.name} ({len(content)} characters)")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    transport = RetryingTransport(UrllibTransport(timeout=30.0))
    innertube = InnerTubeClient(transport)
    players: dict[str, dict[str, Any]] = {}
    for profile, name in ((ANDROID, "android"), (IOS, "ios"), (ANDROID_VR, "android_vr")):
        players[name] = innertube.player_json(profile, VIDEO_ID)
        write(
            f"player_{name}.json",
            json.dumps(trim_player(players[name]), ensure_ascii=False, indent=1) + "\n",
        )
    write("streams_android_vr.json", streams_fixture(players["android_vr"]))

    tracks = players["android"]["captions"]["playerCaptionsTracklistRenderer"]["captionTracks"]
    manual = next(t for t in tracks if t.get("kind") != "asr" and t["languageCode"] == "en")
    auto = next(t for t in tracks if t.get("kind") == "asr")

    def download(url: str) -> str:
        response = transport.send(
            HttpRequest("GET", url, {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"})
        )
        if response.status != 200:
            raise SystemExit(f"caption download failed with HTTP {response.status}")
        return response.text

    manual_json3 = json.loads(download(caption_url(manual["baseUrl"], fmt="json3")))
    write("json3_en_manual.json", json.dumps(manual_json3, ensure_ascii=False, indent=1) + "\n")
    auto_json3 = json.loads(download(caption_url(auto["baseUrl"], fmt="json3")))
    auto_json3["events"] = auto_json3["events"][:40]
    write("json3_en_asr.json", json.dumps(auto_json3, ensure_ascii=False, indent=1) + "\n")
    legacy = download(caption_url(manual["baseUrl"], fmt=None))
    write(
        "legacy_en_manual.xml",
        first_elements(legacy, "text", 12, head_end="<transcript>", tail="</transcript>\n"),
    )
    srv3 = download(caption_url(auto["baseUrl"], fmt="srv3"))
    write(
        "srv3_en_asr.xml",
        first_elements(srv3, "p", 16, head_end="<body>", tail="\n</body></timedtext>\n"),
    )
    vr_first, vr_second = android_vr_pages(innertube)
    web_first, web_second, web_shorts = web_pages(innertube)
    browse_fixtures = {
        "browse_android_vr_1.json": vr_first,
        "browse_android_vr_2.json": vr_second,
        "browse_web_1.json": web_first,
        "browse_web_2.json": web_second,
        "browse_web_shorts.json": web_shorts,
        "resolve_handle.json": resolved(innertube, HANDLE_URL),
        "resolve_unknown.json": resolved(innertube, UNKNOWN_HANDLE_URL),
    }
    for name, data in browse_fixtures.items():
        write(name, json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    write(
        "README.md",
        f"# YouTube fixtures\n\nRecorded {date.today().isoformat()} from video `{VIDEO_ID}` with\n"
        "`uv run python scripts/record_fixtures.py`. URL parameters "
        f"{', '.join(sorted(SECRET_PARAMS))} are replaced with `REDACTED`.\n"
        "`streams_android_vr.json` keeps only the stream fields utmax reads; its URLs are\n"
        "placeholders that keep the itag and the client name.\n"
        "`browse_*.json` hold the first videos of Rick Astley's long-form uploads\n"
        f"(`{VIDEOS_LIST}`: ANDROID_VR pages 1 and 2, the WEB first and last pages) and\n"
        f"of his Shorts (`{SHORTS_LIST}`, WEB), trimmed to the fields utmax reads;\n"
        "`resolve_*.json` hold the ANDROID_VR `navigation/resolve_url` answers for\n"
        "`@RickAstleyYT` and for a handle that does not exist.\n",
    )


if __name__ == "__main__":
    main()
