"""Transcripts and transcript lists, compatible with youtube-transcript-api 1.2.4.

utmax lists the tracks with its own InnerTube clients and downloads YouTube's legacy XML
captions, which youtube-transcript-api parses too, so snippets are the same.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from html import unescape
from itertools import chain
from typing import Any, ClassVar, overload
from xml.etree import ElementTree

from utmax.compat._bridge import Connection, connection_for, make_transport
from utmax.compat._errors import (
    AgeRestricted,
    FailedToCreateConsentCookie,
    InvalidVideoId,
    IpBlocked,
    NoTranscriptFound,
    NotTranslatable,
    PoTokenRequired,
    RequestBlocked,
    TranscriptsDisabled,
    TranslationLanguageNotAvailable,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeRequestFailed,
)
from utmax.compat._settings import INNERTUBE_API_URL, INNERTUBE_CONTEXT, WATCH_URL
from utmax.compat.proxies import ProxyConfig
from utmax.core.player import PlayerData, parse_player_response

__all__ = [
    "INNERTUBE_API_URL",
    "INNERTUBE_CONTEXT",
    "WATCH_URL",
    "AgeRestricted",
    "FailedToCreateConsentCookie",
    "FetchedTranscript",
    "FetchedTranscriptSnippet",
    "InvalidVideoId",
    "IpBlocked",
    "NoTranscriptFound",
    "NotTranslatable",
    "PoTokenRequired",
    "ProxyConfig",
    "RequestBlocked",
    "Transcript",
    "TranscriptList",
    "TranscriptListFetcher",
    "TranscriptsDisabled",
    "TranslationLanguageNotAvailable",
    "VideoUnavailable",
    "VideoUnplayable",
    "YouTubeDataUnparsable",
    "YouTubeRequestFailed",
]

_UNSAFE_XML = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)", re.IGNORECASE)


@dataclass
class FetchedTranscriptSnippet:
    text: str
    start: float
    """
    The timestamp at which this transcript snippet appears on screen in seconds.
    """
    duration: float
    """
    The duration of how long the snippet in seconds. Be aware that this is not the
    duration of the transcribed speech, but how long the snippet stays on screen.
    Therefore, there can be overlaps between snippets!
    """


@dataclass
class FetchedTranscript:
    """
    Represents a fetched transcript. This object is iterable, which allows you to
    iterate over the transcript snippets.
    """

    snippets: list[FetchedTranscriptSnippet]
    video_id: str
    language: str
    language_code: str
    is_generated: bool

    def __iter__(self) -> Iterator[FetchedTranscriptSnippet]:
        return iter(self.snippets)

    @overload
    def __getitem__(self, index: int) -> FetchedTranscriptSnippet: ...
    @overload
    def __getitem__(self, index: slice) -> list[FetchedTranscriptSnippet]: ...
    def __getitem__(
        self, index: int | slice
    ) -> FetchedTranscriptSnippet | list[FetchedTranscriptSnippet]:
        return self.snippets[index]

    def __len__(self) -> int:
        return len(self.snippets)

    def to_raw_data(self) -> list[dict[str, Any]]:
        return [asdict(snippet) for snippet in self]


@dataclass
class _TranslationLanguage:
    language: str
    language_code: str


class Transcript:
    def __init__(  # noqa: PLR0917
        self,
        http_client: Any,
        video_id: str,
        url: str,
        language: str,
        language_code: str,
        is_generated: bool,
        translation_languages: list[_TranslationLanguage],
    ) -> None:
        """
        You probably don't want to initialize this directly. Usually you'll access Transcript objects using a
        TranscriptList.
        """
        self._http_client = http_client
        self.video_id = video_id
        self._url = url
        self.language = language
        self.language_code = language_code
        self.is_generated = is_generated
        self.translation_languages = translation_languages
        self._translation_languages_dict = {
            translation_language.language_code: translation_language.language
            for translation_language in translation_languages
        }

    def fetch(self, preserve_formatting: bool = False) -> FetchedTranscript:
        """
        Loads the actual transcript data.
        :param preserve_formatting: whether to keep select HTML text formatting
        """
        if "&exp=xpe" in self._url:
            raise PoTokenRequired(self.video_id)
        raw_data = connection_for(self._http_client).caption_text(self._url, self.video_id)
        try:
            snippets = _TranscriptParser(preserve_formatting=preserve_formatting).parse(raw_data)
        except (ElementTree.ParseError, KeyError, ValueError) as error:
            raise YouTubeDataUnparsable(self.video_id) from error
        return FetchedTranscript(
            snippets=snippets,
            video_id=self.video_id,
            language=self.language,
            language_code=self.language_code,
            is_generated=self.is_generated,
        )

    def __str__(self) -> str:
        return '{language_code} ("{language}"){translation_description}'.format(
            language=self.language,
            language_code=self.language_code,
            translation_description="[TRANSLATABLE]" if self.is_translatable else "",
        )

    @property
    def is_translatable(self) -> bool:
        return len(self.translation_languages) > 0

    def translate(self, language_code: str) -> Transcript:
        if not self.is_translatable:
            raise NotTranslatable(self.video_id)

        if language_code not in self._translation_languages_dict:
            raise TranslationLanguageNotAvailable(self.video_id)

        return Transcript(
            self._http_client,
            self.video_id,
            f"{self._url}&tlang={language_code}",
            self._translation_languages_dict[language_code],
            language_code,
            True,
            [],
        )


class TranscriptList:
    """
    This object represents a list of transcripts. It can be iterated over to list all transcripts which are available
    for a given YouTube video. Also, it provides functionality to search for a transcript in a given language.
    """

    def __init__(
        self,
        video_id: str,
        manually_created_transcripts: dict[str, Transcript],
        generated_transcripts: dict[str, Transcript],
        translation_languages: list[_TranslationLanguage],
    ) -> None:
        """
        The constructor is only for internal use. Use the static build method instead.

        :param video_id: the id of the video this TranscriptList is for
        :param manually_created_transcripts: dict mapping language codes to the manually created transcripts
        :param generated_transcripts: dict mapping language codes to the generated transcripts
        :param translation_languages: list of languages which can be used for translatable languages
        """
        self.video_id = video_id
        self._manually_created_transcripts = manually_created_transcripts
        self._generated_transcripts = generated_transcripts
        self._translation_languages = translation_languages

    @staticmethod
    def build(http_client: Any, video_id: str, captions_json: dict[str, Any]) -> TranscriptList:
        """
        Factory method for TranscriptList.

        :param http_client: http client which is used to make the transcript retrieving http calls
        :param video_id: the id of the video this TranscriptList is for
        :param captions_json: the ``playerCaptionsTracklistRenderer`` of a player response
        :return: the created TranscriptList
        """
        player = parse_player_response(
            {"captions": {"playerCaptionsTracklistRenderer": captions_json}}, video_id=video_id
        )
        return _transcript_list(http_client, video_id, player)

    def __iter__(self) -> Iterator[Transcript]:
        return chain(
            self._manually_created_transcripts.values(),
            self._generated_transcripts.values(),
        )

    def find_transcript(self, language_codes: Iterable[str]) -> Transcript:
        """
        Finds a transcript for a given language code. Manually created transcripts are returned first and only if none
        are found, generated transcripts are used. If you only want generated transcripts use
        `find_manually_created_transcript` instead.

        :param language_codes: A list of language codes in a descending priority. For example, if this is set to
        ['de', 'en'] it will first try to fetch the german transcript (de) and then fetch the english transcript (en) if
        it fails to do so.
        :return: the found Transcript
        """
        return self._find_transcript(
            language_codes,
            [self._manually_created_transcripts, self._generated_transcripts],
        )

    def find_generated_transcript(self, language_codes: Iterable[str]) -> Transcript:
        """
        Finds an automatically generated transcript for a given language code.

        :param language_codes: A list of language codes in a descending priority. For example, if this is set to
        ['de', 'en'] it will first try to fetch the german transcript (de) and then fetch the english transcript (en) if
        it fails to do so.
        :return: the found Transcript
        """
        return self._find_transcript(language_codes, [self._generated_transcripts])

    def find_manually_created_transcript(self, language_codes: Iterable[str]) -> Transcript:
        """
        Finds a manually created transcript for a given language code.

        :param language_codes: A list of language codes in a descending priority. For example, if this is set to
        ['de', 'en'] it will first try to fetch the german transcript (de) and then fetch the english transcript (en) if
        it fails to do so.
        :return: the found Transcript
        """
        return self._find_transcript(language_codes, [self._manually_created_transcripts])

    def _find_transcript(
        self,
        language_codes: Iterable[str],
        transcript_dicts: list[dict[str, Transcript]],
    ) -> Transcript:
        for language_code in language_codes:
            for transcript_dict in transcript_dicts:
                if language_code in transcript_dict:
                    return transcript_dict[language_code]

        raise NoTranscriptFound(self.video_id, language_codes, self)

    def __str__(self) -> str:
        return (
            "For this video ({video_id}) transcripts are available in the following languages:\n\n"
            "(MANUALLY CREATED)\n"
            "{available_manually_created_transcript_languages}\n\n"
            "(GENERATED)\n"
            "{available_generated_transcripts}\n\n"
            "(TRANSLATION LANGUAGES)\n"
            "{available_translation_languages}"
        ).format(
            video_id=self.video_id,
            available_manually_created_transcript_languages=self._get_language_description(
                str(transcript) for transcript in self._manually_created_transcripts.values()
            ),
            available_generated_transcripts=self._get_language_description(
                str(transcript) for transcript in self._generated_transcripts.values()
            ),
            available_translation_languages=self._get_language_description(
                f'{translation_language.language_code} ("{translation_language.language}")'
                for translation_language in self._translation_languages
            ),
        )

    def _get_language_description(self, transcript_strings: Iterable[str]) -> str:
        description = "\n".join(f" - {transcript}" for transcript in transcript_strings)
        return description if description else "None"


class TranscriptListFetcher:
    """Lists the transcripts of a video through utmax's InnerTube clients."""

    def __init__(self, http_client: Any, proxy_config: ProxyConfig | None) -> None:
        self._http_client = http_client
        self._proxy_config = proxy_config
        self._connection = Connection(
            make_transport(http_client, proxy_config), proxy_config=proxy_config
        )

    def fetch(self, video_id: str) -> TranscriptList:
        video_id, player = self._connection.player(video_id)
        return _transcript_list(self._connection, video_id, player)


