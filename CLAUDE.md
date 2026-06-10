# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

U-Transkript (PyPI: `u-transkript`, version 3.2.1 in `src/__init__.py`) is a Python 3.10+ library + CLI that extracts YouTube transcripts and optionally translates them with Google Gemini. Sole runtime dependency: `requests`. The README is the root `README.md` (also the PyPI long_description).

## Common commands

```bash
pip install -e ".[dev]"        # dev extras are exactly: pytest, pytest-cov, ruff
pip install -e ".[api]"        # adds flask>=3.0 (for api.py)
pre-commit install             # hooks: ruff --fix, ruff-format, trailing-whitespace,
                               #        end-of-file-fixer, check-yaml, check-added-large-files

# Run the CLI from the source tree (no install needed)
python run.py dQw4w9WgXcQ --format json
# NOTE: `python -m cli` only works with cwd=src/ or PYTHONPATH=src — from the repo
# root it fails with "No module named cli". Prefer run.py.

# HTTP API wrapper (Flask)
python api.py                  # env vars: PORT (default 8080), HOST (0.0.0.0), DEBUG

# Tests — there is NO pytest/coverage/ruff config file anywhere (pyproject.toml is
# build-system only; there is no setup.cfg); everything runs on defaults.
pytest
pytest tests/unit/test_formatters.py     # single file
pytest -k "test_json"                    # by pattern
pytest --cov=src --cov-report=term-missing   # coverage is manual; no enforced floor

# Lint / format — ruff is the only lint/format tool in this repo
ruff check src/ tests/
ruff check --fix src/ tests/
ruff format src/ tests/

# Build distributions (PEP 517 `python -m build` + `twine check`)
python release.py
python release.py --test       # upload to TestPyPI
python release.py --upload     # upload to PyPI
# (named release.py, NOT build.py — a root build.py shadows the PyPA `build`
#  package and makes `python -m build` recurse into itself)
```

**Packaging gotcha:** any new top-level module under `src/` must be added to `py_modules` in `setup.py` — `find_packages(where="src")` only discovers the `cli` and `utils` packages, so wheels silently omit unlisted top-level modules.

There are no GitHub Actions workflows in the working tree. Nothing enforces lint or coverage except pre-commit hooks; CONTRIBUTING.md's "90%+ coverage" is aspirational.

## Import layout — critical to understand before editing

`setup.py` declares `package_dir={"": "src"}`, so modules under `src/` are imported by their **top-level** name, never as `src.<module>`:

```python
from youtube_transcript import YouTubeTranscriptApi   # src/youtube_transcript.py
from cli.main import main                              # src/cli/main.py
from utils.retry import retry                          # src/utils/retry.py
```

For this to work from a checkout, `run.py`, `api.py`, and `tests/conftest.py` each do `sys.path.insert(0, <src>)` before any project import (`src/cli/__init__.py` appends instead). If you add a new entry-point script, replicate that pattern. **Do not** rewrite imports as `from src.foo import ...` — the installed package has no `src` prefix. A repo-wide grep for `from src.` should always return zero hits.

The console-scripts entry point is `u-transkript=cli:main` (`src/cli/__init__.py` re-exports `main`). There is intentionally **no top-level `cli.py`** — v3.0.0 removed it because it collided with the `src/cli/` package.

