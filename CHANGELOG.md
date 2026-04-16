# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
