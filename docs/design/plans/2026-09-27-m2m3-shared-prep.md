# M2/M3 Shared Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the two things milestones M2 (AI translation) and M3 (media muxer) both build on — the pure `utmax.core.languages` module and the translation/download error classes — on branch `v4`, before M2 and M3 branch off and run in parallel.

**Architecture:** `src/utmax/core/languages.py` is pure table data plus four lookup functions (no I/O). `src/utmax/errors.py` gains eleven classes in the existing hierarchy style (class-level one-sentence `suggestion`, keyword-only fields, pickling through `UTMaxError.__reduce__`), and `src/utmax/__init__.py` re-exports them. No other file changes, so M2 and M3 can both start from the result without touching these files again.

**Tech Stack:** Python ≥ 3.11 standard library only · pytest · ruff · mypy (strict) · uv.

**Spec:** `docs/design/2026-09-27-u-transcript-max-design.md` — §4.4 (spec parser → `InvalidModelSpec`), §5 "Translation engine" (English language names), §5 "Muxer"/"tx3g" (ISO 639-2/T and Macintosh language codes, `MuxError`), §6 (error tree), §8 item 9 (architecture test).

## Global Constraints

- `requires-python = ">=3.11"`; zero runtime dependencies — `src/utmax` imports only the standard library.
- `utmax.core` stays pure: no network, subprocess, threads, clock or filesystem (the architecture test also bans `time`, `shutil` and `tempfile` there).
- The API below is exact — M2 and M3 are written against it; do not rename anything or change a signature:
  - `base_code(code: str) -> str` · `english_name(code: str) -> str | None` · `iso639_2t(code: str) -> str` · `mac_language_code(code: str) -> int | None` (all in `utmax.core.languages`).
  - `InvalidModelSpec(UTMaxError, ValueError)` · `MissingExtra(UTMaxError, ImportError)(message, *, extra: str, video_id=None, suggestion=None)` with `.extra` · `TranslationError(UTMaxError)(message, *, provider: str, video_id=None, suggestion=None)` with `.provider` · `ProviderNotInstalled(TranslationError, MissingExtra)(message, *, provider: str, extra: str, video_id=None, suggestion=None)` · `ProviderAuthError(TranslationError)` · `ProviderRateLimited(TranslationError)` · `ProviderError(TranslationError)(message, *, provider, status_code: int | None = None, video_id=None, suggestion=None)` with `.status_code` · `TranslationRefused(TranslationError)` · `TranslationMismatch(TranslationError)(message, *, provider, ids: Sequence[int], raw_excerpt: str, video_id=None, suggestion=None)` with `.ids` (tuple) and `.raw_excerpt` · `DownloadError(UTMaxError)` · `MuxError(DownloadError)`.
- Every error class has a one-sentence English class-level `suggestion` ending with ".", keyword-only fields, `.video_id`, survives `pickle`, is listed in `utmax.errors.__all__` and is exported from `utmax`.
- Non-ASCII characters appear in Python source only as escape sequences. This plan writes them as `\xXX` or `\U0000XXXX` (eight hex digits) on purpose: some editing tools silently turn four-digit backslash-u escapes into raw characters, which corrupted files in M1. Copy the escapes exactly.
- Code must pass ruff's 100-column formatter and the M1 lint set as written (for example `itertools.pairwise` instead of `zip(a, a[1:])`, `split(..., maxsplit=1)`, `pytest.raises` with a specific exception and `match=`, no unused `noqa`).
- Gates after each task: `uv run ruff check .` · `uv run ruff format --check .` · `uv run mypy` · `uv run pytest` (branch coverage ≥ 90 %; `uv run coverage report --include="*/utmax/core/*" --fail-under=95` after `uv run pytest --cov`).
- Commits use a conventional prefix, stage explicit paths only and end with the trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Work on `v4`; never push, merge to `main` or publish without the user's explicit approval.

## Review Focus

1. **Language codes as users and YouTube write them** — `"PT-br"`, `"zh_Hant"`, `" es-419 "`, the legacy YouTube codes `iw`/`in`/`ji`/`jw`, three-letter codes such as `tur` or `ger` → the right base code, English name and ISO 639-2/T code, never `und` for a language the table knows. Pinned in Task A (`test_base_code`, `test_english_name`, `test_iso639_2t`).
2. **Codes the table does not know** — `"xx"`, `""`, `"und"`, a bilingual `"en+tr"`, a word like `"klingon"` → `None` / `"und"`, never `KeyError` or `IndexError`. Pinned in Task A (`test_unknown_languages_have_no_name_and_are_undetermined`, `test_unmapped_mac_codes_are_none`).
3. **Chinese scripts in QuickTime** — `zh-Hant`, `zh-TW`, `zh-HK` must get the Traditional code (19) and every other `zh` the Simplified one (33), or QuickTime shows the wrong script's name. Pinned in Task A (`test_chinese_mac_code_follows_the_script`).
4. **Errors crossing process boundaries** — bulk helpers and the MCP server may pickle exceptions (process pools, logging queues) → every new error round-trips with its fields, and `MissingExtra`/`ProviderNotInstalled` keep `ImportError.msg`. Pinned in Task B (`test_translation_and_download_errors_survive_pickling`).
5. **Generic `except` clauses in user code** — code that wraps optional imports in `except ImportError` or bad input in `except ValueError` must keep working: `MissingExtra` and `ProviderNotInstalled` are `ImportError`s, `InvalidModelSpec` is a `ValueError`, and `ProviderNotInstalled` still resolves its keyword arguments despite the diamond. Pinned in Task B (`test_translation_and_download_hierarchy`, `test_provider_not_installed_is_a_translation_error_and_a_missing_extra`).

## File map

