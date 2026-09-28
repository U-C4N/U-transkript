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
from utmax.core.clients import ANDROID, ANDROID_VR, IOS
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
    write(
        "README.md",
        f"# YouTube fixtures\n\nRecorded {date.today().isoformat()} from video `{VIDEO_ID}` with\n"
        "`uv run python scripts/record_fixtures.py`. URL parameters "
        f"{', '.join(sorted(SECRET_PARAMS))} are replaced with `REDACTED`.\n"
        "`streams_android_vr.json` keeps only the stream fields utmax reads; its URLs are\n"
        "placeholders that keep the itag and the client name.\n",
    )


if __name__ == "__main__":
    main()
