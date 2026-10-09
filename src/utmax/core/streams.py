"""Read the streams of a player response and choose the ones to download.

YouTube lists every stream of a video in ``streamingData``: progressive ``formats`` (audio and
video together, at most 360p) and ``adaptiveFormats`` (video-only or audio-only). utmax
downloads one adaptive video stream and one audio stream that fit the target file and muxes
them itself.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit

from utmax.core.clients import DESKTOP_USER_AGENT, PROFILES
from utmax.core.ytdata import items, mapping
from utmax.errors import FormatNotAvailable
from utmax.models import Codec, Container, Format, Quality

__all__ = [
    "COMPAT_MAX_SIDE",
    "QUICKTIME_MAX_RATE",
    "Stream",
    "choose_streams",
    "describe_stream",
    "file_types",
    "parse_streams",
]

COMPAT_MAX_SIDE = 1080
QUICKTIME_MAX_RATE = 65535
_MIME = re.compile(r'(video|audio)/(mp4|webm)\s*;\s*codecs="([^"]*)"')
_KINDS: Mapping[str, Literal["video", "audio"]] = {"video": "video", "audio": "audio"}
_CONTAINERS: Mapping[str, Literal["mp4", "webm"]] = {"mp4": "mp4", "webm": "webm"}
_HDR_TRANSFERS = frozenset(
    {"COLOR_TRANSFER_CHARACTERISTICS_SMPTEST2084", "COLOR_TRANSFER_CHARACTERISTICS_ARIB_STD_B67"}
)
# The video codecs each file type holds, the preferred one first.
_VIDEO_CODECS: Mapping[Container, tuple[Codec, ...]] = {"mp4": ("av1", "h264"), "mov": ("h264",)}
_AUDIO_CODECS: tuple[Codec, ...] = ("aac", "he-aac")
_CODEC_NAMES: tuple[tuple[Codec, str], ...] = (("h264", "H.264"), ("av1", "AV1"))


@dataclass(frozen=True, slots=True)
class Stream:
    """A format plus what downloading it takes; internal, because the URL is bound to your IP."""

    format: Format
    url: str = field(default="", repr=False)
    expires_at: int | None = None
    user_agent: str = DESKTOP_USER_AGENT
    drm: bool = False
    live: bool = False
    progressive: bool = False

    @property
    def problem(self) -> str | None:
        """Why utmax can never download this stream, or ``None`` when it can.

        Whether a usable stream fits a file type is :func:`choose_streams`' business.
        """
        if self.drm:
            return "DRM-protected"
        if self.live:
            return "part of a live stream"
        if not self.url:
            return "needs a signature utmax cannot compute"
        if self.progressive:
            return "audio and video combined"
        if self.format.codec == "other":
            return "other codec"
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


def file_types(fmt: Format) -> tuple[Container, ...]:
    """The file types a stream can go into with ``quality="best"``."""
    if fmt.kind == "video":
        return tuple(
            container for container, codecs in _VIDEO_CODECS.items() if fmt.codec in codecs
        )
    if fmt.codec in _AUDIO_CODECS:
        return ("mp4", "mov", "m4a", "mp3")
    return ()


def choose_streams(
    streams: Sequence[Stream],
    *,
    container: Container,
    quality: Quality,
    resolution: int | None = None,
    video_id: str,
) -> tuple[Stream | None, Stream]:
    """The video stream (``None`` for audio files) and the audio stream to download.

    Video, sizes measured on the short side so that vertical videos count like their landscape
    twins: ``"best"`` takes the largest picture the file type holds (``.mp4``: AV1 or H.264,
    HDR included; ``.mov``: H.264) up to ``resolution`` lines, then the higher frame rate, then
    SDR over HDR, then AV1 over H.264, then the higher bitrate. ``"compat"`` takes SDR H.264 up
    to 1080p (or ``resolution``, when smaller), which plays everywhere. Audio: AAC, preferring
    the original track of a dubbed video, then YouTube's default track, then streams without
    dynamic range compression, then the higher bitrate; ``.mov`` accepts only stereo at most
    65535 Hz.

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
    codecs = ("h264",) if quality == "compat" else _VIDEO_CODECS[container]
    limit = resolution
    if quality == "compat":
        limit = min(resolution or COMPAT_MAX_SIDE, COMPAT_MAX_SIDE)
    video = _best_video(usable, codecs, limit, sdr_only=quality == "compat")
    if video is None:
        raise _not_available(streams, _wanted_video(container, codecs, limit), video_id)
    return video, audio


def _best_video(
    streams: Sequence[Stream], codecs: tuple[Codec, ...], limit: int | None, *, sdr_only: bool
) -> Stream | None:
    candidates = [
        stream
        for stream in streams
        if stream.format.kind == "video"
        and stream.format.codec in codecs
        and 0 < _short_side(stream.format) <= (limit or _short_side(stream.format))
        and not (sdr_only and stream.format.hdr)
    ]
    return max(
        candidates,
        key=lambda stream: (
            _short_side(stream.format),
            stream.format.fps or 0,
            not stream.format.hdr,
            -codecs.index(stream.format.codec),
            stream.format.bitrate,
        ),
        default=None,
    )


def _wanted_video(container: Container, codecs: tuple[Codec, ...], limit: int | None) -> str:
    """``"H.264 or AV1 video up to 720p in MP4"`` and the like, for an error message."""
    names = " or ".join(name for codec, name in _CODEC_NAMES if codec in codecs)
    size = f" up to {limit}p" if limit is not None else ""
    where = " in MP4" if container == "mp4" and len(codecs) > 1 else ""
    return f"{names} video{size}{where}"


def _best_audio(streams: Sequence[Stream], container: Container) -> Stream | None:
    candidates = [
        stream
        for stream in streams
        if stream.format.kind == "audio" and stream.format.codec in _AUDIO_CODECS
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
            stream.format.is_original,
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
    tags = _xtags(query.get("xtags", ""))
    name = str(track.get("displayName") or "")
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
            hdr=_is_hdr(raw),
            bit_depth=_bit_depth(first),
            language=str(track.get("id") or "").partition(".")[0] or tags.get("lang") or None,
            is_original=tags.get("acont") == "original" or name.lower().endswith(" original"),
        ),
        url=url,
        expires_at=_int(query.get("expire")),
        user_agent=profile.user_agent if profile is not None else DESKTOP_USER_AGENT,
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


def _xtags(text: str) -> dict[str, str]:
    """YouTube's ``xtags`` of a stream, such as ``acont=original:lang=en-US``, as a dict."""
    pairs = (part.partition("=") for part in text.split(":") if part)
    return {key: value for key, _, value in pairs}


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