| File | Responsibility | Task |
|---|---|---|
| `src/utmax/core/languages.py` | English names, ISO 639-2/T codes, QuickTime (Macintosh) language codes | A |
| `tests/unit/core/test_languages.py` | Table-driven tests of the four functions and the table | A |
| `src/utmax/errors.py` | Eleven new error classes; `_restore` keeps `ImportError.msg` | B |
| `src/utmax/__init__.py` | Re-export the new errors (import block and `__all__` only) | B |
| `tests/unit/test_errors.py` | M1 tests plus tests for every new class | B |

---

### Task A: Language metadata (`core/languages.py`)

**Files:**
- Create: `src/utmax/core/languages.py`
- Test: `tests/unit/core/test_languages.py`

**Interfaces:**
- Consumes: nothing.
- Produces (in `utmax.core.languages`):
  - `base_code(code: str) -> str` — the lower-cased primary subtag: strip whitespace, treat `_` as `-`, keep what precedes the first `-` (`"pt-BR"` → `"pt"`, `"EN"` → `"en"`, `"zh_Hant"` → `"zh"`).
  - `english_name(code: str) -> str | None` — English name of the base language (`"tr"` → `"Turkish"`, `"pt-BR"` → `"Portuguese"`, `"zh-Hant"` → `"Chinese"`); unknown → `None`.
  - `iso639_2t(code: str) -> str` — ISO 639-2/T code of the base language (`"tr"` → `"tur"`, `"de-DE"` → `"deu"`, `"zh"` → `"zho"`); unknown → `"und"`.
  - `mac_language_code(code: str) -> int | None` — QuickTime language code for a MOV `mdhd` (English 0, French 1, German 2, Japanese 11, Turkish 17, Korean 23, Russian 32, Welsh 128 …); `None` when FFmpeg's table has no entry.
- Lookup rules shared by the three name/code functions: after `base_code`, the legacy YouTube codes `iw`/`in`/`ji`/`jw` become `he`/`id`/`yi`/`jv`; a base found in the table is used directly; otherwise ISO 639-2/T and 639-2/B codes (`tur`, `deu`, `ger`, `fre`, `chi` …) map back to their ISO 639-1 language.
- The table holds all 183 ISO 639-1 languages plus the three-letter-only languages YouTube offers (`ast bho ceb chr ckb doi fil gom haw hmn ilo kok kri lus mai mni nso sat yue`) and `mul` ("Multiple languages", used by M3 for bilingual tracks). ISO 639-3-only languages carry the ISO 639-2 group code (`yue` → `zho`, `ckb` → `kur`, `gom` → `kok`, `kri` → `cpe`).
- The Macintosh codes are FFmpeg's `mov_mdhd_language_map` from `libavformat/isom.c`, transcribed verbatim (139 entries, index = code) from FFmpeg master `b87602a63a52b0f7f968fd314f02be14acde16b7` (2026-09-27; the file last changed in `a302c9ae44ec`, 2026-07-14). A language gets the first index whose FFmpeg spelling maps to it; FFmpeg's non-ISO spellings `sve` (Swedish) and `iri` (Irish) and its space-padded two-letter entries (`"hr "`, `"fo "`, `"sr "`, `"pa "`) are understood; `smi` (Sami, a collective code) and `mol` (Moldavian, retired) match no table language. That yields 99 mapped languages. Chinese is special-cased by script: `hant`/`tw`/`hk`/`mo` subtags → 19 (Traditional), any other `zh` → 33 (Simplified).

- [ ] **Step 1: Write the failing tests**

`tests/unit/core/test_languages.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_languages.py -q`
Expected: collection error `ImportError: cannot import name 'languages' from 'utmax.core'`.

- [ ] **Step 3: Implement `src/utmax/core/languages.py`**

The `# fmt: skip` keeps the FFmpeg table ten entries per row, exactly like the C source, so it can be compared line by line with `libavformat/isom.c`.

`src/utmax/core/languages.py`:

