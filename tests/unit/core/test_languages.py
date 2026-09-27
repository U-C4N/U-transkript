"""Tests for language names, ISO 639-2/T codes and QuickTime language codes."""

from __future__ import annotations

import pytest

from utmax.core import languages
from utmax.core.languages import base_code, english_name, iso639_2t, mac_language_code

# The languages YouTube offered for translation on 2026-09-27 (player fixture), plus the
# caption languages seen in the recorded fixtures.
YOUTUBE_CODES = (
    "ar", "zh-Hant", "nl", "en", "fr", "de", "hi", "id", "it", "ja", "ko", "pt", "ru", "es",
    "th", "tr", "uk", "vi", "de-DE", "pt-BR", "es-419", "zh-Hans", "iw", "fil", "haw", "yue",
)  # fmt: skip


@pytest.mark.parametrize(
    ("code", "expected"),
    [("pt-BR", "pt"), ("EN", "en"), ("zh_Hant", "zh"), (" es-419 ", "es"), ("fil", "fil")],
)
def test_base_code(code: str, expected: str) -> None:
    assert base_code(code) == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("tr", "Turkish"),
        ("pt-BR", "Portuguese"),
        ("zh-Hant", "Chinese"),
        ("iw", "Hebrew"),
        ("in", "Indonesian"),
        ("fil", "Filipino"),
        ("nb", "Norwegian Bokm\xe5l"),
        ("TUR", "Turkish"),
        ("ger", "German"),
        ("mul", "Multiple languages"),
    ],
)
def test_english_name(code: str, expected: str) -> None:
    assert english_name(code) == expected


@pytest.mark.parametrize("code", ["xx", "", "und", "en+tr", "klingon"])
def test_unknown_languages_have_no_name_and_are_undetermined(code: str) -> None:
    assert english_name(code) is None
    assert iso639_2t(code) == "und"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("tr", "tur"),
        ("de-DE", "deu"),
        ("zh", "zho"),
        ("fr-CA", "fra"),
        ("cs", "ces"),
        ("iw", "heb"),
        ("fil", "fil"),
        ("yue", "zho"),
        ("fre", "fra"),
    ],
)
def test_iso639_2t(code: str, expected: str) -> None:
    assert iso639_2t(code) == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("en", 0),
        ("fr", 1),
        ("de-DE", 2),
        ("sv", 5),
        ("iw", 10),
        ("ja", 11),
        ("tr", 17),
        ("hr", 18),
        ("ko", 23),
        ("ru", 32),
        ("ga", 35),
        ("az", 49),
        ("pa", 70),
        ("cy", 128),
        ("jv", 138),
    ],
)
def test_mac_language_code(code: str, expected: int) -> None:
    assert mac_language_code(code) == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [("zh-Hant", 19), ("zh-TW", 19), ("zh-hk", 19), ("zh", 33), ("zh-Hans", 33), ("zh-CN", 33)],
)
def test_chinese_mac_code_follows_the_script(code: str, expected: int) -> None:
    assert mac_language_code(code) == expected


@pytest.mark.parametrize("code", ["fil", "se", "xx", "", "und", "mul"])
def test_unmapped_mac_codes_are_none(code: str) -> None:
    assert mac_language_code(code) is None


def test_the_ffmpeg_table_is_transcribed_in_full() -> None:
    table = languages._FFMPEG_MAC_LANGUAGES
    assert len(table) == 139
    assert (table[0], table[17], table[32], table[94], table[128], table[138]) == (
        "eng",
        "tur",
        "rus",
        "epo",
        "wel",
        "jav",
    )
    assert all(entry == "" for entry in table[95:128])


def test_mac_codes_are_the_first_ffmpeg_index_of_each_language() -> None:
    table = languages._FFMPEG_MAC_LANGUAGES
    for spelled in table:
        name = spelled.strip()
        if name in {"", "smi", "mol", "chi"}:  # blank, no ISO 639-1 code, script-dependent
            continue
        code = languages._FFMPEG_SPELLINGS.get(name, name)
        assert mac_language_code(code) == table.index(spelled), spelled
    assert len(languages._MAC_CODES) == 99


def test_table_entries_are_well_formed() -> None:
    for base, (iso, name) in languages._LANGUAGES.items():
        assert base == base.lower()
        assert base.isascii()
        assert len(base) in (2, 3)
        assert len(iso) == 3
        assert iso.isascii()
        assert iso.islower()
        assert name
        assert name == name.strip()
    assert sum(len(base) == 2 for base in languages._LANGUAGES) == 183


@pytest.mark.parametrize("code", YOUTUBE_CODES)
def test_every_youtube_language_is_known(code: str) -> None:
    assert english_name(code)
    assert iso639_2t(code) != "und"
