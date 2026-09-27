"""Tests for video ID extraction."""

from __future__ import annotations

import pytest

from utmax.core.ids import parse_video_id
from utmax.errors import InvalidVideoId

ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "value",
    [
        ID,
        f"  {ID}\n",
        f"https://www.youtube.com/watch?v={ID}",
        f"https://www.youtube.com/watch?feature=share&v={ID}&t=42s",
        f"https://www.youtube.com/watch?v={ID}&list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI&index=2",
        f"http://youtube.com/watch?v={ID}",
        f"youtube.com/watch?v={ID}",
        f"HTTPS://WWW.YOUTUBE.COM/watch?v={ID}",
        f"https://m.youtube.com/watch?v={ID}",
        f"https://music.youtube.com/watch?v={ID}&feature=share",
        f"https://www.youtube.com/watch/?v={ID}",
        f"https://www.youtube.com/?v={ID}",
        f"https://youtu.be/{ID}",
        f"https://youtu.be/{ID}?si=Ab12Cd34&t=10",
        f"youtu.be/{ID}",
        f"https://www.youtube.com/shorts/{ID}?feature=share",
        f"https://www.youtube.com/shorts/{ID}/",
        f"https://www.youtube.com/live/{ID}?si=x",
        f"https://www.youtube.com/embed/{ID}?start=30",
        f"https://www.youtube-nocookie.com/embed/{ID}",
        f"https://www.youtube.com/v/{ID}",
    ],
)
def test_accepts_ids_and_every_common_url_shape(value: str) -> None:
    assert parse_video_id(value) == ID


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "not a video",
        ID[:-1],
        f"{ID}Q",
        "https://vimeo.com/123456789",
        "https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI",
        "https://www.youtube.com/@RickAstleyYT",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/",
        "https://youtu.be/",
        f"https://evil.example/watch?v={ID}",
        f"https://youtube.com.evil.example/watch?v={ID}",
        "http://[::1",
    ],
)
def test_rejects_anything_without_a_video_id(value: str) -> None:
    with pytest.raises(InvalidVideoId) as caught:
        parse_video_id(value)
    assert repr(value) in str(caught.value)
    assert "11-character" in caught.value.suggestion