```python
"""Language metadata: English names, ISO 639-2/T codes and QuickTime language codes.

Codes are matched on their primary subtag, case-insensitively (``"pt-BR"`` and ``"PT"`` both
mean Portuguese); ``_`` works like ``-``. Legacy YouTube codes (``iw``, ``in``, ``ji``, ``jw``)
and three-letter ISO 639-2 codes (``tur``, ``deu``, ``ger`` ...) are understood as well.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

__all__ = ["base_code", "english_name", "iso639_2t", "mac_language_code"]

# Primary subtag -> (ISO 639-2/T code, English name). Every ISO 639-1 language plus the
# three-letter-only languages YouTube offers for captions and translation.
_LANGUAGES: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "aa": ("aar", "Afar"),
        "ab": ("abk", "Abkhazian"),
        "ae": ("ave", "Avestan"),
        "af": ("afr", "Afrikaans"),
        "ak": ("aka", "Akan"),
        "am": ("amh", "Amharic"),
        "an": ("arg", "Aragonese"),
        "ar": ("ara", "Arabic"),
        "as": ("asm", "Assamese"),
        "av": ("ava", "Avaric"),
        "ay": ("aym", "Aymara"),
        "az": ("aze", "Azerbaijani"),
        "ba": ("bak", "Bashkir"),
        "be": ("bel", "Belarusian"),
        "bg": ("bul", "Bulgarian"),
        "bi": ("bis", "Bislama"),
        "bm": ("bam", "Bambara"),
        "bn": ("ben", "Bengali"),
        "bo": ("bod", "Tibetan"),
        "br": ("bre", "Breton"),
        "bs": ("bos", "Bosnian"),
        "ca": ("cat", "Catalan"),
        "ce": ("che", "Chechen"),
        "ch": ("cha", "Chamorro"),
        "co": ("cos", "Corsican"),
        "cr": ("cre", "Cree"),
        "cs": ("ces", "Czech"),
        "cu": ("chu", "Church Slavic"),
        "cv": ("chv", "Chuvash"),
        "cy": ("cym", "Welsh"),
        "da": ("dan", "Danish"),
        "de": ("deu", "German"),
        "dv": ("div", "Divehi"),
        "dz": ("dzo", "Dzongkha"),
        "ee": ("ewe", "Ewe"),
        "el": ("ell", "Greek"),
        "en": ("eng", "English"),
        "eo": ("epo", "Esperanto"),
        "es": ("spa", "Spanish"),
        "et": ("est", "Estonian"),
        "eu": ("eus", "Basque"),
        "fa": ("fas", "Persian"),
        "ff": ("ful", "Fulah"),
        "fi": ("fin", "Finnish"),
        "fj": ("fij", "Fijian"),
        "fo": ("fao", "Faroese"),
        "fr": ("fra", "French"),
        "fy": ("fry", "Western Frisian"),
        "ga": ("gle", "Irish"),
        "gd": ("gla", "Scottish Gaelic"),
        "gl": ("glg", "Galician"),
        "gn": ("grn", "Guarani"),
        "gu": ("guj", "Gujarati"),
        "gv": ("glv", "Manx"),
        "ha": ("hau", "Hausa"),
        "he": ("heb", "Hebrew"),
        "hi": ("hin", "Hindi"),
        "ho": ("hmo", "Hiri Motu"),
        "hr": ("hrv", "Croatian"),
        "ht": ("hat", "Haitian Creole"),
        "hu": ("hun", "Hungarian"),
        "hy": ("hye", "Armenian"),
        "hz": ("her", "Herero"),
        "ia": ("ina", "Interlingua"),
        "id": ("ind", "Indonesian"),
        "ie": ("ile", "Interlingue"),
        "ig": ("ibo", "Igbo"),
        "ii": ("iii", "Sichuan Yi"),
        "ik": ("ipk", "Inupiaq"),
        "io": ("ido", "Ido"),
        "is": ("isl", "Icelandic"),
        "it": ("ita", "Italian"),
        "iu": ("iku", "Inuktitut"),
        "ja": ("jpn", "Japanese"),
        "jv": ("jav", "Javanese"),
        "ka": ("kat", "Georgian"),
        "kg": ("kon", "Kongo"),
        "ki": ("kik", "Kikuyu"),
        "kj": ("kua", "Kuanyama"),
        "kk": ("kaz", "Kazakh"),
        "kl": ("kal", "Kalaallisut"),
        "km": ("khm", "Khmer"),
        "kn": ("kan", "Kannada"),
        "ko": ("kor", "Korean"),
        "kr": ("kau", "Kanuri"),
        "ks": ("kas", "Kashmiri"),
        "ku": ("kur", "Kurdish"),
        "kv": ("kom", "Komi"),
        "kw": ("cor", "Cornish"),
        "ky": ("kir", "Kyrgyz"),
        "la": ("lat", "Latin"),
        "lb": ("ltz", "Luxembourgish"),
        "lg": ("lug", "Ganda"),
        "li": ("lim", "Limburgish"),
        "ln": ("lin", "Lingala"),
        "lo": ("lao", "Lao"),
        "lt": ("lit", "Lithuanian"),
        "lu": ("lub", "Luba-Katanga"),
        "lv": ("lav", "Latvian"),
        "mg": ("mlg", "Malagasy"),
        "mh": ("mah", "Marshallese"),
        "mi": ("mri", "Maori"),
        "mk": ("mkd", "Macedonian"),
        "ml": ("mal", "Malayalam"),
        "mn": ("mon", "Mongolian"),
        "mr": ("mar", "Marathi"),
        "ms": ("msa", "Malay"),
        "mt": ("mlt", "Maltese"),
        "my": ("mya", "Burmese"),
        "na": ("nau", "Nauru"),
        "nb": ("nob", "Norwegian Bokm\xe5l"),
        "nd": ("nde", "North Ndebele"),
        "ne": ("nep", "Nepali"),
        "ng": ("ndo", "Ndonga"),
        "nl": ("nld", "Dutch"),
        "nn": ("nno", "Norwegian Nynorsk"),
        "no": ("nor", "Norwegian"),
        "nr": ("nbl", "South Ndebele"),
        "nv": ("nav", "Navajo"),
        "ny": ("nya", "Nyanja"),
        "oc": ("oci", "Occitan"),
        "oj": ("oji", "Ojibwa"),
        "om": ("orm", "Oromo"),
        "or": ("ori", "Odia"),
        "os": ("oss", "Ossetian"),
        "pa": ("pan", "Punjabi"),
        "pi": ("pli", "Pali"),
        "pl": ("pol", "Polish"),
        "ps": ("pus", "Pashto"),
        "pt": ("por", "Portuguese"),
        "qu": ("que", "Quechua"),
        "rm": ("roh", "Romansh"),
        "rn": ("run", "Rundi"),
        "ro": ("ron", "Romanian"),
        "ru": ("rus", "Russian"),
        "rw": ("kin", "Kinyarwanda"),
        "sa": ("san", "Sanskrit"),
        "sc": ("srd", "Sardinian"),
        "sd": ("snd", "Sindhi"),
        "se": ("sme", "Northern Sami"),
        "sg": ("sag", "Sango"),
        "si": ("sin", "Sinhala"),
        "sk": ("slk", "Slovak"),
        "sl": ("slv", "Slovenian"),
        "sm": ("smo", "Samoan"),
        "sn": ("sna", "Shona"),
        "so": ("som", "Somali"),
        "sq": ("sqi", "Albanian"),
        "sr": ("srp", "Serbian"),
        "ss": ("ssw", "Swati"),
        "st": ("sot", "Southern Sotho"),
        "su": ("sun", "Sundanese"),
        "sv": ("swe", "Swedish"),
        "sw": ("swa", "Swahili"),
        "ta": ("tam", "Tamil"),
        "te": ("tel", "Telugu"),
        "tg": ("tgk", "Tajik"),
        "th": ("tha", "Thai"),
        "ti": ("tir", "Tigrinya"),
        "tk": ("tuk", "Turkmen"),
        "tl": ("tgl", "Tagalog"),
        "tn": ("tsn", "Tswana"),
        "to": ("ton", "Tongan"),
        "tr": ("tur", "Turkish"),
        "ts": ("tso", "Tsonga"),
        "tt": ("tat", "Tatar"),
        "tw": ("twi", "Twi"),
        "ty": ("tah", "Tahitian"),
        "ug": ("uig", "Uyghur"),
        "uk": ("ukr", "Ukrainian"),
        "ur": ("urd", "Urdu"),
        "uz": ("uzb", "Uzbek"),
        "ve": ("ven", "Venda"),
        "vi": ("vie", "Vietnamese"),
        "vo": ("vol", "Volap\xfck"),
        "wa": ("wln", "Walloon"),
        "wo": ("wol", "Wolof"),
        "xh": ("xho", "Xhosa"),
        "yi": ("yid", "Yiddish"),
        "yo": ("yor", "Yoruba"),
        "za": ("zha", "Zhuang"),
        "zh": ("zho", "Chinese"),
        "zu": ("zul", "Zulu"),
        # Three-letter-only languages (ISO 639-2/3); 639-3 codes map to their 639-2 group.
        "ast": ("ast", "Asturian"),
        "bho": ("bho", "Bhojpuri"),
        "ceb": ("ceb", "Cebuano"),
        "chr": ("chr", "Cherokee"),
        "ckb": ("kur", "Central Kurdish"),
        "doi": ("doi", "Dogri"),
        "fil": ("fil", "Filipino"),
        "gom": ("kok", "Goan Konkani"),
        "haw": ("haw", "Hawaiian"),
        "hmn": ("hmn", "Hmong"),
        "ilo": ("ilo", "Iloko"),
        "kok": ("kok", "Konkani"),
        "kri": ("cpe", "Krio"),
        "lus": ("lus", "Mizo"),
        "mai": ("mai", "Maithili"),
        "mni": ("mni", "Manipuri"),
        "mul": ("mul", "Multiple languages"),
        "nso": ("nso", "Northern Sotho"),
        "sat": ("sat", "Santali"),
        "yue": ("zho", "Cantonese"),
    }
)

# Deprecated codes YouTube still uses -> current ISO 639-1 codes.
_ALIASES: Mapping[str, str] = MappingProxyType({"iw": "he", "in": "id", "ji": "yi", "jw": "jv"})

# ISO 639-2/B codes that differ from the /T codes stored above.
_BIBLIOGRAPHIC: Mapping[str, str] = MappingProxyType(
    {
        "alb": "sq",
        "arm": "hy",
        "baq": "eu",
        "bur": "my",
        "chi": "zh",
        "cze": "cs",
        "dut": "nl",
        "fre": "fr",
        "geo": "ka",
        "ger": "de",
        "gre": "el",
        "ice": "is",
        "mac": "mk",
        "mao": "mi",
        "may": "ms",
        "per": "fa",
        "rum": "ro",
        "slo": "sk",
        "tib": "bo",
        "wel": "cy",
    }
)


def _iso639_2_index() -> dict[str, str]:
    index = {code: base for base, (code, _) in _LANGUAGES.items() if len(base) == 2}
    index.update(_BIBLIOGRAPHIC)
    return index


_FROM_ISO639_2: Mapping[str, str] = MappingProxyType(_iso639_2_index())

# FFmpeg's mov_mdhd_language_map (libavformat/isom.c, FFmpeg master b87602a63a52,
# 2026-09-27): the QuickTime (Macintosh) language code is the index. Copied verbatim,
# including FFmpeg's own spellings ("sve", "iri", two-letter codes padded with a space).
_FFMPEG_MAC_LANGUAGES: tuple[str, ...] = (
    "eng", "fra", "ger", "ita", "dut", "sve", "spa", "dan", "por", "nor",  # 0-9
    "heb", "jpn", "ara", "fin", "gre", "ice", "mlt", "tur", "hr ", "chi",  # 10-19
    "urd", "hin", "tha", "kor", "lit", "pol", "hun", "est", "lav", "smi",  # 20-29
    "fo ", "per", "rus", "chi", "", "iri", "alb", "ron", "ces", "slk",  # 30-39
    "slv", "yid", "sr ", "mac", "bul", "ukr", "bel", "uzb", "kaz", "aze",  # 40-49
    "aze", "arm", "geo", "mol", "kir", "tgk", "tuk", "mon", "", "pus",  # 50-59
    "kur", "kas", "snd", "tib", "nep", "san", "mar", "ben", "asm", "guj",  # 60-69
    "pa ", "ori", "mal", "kan", "tam", "tel", "sin", "bur", "khm", "lao",  # 70-79
    "vie", "ind", "tgl", "may", "may", "amh", "tir", "orm", "som", "swa",  # 80-89
    "kin", "run", "nya", "mlg", "epo", "", "", "", "", "",  # 90-99
    "", "", "", "", "", "", "", "", "", "",  # 100-109
    "", "", "", "", "", "", "", "", "", "",  # 110-119
    "", "", "", "", "", "", "", "",  # 120-127
    "wel", "baq", "cat", "lat", "que", "grn", "aym", "tat", "uig", "dzo",  # 128-137
    "jav",  # 138
)  # fmt: skip

# FFmpeg spellings that are not ISO 639-2 codes.
_FFMPEG_SPELLINGS: Mapping[str, str] = MappingProxyType({"sve": "sv", "iri": "ga"})

_TRADITIONAL_CHINESE = 19
_SIMPLIFIED_CHINESE = 33
_TRADITIONAL_SUBTAGS = frozenset({"hant", "tw", "hk", "mo"})


def base_code(code: str) -> str:
    """The lower-cased primary subtag: ``"pt-BR"`` -> ``"pt"``, ``"EN"`` -> ``"en"``."""
    return code.strip().replace("_", "-").split("-", maxsplit=1)[0].lower()


def english_name(code: str) -> str | None:
    """The English name of the language, e.g. ``"tr"`` -> ``"Turkish"``; ``None`` if unknown."""
    entry = _LANGUAGES.get(_canonical(code))
    return entry[1] if entry else None


def iso639_2t(code: str) -> str:
    """The ISO 639-2/T code, e.g. ``"de-DE"`` -> ``"deu"``; ``"und"`` if unknown."""
    entry = _LANGUAGES.get(_canonical(code))
    return entry[0] if entry else "und"


def mac_language_code(code: str) -> int | None:
    """The QuickTime (Macintosh) language code for a MOV ``mdhd``; ``None`` when unmapped.

    Chinese follows the script: ``zh-Hant``, ``zh-TW``, ``zh-HK`` and ``zh-MO`` are
    Traditional (19), every other ``zh`` is Simplified (33).
    """
    canonical = _canonical(code)
    if canonical == "zh":
        subtags = set(code.strip().replace("_", "-").lower().split("-")[1:])
        return _TRADITIONAL_CHINESE if subtags & _TRADITIONAL_SUBTAGS else _SIMPLIFIED_CHINESE
    return _MAC_CODES.get(canonical)


def _canonical(code: str) -> str:
    base = base_code(code)
    base = _ALIASES.get(base, base)
    if base in _LANGUAGES:
        return base
    return _FROM_ISO639_2.get(base, base)


def _mac_codes() -> dict[str, int]:
    codes: dict[str, int] = {}
    for index, spelled in enumerate(_FFMPEG_MAC_LANGUAGES):
        name = spelled.strip()
        canonical = _canonical(_FFMPEG_SPELLINGS.get(name, name)) if name else ""
        if canonical in _LANGUAGES and canonical not in codes:
            codes[canonical] = index
    return codes


_MAC_CODES: Mapping[str, int] = MappingProxyType(_mac_codes())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_languages.py -q`
Expected: `85 passed` (5 `base_code` + 10 names + 5 unknown + 9 ISO + 15 Macintosh + 6 Chinese + 6 unmapped + 1 table + 1 round trip + 1 well-formed + 26 YouTube codes).

