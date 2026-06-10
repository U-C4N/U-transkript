import argparse
import os
from unittest.mock import MagicMock, patch

import pytest

from cli.channel_downloader import _ensure_output_dir
from cli.channel_scraper import (
    _channel_url_variants,
    _dedup_preserving_order,
    _extract_ids_from_html,
    _fetch_html,
)
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
    def test_returns_iterable(self):
        items = [1, 2, 3]
        assert list(get_progress_bar(items, total=3)) == items


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
        args = argparse.Namespace(output=str(tmp_path / "out.txt"))
        format_and_output("hello", args)
        assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hello"

    def test_prints_to_stdout(self, capsys):
        args = argparse.Namespace(output=None)
        format_and_output("hi", args)
        captured = capsys.readouterr()
        assert "hi" in captured.out


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


class TestFetchHtml:
    def test_uses_timeout(self):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.text = "<html></html>"
        with patch(
            "cli.channel_scraper.requests.get", return_value=mock_response
        ) as mock_get:
            assert _fetch_html("https://www.youtube.com/@x/videos") == "<html></html>"
        assert mock_get.call_args.kwargs["timeout"] == 30


class TestEnsureOutputDir:
    def test_url_target_sanitized_for_windows(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _ensure_output_dir("https://www.youtube.com/@SomeChannel", None)
        assert not any(c in result for c in '<>:"/\\|?*')
        assert os.path.isdir(result)

    def test_explicit_output_used_verbatim(self, tmp_path):
        out = str(tmp_path / "outdir")
        assert _ensure_output_dir("@x", out) == out
        assert os.path.isdir(out)

    def test_bare_at_falls_back_to_channel(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert _ensure_output_dir("@", None) == "channel"