class _TranscriptParser:
    _FORMATTING_TAGS: ClassVar[list[str]] = [
        "strong",  # important
        "em",  # emphasized
        "b",  # bold
        "i",  # italic
        "mark",  # marked
        "small",  # smaller
        "del",  # deleted
        "ins",  # inserted
        "sub",  # subscript
        "sup",  # superscript
    ]

    def __init__(self, preserve_formatting: bool = False) -> None:
        self._html_regex = self._get_html_regex(preserve_formatting)

    def _get_html_regex(self, preserve_formatting: bool) -> re.Pattern[str]:
        if preserve_formatting:
            formats_regex = "|".join(self._FORMATTING_TAGS)
            formats_regex = r"<\/?(?!\/?(" + formats_regex + r")\b).*?\b>"
            html_regex = re.compile(formats_regex, re.IGNORECASE)
        else:
            html_regex = re.compile(r"<[^>]*>", re.IGNORECASE)
        return html_regex

    def parse(self, raw_data: str) -> list[FetchedTranscriptSnippet]:
        if _UNSAFE_XML.search(raw_data):
            raise ValueError("refusing caption XML that declares a DOCTYPE or entities")
        return [
            FetchedTranscriptSnippet(
                text=re.sub(self._html_regex, "", unescape(xml_element.text)),
                start=float(xml_element.attrib["start"]),
                duration=float(xml_element.attrib.get("dur", "0.0")),
            )
            for xml_element in ElementTree.fromstring(raw_data)
            if xml_element.text is not None
        ]


def _transcript_list(http_client: Any, video_id: str, player: PlayerData) -> TranscriptList:
    """Build the list as youtube-transcript-api does: one transcript per language code and kind
    (a later track replaces an earlier one), the ``fmt`` dropped from each URL, and the
    translation languages only on translatable tracks."""
    translation_languages = [
        _TranslationLanguage(language=language.name, language_code=language.code)
        for language in player.translation_languages
    ]
    manually_created_transcripts: dict[str, Transcript] = {}
    generated_transcripts: dict[str, Transcript] = {}
    for track in player.caption_tracks or ():
        transcript_dict = (
            generated_transcripts if track.is_generated else manually_created_transcripts
        )
        transcript_dict[track.language_code] = Transcript(
            http_client,
            video_id,
            track.base_url.replace("&fmt=srv3", ""),
            track.name,
            track.language_code,
            track.is_generated,
            translation_languages if track.is_translatable else [],
        )
    return TranscriptList(
        video_id, manually_created_transcripts, generated_transcripts, translation_languages
    )