- [ ] **Step 5: Gates and full suite**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected: `All checks passed!`, `… files already formatted`, `Success: no issues found in 27 source files`, `384 passed, 6 deselected` (299 from M1 + 85). The architecture test still passes: `languages.py` imports only `collections.abc` and `types`.

- [ ] **Step 6: Commit**

```bash
git add src/utmax/core/languages.py tests/unit/core/test_languages.py
git commit -m "feat: add language names, ISO 639-2/T codes and QuickTime language codes

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task B: Translation and download errors

**Files:**
- Modify: `src/utmax/errors.py` (complete new content below: new `__all__`, `_install_hint`, `_restore`, `InvalidModelSpec`, `MissingExtra` and seven classes appended at the end; the M1 classes are unchanged)
- Modify: `src/utmax/__init__.py` (only the `from utmax.errors import (...)` block and the `__all__` list)
- Test: `tests/unit/test_errors.py` (complete new content below: the M1 tests unchanged plus six new tests and `import utmax`)

**Interfaces:**
- Consumes: `UTMaxError(message, *, video_id=None, suggestion=None)` and its `__reduce__`/`_restore` pickling (M1).
- Produces (in `utmax.errors`, re-exported by `utmax`): exactly the classes and signatures listed under Global Constraints. Default suggestions: `MissingExtra` and `ProviderNotInstalled` instances without an explicit `suggestion` say `Install it with pip install "u-transcript-max[<extra>]".` with the real extra name; every other class uses its class-level sentence.
- MRO notes: `MissingExtra` → `UTMaxError` → `ImportError`, so `UTMaxError.__init__`'s `super().__init__(message)` runs `ImportError.__init__` and sets `.msg`. `ProviderNotInstalled` is `TranslationError, MissingExtra, UTMaxError, ImportError, Exception`; its parents take different keyword arguments, so it calls `UTMaxError.__init__` directly and sets `provider` and `extra` itself. `_restore` (used when unpickling) now calls `super(UTMaxError, error).__init__(message)` instead of `Exception.__init__`, which also restores `ImportError.msg`; for every other class it is the same as before.

- [ ] **Step 1: Write the failing tests**

Replace `tests/unit/test_errors.py` with:

```python
"""Tests for the exception hierarchy."""

