"""A fake YouTube for download tests: InnerTube, captions and googlevideo behind one transport.

The streams are real fragmented MP4 files built by ``tests.helpers.fmp4_factory``: H.264
(itag 137) and AV1 (itag 399) video of 100 frames at 25 fps, and AAC audio (itag 140) of
172 frames at 44.1 kHz, so the muxer and ``parse_progressive`` run on genuine data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.helpers.fake_media import FakeBody, FakeMedia
from tests.helpers.fake_transport import FakeTransport, json_response
from tests.helpers.fmp4_factory import Sample, Track, simple_file
from tests.helpers.youtube import MANUAL_JSON3, json3_payload, player_payload, visitor_payload
from utmax.adapters.ffmpeg import FFmpeg
from utmax.adapters.files import FileByteSource
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.media.progressive import ProgressiveFile, parse_progressive
from utmax.services.download import DownloadService
from utmax.services.transcripts import TranscriptService
from utmax.transport import HttpRequest, HttpResponse

VIDEO_BYTES = simple_file(
    [Sample(512, 600 + index % 50, sync=index % 25 == 0) for index in range(100)],
    track=Track(),
    per_fragment=25,
)
AV1_BYTES = simple_file(
    [Sample(512, 400 + index % 30, sync=index % 25 == 0) for index in range(100)],
    track=Track(codec="av01"),
    per_fragment=25,
)
AUDIO_BYTES = simple_file(
    [Sample(1024, 300 + index % 9) for index in range(172)],
    track=Track(handler="soun", codec="mp4a", timescale=44100),
    per_fragment=43,
)
LAST_MODIFIED = "1766957926174250"


def _format(itag: int, mime: str, url: str, size: int, **fields: Any) -> dict[str, Any]:
    return {
        "itag": itag,
        "mimeType": mime,
        "url": f"{url}?c=VISIONOS",
        "bitrate": 1000 * itag,
        "contentLength": str(size),
        "lastModified": LAST_MODIFIED,
        **fields,
    }


def streaming_data_for(media: FakeMedia) -> dict[str, Any]:
    """``streamingData`` whose URLs point at ``media``."""
    video = {"width": 1920, "height": 1080, "fps": 25}
    return {
        "expiresInSeconds": "21540",
        "adaptiveFormats": [
            _format(
                137,
                'video/mp4; codecs="avc1.640028"',
                media.add("137", VIDEO_BYTES),
                len(VIDEO_BYTES),
                **video,
            ),
            _format(
                399,
                'video/mp4; codecs="av01.0.08M.08"',
                media.add("399", AV1_BYTES),
                len(AV1_BYTES),
                **video,
            ),
            _format(
                140,
                'audio/mp4; codecs="mp4a.40.2"',
                media.add("140", AUDIO_BYTES),
                len(AUDIO_BYTES),
                audioSampleRate="44100",
                audioChannels=2,
            ),
        ],
    }


class FakeYouTube:
    """One transport: InnerTube and captions (``api``) plus googlevideo (``media``)."""

    def __init__(self, *, captions: bool = True) -> None:
        self.media = FakeMedia()
        self.api = FakeTransport()
        self.api.add(
            "POST", "/youtubei/v1/visitor_id", json_response(visitor_payload()), repeat=True
        )
        payload = player_payload(streaming_data=streaming_data_for(self.media), captions=captions)
        self.api.add("POST", "/youtubei/v1/player", json_response(payload), repeat=True)
        self.api.add("GET", "lang=en&fmt=json3", json_response(MANUAL_JSON3), repeat=True)
        german = json3_payload((1000, 2000, "Wir sind keine Fremden"))
        self.api.add("GET", "lang=de-DE", json_response(german), repeat=True)

    def send(self, request: HttpRequest) -> HttpResponse:
        return self.api.send(request)

    def stream(self, request: HttpRequest) -> FakeBody:
        return self.media.stream(request)

    def service(self, **options: Any) -> DownloadService:
        innertube = InnerTubeClient(self)
        return DownloadService(innertube, TranscriptService(innertube), self.stream, **options)


def read_movie(path: Path) -> ProgressiveFile:
    with FileByteSource(path) as source:
        return parse_progressive(source)


def codec_of(track: Any) -> bytes:
    """The sample entry type of a parsed track: ``b"avc1"``, ``b"av01"``, ``b"mp4a"``, ``b"tx3g"``."""
    entry: bytes = track.sample_entries[0]
    return entry[4:8]


class _Finished:
    """A process that has already exited successfully."""

    def __init__(self, stdout: bytes = b"") -> None:
        self.returncode: int | None = None
        self._stdout = stdout

    def communicate(self, input: Any = None, timeout: float | None = None) -> tuple[bytes, bytes]:
        self.returncode = 0
        return self._stdout, b""

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        """Nothing to stop."""

    def kill(self) -> None:
        """Nothing to stop."""


class FakeFFmpegRuns:
    """Stands in for ffmpeg: lists libmp3lame, and "converts" by writing an ID3 header."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], **options: Any) -> _Finished:
        self.calls.append(args)
        if "-encoders" in args:
            return _Finished(b" A..... libmp3lame           libmp3lame MP3 (MPEG audio layer 3)\n")
        Path(args[-1]).write_bytes(b"ID3" + bytes(100))
        return _Finished()

    def service(self, youtube: FakeYouTube) -> DownloadService:
        return youtube.service(
            locate=lambda _: "ffmpeg-for-tests",
            make_ffmpeg=lambda executable: FFmpeg(executable, spawn=self),
        )
