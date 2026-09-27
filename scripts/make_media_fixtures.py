"""Record "hollow" YouTube stream fixtures into tests/fixtures/media/.

A hollow fixture is the beginning of a real DASH stream (itags 137, 140 and 399 of
dQw4w9WgXcQ) with every mdat payload left out: the real ftyp, moov, sidx and moof boxes plus
the header of each mdat. tests/helpers/hollow_source.py replays it with zero-filled payloads,
so the muxer meets YouTube's exact box structure offline, in a few kilobytes.

Run from the repository root (needs network access):

    uv run python scripts/make_media_fixtures.py

Stream URLs, and with them their ip/ei/sig/lsig/signature/key/expire parameters, are never
written anywhere. Re-run when YouTube changes its streams and review the diff before committing.
"""

from __future__ import annotations

import json
import struct
from datetime import date
from pathlib import Path
from typing import Any

from utmax.adapters.http import RetryingTransport, UrllibTransport
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.clients import ANDROID_VR
from utmax.transport import HttpRequest, Transport

VIDEO_ID = "dQw4w9WgXcQ"
ITAGS = (137, 140, 399)
FRAGMENTS = 2
HEAD_BYTES = 64 * 1024
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "media"


def fetch(transport: Transport, url: str, start: int, length: int) -> bytes:
    headers = {"Range": f"bytes={start}-{start + length - 1}", "User-Agent": ANDROID_VR.user_agent}
    response = transport.send(HttpRequest("GET", url, headers))
    if response.status not in (200, 206):
        raise SystemExit(f"a stream request failed with HTTP {response.status}")
    return response.body[:length]


def children(data: bytes) -> list[tuple[str, bytes]]:
    found: list[tuple[str, bytes]] = []
    offset = 0
    while offset + 8 <= len(data):
        size, kind = struct.unpack_from(">I4s", data, offset)
        header = 8
        if size == 1:
            (size,) = struct.unpack_from(">Q", data, offset + 8)
            header = 16
        found.append((kind.decode("latin-1"), data[offset + header : offset + size]))
        offset += size
    return found


def child(data: bytes, *path: str) -> bytes:
    for name in path:
        data = next(body for kind, body in children(data) if kind == name)
    return data


def sidx_references(sidx: bytes) -> tuple[int, list[int]]:
    version = sidx[0]
    (timescale,) = struct.unpack_from(">I", sidx, 8)
    position = 12 + (8 if version == 0 else 16)
    (count,) = struct.unpack_from(">H", sidx, position + 2)
    sizes = [
        struct.unpack_from(">I", sidx, position + 4 + 12 * index)[0] & 0x7FFF_FFFF
        for index in range(count)
    ]
    return timescale, sizes


def fragment_facts(moof: bytes) -> dict[str, Any]:
    traf = child(moof, "traf")
    tfhd, tfdt, trun = child(traf, "tfhd"), child(traf, "tfdt"), child(traf, "trun")
    trun_flags = int.from_bytes(trun[1:4], "big")
    if not trun_flags & 0x200:
        raise SystemExit("YouTube's trun boxes no longer list sample sizes; update this script")
    (count,) = struct.unpack_from(">I", trun, 4)
    start = 8 + (4 if trun_flags & 0x1 else 0) + (4 if trun_flags & 0x4 else 0)
    width = sum(4 for bit in (0x100, 0x200, 0x400, 0x800) if trun_flags & bit)
    size_column = 4 if trun_flags & 0x100 else 0
    sizes = [
        struct.unpack_from(">I", trun, start + index * width + size_column)[0]
        for index in range(count)
    ]
    return {
        "tfhd_flags": int.from_bytes(tfhd[1:4], "big"),
        "tfdt_version": tfdt[0],
        "trun_version": trun[0],
        "trun_flags": trun_flags,
        "samples": count,
        "sample_bytes": sum(sizes),
    }


def record(transport: Transport, fmt: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    url = fmt["url"]
    init_start, init_end = int(fmt["initRange"]["start"]), int(fmt["initRange"]["end"])
    index_start, index_end = int(fmt["indexRange"]["start"]), int(fmt["indexRange"]["end"])
    init = fetch(transport, url, init_start, init_end - init_start + 1)
    index = fetch(transport, url, index_start, index_end - index_start + 1)
    sidx = child(index, "sidx")
    timescale, sizes = sidx_references(sidx)
    hollow = bytearray(init + index)
    position = index_end + 1
    fragments: list[dict[str, Any]] = []
    for size in sizes[:FRAGMENTS]:
        head = fetch(transport, url, position, min(size, HEAD_BYTES))
        (moof_size,) = struct.unpack_from(">I", head, 0)
        mdat_size, mdat_kind = struct.unpack_from(">I4s", head, moof_size)
        if head[4:8] != b"moof" or mdat_kind != b"mdat" or moof_size + mdat_size != size:
            raise SystemExit("a fragment is not one moof followed by one mdat")
        facts = fragment_facts(head[8:moof_size])
        if facts["sample_bytes"] != mdat_size - 8:
            raise SystemExit("the trun sample sizes do not add up to the mdat size")
        hollow += head[: moof_size + 8]
        fragments.append({**facts, "size": size, "mdat_payload": mdat_size - 8})
        position += size
    trak = child(init, "moov", "trak")
    edits = next((body for kind, body in children(trak) if kind == "edts"), None)
    media_time = None
    if edits is not None:
        elst = child(edits, "elst")
        (media_time,) = struct.unpack_from(">q" if elst[0] == 1 else ">i", elst, 12 + 4 * elst[0])
    facts = {
        "file": f"{VIDEO_ID}_{fmt['itag']}.hollow.bin",
        "mime_type": fmt["mimeType"],
        "content_length": int(fmt["contentLength"]),
        "timescale": timescale,
        "sidx_references": len(sizes),
        "elst_media_time": media_time,
        "virtual_size": position,
        "fragments": fragments,
    }
    return bytes(hollow), facts


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    transport = RetryingTransport(UrllibTransport(timeout=30.0))
    player = InnerTubeClient(transport).player_json(ANDROID_VR, VIDEO_ID)
    formats = {
        fmt.get("itag"): fmt for fmt in player.get("streamingData", {}).get("adaptiveFormats", [])
    }
    manifest: dict[str, Any] = {
        "video_id": VIDEO_ID,
        "recorded": date.today().isoformat(),
        "client": ANDROID_VR.name,
        "streams": {},
    }
    for itag in ITAGS:
        if itag not in formats or "url" not in formats[itag]:
            raise SystemExit(f"itag {itag} is not offered with a direct URL; try again later")
        hollow, facts = record(transport, formats[itag])
        (OUT / facts["file"]).write_bytes(hollow)
        manifest["streams"][str(itag)] = facts
        print(f"wrote {facts['file']} ({len(hollow)} bytes standing for {facts['virtual_size']})")
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    (OUT / "README.md").write_text(
        "# Hollow media fixtures\n\n"
        f"Recorded {manifest['recorded']} from video `{VIDEO_ID}` (itags "
        f"{', '.join(map(str, ITAGS))}, first {FRAGMENTS} fragments) with\n"
        "`uv run python scripts/make_media_fixtures.py`. Each `.hollow.bin` file holds the real\n"
        "`ftyp`, `moov`, `sidx` and `moof` boxes and every `mdat` header, without payloads;\n"
        "`tests/helpers/hollow_source.py` replays them with zero-filled payloads. No stream URL\n"
        "or URL parameter is stored. `manifest.json` lists facts read independently of utmax.\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
