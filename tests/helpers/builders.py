"""Tiny builders for model objects used across tests."""

from __future__ import annotations

from utmax.models import Language, Segment, Track, TrackFetcher, Transcript, VideoInfo

VIDEO = VideoInfo(
    video_id="dQw4w9WgXcQ",
    title="Rick Astley - Never Gonna Give You Up (Official Video)",
    channel="Rick Astley",
    channel_id="UCuAXFkgsw1L7xaCfnd5JJOw",
    duration=213.0,
    is_live_content=False,
)


def make_track(
    code: str = "en",
    *,
    generated: bool = False,
    name: str | None = None,
    translatable: bool = True,
    url: str | None = None,
    translation_languages: tuple[Language, ...] = (),
    fetcher: TrackFetcher | None = None,
) -> Track:
    return Track(
        video=VIDEO,
        language_code=code,
        language=name or code,
        is_generated=generated,
        is_translatable=translatable,
        vss_id=f"{'a' if generated else ''}.{code}",
        _url=url or f"https://www.youtube.com/api/timedtext?v={VIDEO.video_id}&lang={code}",
        _translation_languages=translation_languages,
        _fetcher=fetcher,
    )


def make_transcript(
    *segments: Segment,
    language_code: str = "en",
    language: str = "English",
    is_generated: bool = False,
) -> Transcript:
    return Transcript(
        video=VIDEO,
        language_code=language_code,
        language=language,
        is_generated=is_generated,
        segments=tuple(segments),
    )
