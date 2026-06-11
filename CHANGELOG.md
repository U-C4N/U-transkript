# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.3.0] - 2026-06-10

### Added
- `-n/--count` flag: choose how many recent videos channel mode downloads
  (default 10; previously a hard-coded cap).
- `--list-transcripts` flag: list available transcript languages for a video
  (human-readable, or JSON with `-f json`).
- `--translate LANGUAGE` flag: translate the transcript with Gemini AI from the
  CLI (reads the API key from the `GEMINI_API_KEY` environment variable;
  supports `pretty`/`text`/`json` output, not `srt`/`vtt`).
- Transcript disk cache (24h TTL, `~/.cache/u-transkript`) is now active on the
  CLI single-video and channel paths; opt out with `--no-cache`. The library
  API and HTTP API never cache.
- Long transcripts are now translated in chunks (split at entry boundaries,
  ~12k chars per request) instead of one giant request that could silently
  truncate at the model output limit.
- `AITranscriptTranslator.translate_transcript()` accepts a `languages`
  preference list, forwarded to transcript extraction.

- `TranscriptList.all_transcripts()`: returns every track, including languages
  that have both a manual and an auto-generated version (iteration collapses to
  one per language); used by `--list-transcripts`.

### Changed
- Channel-mode files now include the video ID in the filename
  (`1_dQw4w9WgXcQ.srt` instead of `1.srt`).
- `AITranscriptTranslator` lets `TranscriptRetrievalError` and
  `requests.RequestException` propagate unwrapped (previously both were wrapped
  in plain `Exception`), so the CLI's exit codes (3 / 2) hold on `--translate`.
- The transcript cache fails open: any cache I/O error (unwritable cache dir,
  corrupt entry, disk full) falls back to a direct fetch instead of aborting.
- A config-file `format=srt`/`vtt` default is ignored on the `--translate` path,
  where those formats are invalid.
- Exception suggestions no longer reference CLI flags that do not exist
  (`--proxy`, `--cookies`); proxy/cookie support remains available through the
  library API and the HTTP API's `proxy` query parameter.

## [3.2.1] - 2026-06-10

### Fixed
- **Critical: installed packages were broken** — wheels omitted every top-level module
  (`youtube_transcript`, `fetched_transcript`, `transcript_list`, `formatters`,
  `exceptions`, `ai_translator`) because `setup.py` declared no `py_modules`; the
  `u-transkript` console script crashed with `ModuleNotFoundError`. All six modules now ship.
- Building distributions was broken twice over: `setup.py` reads a root `README.md`
  that did not exist (`FileNotFoundError`), and the root `build.py` shadowed the PyPA
  `build` package so its `python -m build` subprocess recursed into the script itself.
  The README now lives at the repository root and the script is renamed `release.py`.
- `u-transkript --version` works in installed environments: `cli.parser` falls back to
  `importlib.metadata.version("u-transkript")` when the dev-checkout `src/__init__.py`
  is not importable.
- Channel mode produced invalid directory names on Windows when given a channel URL
  without `-o` (e.g. `:` was not stripped); names are now sanitized.
- Channel mode exited 0 even when every download failed; it now raises
  `TranscriptRetrievalError` (exit code 3).
- Added `timeout=30` to the three outbound HTTP calls that lacked one: the InnerTube
  POST, the channel-page GET, and the Gemini POST.

### Changed
- `quick_translate()` now lives in `ai_translator.py` (re-exported from
  `src/__init__.py` for dev checkouts) so it is importable from installed wheels.
- License file renamed `MIT` → `LICENSE` so setuptools bundles it in distributions.
- Removed no-op `setup.cfg`; replaced outdated `docs/README.md` / `docs/example.md`
  with a new root `README.md`; removed GitHub Actions workflows (no CI).

## [3.2.0] - 2026-05-15

_Retroactive entry. The version went straight from 3.0.0 to 3.2.0; no 3.1.0 was ever released._

### Changed
- CLI simplified to a single positional `target` plus `-l/--languages`, `-f/--format`,
  `-o/--output`, `--version`; the previous 16-flag interface was removed.
- `AITranscriptTranslator` refactored: standardized prompt, retry/error handling,
  hand-rolled JSON/XML renderers with XML escaping.
- `build.py` reworked into an argparse-driven build tool (`--test` / `--upload`).
- Public exports reorganized in `src/__init__.py`; added `quick_translate()`.
- Added CLAUDE.md contributor guidance.

## [3.0.0] - 2026-04-17

### Breaking Changes
- `cli.py` has been split into a `cli` package under `src/cli/`. Internal symbols previously importable from the top-level `cli` module now live in focused submodules:
  - `extract_video_id`, `build_youtube_channel_url` → `cli.url_parser`
  - `get_channel_video_ids` → `cli.channel_scraper`
  - `download_channel_transcripts` → `cli.channel_downloader`
  - `process_single_video` → `cli.single_video`
  - `create_argument_parser`, `validate_args` → `cli.parser`
  - `format_and_output` → `cli.output`
  - `main` → `cli.main` (also re-exported as `cli.main` attribute for the `u-transkript` entry point)
