# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common commands

```bash
# Install for development (Python 3.10+)
pip install -e ".[dev]"          # adds pytest, pytest-cov, responses, freezegun, black, flake8, mypy
pip install -e ".[api]"          # adds flask (for api.py)
pre-commit install               # hooks: ruff, ruff-format, trailing-whitespace, yaml/large-file checks

# Run the CLI from the source tree (no install needed)
python run.py dQw4w9WgXcQ --format json
python -m cli dQw4w9WgXcQ        # equivalent — uses src/cli/__main__.py

# Run the HTTP API wrapper
python api.py                    # binds 0.0.0.0:$PORT (default 8080)

# Tests
pytest                           # all
pytest --cov=src --cov-report=term-missing
pytest --cov=src --cov-fail-under=70    # what CI enforces
pytest tests/unit/test_formatters.py    # single file
pytest -k "test_json"                   # by pattern

# Lint / format (ruff is the source of truth — flake8/black/mypy are listed in extras but pre-commit only runs ruff)
ruff check .
ruff check --fix src/ tests/
ruff format src/ tests/

# Build distributions (sdist + wheel via setup.py, then twine check)
python build.py
python build.py --test           # upload to TestPyPI
python build.py --upload         # upload to PyPI
```

## Import layout — critical to understand before editing

`setup.py` declares `package_dir={"": "src"}` and `packages=find_packages(where="src")`. This means modules under `src/` are imported by their **top-level** name, *not* as `src.<module>`:

```python
from youtube_transcript import YouTubeTranscriptApi   # src/youtube_transcript.py
from cli.main import main                              # src/cli/main.py
from utils.retry import retry                          # src/utils/retry.py
```

For this to work when running from a checkout (without installing), three entry points each prepend `src/` to `sys.path` before any imports:

- `run.py` (dev CLI launcher)
- `api.py` (Flask wrapper)
- `src/cli/__init__.py` (so `python -m cli` works)
- `tests/conftest.py` (so pytest can import flat module names)

**Do not** rewrite these imports as `from src.foo import ...` — that breaks the installed package, which has no `src` prefix. If you add a new entry-point script, replicate the `sys.path.insert(0, _SRC_DIR)` pattern.

The console-scripts entry point in `setup.py` is `u-transkript=cli:main`, which resolves to `src/cli/__init__.py`'s re-exported `main`.

There is intentionally **no top-level `cli.py`** at the repo root — v3.0.0 removed it because it collided with the `src/cli/` package name during dev runs.

## CLI architecture (src/cli/)

The CLI was split out of a 532-line monolith in v3.0.0. The orchestration flow is:

```
main.py            (entry point; exception → exit-code mapping)
  ├─ parser.py            argparse setup + validate_args
  ├─ helpers.py           shared: build_formatter_kwargs, build_proxies,
  │                       get_progress_bar (optional tqdm), EXIT_* codes
  ├─ url_parser.py        extract_video_id, build_youtube_channel_url
  ├─ single_video.py      single-video path (calls YouTubeTranscriptApi + filters)
  ├─ channel_scraper.py   HTML scraping for channel video IDs (multiple URL variants + regexes)
  ├─ channel_downloader.py bulk download orchestrator (uses scraper + downloader helpers)
  └─ output.py            format_and_output, file_extension_for
```

Exit codes are `EXIT_SUCCESS=0`, `EXIT_USER_ERROR=1`, `EXIT_NETWORK_ERROR=2`, `EXIT_API_ERROR=3` (defined in `cli/helpers.py`). `main.py` maps exception classes to these codes — keep that mapping authoritative.

When monkey-patching in tests, target the **submodule** that uses the symbol (e.g. `cli.single_video.YouTubeTranscriptApi`), not `cli.YouTubeTranscriptApi` — the latter no longer exists.

## YouTube transcript fetching — two non-obvious requirements