Packaging: the six top-level modules ship via `py_modules` in `setup.py` alongside the `cli` and `utils` packages. `src/__init__.py` is a **dev-checkout-only aggregator** — it is not shipped in wheels (a top-level `__init__` module can't be), which is why `cli/parser.py` resolves `__version__` with a try/except falling back to `importlib.metadata.version("u-transkript")`.

## CLI architecture (src/cli/)

```
main.py             entry point; loads config defaults, routes single-video vs channel,
                    maps exceptions to exit codes
  ├─ parser.py             create_argument_parser() — args: target, -l/--languages,
  │                        -f/--format {pretty,json,text,srt,vtt}, -o/--output, --version
  ├─ helpers.py            EXIT_* codes, build_formatter_kwargs, build_proxies,
  │                        get_progress_bar (optional tqdm)
  ├─ url_parser.py         extract_video_id, is_channel_target, build_youtube_channel_url
  ├─ single_video.py       single-video path
  ├─ channel_scraper.py    HTML scraping for channel video IDs (URL variants + regexes)
  ├─ channel_downloader.py bulk download (default/hard cap 10 videos; no CLI flag for count)
  └─ output.py             format_and_output, file_extension_for
```

Channel mode raises `TranscriptRetrievalError` (exit 3) when every download fails; partial failures still exit 0 with a warning.

Exit codes (`cli/helpers.py`): `EXIT_SUCCESS=0`, `EXIT_USER_ERROR=1`, `EXIT_NETWORK_ERROR=2`, `EXIT_API_ERROR=3`. `main.py` maps `TranscriptRetrievalError→3`, `requests.RequestException→2`, `ValueError`/`KeyboardInterrupt`/other→1. Keep that mapping authoritative.

`build_proxies` lives in `cli/helpers.py` but is consumed only by `api.py` — the CLI has no `--proxy` flag. The CLI does **not** print exception `.suggestion`s; only the HTTP API surfaces them.

## YouTube transcript fetching — non-obvious requirements

`src/youtube_transcript.py` carries YouTube quirks that **must** be preserved:

1. **ANDROID InnerTube client, not WEB.** `_fetch_innertube_data` posts `clientName: "ANDROID", clientVersion: "20.10.38"`. The WEB client requires a PoToken and returns transcript URLs that resolve to empty content. Do not switch back to WEB.
2. **Three transcript wire formats.** `fetched_transcript.py` parses srv3 XML (`<p t="ms" d="ms">`, preferred), legacy XML (`<text start="s" dur="s">`), and json3 (`events/segs`) as a fallback when XML parsing fails. Keep all branches.
3. **Three-tier extraction fallback** in `_extract_transcript_data`: InnerTube API → `_CAPTION_PATTERNS` regex scrape of `ytInitialPlayerResponse` from the watch page → `_extract_alternative_transcript_data` (bare timedtext URL, fabricates a single English entry). All regex patterns are pre-compiled module-level constants — put new patterns there too.

`YouTubeTranscriptApi._session` is a **class-level singleton** (`requests.Session`, `HTTPAdapter(pool_connections=10, pool_maxsize=10)`, urllib3 retries explicitly disabled). Use `get_session()`/`close_session()` or the context manager. Don't create per-request sessions — batch ops rely on connection reuse.

`fetched_transcript.py` imports `YouTubeTranscriptApi` lazily inside `_fetch_raw` to avoid a circular import — don't hoist it.

## Network resilience — three retry layers, on purpose

- `@retry` from `utils.retry` (exponential backoff + jitter), on three sites: `_fetch_video_page` (Timeout/ConnectionError only), `FetchedTranscript._fetch_raw` (Timeout/ConnectionError only), and `AITranscriptTranslator._call_gemini_api` (RequestException).
- Manual 429-aware loops with `retry_delay * 2**attempt` backoff exist in **both** `list_transcripts` and `FetchedTranscript.fetch` — separate from `@retry` because they honor HTTP-status-based backoff.
- Adapter-level retries are disabled (`URLLibRetry(total=0)`) so all retry behavior is application-level. Don't add ad-hoc retry loops elsewhere.

## AI translator (src/ai_translator.py) — library-only, with sharp edges

Neither the CLI nor `api.py` uses `AITranscriptTranslator`; the only convenience wrapper is `quick_translate()`, defined in `ai_translator.py` and re-exported from `src/__init__.py` (it defaults to Turkish, while the class defaults to English). Facts to keep in mind when editing:

- Calls the Gemini REST API directly (`POST {base}/{model}:generateContent`, default model `gemini-2.5-flash`), key in the `x-goog-api-key` header — **never in the URL**. `validate_url` runs before every call.
- **No chunking**: the whole transcript is joined into one string and sent in a single request. Long videos can silently truncate at the output-token limit.
- All five outbound HTTP calls pass `timeout=30` (watch page, transcript fetch, InnerTube POST, channel-page scrape, Gemini POST) — keep it that way for new calls.
- Response parsing assumes exactly `candidates[0].content.parts[0].text`; safety blocks / MAX_TOKENS surface as a generic `Exception` — this module raises plain `Exception`, not the project exception hierarchy.
- Output types `txt`/`json`/`xml` are hand-rolled (`_render_json`/`_render_xml`); `formatters.py` is **not** used for translations.
- `custom_prompt` goes through `.format()` — literal `{`/`}` must be doubled.

## Security: SSRF whitelist

`utils.security.validate_url` enforces `ALLOWED_HOSTS` (YouTube domains + `generativelanguage.googleapis.com`) and rejects private/loopback IPs — but it is only invoked on the Gemini path; YouTube fetches use hard-coded `youtube.com` URL templates. Any new outbound destination must be added to `ALLOWED_HOSTS` or `validate_url` raises `ValueError`.

## Configuration (src/utils/config.py)

Lookup: `~/.u-transkriptrc` (key=value), else `~/.config/u-transkript/config.toml` (flattened one level). **First existing file wins entirely — no merge.** Only two keys are implemented: `language` and `format`. `apply_config_defaults` fills args still at their argparse default — caveat: an explicit `--format pretty` is indistinguishable from the default and can be overridden by config.

`utils/cache.py` (`TranscriptCache`, disk JSON cache, 24h TTL) is exported from `utils/__init__.py` but currently has **no call sites** — wire it up or ignore it, but don't assume caching is active.

## Test conventions (tests/)

- `tests/conftest.py` provides `sample_transcript`, `sample_transcript_long`, `mock_youtube_html`, `mock_transcript_xml`, `mock_gemini_response`. `tests/integration/` is empty.
- Mocking is `unittest.mock` only (no `responses` library). Patch where the name is **used**, not defined: `cli.single_video.YouTubeTranscriptApi`, `cli.channel_downloader.get_formatter`, `ai_translator.requests.post` — `cli.YouTubeTranscriptApi` does not exist.
- To exercise the HTML-scrape fallback, patch `_extract_innertube_api_key` to return `None`.
- Tests calling `list_transcripts` must pass `max_retries=0, retry_delay=0` or they sleep through real backoff.
- Style: plain-assert pytest grouped in `Test<Subject>` classes, `@pytest.mark.parametrize`, no custom markers.

## Versioning and public API

`__version__` is single-sourced in `src/__init__.py` (setup.py reads it via regex) — bump only there. `__all__` in `src/__init__.py` is the public surface: the two API classes, `TranscriptList`/`FetchedTranscript`, the full exception hierarchy, all formatters including the `Formatter` base class, and `quick_translate`. Changing it is a breaking change. `formatters.get_formatter(name)` is the non-exported registry `api.py` and the CLI use.

All transcript errors inherit `TranscriptRetrievalError` and carry a `.suggestion` property with actionable advice — preserve it on new exception classes (the HTTP API returns it in error JSON).

## Docs

`CHANGELOG.md`, `CONTRIBUTING.md`, and the root `README.md` were brought in line with the code in v3.2.1 (the old `docs/` directory was removed; the license file is `LICENSE`). Keep them in sync — in particular, the README documents the CLI's exact 5-flag surface and the flat import layout; update it when either changes.
