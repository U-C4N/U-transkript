"""A drop-in replacement for youtube-transcript-api 1.2.4 that runs on utmax.

Change the import and the rest of the code stays as it is::

    from utmax.compat import YouTubeTranscriptApi  # was: from youtube_transcript_api import ...

    transcript = YouTubeTranscriptApi().fetch("dQw4w9WgXcQ", languages=["de", "en"])

The modules mirror youtube-transcript-api's (``utmax.compat.formatters``,
``utmax.compat.proxies``, ...) with the same classes, signatures, attributes and messages. The
class methods of version 0.6 (``get_transcript``, ``get_transcripts``, ``list_transcripts``) and
its exception names work too. Unlike the original, ``YouTubeTranscriptApi`` is thread-safe,
accepts video URLs, and needs no third-party packages.

For libraries that import ``youtube_transcript_api`` themselves, call :func:`install` once,
before they import it.
"""

# utmax.compat reproduces the interface, messages and output formats of youtube-transcript-api
# (https://github.com/jdepoix/youtube-transcript-api), which is distributed under this license:
#
# MIT License
#
# Copyright (c) 2018 Jonas Depoix
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import annotations

import sys

from utmax.compat import _api, _errors, _settings, _transcripts, formatters, proxies
from utmax.compat._api import YouTubeTranscriptApi
from utmax.compat._errors import (
    AgeRestricted,
    CookieError,
    CookieInvalid,
    CookiePathInvalid,
    CookiesInvalid,
    CouldNotRetrieveTranscript,
    FailedToCreateConsentCookie,
    InvalidVideoId,
    IpBlocked,
    NoTranscriptAvailable,
    NoTranscriptFound,
    NotTranslatable,
    PoTokenRequired,
    RequestBlocked,
    TooManyRequests,
    TranscriptsDisabled,
    TranslationLanguageNotAvailable,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeRequestFailed,
    YouTubeTranscriptApiException,
)
from utmax.compat._transcripts import (
    FetchedTranscript,
    FetchedTranscriptSnippet,
    Transcript,
    TranscriptList,
)

__all__ = [
    "AgeRestricted",
    "CookieError",
    "CookieInvalid",
    "CookiePathInvalid",
    "CookiesInvalid",
    "CouldNotRetrieveTranscript",
    "FailedToCreateConsentCookie",
    "FetchedTranscript",
    "FetchedTranscriptSnippet",
    "InvalidVideoId",
    "IpBlocked",
    "NoTranscriptAvailable",
    "NoTranscriptFound",
    "NotTranslatable",
    "PoTokenRequired",
    "RequestBlocked",
    "TooManyRequests",
    "Transcript",
    "TranscriptList",
    "TranscriptsDisabled",
    "TranslationLanguageNotAvailable",
    "VideoUnavailable",
    "VideoUnplayable",
    "YouTubeDataUnparsable",
    "YouTubeRequestFailed",
    "YouTubeTranscriptApi",
    "YouTubeTranscriptApiException",
    "install",
]

_MODULE = "youtube_transcript_api"


def install() -> None:
    """Make ``import youtube_transcript_api`` load utmax.compat.

    For libraries that import youtube-transcript-api themselves (such as LangChain's YouTube
    loader): call it once, before they import it. It registers ``youtube_transcript_api`` and
    its modules in ``sys.modules``, replacing a real installation for every import that
    follows; modules that imported it earlier keep what they have. Calling it again changes
    nothing.
    """
    package = sys.modules[__name__]
    modules = {
        _MODULE: package,
        f"{_MODULE}._api": _api,
        f"{_MODULE}._errors": _errors,
        f"{_MODULE}._settings": _settings,
        f"{_MODULE}._transcripts": _transcripts,
        f"{_MODULE}.formatters": formatters,
        f"{_MODULE}.proxies": proxies,
    }
    sys.modules.update(modules)
