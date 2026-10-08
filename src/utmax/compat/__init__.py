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