- Users patching `cli.YouTubeTranscriptApi` or `cli.get_formatter` in tests must now target `cli.single_video.YouTubeTranscriptApi` / `cli.single_video.get_formatter` (or `cli.channel_downloader.*` for bulk mode).

### Changed
- Removed duplicated formatter-kwargs construction (was repeated in single-video and channel-download paths); now centralized in `cli.helpers.build_formatter_kwargs`.
- Removed duplicated proxy-dict construction; now centralized in `cli.helpers.build_proxies`.
- File-extension mapping for bulk downloads is now `cli.output.file_extension_for` instead of an inline `if/elif` chain.
- Channel-scraping URL variants and video-ID regex patterns are now module-level constants (pre-compiled regexes) in `cli.channel_scraper`.
- `get_channel_video_ids` and `download_channel_transcripts` split from ~90 and ~125-line god-functions into small orchestrators plus focused helpers (`_fetch_html`, `_extract_ids_from_html`, `_dedup_preserving_order`, `_download_one`, `_print_summary`, `_ensure_output_dir`).
- No user-facing CLI flags changed; all 16 existing flags behave identically.

### Added
- `python -m cli` entry point via `src/cli/__main__.py`.
- **HTTP API** (`api.py` at repo root) — optional Flask-based wrapper that exposes transcript extraction as `GET /api?url=<youtube_url>`. Supports `json`/`srt`/`vtt`/`text`/`pretty` formats, CORS-enabled, respects `$PORT` for Replit/Render/Railway deployments. Install with `pip install u-transkript[api]`.

## [2.0.0] - 2026-02-17

### Breaking Changes
- Python minimum version is now `>=3.10` (dropped 3.7-3.9)
- API key is now sent via `x-goog-api-key` HTTP header instead of URL parameter
- `lxml` dependency removed (was never used)
- `örnek_fonksiyon()` placeholder removed from `AITranscriptTranslator`
- `requests` minimum version bumped to `>=2.32.5`

### Added
- **YouTube ANDROID client support** - YouTube now requires PoToken for WEB client; switched to ANDROID client context for reliable transcript fetching
- **srv3 XML format parser** - YouTube changed transcript format from `<text start="s">` to `<p t="ms">`; both formats now supported
- Test infrastructure with pytest (`tests/unit/` - 6 test files, 1400+ lines)
- CI/CD pipeline with GitHub Actions (`ci.yml` + `release.yml`)
- Pre-commit hooks configuration (ruff, trailing-whitespace, yaml check)
- HTTP session singleton with connection pooling (`get_session()`, `close_session()`)
- Unified retry decorator with exponential backoff + jitter (`src/utils/retry.py`)
- SSRF protection with URL whitelisting (`src/utils/security.py`)
- Disk-based transcript caching with TTL (`src/utils/cache.py`)
- Colored terminal output with graceful fallback (`src/utils/console.py`)
- Config file support for defaults (`src/utils/config.py`)
- `--version` CLI flag
- `--verbose` / `--quiet` CLI flags
- `console_scripts` entry point (`u-transkript` command)
- Standardized exit codes (0=success, 1=user error, 2=network, 3=API)
- Type hints for all public APIs
- Actionable suggestion messages on all exception classes
- CHANGELOG.md, CONTRIBUTING.md

### Changed
- `build.py`: `os.system()` replaced with `subprocess.run(shell=False)` (security fix)
- `main()` God Function refactored into `create_argument_parser()`, `validate_args()`, `process_single_video()`, `format_and_output()`
- Bare `except:` clauses replaced with specific exception types
- Retry logic consolidated from 3 separate implementations into single `@retry` decorator
- String concatenation optimized with `''.join()` pattern
- Regex patterns pre-compiled at module level
- Version number managed from single source (`src/__init__.py`)
- Language name parsing supports both `simpleText` (WEB) and `runs[0].text` (ANDROID) formats

### Fixed
- **Critical: YouTube transcript fetching broken** - WEB client URLs return empty due to PoToken requirement; fixed by switching to ANDROID client
- **Critical: srv3 XML format not parsed** - New YouTube format uses `<p t="ms" d="ms">` instead of `<text start="s" dur="s">`; parser now handles both
- Shell injection vulnerability in `build.py`
- API key exposure in URLs and server logs
- Version inconsistency between `__init__.py` (1.0.0) and `setup.py` (1.1.0)
- HTTP session created per-request instead of reused

### Security
- Fixed critical shell injection in `build.py` (`os.system` → `subprocess.run`)
- Fixed API key leakage through URL parameters (moved to HTTP header)
- Added XXE-safe XML parsing
- Added SSRF protection with domain whitelisting
- Removed unused `lxml` to reduce attack surface
- Updated `requests` minimum to 2.32.5 to fix known CVEs

## [1.1.1] - 2025-06-01
### Fixed
- Bug fixes and improvements

## [1.1.0] - 2025-05-01
### Added
- AI-powered translation with Google Gemini
- Multiple output formats (SRT, VTT, JSON, TXT, Pretty)
- Bulk channel transcript download
- Method chaining API for translator

## [1.0.0] - 2025-04-01
### Added
- Initial release
- YouTube transcript extraction
- Multiple language support
- Basic CLI interface
