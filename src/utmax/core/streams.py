"""Read the streams of a player response and choose the ones to download.

YouTube lists every stream of a video in ``streamingData``: progressive ``formats`` (audio and
video together, at most 360p) and ``adaptiveFormats`` (video-only or audio-only). utmax
downloads one adaptive MP4 video stream and one AAC audio stream and muxes them itself.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit

from utmax.core.clients import DESKTOP_USER_AGENT, PROFILES
from utmax.core.ytdata import items, mapping
from utmax.errors import FormatNotAvailable
from utmax.models import Codec, Container, Format, Quality

__all__ = [
    "COMPAT_MAX_SIDE",
    "MAX_MAX_SIDE",
    "QUICKTIME_MAX_RATE",
    "Stream",
    "choose_streams",
    "describe_stream",
    "parse_streams",
]

COMPAT_MAX_SIDE = 1080
MAX_MAX_SIDE = 2160
QUICKTIME_MAX_RATE = 65535
_MIME = re.compile(r'(video|audio)/(mp4|webm)\s*;\s*codecs="([^"]*)"')
_KINDS: Mapping[str, Literal["video", "audio"]] = {"video": "video", "audio": "audio"}
_CONTAINERS: Mapping[str, Literal["mp4", "webm"]] = {"mp4": "mp4", "webm": "webm"}
_HDR_TRANSFERS = frozenset(
    {"COLOR_TRANSFER_CHARACTERISTICS_SMPTEST2084", "COLOR_TRANSFER_CHARACTERISTICS_ARIB_STD_B67"}
)
_MUXABLE: frozenset[str] = frozenset({"h264", "av1", "aac", "he-aac"})


@dataclass(frozen=True, slots=True)
class Stream:
    """A format plus what downloading it takes; internal, because the URL is bound to your IP."""

    format: Format
    url: str = ""
    expires_at: int | None = None
    user_agent: str = DESKTOP_USER_AGENT
    bit_depth: int = 8
    hdr: bool = False
    drm: bool = False
    live: bool = False
    progressive: bool = False

    @property
    def problem(self) -> str | None:
        """Why utmax cannot download and mux this stream, or ``None`` when it can."""
        if self.drm:
            return "DRM-protected"
        if self.live:
            return "part of a live stream"
        if not self.url:
            return "needs a signature utmax cannot compute"
        if self.progressive:
            return "audio and video combined"
        if self.format.container != "mp4":
            return "WebM"
        if self.hdr or self.bit_depth > 8:
            return "HDR or more than 8 bits"
        if self.format.codec not in _MUXABLE:
            return f"{self.format.codec} codec"
        return None


def parse_streams(streaming_data: Mapping[str, Any]) -> tuple[Stream, ...]:
    """Every stream of ``streamingData`` with a known type, progressive ones first."""
    raws = [*items(streaming_data.get("formats")), *items(streaming_data.get("adaptiveFormats"))]
    parsed = (_stream(mapping(raw)) for raw in raws)
    return tuple(stream for stream in parsed if stream is not None)


def describe_stream(stream: Stream) -> str:
    """``"313 webm vp9 2160p25 (WebM)"``: the label, plus why the stream cannot be used."""
    problem = stream.problem
    return stream.format.label if problem is None else f"{stream.format.label} ({problem})"


def choose_streams(
    streams: Sequence[Stream], *, container: Container, quality: Quality, video_id: str
) -> tuple[Stream | None, Stream]:
    """The video stream (``None`` for audio files) and the audio stream to download.

    Video: MP4 H.264 up to 1080p for ``"compat"``; MP4 H.264 or 8-bit AV1 up to 2160p for
    ``"max"``, AV1 first at the same size; then the higher frame rate and bitrate. Sizes are
    measured on the short side, so vertical videos count like their landscape twins. Audio: MP4
    AAC, preferring the video's default audio track, then streams without dynamic range
    compression, then the higher bitrate; ``.mov`` accepts only stereo at most 65535 Hz.

    Raises:
        FormatNotAvailable: nothing fits; the error lists every stream YouTube offered.
    """
    usable = [stream for stream in streams if stream.problem is None]
    audio = _best_audio(usable, container)
    if audio is None:
        wanted = "stereo AAC audio (needed for .mov)" if container == "mov" else "AAC audio in MP4"
        raise _not_available(streams, wanted, video_id)
    if container in ("m4a", "mp3"):
        return None, audio
    video = _best_video(usable, quality)
    if video is None:
        wanted = (
            "H.264 or 8-bit AV1 video up to 2160p in MP4"
            if quality == "max"
            else "H.264 video up to 1080p in MP4"
        )
        raise _not_available(streams, wanted, video_id)
    return video, audio


def _best_video(streams: Sequence[Stream], quality: Quality) -> Stream | None:
    limit = MAX_MAX_SIDE if quality == "max" else COMPAT_MAX_SIDE
    codecs = ("h264", "av1") if quality == "max" else ("h264",)
    candidates = [
        stream
        for stream in streams
        if stream.format.kind == "video"
        and stream.format.codec in codecs
        and 0 < _short_side(stream.format) <= limit
    ]
    return max(
        candidates,
        key=lambda stream: (
            _short_side(stream.format),
            stream.format.codec == "av1",
            stream.format.fps or 0,
            stream.format.bitrate,
        ),
        default=None,
    )


def _best_audio(streams: Sequence[Stream], container: Container) -> Stream | None:
    candidates = [
        stream
        for stream in streams
        if stream.format.kind == "audio" and stream.format.codec in ("aac", "he-aac")
    ]
    if container == "mov":
        candidates = [
            stream
            for stream in candidates
            if (stream.format.audio_channels or 2) <= 2
            and (stream.format.audio_sample_rate or 0) <= QUICKTIME_MAX_RATE
        ]
    return max(
        candidates,
        key=lambda stream: (
            stream.format.is_default_audio,
            not stream.format.is_drc,
            stream.format.bitrate,
        ),
        default=None,
    )


def _short_side(fmt: Format) -> int:
    return min((n for n in (fmt.width, fmt.height) if n), default=0)


def _not_available(streams: Sequence[Stream], wanted: str, video_id: str) -> FormatNotAvailable:
    if streams and all(stream.live for stream in streams):
        message = f"Video {video_id} is a live stream; it can be downloaded after it ends."
    elif not streams:
        message = f"YouTube offered no streams for video {video_id}."
    else:
        message = f"Video {video_id} has no {wanted}."
    return FormatNotAvailable(
        message, available=[describe_stream(stream) for stream in streams], video_id=video_id
    )


def _stream(raw: Mapping[str, Any]) -> Stream | None:
    match = _MIME.match(str(raw.get("mimeType") or ""))
    itag = _int(raw.get("itag"))
    if match is None or itag is None:
        return None
    codecs = match[3].strip()
    first = codecs.split(",", maxsplit=1)[0].strip()
    url = raw["url"] if isinstance(raw.get("url"), str) else ""
    query = dict(parse_qsl(urlsplit(url).query))
    profile = PROFILES.get(query.get("c", ""))
    track = mapping(raw.get("audioTrack"))
    return Stream(
        format=Format(
            itag=itag,
            kind=_KINDS[match[1]],
            container=_CONTAINERS[match[2]],
            codec=_codec(first),
            codecs=codecs,
            width=_int(raw.get("width")),
            height=_int(raw.get("height")),
            fps=_int(raw.get("fps")),
            bitrate=_int(raw.get("bitrate")) or 0,
            content_length=_int(raw.get("contentLength")),
            audio_sample_rate=_int(raw.get("audioSampleRate")),
            audio_channels=_int(raw.get("audioChannels")),
            is_default_audio=bool(track.get("audioIsDefault", True)),
            is_drc=bool(raw.get("isDrc", False)),
            last_modified=str(raw.get("lastModified") or ""),
        ),
        url=url,
        expires_at=_int(query.get("expire")),
        user_agent=profile.user_agent if profile is not None else DESKTOP_USER_AGENT,
        bit_depth=_bit_depth(first),
        hdr=_is_hdr(raw),
        drm=bool(raw.get("drmFamilies")),
        live="targetDurationSec" in raw,
        progressive="," in codecs,
    )


def _codec(codec: str) -> Codec:
    family, _, rest = codec.lower().partition(".")
    if family == "avc1":
        return "h264"
    if family == "av01":
        return "av1"
    if family in ("vp9", "vp09"):
        return "vp9"
    if family == "opus":
        return "opus"
    if family == "mp4a" and rest.startswith("40."):
        return "he-aac" if rest in ("40.5", "40.29") else "aac"
    return "other"


def _bit_depth(codec: str) -> int:
    """The bit depth of AV1 (``av01.P.LLT.DD``) and VP9 (``vp09.PP.LL.DD``) codec strings."""
    parts = codec.lower().split(".")
    if (
        parts[0] in ("av01", "vp09")
        and len(parts) > 3
        and parts[3].isascii()
        and parts[3].isdigit()
    ):
        return int(parts[3])
    return 8


def _is_hdr(raw: Mapping[str, Any]) -> bool:
    transfer = mapping(raw.get("colorInfo")).get("transferCharacteristics")
    return transfer in _HDR_TRANSFERS or "HDR" in str(raw.get("qualityLabel") or "")


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None