from __future__ import annotations

import pickle

import pytest

import utmax
from utmax import errors


def test_every_public_error_has_a_real_suggestion() -> None:
    for name in errors.__all__:
        cls = getattr(errors, name)
        assert issubclass(cls, errors.UTMaxError)
        assert cls.suggestion.endswith(".")
        assert len(cls.suggestion) > 20


@pytest.mark.parametrize(
    ("child", "parent"),
    [
        (errors.InvalidVideoId, ValueError),
        (errors.InvalidOption, ValueError),
        (errors.UnsupportedFormat, ValueError),
        (errors.NetworkError, errors.UTMaxError),
        (errors.YouTubeError, errors.UTMaxError),
        (errors.RequestBlocked, errors.YouTubeError),
        (errors.IpBlocked, errors.RequestBlocked),
        (errors.NoTranscriptFound, errors.YouTubeError),
        (errors.TranscriptsDisabled, errors.YouTubeError),
    ],
)
def test_hierarchy(child: type[Exception], parent: type[Exception]) -> None:
    assert issubclass(child, parent)


def test_message_video_id_and_suggestion_override() -> None:
    error = errors.VideoUnavailable("gone", video_id="abc")
    assert str(error) == "gone"
    assert error.message == "gone"
    assert error.video_id == "abc"
    assert error.suggestion == errors.VideoUnavailable.suggestion
    custom = errors.VideoUnavailable("gone", suggestion="Try another video.")
    assert custom.suggestion == "Try another video."
    assert errors.VideoUnavailable.suggestion != "Try another video."


def test_specific_fields_are_stored_as_tuples() -> None:
    unplayable = errors.VideoUnplayable("no", reason="Private video", sub_reasons=["Sign in"])
    assert unplayable.reason == "Private video"
    assert unplayable.sub_reasons == ("Sign in",)
    assert errors.YouTubeRequestFailed("bad", status_code=403).status_code == 403
    missing = errors.NoTranscriptFound("none", requested=["tr"], available=["en (English, manual)"])
    assert missing.requested == ("tr",)
    assert missing.available == ("en (English, manual)",)
    assert errors.TranslationLanguageNotAvailable("no", available=["de"]).available == ("de",)


