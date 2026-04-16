"""
HTTP API wrapper for U-Transkript.

Run locally:
    pip install flask
    python api.py

Deploy on Replit / Render / Railway / Heroku:
    1. Ensure `flask` is in requirements (pip install flask)
    2. Set run command to: python api.py
    3. The service binds to $PORT (default: 8080) on 0.0.0.0

Endpoints:
    GET /         — usage info
    GET /health   — health check
    GET /api?url=<youtube_url>&format=json|srt|vtt|text|pretty
                   &languages=en,es&proxy=...&preserve_formatting=1

Examples:
    curl "https://your-app.example/api?url=dQw4w9WgXcQ"
    curl "https://your-app.example/api?url=dQw4w9WgXcQ&format=srt"
    curl "https://your-app.example/api?url=https://youtu.be/dQw4w9WgXcQ&languages=en,es"
"""

from __future__ import annotations

import os
import sys

_SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

try:
    from flask import Flask, Response, jsonify, request
except ImportError:
    sys.stderr.write(
        "Flask is required to run the API. Install it with:\n"
        "    pip install flask\n"
    )
    sys.exit(1)

from __init__ import __version__  # noqa: E402
from cli.helpers import build_formatter_kwargs, build_proxies  # noqa: E402
from cli.url_parser import extract_video_id  # noqa: E402
from exceptions import (  # noqa: E402
    NoTranscriptAvailable,
    NoTranscriptFound,
    TooManyRequests,
    TranscriptDisabled,
    TranscriptNotFound,
    TranscriptRetrievalError,
    VideoUnavailable,
)
from formatters import get_formatter  # noqa: E402
from youtube_transcript import YouTubeTranscriptApi  # noqa: E402

app = Flask(__name__)

_VALID_FORMATS = {"pretty", "json", "text", "srt", "vtt"}
_MIME_TYPES = {
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
    "text": "text/plain",
    "pretty": "text/plain",
}

_USAGE = {
    "service": "u-transkript",
    "version": __version__,
    "endpoints": {
        "GET /": "This usage info",
        "GET /health": "Health check",
        "GET /api": (
            "Fetch transcript. Query params: "
            "url (required), format (json|srt|vtt|text|pretty), "
            "languages (comma-separated, e.g. en,es), "
            "proxy, preserve_formatting (1|0)"
        ),
    },
    "examples": [
        "/api?url=dQw4w9WgXcQ",
        "/api?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ&format=srt",
        "/api?url=dQw4w9WgXcQ&languages=en,es&format=json",
    ],
}


@app.after_request
def _add_cors(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.get("/")
def usage():
    return jsonify(_USAGE)


@app.get("/health")
def health():
    return jsonify({"status": "ok", "version": __version__})


def _parse_languages(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    langs = [lang.strip() for lang in raw.split(",") if lang.strip()]
    return langs or None


def _is_truthy(raw: str | None) -> bool:
    return (raw or "").lower() in {"1", "true", "yes", "on"}


def _error(status: int, error_type: str, message: str, suggestion: str | None = None):
    payload: dict[str, str] = {"error": message, "type": error_type}
    if suggestion:
        payload["suggestion"] = suggestion
    return jsonify(payload), status


@app.get("/api")
def api_transcript():
    url = request.args.get("url") or request.args.get("video")
    if not url:
        return _error(
            400,
            "MissingParameter",
            "Query parameter 'url' is required. Example: /api?url=dQw4w9WgXcQ",
        )

    fmt = (request.args.get("format") or "json").lower()
    if fmt not in _VALID_FORMATS:
        return _error(
            400,
            "InvalidFormat",
            f"format must be one of: {sorted(_VALID_FORMATS)}",
        )

    try:
        video_id = extract_video_id(url)
    except ValueError as e:
        return _error(400, "InvalidUrl", str(e))

    languages = _parse_languages(request.args.get("languages"))
    proxies = build_proxies(request.args.get("proxy"))
    preserve_formatting = _is_truthy(request.args.get("preserve_formatting"))

    try:
        transcript = YouTubeTranscriptApi.get_transcript(
            video_id,
            languages=languages,
            proxies=proxies,
            preserve_formatting=preserve_formatting,
        )
    except VideoUnavailable as e:
        return _error(404, "VideoUnavailable", str(e), getattr(e, "suggestion", None))
    except (
        TranscriptNotFound,
        NoTranscriptFound,
        NoTranscriptAvailable,
        TranscriptDisabled,
    ) as e:
        return _error(404, type(e).__name__, str(e), getattr(e, "suggestion", None))
    except TooManyRequests as e:
        return _error(429, "TooManyRequests", str(e), getattr(e, "suggestion", None))
    except TranscriptRetrievalError as e:
        return _error(502, type(e).__name__, str(e), getattr(e, "suggestion", None))
    except Exception as e:
        return _error(500, "ServerError", str(e))

    if fmt == "json":
        return jsonify(
            {
                "video_id": video_id,
                "language": languages[0] if languages else None,
                "entry_count": len(transcript),
                "transcript": transcript,
            }
        )

    formatter = get_formatter(fmt)
    kwargs = build_formatter_kwargs(fmt)
    body = formatter.format_transcript(transcript, **kwargs)
    mime = _MIME_TYPES.get(fmt, "text/plain")
    return Response(body, status=200, mimetype=mime)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    debug = _is_truthy(os.environ.get("DEBUG"))
    app.run(host=host, port=port, debug=debug)
