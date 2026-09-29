"""List the videos of a playlist or a channel."""

from __future__ import annotations

import logging
from typing import Any

from utmax.adapters.innertube import InnerTubeClient
from utmax.core.browse import MAX_PAGES, Pager, alert_error, parse_browse_page, resolved_channel_id
from utmax.core.clients import ORDER, ClientProfile
from utmax.core.ids import COLLECTION_KINDS, parse_source, uploads_playlist_id
from utmax.errors import (
    CollectionNotFound,
    CollectionUnavailable,
    InvalidOption,
    YouTubeDataUnparsable,
    YouTubeError,
    YouTubeRequestFailed,
)
from utmax.models import CollectionKind, VideoList

__all__ = ["CollectionService"]

log = logging.getLogger("utmax.youtube")

_NOT_FOUND = (400, 404)
_NEXT_CLIENT = (
    CollectionNotFound,
    CollectionUnavailable,
    YouTubeRequestFailed,
    YouTubeDataUnparsable,
)


class CollectionService:
    """Lists playlists and channels with InnerTube ``browse``: ANDROID_VR first, then WEB."""

    def __init__(self, innertube: InnerTubeClient, *, max_pages: int = MAX_PAGES) -> None:
        self._innertube = innertube
        self._max_pages = max_pages

    def list_videos(
        self, source: str, *, kind: CollectionKind | None = None, limit: int | None = None
    ) -> VideoList:
        """The videos of a playlist or channel; :func:`utmax.list_videos` documents the rules.

        Without ``kind``, a channel link's tab (``/shorts`` and so on) chooses the list, and
        otherwise every upload is listed.
        """
        if kind is not None and kind not in COLLECTION_KINDS:
            raise InvalidOption(f'kind={kind!r} is not "all", "videos", "shorts", "live" or None.')
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
        ):
            raise InvalidOption(f"limit must be a positive whole number or None, not {limit!r}.")
        parsed = parse_source(source)
        if parsed.kind == "playlist":
            if kind not in (None, "all"):
                raise InvalidOption(
                    f"kind={kind!r} only applies to channels; a playlist is listed as it is.",
                    suggestion="Leave kind out for playlists.",
                )
            return self._listing(parsed.id, "all", limit, source=source)
        kind = kind or parsed.tab or "all"
        channel_id = parsed.id or self._resolve(parsed.url, source=source)
        playlist_id = uploads_playlist_id(channel_id, kind)
        try:
            return self._listing(playlist_id, kind, limit, source=source)
        except CollectionNotFound:
            if kind == "all":
                raise
        # YouTube keeps no Shorts or live list for a channel without them, so a missing list
        # means "none" as long as the channel itself has uploads.
        self._listing(uploads_playlist_id(channel_id, "all"), "all", 1, source=source)
        log.info("channel %s has no %s", channel_id, kind)
        return VideoList(title="", source_id=playlist_id, kind=kind, video_count=0, entries=())

    def _listing(
        self, playlist_id: str, kind: CollectionKind, limit: int | None, *, source: str
    ) -> VideoList:
        """Every page of one playlist, from the first client that lists all of it."""
        failures: list[YouTubeError] = []
        for profile in ORDER["browse"]:
            try:
                return self._listing_with(profile, playlist_id, kind, limit, source=source)
            except _NEXT_CLIENT as error:
                log.info(
                    "InnerTube client %s could not list %s: %s", profile.name, playlist_id, error
                )
                failures.append(error)
        raise _most_telling(failures)

    def _listing_with(
        self,
        profile: ClientProfile,
        playlist_id: str,
        kind: CollectionKind,
        limit: int | None,
        *,
        source: str,
    ) -> VideoList:
        first = parse_browse_page(self._first_page(profile, playlist_id, source=source))
        if not first.items:
            if first.alerts:
                raise alert_error(first, source=source)
            if first.video_count != 0:
                raise YouTubeDataUnparsable(
                    f"The {profile.name} client's answer for {playlist_id} holds no videos "
                    "utmax can read."
                )
        pager = Pager(limit=limit, max_pages=self._max_pages)
        token = pager.add(first)
        while token is not None:
            token = pager.add(
                parse_browse_page(self._innertube.browse(profile, continuation=token))
            )
        if pager.truncated:
            log.warning(
                "stopped listing %s after %d pages; the list is incomplete",
                playlist_id,
                self._max_pages,
            )
        elif pager.ended_short(first.video_count):
            # WEB answers a channel's Shorts with 100 items and no continuation, and a page
            # that holds nothing ends any listing, so a short list is not an error, but it
            # must not pass unnoticed either.
            log.warning(
                "InnerTube client %s, playlist %s: listed %d of the %d videos YouTube counts; "
                "the list may be incomplete",
                profile.name,
                playlist_id,
                pager.items,
                first.video_count,
            )
        return VideoList(
            title=first.title,
            source_id=playlist_id,
            kind=kind,
            video_count=first.video_count,
            entries=pager.entries,
        )

    def _first_page(
        self, profile: ClientProfile, playlist_id: str, *, source: str
    ) -> dict[str, Any]:
        try:
            return self._innertube.browse(profile, browse_id=f"VL{playlist_id}")
        except YouTubeRequestFailed as error:
            if error.status_code not in _NOT_FOUND:
                raise
            raise CollectionNotFound(
                f"YouTube could not find {source!r} (HTTP {error.status_code}).", source=source
            ) from None

    def _resolve(self, url: str, *, source: str) -> str:
        """The channel ID behind a handle or custom URL: ANDROID_VR's answer, then WEB's."""
        failures: list[YouTubeError] = []
        for profile in ORDER["resolve"]:
            try:
                channel_id = resolved_channel_id(self._innertube.resolve_url(profile, url))
            except YouTubeRequestFailed as error:
                if error.status_code not in _NOT_FOUND:
                    failures.append(error)
                    continue
                channel_id = None
            except YouTubeDataUnparsable as error:
                failures.append(error)
                continue
            if channel_id is not None:
                return channel_id
            failures.append(
                CollectionNotFound(f"YouTube knows no channel at {source!r}.", source=source)
            )
        raise _most_telling(failures)


def _most_telling(failures: list[YouTubeError]) -> YouTubeError:
    """YouTube's own reason first, then "not found", then the first failure."""
    for wanted in (CollectionUnavailable, CollectionNotFound):
        for failure in failures:
            if isinstance(failure, wanted):
                return failure
    return failures[0]