@pytest.mark.parametrize(
    "error",
    [
        errors.InvalidVideoId("bad id"),
        errors.VideoUnplayable("no", reason="r", sub_reasons=["s"], video_id="v"),
        errors.YouTubeRequestFailed("bad", status_code=500, video_id="v"),
        errors.NoTranscriptFound("none", requested=["tr"], available=["en"], video_id="v"),
        errors.IpBlocked("slow down", suggestion="Wait a minute."),
    ],
)
def test_errors_survive_pickling(error: errors.UTMaxError) -> None:
    clone = pickle.loads(pickle.dumps(error))
    assert type(clone) is type(error)
    assert str(clone) == str(error)
    assert clone.__dict__ == error.__dict__


@pytest.mark.parametrize(
    ("child", "parents"),
    [
        (errors.InvalidModelSpec, (errors.UTMaxError, ValueError)),
        (errors.MissingExtra, (errors.UTMaxError, ImportError)),
        (errors.TranslationError, (errors.UTMaxError,)),
        (errors.ProviderNotInstalled, (errors.TranslationError, errors.MissingExtra, ImportError)),
        (errors.ProviderAuthError, (errors.TranslationError,)),
        (errors.ProviderRateLimited, (errors.TranslationError,)),
        (errors.ProviderError, (errors.TranslationError,)),
        (errors.TranslationRefused, (errors.TranslationError,)),
        (errors.TranslationMismatch, (errors.TranslationError,)),
        (errors.DownloadError, (errors.UTMaxError,)),
        (errors.MuxError, (errors.DownloadError,)),
    ],
)
def test_translation_and_download_hierarchy(
    child: type[Exception], parents: tuple[type[Exception], ...]
) -> None:
    for parent in parents:
        assert issubclass(child, parent)


def test_missing_extra_names_the_pip_extra_and_stays_an_import_error() -> None:
    error = errors.MissingExtra("The mcp package is not installed.", extra="mcp", video_id="v")
    assert (error.extra, error.video_id) == ("mcp", "v")
    assert error.suggestion == 'Install it with pip install "u-transcript-max[mcp]".'
    assert error.msg == "The mcp package is not installed."
    assert str(error) == "The mcp package is not installed."
    custom = errors.MissingExtra("missing", extra="mcp", suggestion="Install mcp yourself.")
    assert custom.suggestion == "Install mcp yourself."


def test_provider_not_installed_is_a_translation_error_and_a_missing_extra() -> None:
    error = errors.ProviderNotInstalled("anthropic is missing", provider="claude", extra="claude")
    assert (error.provider, error.extra, error.video_id) == ("claude", "claude", None)
    assert error.suggestion == 'Install it with pip install "u-transcript-max[claude]".'
    assert error.msg == "anthropic is missing"
    with pytest.raises(ImportError, match="anthropic is missing"):
        raise error


def test_translation_error_fields() -> None:
    assert errors.ProviderAuthError("bad key", provider="openai").provider == "openai"
    assert errors.ProviderRateLimited("slow down", provider="gemini").provider == "gemini"
    failed = errors.ProviderError("server error", provider="gemini", status_code=503)
    assert (failed.provider, failed.status_code) == ("gemini", 503)
    assert errors.ProviderError("no status", provider="openrouter").status_code is None
    mismatch = errors.TranslationMismatch(
        "ids differ", provider="claude", ids=[3, 1], raw_excerpt='{"items": [', video_id="v"
    )
    assert (mismatch.ids, mismatch.raw_excerpt, mismatch.video_id) == ((3, 1), '{"items": [', "v")
    assert errors.TranslationRefused("no", provider="claude").provider == "claude"


@pytest.mark.parametrize(
    "error",
    [
        errors.InvalidModelSpec("claude-opus-5"),
        errors.MissingExtra("no mcp", extra="mcp", video_id="v"),
        errors.TranslationError("failed", provider="openai"),
        errors.ProviderNotInstalled("no sdk", provider="gemini", extra="gemini"),
        errors.ProviderAuthError("bad key", provider="claude", suggestion="Set the key."),
        errors.ProviderRateLimited("429", provider="openai"),
        errors.ProviderError("500", provider="openrouter", status_code=500),
        errors.TranslationRefused("refused", provider="claude"),
        errors.TranslationMismatch("bad ids", provider="claude", ids=(2,), raw_excerpt="[]"),
        errors.DownloadError("failed", video_id="v"),
        errors.MuxError("bad stream", video_id="v"),
    ],
)
def test_translation_and_download_errors_survive_pickling(error: errors.UTMaxError) -> None:
    clone = pickle.loads(pickle.dumps(error))
    assert type(clone) is type(error)
    assert str(clone) == str(error)
    assert clone.args == error.args
    assert clone.__dict__ == error.__dict__
    if isinstance(error, ImportError):
        assert isinstance(clone, ImportError)
        assert clone.msg == error.msg


