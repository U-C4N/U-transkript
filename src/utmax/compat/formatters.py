"""Transcript formatters, compatible with ``youtube_transcript_api.formatters`` 1.2.4.

The output is identical to youtube-transcript-api's. Besides a ``FetchedTranscript``, every
formatter also accepts what version 0.6 returned: a list of ``{"text", "start", "duration"}``
dictionaries.
"""

from __future__ import annotations

import json
import pprint
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, ClassVar

from utmax.compat._transcripts import FetchedTranscript, FetchedTranscriptSnippet

__all__ = [
    "FetchedTranscript",
    "FetchedTranscriptSnippet",
    "Formatter",
    "FormatterLoader",
    "JSONFormatter",
    "PrettyPrintFormatter",
    "SRTFormatter",
    "TextFormatter",
    "WebVTTFormatter",
]

AnyTranscript = FetchedTranscript | Sequence[Mapping[str, Any]]
"""A ``FetchedTranscript``, or the list of dictionaries youtube-transcript-api 0.6 returned."""


class Formatter:
    """Formatter should be used as an abstract base class.

    Formatter classes should inherit from this class and implement
    their own .format() method which should return a string. A
    transcript is represented by a List of Dictionary items.
    """

    def format_transcript(self, transcript: AnyTranscript, **kwargs: Any) -> str:
        raise NotImplementedError(
            "A subclass of Formatter must implement their own .format_transcript() method."
        )

    def format_transcripts(self, transcripts: Sequence[AnyTranscript], **kwargs: Any) -> str:
        raise NotImplementedError(
            "A subclass of Formatter must implement their own .format_transcripts() method."
        )


class PrettyPrintFormatter(Formatter):
    def format_transcript(self, transcript: AnyTranscript, **kwargs: Any) -> str:
        """Pretty prints a transcript.

        :param transcript:
        :return: A pretty printed string representation of the transcript.
        """
        return pprint.pformat(_raw_data(transcript), **kwargs)

    def format_transcripts(self, transcripts: Sequence[AnyTranscript], **kwargs: Any) -> str:
        """Converts a list of transcripts into a JSON string.

        :param transcripts:
        :return: A JSON string representation of the transcript.
        """
        return pprint.pformat([_raw_data(transcript) for transcript in transcripts], **kwargs)


class JSONFormatter(Formatter):
    def format_transcript(self, transcript: AnyTranscript, **kwargs: Any) -> str:
        """Converts a transcript into a JSON string.

        :param transcript:
        :return: A JSON string representation of the transcript.
        """
        return json.dumps(_raw_data(transcript), **kwargs)

    def format_transcripts(self, transcripts: Sequence[AnyTranscript], **kwargs: Any) -> str:
        """Converts a list of transcripts into a JSON string.

        :param transcripts:
        :return: A JSON string representation of the transcript.
        """
        return json.dumps([_raw_data(transcript) for transcript in transcripts], **kwargs)


class TextFormatter(Formatter):
    def format_transcript(self, transcript: AnyTranscript, **kwargs: Any) -> str:
        """Converts a transcript into plain text with no timestamps.

        :param transcript:
        :return: all transcript text lines separated by newline breaks.
        """
        return "\n".join(line.text for line in _snippets(transcript))

    def format_transcripts(self, transcripts: Sequence[AnyTranscript], **kwargs: Any) -> str:
        """Converts a list of transcripts into plain text with no timestamps.

        :param transcripts:
        :return: all transcript text lines separated by newline breaks.
        """
        return "\n\n\n".join(
            [self.format_transcript(transcript, **kwargs) for transcript in transcripts]
        )