`src/youtube_transcript.py` carries two YouTube quirks that **must** be preserved when editing:

1. **ANDROID InnerTube client, not WEB.** `_fetch_innertube_data` posts `clientName: "ANDROID", clientVersion: "20.10.38"`. The WEB client requires a PoToken and returns transcript URLs with `&exp=xpe` that resolve to empty content. Do not switch back to WEB.
2. **srv3 XML format.** YouTube switched from `<text start="s" dur="s">` to `<p t="ms" d="ms">`. The fetcher in `fetched_transcript.py` handles both — keep both branches.

Extraction has a two-tier fallback inside `YouTubeTranscriptApi._extract_transcript_data`: try the InnerTube API first, then fall back to scraping `ytInitialPlayerResponse` from the watch page with pre-compiled regex patterns (`_CAPTION_PATTERNS`). All regex patterns are module-level constants — keep new patterns there too.

`YouTubeTranscriptApi._session` is a **class-level singleton** (`requests.Session` with `HTTPAdapter(pool_connections=10)`). Use `get_session()` / `close_session()` or the context manager (`with YouTubeTranscriptApi() as api:`). Don't create per-request sessions — batch ops rely on connection reuse.

## Security: SSRF whitelist

All outbound URLs that aren't hard-coded to youtube.com go through `utils.security.validate_url`. The whitelist (`ALLOWED_HOSTS`) currently contains YouTube domains plus `generativelanguage.googleapis.com`. Any new outbound destination (e.g. an alternate translation provider, a new YouTube subdomain) must be added there or `validate_url` will raise `ValueError`. The Gemini API key is sent via the `x-goog-api-key` header — never put it in the URL.

## Network resilience

The `@retry` decorator from `utils.retry` is the **only** retry implementation — it does exponential backoff with optional jitter. Don't reintroduce ad-hoc retry loops. Currently applied to `YouTubeTranscriptApi._fetch_video_page` and `AITranscriptTranslator._call_gemini_api` for transient `requests.exceptions.Timeout`/`ConnectionError`/`RequestException`.

`YouTubeTranscriptApi.list_transcripts` has its own 429-aware retry loop (separate from `@retry`) because it needs to honor HTTP-status-based backoff, not just exception-based.

## Configuration

Config files are looked up in this order (first hit wins):
1. `~/.u-transkriptrc` — simple `key=value` lines, `#` comments
2. `~/.config/u-transkript/config.toml` — TOML; flattened one level (e.g. `[defaults]` keys become top-level)

Supported keys: `language`, `format`, `model`, `api_key`, `proxy`, `cache_ttl`. `apply_config_defaults` only fills args that are still at their argparse default — CLI flags always win.

## Version is single-sourced

`__version__` lives in `src/__init__.py`. `setup.py` reads it via regex. Bump only there; don't duplicate.

## CI

`.github/workflows/ci.yml` runs on Python 3.10, 3.11, 3.12, 3.13 (Ubuntu). It runs `ruff check .` then `pytest tests/ -v --cov=src --cov-report=xml --cov-report=term-missing`, then re-runs pytest with `--cov-fail-under=70`. Keep coverage at or above 70%.

## Public API surface (src/__init__.py)

`__all__` exports: `AITranscriptTranslator`, `YouTubeTranscriptApi`, `TranscriptList`, `FetchedTranscript`, the full exception hierarchy, all formatters (`PrettyPrintFormatter`, `JSONFormatter`, `TextFormatter`, `SRTFormatter`, `VTTFormatter`), and a `quick_translate(video_id, api_key, target_language, output_type)` convenience function. These are the only symbols downstream users should import from `u_transkript`; changing them is a breaking change.

## Exception hierarchy

All transcript errors inherit from `TranscriptRetrievalError` and carry a `.suggestion` property with actionable user advice. CLI and HTTP API both surface `.suggestion` when verbose / in error responses — preserve this when adding new exception classes.