def test_translation_and_download_errors_are_exported_from_utmax() -> None:
    for name in (
        "DownloadError",
        "InvalidModelSpec",
        "MissingExtra",
        "MuxError",
        "ProviderAuthError",
        "ProviderError",
        "ProviderNotInstalled",
        "ProviderRateLimited",
        "TranslationError",
        "TranslationMismatch",
        "TranslationRefused",
    ):
        assert name in errors.__all__
        assert name in utmax.__all__
        assert getattr(utmax, name) is getattr(errors, name)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_errors.py -q`
Expected: collection error `AttributeError: module 'utmax.errors' has no attribute 'InvalidModelSpec'`.

- [ ] **Step 3: Implement the error classes**

Replace `src/utmax/errors.py` with:

```python
"""The utmax exception hierarchy.

Every error carries a one-sentence English ``suggestion`` telling the caller what to do next
and, when known, the ``video_id`` it concerns. Names mirror youtube-transcript-api where the
meaning is the same, which keeps migrations simple.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

__all__ = [
    "AgeRestricted",
    "DownloadError",
    "FailedToCreateConsentCookie",
    "InvalidModelSpec",
    "InvalidOption",
    "InvalidVideoId",
    "IpBlocked",
    "MissingExtra",
    "MuxError",
    "NetworkError",
    "NoTranscriptFound",
    "NotTranslatable",
    "PoTokenRequired",
    "ProviderAuthError",
    "ProviderError",
    "ProviderNotInstalled",
    "ProviderRateLimited",
    "RequestBlocked",
    "TranscriptsDisabled",
    "TranslationError",
    "TranslationLanguageNotAvailable",
    "TranslationMismatch",
    "TranslationRefused",
    "UTMaxError",
    "UnsupportedFormat",
    "VideoUnavailable",
    "VideoUnplayable",
    "YouTubeDataUnparsable",
    "YouTubeError",
    "YouTubeRequestFailed",
]


def _install_hint(extra: str) -> str:
    return f'Install it with pip install "u-transcript-max[{extra}]".'


def _restore(cls: type[UTMaxError], message: str, state: dict[str, Any]) -> UTMaxError:
    error = cls.__new__(cls)
    super(UTMaxError, error).__init__(message)  # also sets ImportError.msg for MissingExtra
    error.__dict__.update(state)
    return error


class UTMaxError(Exception):
    """Base class of every error raised by utmax."""

    suggestion: str = "Read the error message for details."

    def __init__(
        self, message: str, *, video_id: str | None = None, suggestion: str | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.video_id = video_id
        if suggestion is not None:
            self.suggestion = suggestion

    def __str__(self) -> str:
        return self.message

    def __reduce__(self) -> tuple[Any, ...]:
        return (_restore, (type(self), self.message, dict(self.__dict__)))


class InvalidVideoId(UTMaxError, ValueError):
    """The input does not contain a YouTube video ID."""

    suggestion = "Pass a YouTube URL or an 11-character video ID."


class InvalidModelSpec(UTMaxError, ValueError):
    """A translator model string is not ``"provider=model-id"``."""

    suggestion = (
        'Pass model="provider=model-id", where provider is claude, openai, gemini or openrouter.'
    )


class InvalidOption(UTMaxError, ValueError):
    """An option value, or a combination of options, is not supported."""

    suggestion = "Check the options passed to this call against the documentation."


class UnsupportedFormat(UTMaxError, ValueError):
    """The requested output format is unknown."""

    suggestion = "Use a .srt, .vtt, .json or .txt file name, or pass format=... explicitly."


class MissingExtra(UTMaxError, ImportError):
    """An optional dependency (a pip "extra") is not installed."""

    suggestion = 'Install the optional dependency with pip install "u-transcript-max[<extra>]".'

    def __init__(
        self,
        message: str,
        *,
        extra: str,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion or _install_hint(extra))
        self.extra = extra


class NetworkError(UTMaxError):
    """The network failed and retries did not help."""

    suggestion = "Check your internet connection, proxy settings and firewall, then try again."


class YouTubeError(UTMaxError):
    """YouTube refused or could not serve the request."""

    suggestion = "YouTube could not serve this request; try again later."


class VideoUnavailable(YouTubeError):
    """The video does not exist or was removed."""

    suggestion = "Check that the video ID is correct and that the video is still public."


class VideoUnplayable(YouTubeError):
    """YouTube will not play the video for this client."""

    suggestion = "Private, members-only and region-locked videos are not supported."

    def __init__(
        self,
        message: str,
        *,
        reason: str = "",
        sub_reasons: Sequence[str] = (),
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.reason = reason
        self.sub_reasons = tuple(sub_reasons)


class AgeRestricted(YouTubeError):
    """The video is age-restricted."""

    suggestion = "Age-restricted videos need a signed-in session, which utmax does not support."


class RequestBlocked(YouTubeError):
    """YouTube is blocking requests from this IP address."""

    suggestion = (
        "Use a proxy (Client(proxy=...)) with block_retries, and avoid cloud-provider IP addresses."
    )


class IpBlocked(RequestBlocked):
    """YouTube rate-limited this IP address (HTTP 429 or a CAPTCHA)."""

    suggestion = "Wait before retrying, or use a rotating residential proxy with block_retries."


class PoTokenRequired(YouTubeError):
    """YouTube requires a proof-of-origin token that utmax cannot produce."""

    suggestion = (
        "YouTube changed how captions are served; please report it at "
        "https://github.com/U-C4N/U-transkript/issues."
    )


class FailedToCreateConsentCookie(YouTubeError):
    """YouTube kept showing its cookie-consent page."""

    suggestion = "Try again later, or from a different region or proxy."


class YouTubeRequestFailed(YouTubeError):
    """YouTube answered with an unexpected HTTP status."""

    suggestion = "YouTube answered with an unexpected HTTP status; try again later."

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.status_code = status_code


class YouTubeDataUnparsable(YouTubeError):
    """YouTube returned data utmax could not understand."""

    suggestion = "YouTube may have changed its responses; please report it with the video ID."


class TranscriptsDisabled(YouTubeError):
    """The video has no subtitles at all."""

    suggestion = "The uploader disabled subtitles for this video, so there is nothing to fetch."


class NoTranscriptFound(YouTubeError):
    """No track matches the requested languages or filters."""

    suggestion = "Pick one of the available languages, or call utmax.list_tracks() to see them."

    def __init__(
        self,
        message: str,
        *,
        requested: Sequence[str] = (),
        available: Sequence[str] = (),
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.requested = tuple(requested)
        self.available = tuple(available)


class NotTranslatable(YouTubeError):
    """YouTube cannot translate this track."""

    suggestion = "YouTube cannot translate this track; use AI translation instead."


class TranslationLanguageNotAvailable(YouTubeError):
    """YouTube cannot translate into the requested language."""

    suggestion = "Use a language from TrackList.translation_languages, or use AI translation."

    def __init__(
        self,
        message: str,
        *,
        available: Sequence[str] = (),
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.available = tuple(available)


class DownloadError(UTMaxError):
    """Downloading or assembling a video or audio file failed."""

    suggestion = "The download failed; check your connection and disk space, then try again."


class MuxError(DownloadError):
    """The downloaded streams could not be combined into the requested file."""

    suggestion = (
        "The streams could not be combined; try another format, or report it with the video ID."
    )


class TranslationError(UTMaxError):
    """AI translation failed."""

    suggestion = "Check the provider, the model ID and your API key, then try again."

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.provider = provider


class ProviderNotInstalled(TranslationError, MissingExtra):
    """The official SDK of the chosen translation provider is not installed."""

    suggestion = 'Install the provider SDK with pip install "u-transcript-max[<extra>]".'

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        extra: str,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        # The two parents take different keyword arguments, so skip their constructors.
        UTMaxError.__init__(
            self, message, video_id=video_id, suggestion=suggestion or _install_hint(extra)
        )
        self.provider = provider
        self.extra = extra


class ProviderAuthError(TranslationError):
    """The provider rejected the API key."""

    suggestion = "Check the API key passed to the translator or set in the environment."


class ProviderRateLimited(TranslationError):
    """The provider rate-limited the request or the account ran out of quota."""

    suggestion = "Wait and retry with lower concurrency, or check the provider account's quota."


class ProviderError(TranslationError):
    """The provider answered with an error."""

    suggestion = "The provider reported an error; check the model ID and try again later."

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, provider=provider, video_id=video_id, suggestion=suggestion)
        self.status_code = status_code


class TranslationRefused(TranslationError):
    """The model refused to translate the text."""

    suggestion = "The model declined this text; try another model or provider."


class TranslationMismatch(TranslationError):
    """The model kept returning output that does not match the requested lines."""

    suggestion = "The model returned unusable output; retry, or use a more capable model."

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        ids: Sequence[int],
        raw_excerpt: str,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, provider=provider, video_id=video_id, suggestion=suggestion)
        self.ids = tuple(ids)
        self.raw_excerpt = raw_excerpt
```

- [ ] **Step 4: Export the new errors from `utmax`**

In `src/utmax/__init__.py`, replace the `from utmax.errors import (...)` block with:

```python
from utmax.errors import (
    AgeRestricted,
    DownloadError,
    FailedToCreateConsentCookie,
    InvalidModelSpec,
    InvalidOption,
    InvalidVideoId,
    IpBlocked,
    MissingExtra,
    MuxError,
    NetworkError,
    NoTranscriptFound,
    NotTranslatable,
    PoTokenRequired,
    ProviderAuthError,
    ProviderError,
    ProviderNotInstalled,
    ProviderRateLimited,
    RequestBlocked,
    TranscriptsDisabled,
    TranslationError,
    TranslationLanguageNotAvailable,
    TranslationMismatch,
    TranslationRefused,
    UnsupportedFormat,
    UTMaxError,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeError,
    YouTubeRequestFailed,
)
```

and replace the `__all__` list with:

```python
__all__ = [
    "AgeRestricted",
    "Client",
    "DownloadError",
    "FailedToCreateConsentCookie",
    "FormatName",
    "InvalidModelSpec",
    "InvalidOption",
    "InvalidVideoId",
    "IpBlocked",
    "Language",
    "MissingExtra",
    "MuxError",
    "NetworkError",
    "NoTranscriptFound",
    "NotTranslatable",
    "PoTokenRequired",
    "ProviderAuthError",
    "ProviderError",
    "ProviderNotInstalled",
    "ProviderRateLimited",
    "RequestBlocked",
    "Segment",
    "Track",
    "TrackList",
    "Transcript",
    "TranscriptsDisabled",
    "TranslationError",
    "TranslationLanguageNotAvailable",
    "TranslationMismatch",
    "TranslationRefused",
    "UTMaxError",
    "UnsupportedFormat",
    "VideoInfo",
    "VideoUnavailable",
    "VideoUnplayable",
    "Word",
    "YouTubeDataUnparsable",
    "YouTubeError",
    "YouTubeRequestFailed",
    "__version__",
    "fetch",
    "list_tracks",
    "video_info",
]
```

Leave everything else in the file (docstring, other imports, `_client`, `fetch`, `list_tracks`, `video_info`) untouched.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_errors.py -q`
Expected: `43 passed` (17 from M1 + 11 hierarchy + 1 `MissingExtra` + 1 `ProviderNotInstalled` + 1 fields + 11 pickling + 1 export). Before Step 4 is done, exactly one test fails (`test_translation_and_download_errors_are_exported_from_utmax`).

- [ ] **Step 6: Gates, coverage and full suite**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov -q
uv run coverage report --include="*/utmax/core/*" --fail-under=95
```

Expected: clean lint, format and types; `410 passed, 6 deselected`; total coverage above 99 %; core coverage above 95 %.

- [ ] **Step 7: Commit**

```bash
git add src/utmax/errors.py src/utmax/__init__.py tests/unit/test_errors.py
git commit -m "feat: add translation and download error classes

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Hand-off to M2 and M3

- [ ] **Step 1: Confirm the branch point**

Run: `git log --oneline -3` and `git status --short`
Expected: the two commits above on top of M1, a clean tree. This commit is where the parallel branches start: M2 (AI translation and bilingual subtitles) and M3 (media muxer, `docs/design/plans/2026-09-27-m3-media-muxer.md`, branch `m3-muxer`). From here on, `src/utmax/core/languages.py` and `src/utmax/errors.py` belong to neither milestone: if either needs a change, it goes back to `v4` first.

- [ ] **Step 2: Report**

Tell the user: the commits, `410 passed`, coverage numbers, and that `v4` is ready for M2 and M3 to branch. Do not push without approval.
