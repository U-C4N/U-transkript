import argparse

import pytest

from cli.helpers import (
    EXIT_API_ERROR,
    EXIT_NETWORK_ERROR,
    EXIT_SUCCESS,
    EXIT_USER_ERROR,
    build_formatter_kwargs,
    build_proxies,
    get_progress_bar,
)
from cli.output import file_extension_for, format_and_output
from cli.channel_scraper import (
    _channel_url_variants,
    _dedup_preserving_order,
    _extract_ids_from_html,
)


class TestExitCodes:
    def test_distinct_and_stable(self):
        assert {EXIT_SUCCESS, EXIT_USER_ERROR, EXIT_NETWORK_ERROR, EXIT_API_ERROR} == {0, 1, 2, 3}


class TestBuildFormatterKwargs:
    def test_pretty(self):
        assert build_formatter_kwargs("pretty") == {
            "show_timestamps": True,
            "max_chars_per_line": 80,
        }

    def test_json(self):
        assert build_formatter_kwargs("json") == {"indent": 2, "ensure_ascii": False}

    def test_text(self):
        assert build_formatter_kwargs("text") == {"separator": " "}

    def test_srt_and_vtt_empty(self):
        assert build_formatter_kwargs("srt") == {}
        assert build_formatter_kwargs("vtt") == {}

    def test_unknown_returns_empty(self):
        assert build_formatter_kwargs("bogus") == {}


class TestBuildProxies:
    def test_none(self):
        assert build_proxies(None) is None

    def test_empty_string(self):
        assert build_proxies("") is None

    def test_url(self):
        assert build_proxies("http://p:8080") == {
            "http": "http://p:8080",
            "https": "http://p:8080",
        }


class TestProgressBar:
    def test_disable_returns_iterable_verbatim(self):
        items = [1, 2, 3]
        assert list(get_progress_bar(items, total=3, disable=True)) == items

    def test_enabled_returns_wrapped_iterable(self):
        items = [1, 2]
        result = list(get_progress_bar(items, total=2, disable=False))
        assert result == items


class TestFileExtensionFor:
    @pytest.mark.parametrize(
        "fmt,ext",
        [
            ("json", "json"),
            ("srt", "srt"),
            ("vtt", "vtt"),
            ("pretty", "txt"),
            ("text", "txt"),
            ("bogus", "txt"),
        ],
    )
    def test_extensions(self, fmt, ext):
        assert file_extension_for(fmt) == ext


class TestFormatAndOutput:
    def test_writes_to_file(self, tmp_path):
        args = argparse.Namespace(output=str(tmp_path / "out.txt"), quiet=True)
        format_and_output("hello", args)
        assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hello"

    def test_prints_to_stdout(self, capsys):
        args = argparse.Namespace(output=None, quiet=False)
        format_and_output("hi", args)
        captured = capsys.readouterr()
        assert "hi" in captured.out

    def test_writes_to_file_not_quiet(self, tmp_path, capsys):
        args = argparse.Namespace(output=str(tmp_path / "out.txt"), quiet=False)
        format_and_output("hello", args)
        captured = capsys.readouterr()
        assert "saved" in captured.out.lower() or "hello" not in captured.out


class TestChannelUrlVariants:
    def test_videos_variant_list(self):
        base = "https://www.youtube.com/@MrBeast/videos?sort=dd"
        variants = _channel_url_variants(base)
        assert base in variants
        assert any("uploads" in v for v in variants)
        assert any("c/" in v for v in variants)


class TestDedupPreservingOrder:
    def test_order_preserved(self):
        assert _dedup_preserving_order(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]

    def test_empty(self):
        assert _dedup_preserving_order([]) == []


class TestExtractIdsFromHtml:
    def test_matches_video_id_pattern(self):
        html = '{"videoId":"dQw4w9WgXcQ"} also /watch?v=aBcDeFgHiJk'
        ids = _extract_ids_from_html(html)
        assert "dQw4w9WgXcQ" in ids
        assert "aBcDeFgHiJk" in ids

    def test_no_matches(self):
        assert _extract_ids_from_html("no ids here") == []