class _TextBasedFormatter(TextFormatter):
    def _format_timestamp(self, hours: int, mins: int, secs: int, ms: int) -> str:
        raise NotImplementedError(
            "A subclass of _TextBasedFormatter must implement their own .format_timestamp() method."
        )

    def _format_transcript_header(self, lines: Iterable[str]) -> str:
        raise NotImplementedError(
            "A subclass of _TextBasedFormatter must implement "
            "their own _format_transcript_header method."
        )

    def _format_transcript_helper(
        self, i: int, time_text: str, snippet: FetchedTranscriptSnippet
    ) -> str:
        raise NotImplementedError(
            "A subclass of _TextBasedFormatter must implement "
            "their own _format_transcript_helper method."
        )

    def _seconds_to_timestamp(self, time: float) -> str:
        """Helper that converts `time` into a transcript cue timestamp.

        :reference: https://www.w3.org/TR/webvtt1/#webvtt-timestamp

        :param time: a float representing time in seconds.
        :type time: float
        :return: a string formatted as a cue timestamp, 'HH:MM:SS.MS'
        :example:
        >>> self._seconds_to_timestamp(6.93)
        '00:00:06.930'
        """
        time = float(time)
        hours_float, remainder = divmod(time, 3600)
        mins_float, secs_float = divmod(remainder, 60)
        hours, mins, secs = int(hours_float), int(mins_float), int(secs_float)
        ms = int(round((time - int(time)) * 1000, 2))
        return self._format_timestamp(hours, mins, secs, ms)

    def format_transcript(self, transcript: AnyTranscript, **kwargs: Any) -> str:
        """A basic implementation of WEBVTT/SRT formatting.

        :param transcript:
        :reference:
        https://www.w3.org/TR/webvtt1/#introduction-caption
        https://www.3playmedia.com/blog/create-srt-file/
        """
        snippets = _snippets(transcript)
        lines = []
        for i, line in enumerate(snippets):
            end = line.start + line.duration
            time_text = "{} --> {}".format(
                self._seconds_to_timestamp(line.start),
                self._seconds_to_timestamp(
                    snippets[i + 1].start
                    if i < len(snippets) - 1 and snippets[i + 1].start < end
                    else end
                ),
            )
            lines.append(self._format_transcript_helper(i, time_text, line))

        return self._format_transcript_header(lines)


class SRTFormatter(_TextBasedFormatter):
    def _format_timestamp(self, hours: int, mins: int, secs: int, ms: int) -> str:
        return f"{hours:02d}:{mins:02d}:{secs:02d},{ms:03d}"

    def _format_transcript_header(self, lines: Iterable[str]) -> str:
        return "\n\n".join(lines) + "\n"

    def _format_transcript_helper(
        self, i: int, time_text: str, snippet: FetchedTranscriptSnippet
    ) -> str:
        return f"{i + 1}\n{time_text}\n{snippet.text}"


class WebVTTFormatter(_TextBasedFormatter):
    def _format_timestamp(self, hours: int, mins: int, secs: int, ms: int) -> str:
        return f"{hours:02d}:{mins:02d}:{secs:02d}.{ms:03d}"

    def _format_transcript_header(self, lines: Iterable[str]) -> str:
        return "WEBVTT\n\n" + "\n\n".join(lines) + "\n"

    def _format_transcript_helper(
        self, i: int, time_text: str, snippet: FetchedTranscriptSnippet
    ) -> str:
        return f"{time_text}\n{snippet.text}"


class FormatterLoader:
    TYPES: ClassVar[dict[str, type[Formatter]]] = {
        "json": JSONFormatter,
        "pretty": PrettyPrintFormatter,
        "text": TextFormatter,
        "webvtt": WebVTTFormatter,
        "srt": SRTFormatter,
    }

    class UnknownFormatterType(Exception):
        def __init__(self, formatter_type: str) -> None:
            super().__init__(
                f"The format '{formatter_type}' is not supported. "
                f"Choose one of the following formats: {', '.join(FormatterLoader.TYPES.keys())}"
            )

    def load(self, formatter_type: str = "pretty") -> Formatter:
        """
        Loads the Formatter for the given formatter type.

        :param formatter_type:
        :return: Formatter object
        """
        if formatter_type not in FormatterLoader.TYPES:
            raise FormatterLoader.UnknownFormatterType(formatter_type)
        return FormatterLoader.TYPES[formatter_type]()


def _raw_data(transcript: AnyTranscript) -> Any:
    """What the JSON and pretty formatters print: ``to_raw_data()``, or 0.6's list as given."""
    to_raw_data = getattr(transcript, "to_raw_data", None)
    if callable(to_raw_data):
        return to_raw_data()
    return list(transcript)


def _snippets(transcript: AnyTranscript) -> list[FetchedTranscriptSnippet]:
    """The snippets of a transcript; 0.6's dictionaries become snippets."""
    return [
        FetchedTranscriptSnippet(text=line["text"], start=line["start"], duration=line["duration"])
        if isinstance(line, Mapping)
        else line
        for line in transcript
    ]
