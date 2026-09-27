"""Language metadata: English names, ISO 639-2/T codes and QuickTime language codes.

Codes are matched on their primary subtag, case-insensitively (``"pt-BR"`` and ``"PT"`` both
mean Portuguese); ``_`` works like ``-``. Legacy YouTube codes (``iw``, ``in``, ``ji``, ``jw``)
and three-letter ISO 639-2 codes (``tur``, ``deu``, ``ger`` ...) are understood as well.
Chinese is the one exception to primary-subtag matching: its script (``Hant``/``Hans``, or a
region such as ``TW``) picks the English name and the QuickTime code.
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
_CHINESE_SCRIPTS = frozenset({"hans", "hant"})
# Regions that imply a Chinese script when the tag names none.
_CHINESE_REGION_SCRIPTS: Mapping[str, str] = MappingProxyType(
    {"tw": "hant", "hk": "hant", "mo": "hant", "cn": "hans", "sg": "hans"}
)
_CHINESE_NAMES: Mapping[str, str] = MappingProxyType(
    {"hant": "Chinese (Traditional)", "hans": "Chinese (Simplified)"}
)


def base_code(code: str) -> str:
    """The lower-cased primary subtag: ``"pt-BR"`` -> ``"pt"``, ``"EN"`` -> ``"en"``."""
    return code.strip().replace("_", "-").split("-", maxsplit=1)[0].lower()


def english_name(code: str) -> str | None:
    """The English name of the language, e.g. ``"tr"`` -> ``"Turkish"``; ``None`` if unknown.

    Chinese names its script when the tag implies one: ``zh-Hant`` and ``zh-TW`` are
    ``"Chinese (Traditional)"``, ``zh-Hans`` and ``zh-CN`` are ``"Chinese (Simplified)"``,
    and a bare ``zh`` is ``"Chinese"``.
    """
    canonical = _canonical(code)
    script = _chinese_script(code) if canonical == "zh" else None
    if script:
        return _CHINESE_NAMES[script]
    entry = _LANGUAGES.get(canonical)
    return entry[1] if entry else None


def iso639_2t(code: str) -> str:
    """The ISO 639-2/T code, e.g. ``"de-DE"`` -> ``"deu"``; ``"und"`` if unknown."""
    entry = _LANGUAGES.get(_canonical(code))
    return entry[0] if entry else "und"


def mac_language_code(code: str) -> int | None:
    """The QuickTime (Macintosh) language code for a MOV ``mdhd``; ``None`` when unmapped.

    Chinese follows the script: an explicit ``Hant`` or ``Hans`` subtag decides, else
    ``zh-TW``, ``zh-HK`` and ``zh-MO`` are Traditional (19); every other ``zh`` is
    Simplified (33).
    """
    canonical = _canonical(code)
    if canonical == "zh":
        return _TRADITIONAL_CHINESE if _chinese_script(code) == "hant" else _SIMPLIFIED_CHINESE
    return _MAC_CODES.get(canonical)


def _canonical(code: str) -> str:
    base = base_code(code)
    base = _ALIASES.get(base, base)
    if base in _LANGUAGES:
        return base
    return _FROM_ISO639_2.get(base, base)


def _chinese_script(code: str) -> str | None:
    """``"hant"`` or ``"hans"`` when a Chinese tag implies a script; the script subtag wins."""
    subtags = code.strip().replace("_", "-").lower().split("-")[1:]
    for subtag in subtags:
        if subtag in _CHINESE_SCRIPTS:
            return subtag
    for subtag in subtags:
        if subtag in _CHINESE_REGION_SCRIPTS:
            return _CHINESE_REGION_SCRIPTS[subtag]
    return None


def _mac_codes() -> dict[str, int]:
    codes: dict[str, int] = {}
    for index, spelled in enumerate(_FFMPEG_MAC_LANGUAGES):
        name = spelled.strip()
        canonical = _canonical(_FFMPEG_SPELLINGS.get(name, name)) if name else ""
        if canonical in _LANGUAGES and canonical not in codes:
            codes[canonical] = index
    return codes


_MAC_CODES: Mapping[str, int] = MappingProxyType(_mac_codes())
