"""Caption URL handling and parsers for YouTube's json3 and XML timed-text formats."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

from utmax.core.ytdata import items, mapping
from utmax.errors import PoTokenRequired, YouTubeDataUnparsable
from utmax.models import Segment, Word

__all__ = [
    "caption_url",
    "check_caption_url",
    "parse_captions",
    "parse_json3",
    "parse_xml",
    "set_query_param",
]

_FORMAT_ATTRIBUTES = (("bAttr", "b"), ("iAttr", "i"), ("uAttr", "u"))
_ANY_TAG = re.compile(r"<[^>]*>")
_NON_FORMAT_TAG = re.compile(r"<(?!(?:/?(?:b|i|u|em|strong)(?:[>\s/]|$)))[^>]*>", re.IGNORECASE)
_UNSAFE_XML = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)", re.IGNORECASE)


def set_query_param(url: str, name: str, value: str | None) -> str:
    """``url`` with query parameter ``name`` replaced, or removed when ``value`` is None."""
    parts = urlsplit(url)
    query = [
        (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True) if key != name
    ]
    if value is not None:
        query.append((name, value))
    return urlunsplit(parts._replace(query=urlencode(query)))


def caption_url(base_url: str, *, fmt: str | None = "json3") -> str:
    """The download URL of a caption track in ``fmt`` (``None`` = YouTube's legacy XML)."""
    return set_query_param(base_url, "fmt", fmt)


def check_caption_url(url: str, *, video_id: str) -> None:
    """Refuse URLs outside youtube.com and ones that need a proof-of-origin token."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not (host == "youtube.com" or host.endswith(".youtube.com")):
        message = (
            f"Refusing to download captions from unexpected host {host!r}."
            if host
            else "Refusing to download captions from a URL without a host."
        )
        raise YouTubeDataUnparsable(message, video_id=video_id)
    if parts.scheme != "https":
        raise YouTubeDataUnparsable(
            "Refusing to download captions over plain HTTP.", video_id=video_id
        )
    experiments = dict(parse_qsl(parts.query)).get("exp", "")
    if "xpe" in experiments.split(","):
        raise PoTokenRequired(
            "YouTube requires a proof-of-origin token for these captions.", video_id=video_id
        )


def parse_captions(
    body: bytes,
    content_type: str,
    *,
    is_generated: bool,
    preserve_formatting: bool = False,
    video_id: str | None = None,
) -> tuple[Segment, ...]:
    """Parse a caption download, whichever format YouTube answered with."""
    text = body.decode("utf-8", errors="replace").lstrip("\ufeff").strip()
    if not text:
        raise YouTubeDataUnparsable(
            "YouTube returned an empty caption file.",
            video_id=video_id,
            suggestion=(
                "YouTube may now require a proof-of-origin token or changed its caption "
                "format; please report it with the video ID."
            ),
        )
    lowered = text[:200].lower()
    if "html" in content_type.lower() or lowered.startswith(("<!doctype html", "<html")):
        raise YouTubeDataUnparsable(
            "YouTube returned a web page instead of captions (a consent, CAPTCHA or proxy page).",
            video_id=video_id,
            suggestion="Retry later or from another network or proxy; YouTube may be blocking this IP address.",
        )
    try:
        if text.startswith("{") or "json" in content_type.lower():
            data = json.loads(text)
            if not isinstance(data, dict):
                raise YouTubeDataUnparsable(
                    "YouTube returned unexpected caption JSON.", video_id=video_id
                )
            return parse_json3(
                data, is_generated=is_generated, preserve_formatting=preserve_formatting
            )
        if text.startswith("<"):
            return parse_xml(
                text,
                is_generated=is_generated,
                preserve_formatting=preserve_formatting,
                video_id=video_id,
            )
    except (TypeError, ValueError) as error:
        raise YouTubeDataUnparsable(
            f"YouTube returned captions utmax could not parse ({error}).", video_id=video_id
        ) from error
    raise YouTubeDataUnparsable(
        "YouTube returned captions in an unknown format.", video_id=video_id
    )


def parse_json3(
    data: Mapping[str, Any], *, is_generated: bool, preserve_formatting: bool = False
) -> tuple[Segment, ...]:
    """Parse YouTube's ``fmt=json3`` captions."""
    pens = items(data.get("pens"))
    segments: list[Segment] = []
    for event in map(mapping, items(data.get("events"))):
        pieces = [
            (html.unescape(str(seg.get("utf8", ""))), seg)
            for seg in map(mapping, items(event.get("segs")))
        ]
        if not "".join(piece for piece, _ in pieces).strip():
            continue
        start_ms = int(event.get("tStartMs") or 0)
        if preserve_formatting:
            text = "".join(_styled(piece, seg, pens) for piece, seg in pieces)
        else:
            text = "".join(piece for piece, _ in pieces)
        words: tuple[Word, ...] = ()
        if is_generated:
            words = tuple(
                Word(piece.strip(), (start_ms + int(seg.get("tOffsetMs") or 0)) / 1000)
                for piece, seg in pieces
                if piece.strip()
            )
        segments.append(
            Segment(
                start=start_ms / 1000,
                duration=int(event.get("dDurationMs") or 0) / 1000,
                text=_normalize(text, is_generated=is_generated),
                words=words,
            )
        )
    return tuple(segments)


def parse_xml(
    text: str,
    *,
    is_generated: bool,
    preserve_formatting: bool = False,
    video_id: str | None = None,
) -> tuple[Segment, ...]:
    """Parse YouTube's XML captions: ``srv3`` (``<timedtext>``) or legacy (``<transcript>``)."""
    if _UNSAFE_XML.search(text):
        raise YouTubeDataUnparsable(
            "Refusing caption XML that declares a DOCTYPE or entities.", video_id=video_id
        )
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        raise YouTubeDataUnparsable(
            "YouTube returned malformed caption XML.", video_id=video_id
        ) from None
    if root.tag == "timedtext":
        return _parse_srv3(root, is_generated=is_generated, preserve_formatting=preserve_formatting)
    if root.tag == "transcript":
        return _parse_legacy(
            root, is_generated=is_generated, preserve_formatting=preserve_formatting
        )
    raise YouTubeDataUnparsable(
        f"Unknown caption XML root element <{root.tag}>.", video_id=video_id
    )


def _parse_srv3(
    root: ElementTree.Element, *, is_generated: bool, preserve_formatting: bool
) -> tuple[Segment, ...]:
    body = root.find("body")
    if body is None:
        return ()
    segments: list[Segment] = []
    for paragraph in body.iter("p"):
        raw = "".join(paragraph.itertext())
        text = _xml_text(raw, is_generated=is_generated, preserve_formatting=preserve_formatting)
        if not text:
            continue
        start_ms = int(paragraph.get("t", "0"))
        words: tuple[Word, ...] = ()
        if is_generated:
            spans = [
                (html.unescape(span.text or "").strip(), int(span.get("t", "0")))
                for span in paragraph.findall("s")
            ]
            words = tuple(Word(word, (start_ms + offset) / 1000) for word, offset in spans if word)
            words = words or (Word(text, start_ms / 1000),)
        segments.append(Segment(start_ms / 1000, int(paragraph.get("d", "0")) / 1000, text, words))
    return tuple(segments)


def _parse_legacy(
    root: ElementTree.Element, *, is_generated: bool, preserve_formatting: bool
) -> tuple[Segment, ...]:
    segments: list[Segment] = []
    for element in root.iter("text"):
        text = _xml_text(
            element.text or "", is_generated=is_generated, preserve_formatting=preserve_formatting
        )
        if not text:
            continue
        start = float(element.get("start", "0"))
        words = (Word(text, start),) if is_generated else ()
        segments.append(Segment(start, float(element.get("dur", "0")), text, words))
    return tuple(segments)


def _xml_text(raw: str, *, is_generated: bool, preserve_formatting: bool) -> str:
    text = html.unescape(raw)
    text = (_NON_FORMAT_TAG if preserve_formatting else _ANY_TAG).sub("", text)
    return _normalize(text, is_generated=is_generated)


def _styled(text: str, seg: Mapping[str, Any], pens: list[Any]) -> str:
    pen_id = seg.get("pPenId")
    pen: Mapping[str, Any] = (
        mapping(pens[pen_id]) if isinstance(pen_id, int) and 0 <= pen_id < len(pens) else {}
    )
    tags = [tag for attribute, tag in _FORMAT_ATTRIBUTES if pen.get(attribute)]
    if not tags or not text.strip():
        return text
    opening = "".join(f"<{tag}>" for tag in tags)
    closing = "".join(f"</{tag}>" for tag in reversed(tags))
    return f"{opening}{text}{closing}"


def _normalize(text: str, *, is_generated: bool) -> str:
    if is_generated:
        return " ".join(text.split())
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)
