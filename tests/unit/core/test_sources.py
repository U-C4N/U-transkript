"""Tests for finding the playlist or channel in what a user pastes."""

from __future__ import annotations

import pytest

from utmax.core.ids import COLLECTION_KINDS, Source, parse_source, uploads_playlist_id
from utmax.errors import CollectionUnavailable, InvalidSource
from utmax.models import CollectionKind

PLAYLIST = "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"
ALBUM = "OLAK5uy_nMr9h2VlS-2PULNz3M3XVXQj_P3C2bqaY"
CHANNEL = "UCuAXFkgsw1L7xaCfnd5JJOw"
HANDLE_URL = "https://www.youtube.com/@RickAstleyYT"


@pytest.mark.parametrize(
    ("value", "playlist_id"),
    [
        (PLAYLIST, PLAYLIST),
        (f"  {PLAYLIST}\n", PLAYLIST),
        (f"https://www.youtube.com/playlist?list={PLAYLIST}", PLAYLIST),
        (f"youtube.com/playlist?list={PLAYLIST}&si=abc", PLAYLIST),
        (f"https://www.youtube.com/watch?v=dQw4w9WgXcQ&list={PLAYLIST}&index=3", PLAYLIST),
        (f"https://youtu.be/dQw4w9WgXcQ?list={PLAYLIST}", PLAYLIST),
        (f"https://m.youtube.com/playlist?list={PLAYLIST}", PLAYLIST),
        (f"https://music.youtube.com/playlist?list={ALBUM}", ALBUM),
        (ALBUM, ALBUM),
        ("UUuAXFkgsw1L7xaCfnd5JJOw", "UUuAXFkgsw1L7xaCfnd5JJOw"),
        ("UULFuAXFkgsw1L7xaCfnd5JJOw", "UULFuAXFkgsw1L7xaCfnd5JJOw"),
        ("FLuAXFkgsw1L7xaCfnd5JJOw", "FLuAXFkgsw1L7xaCfnd5JJOw"),
        ("https://www.youtube.com/playlist?list=WL", "WL"),
    ],
)
def test_playlists(value: str, playlist_id: str) -> None:
    assert parse_source(value) == Source("playlist", id=playlist_id)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (CHANNEL, Source("channel", id=CHANNEL)),
        (f"https://www.youtube.com/channel/{CHANNEL}", Source("channel", id=CHANNEL)),
        (f"www.youtube.com/channel/{CHANNEL}/videos", Source("channel", id=CHANNEL, tab="videos")),
        (f"https://music.youtube.com/channel/{CHANNEL}", Source("channel", id=CHANNEL)),
        ("@RickAstleyYT", Source("channel", url=HANDLE_URL)),
        (HANDLE_URL, Source("channel", url=HANDLE_URL)),
        (f"{HANDLE_URL}/shorts", Source("channel", url=HANDLE_URL, tab="shorts")),
        (f"{HANDLE_URL}/streams", Source("channel", url=HANDLE_URL, tab="live")),
        (f"{HANDLE_URL}/Shorts/", Source("channel", url=HANDLE_URL, tab="shorts")),
        (f"{HANDLE_URL}/playlists", Source("channel", url=HANDLE_URL)),
        (
            "m.youtube.com/@RickAstleyYT/videos?view=0",
            Source("channel", url=HANDLE_URL, tab="videos"),
        ),
        ("//www.youtube.com/@RickAstleyYT", Source("channel", url=HANDLE_URL)),
        (
            "https://www.youtube.com/c/RickAstleyYT/featured",
            Source("channel", url="https://www.youtube.com/c/RickAstleyYT"),
        ),
        (
            "https://www.youtube.com/user/RickAstleyVEVO",
            Source("channel", url="https://www.youtube.com/user/RickAstleyVEVO"),
        ),
        (
            "https://www.youtube.com/user/RickAstleyVEVO/streams",
            Source("channel", url="https://www.youtube.com/user/RickAstleyVEVO", tab="live"),
        ),
        (
            "https://www.youtube.com/@%D0%9A%D0%B0%D0%BD%D0%B0%D0%BB",
            Source("channel", url="https://www.youtube.com/@%D0%9A%D0%B0%D0%BD%D0%B0%D0%BB"),
        ),
    ],
)
def test_channels(value: str, expected: Source) -> None:
    assert parse_source(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "RDdQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ&start_radio=1",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RDAMVMdQw4w9WgXcQ",
    ],
)
def test_mixes_are_refused_before_any_request(value: str) -> None:
    with pytest.raises(CollectionUnavailable, match="is a Mix") as caught:
        parse_source(value)
    assert caught.value.source == value
    assert caught.value.reason == "YouTube does not list Mixes."


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "@",
        "PLshort",
        "RickAstleyYT",
        "https://example.com/playlist?list=" + PLAYLIST,
        "https://www.youtube.com/playlist?list=PL%20bad",
        "https://www.youtube.com/channel/UCshort",
        "https://www.youtube.com/channel/",
        "https://www.youtube.com/c/",
        "https://www.youtube.com/feed/subscriptions",
        "https://www.youtube.com/RickAstleyYT",
        "https://youtu.be/",
        "http://[::1",
    ],
)
def test_anything_else_is_invalid(value: str) -> None:
    with pytest.raises(InvalidSource, match="Could not find a playlist or channel"):
        parse_source(value)


@pytest.mark.parametrize(
    "value", ["dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ", "youtube.com/shorts/dQw4w9WgXcQ"]
)
def test_single_videos_point_to_fetch_and_download(value: str) -> None:
    with pytest.raises(InvalidSource, match="single video") as caught:
        parse_source(value)
    assert "utmax.fetch()" in caught.value.suggestion


@pytest.mark.parametrize(
    ("kind", "playlist_id"),
    [
        ("all", "UUuAXFkgsw1L7xaCfnd5JJOw"),
        ("videos", "UULFuAXFkgsw1L7xaCfnd5JJOw"),
        ("shorts", "UUSHuAXFkgsw1L7xaCfnd5JJOw"),
        ("live", "UULVuAXFkgsw1L7xaCfnd5JJOw"),
    ],
)
def test_uploads_playlists_by_kind(kind: CollectionKind, playlist_id: str) -> None:
    assert kind in COLLECTION_KINDS
    assert uploads_playlist_id(CHANNEL, kind) == playlist_id
