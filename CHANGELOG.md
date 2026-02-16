# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
