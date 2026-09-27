"""Real-shaped YouTube payloads for tests (captured 2026-09-27 from dQw4w9WgXcQ, trimmed)."""

from __future__ import annotations

from typing import Any

VIDEO_ID = "dQw4w9WgXcQ"

MANUAL_JSON3: dict[str, Any] = {
    "wireMagic": "pb3",
    "pens": [{}],
    "events": [
        {"tStartMs": 1360, "dDurationMs": 1680, "segs": [{"utf8": "[♪♪♪]"}]},
        {
            "tStartMs": 18640,
            "dDurationMs": 3240,
            "segs": [{"utf8": "♪ We're no strangers to love ♪"}],
        },
        {
            "tStartMs": 22640,
            "dDurationMs": 4320,
            "segs": [{"utf8": "♪ You know the rules\nand so do I ♪"}],
        },
    ],
}

ASR_JSON3: dict[str, Any] = {
    "wireMagic": "pb3",
    "events": [
        {"tStartMs": 0, "dDurationMs": 211879, "id": 1, "wpWinPosId": 1, "wsWinStyleId": 1},
        {"tStartMs": 320, "dDurationMs": 14260, "wWinId": 1, "segs": [{"utf8": "[Music]"}]},
        {"tStartMs": 18790, "wWinId": 1, "aAppend": 1, "segs": [{"utf8": "\n"}]},
        {
            "tStartMs": 18800,
            "dDurationMs": 7160,
            "wWinId": 1,
            "segs": [
                {"utf8": "We're", "acAsrConf": 0},
                {"utf8": " no", "tOffsetMs": 239, "acAsrConf": 0},
                {"utf8": " strangers", "tOffsetMs": 559, "acAsrConf": 0},
                {"utf8": " to", "tOffsetMs": 1040, "acAsrConf": 0},
            ],
        },
    ],
}

LEGACY_XML = (
    '<?xml version="1.0" encoding="utf-8" ?><transcript>'
    '<text start="1.36" dur="1.68">[♪♪♪]</text>'
    '<text start="18.64" dur="3.24">♪ We&amp;#39;re no strangers to love ♪</text>'
    '<text start="22.64" dur="4.32">♪ You know the rules\nand so do I ♪</text>'
    "</transcript>"
)

SRV3_ASR_XML = (
    '<?xml version="1.0" encoding="utf-8" ?><timedtext format="3">\n<body>\n'
    '<w t="0" id="1" wp="1" ws="1"/>\n'
    '<p t="320" d="14260" w="1">[Music]</p>\n'
    '<p t="18790" w="1" a="1">\n</p>\n'
    '<p t="18800" d="7160" w="1"><s ac="0">We&#39;re</s><s t="239" ac="0"> no</s>'
    '<s t="559" ac="0"> strangers</s><s t="1040" ac="0"> to</s></p>\n'
    "</body></timedtext>"
)


def json3_payload(*cues: tuple[int, int, str]) -> dict[str, Any]:
    """A minimal manual json3 document built from ``(start_ms, duration_ms, text)`` cues."""
    return {
        "wireMagic": "pb3",
        "pens": [{}],
        "events": [
            {"tStartMs": start, "dDurationMs": duration, "segs": [{"utf8": text}]}
            for start, duration, text in cues
        ],
    }
