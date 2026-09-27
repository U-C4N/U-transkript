"""List, select and download subtitle tracks."""

from __future__ import annotations

from collections.abc import Sequence

from utmax.adapters.innertube import InnerTubeClient
from utmax.core.captions import parse_captions
from utmax.core.ids import parse_video_id
from utmax.errors import TranscriptsDisabled
from utmax.models import Track, TrackList, Transcript, VideoInfo

__all__ = ["TranscriptService"]


class TranscriptService:
    """Transcript use cases on top of the InnerTube adapter; binds tracks to itself for fetching."""

    def __init__(self, innertube: InnerTubeClient) -> None:
        self._innertube = innertube

    def list_tracks(self, video: str) -> TrackList:
        video_id = parse_video_id(video)
        player = self._innertube.player(video_id, purpose="captions")
        if not player.caption_tracks:
            raise TranscriptsDisabled(f"Video {video_id} has no subtitles.", video_id=video_id)
        tracks = tuple(
            Track(
                video=player.video,
                language_code=info.language_code,
                language=info.name,
                is_generated=info.is_generated,
                is_translatable=info.is_translatable,
                vss_id=info.vss_id,
                _url=info.base_url,
                _translation_languages=player.translation_languages,
                _fetcher=self,
            )
            for info in player.caption_tracks
        )
        return TrackList(
            video=player.video, tracks=tracks, translation_languages=player.translation_languages
        )

    def fetch(
        self,
        video: str,
        languages: Sequence[str] | str | None = None,
        *,
        include_manual: bool = True,
        include_generated: bool = True,
        preserve_formatting: bool = False,
        youtube_translation: str | None = None,
    ) -> Transcript:
        track = self.list_tracks(video).find(
            languages, include_manual=include_manual, include_generated=include_generated
        )
        if youtube_translation is not None:
            track = track.translate(youtube_translation)
        return track.fetch(preserve_formatting=preserve_formatting)

    def video_info(self, video: str) -> VideoInfo:
        return self._innertube.player(parse_video_id(video), purpose="captions").video

    def fetch_track(self, track: Track, *, preserve_formatting: bool) -> Transcript:
        response = self._innertube.fetch_captions(track._url, video_id=track.video_id)
        segments = parse_captions(
            response.body,
            response.content_type,
            is_generated=track.is_generated,
            preserve_formatting=preserve_formatting,
            video_id=track.video_id,
        )
        return Transcript(
            video=track.video,
            language_code=track.language_code,
            language=track.language,
            is_generated=track.is_generated,
            segments=segments,
            translated_from=track.translation_of,
            translator="youtube" if track.translation_of else None,
        )
