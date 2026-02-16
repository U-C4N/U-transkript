<p align="center">
  <h1 align="center">U-Transkript</h1>
  <p align="center">
    <strong>Extract YouTube transcripts and translate them with AI — no dependencies on youtube-transcript-api.</strong>
  </p>
  <p align="center">
    <a href="https://pypi.org/project/u-transkript/"><img src="https://img.shields.io/pypi/v/u-transkript?color=blue&label=PyPI" alt="PyPI"></a>
    <a href="https://pypi.org/project/u-transkript/"><img src="https://img.shields.io/pypi/pyversions/u-transkript" alt="Python"></a>
    <a href="https://github.com/U-C4N/u-transkript/actions"><img src="https://img.shields.io/github/actions/workflow/status/U-C4N/u-transkript/ci.yml?branch=main&label=CI" alt="CI"></a>
    <a href="https://codecov.io/gh/U-C4N/u-transkript"><img src="https://img.shields.io/codecov/c/github/U-C4N/u-transkript" alt="Coverage"></a>
    <a href="../LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License"></a>
  </p>
</p>

---

U-Transkript is a **standalone** Python library that extracts transcripts (subtitles) from any YouTube video and translates them into 50+ languages using Google Gemini AI. It is a fully independent alternative to `youtube-transcript-api` with its own YouTube integration, fluent API, and built-in CLI.

## What's New in v2.0.0

| Feature | Description |
|---------|-------------|
| **ANDROID Client** | Bypasses YouTube's PoToken requirement for reliable transcript fetching |
| **srv3 Format Support** | Handles YouTube's new `<p t="ms">` XML format alongside legacy `<text>` |
| **Security Hardening** | Shell injection fix, API key moved to headers, XXE/SSRF protection |
| **Session Pooling** | Singleton HTTP session with connection reuse — 3-5x faster batch ops |
| **Test Suite** | 1,400+ lines of tests, GitHub Actions CI/CD, pre-commit hooks |
| **CLI Upgrades** | `--version`, `--verbose`, `--quiet`, colored output, progress bars |
| **Utils Package** | Retry with backoff, disk cache, URL validation, config files |

## Installation

```bash
pip install u-transkript
```

> **Requires** Python 3.10+ and `requests >= 2.32.5`

<details>
<summary><strong>Development setup</strong></summary>

```bash
git clone https://github.com/U-C4N/u-transkript.git
cd u-transkript
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e ".[dev]"
```
</details>

## Quick Start

### Translate a transcript with Gemini AI

```python
from u_transkript import AITranscriptTranslator

translator = AITranscriptTranslator("YOUR_GEMINI_API_KEY")
result = translator.set_lang("English").translate_transcript("dQw4w9WgXcQ")
print(result)
```

### Method chaining

```python
result = (AITranscriptTranslator("YOUR_API_KEY")
    .set_model("gemini-3-flash-preview")
    .set_lang("Spanish")
    .set_type("json")
    .translate_transcript("dQw4w9WgXcQ"))
```

### One-liner

```python
from u_transkript import quick_translate

print(quick_translate("dQw4w9WgXcQ", "YOUR_API_KEY", "French"))
```

### Extract transcripts (no AI)

```python
from u_transkript import YouTubeTranscriptApi

# Fetch transcript
transcript = YouTubeTranscriptApi.get_transcript("dQw4w9WgXcQ")
for entry in transcript:
    print(f"[{entry['start']:.1f}s] {entry['text']}")

# Specify language preference
transcript = YouTubeTranscriptApi.get_transcript("dQw4w9WgXcQ", languages=["es", "en"])

# List all available transcripts
for t in YouTubeTranscriptApi.list_transcripts("dQw4w9WgXcQ"):
    print(f"{t.language_code}: {t.language} (generated={t.is_generated})")
```

### Format output

```python
from u_transkript import YouTubeTranscriptApi, SRTFormatter, VTTFormatter, JSONFormatter

transcript = YouTubeTranscriptApi.get_transcript("dQw4w9WgXcQ")

srt = SRTFormatter().format_transcript(transcript)           # SubRip (.srt)
vtt = VTTFormatter().format_transcript(transcript)           # WebVTT (.vtt)
js  = JSONFormatter().format_transcript(transcript, indent=2) # JSON (.json)
```

### Session management (performance)

```python
# Context manager — auto-cleanup
with YouTubeTranscriptApi() as api:
    t1 = api.get_transcript("VIDEO_1")
    t2 = api.get_transcript("VIDEO_2")  # reuses the same TCP connection

# Manual
YouTubeTranscriptApi.get_transcript("VIDEO_ID")
YouTubeTranscriptApi.close_session()
```

## CLI

```bash
# Basic usage
u-transkript dQw4w9WgXcQ
u-transkript "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Language preference
u-transkript dQw4w9WgXcQ --languages en es fr

# Output formats
u-transkript dQw4w9WgXcQ --format json
u-transkript dQw4w9WgXcQ --format srt --output subtitles.srt

# List available transcripts
u-transkript dQw4w9WgXcQ --list-transcripts

# Bulk download from a channel
u-transkript --username @MrBeast --count 50
u-transkript --username pewdiepie -n 20 --format json

# Filters
u-transkript dQw4w9WgXcQ --generated-only
u-transkript dQw4w9WgXcQ --manual-only

# Proxy & auth
u-transkript dQw4w9WgXcQ --proxy http://proxy:8080
u-transkript dQw4w9WgXcQ --cookies "SESSION=abc123"

# Verbosity
u-transkript dQw4w9WgXcQ --verbose
u-transkript dQw4w9WgXcQ --quiet

# Version
u-transkript --version
```

<details>
<summary><strong>All CLI flags</strong></summary>

| Flag | Short | Description |
|------|-------|-------------|
| `--version` | | Show version and exit |
| `--languages` | `-l` | Language codes in order of preference |
| `--format` | `-f` | Output format: `pretty` `json` `text` `srt` `vtt` |
| `--output` | `-o` | Write output to file |
| `--list-transcripts` | | List available transcripts for the video |
| `--username` | `-u` | YouTube channel username for bulk download |
| `--count` | `-n` | Number of videos to download (default: 10, max: 100) |
| `--generated-only` | | Only auto-generated transcripts |
| `--manual-only` | | Only manually created transcripts |
| `--exclude-generated` | | Exclude auto-generated transcripts |
| `--exclude-manual` | | Exclude manually created transcripts |
| `--preserve-formatting` | | Keep HTML formatting in transcript text |
| `--proxy` | | HTTP/HTTPS proxy URL |
| `--cookies` | | Cookie string for authenticated requests |
| `--verbose` | `-v` | Detailed progress output |
| `--quiet` | `-q` | Suppress all non-essential output |

</details>

## API Reference

### AITranscriptTranslator

| Method | Description | Returns |
|--------|-------------|---------|
| `__init__(api_key, model="gemini-2.5-flash")` | Create a translator instance | — |
| `set_model(name)` | Set the Gemini model | `self` |
| `set_api(key)` | Set the API key | `self` |
| `set_lang(language)` | Set target language (e.g. `"English"`) | `self` |
| `set_type(fmt)` | Set output format: `"txt"` `"json"` `"xml"` | `self` |
| `translate_transcript(video_id, ...)` | Extract, translate, and format | `str` |

### YouTubeTranscriptApi

| Method | Description | Returns |
|--------|-------------|---------|
| `get_transcript(video_id, ...)` | Fetch transcript for a single video | `list[dict]` |
| `get_transcripts(video_ids, ...)` | Fetch transcripts for multiple videos | `list[dict]` |
| `list_transcripts(video_id, ...)` | List all available transcripts | `TranscriptList` |
| `get_session()` | Get the singleton HTTP session | `Session` |
| `close_session()` | Close and reset the HTTP session | `None` |

### Output Formats

| Format | Description | Extension |
|--------|-------------|-----------|
| **Pretty** | Human-readable with timestamps (CLI default) | `.txt` |
| **Text** | Plain concatenated text | `.txt` |
| **JSON** | Structured data with metadata | `.json` |
| **SRT** | SubRip subtitle format | `.srt` |
| **VTT** | WebVTT subtitle format | `.vtt` |
| **XML** | Full XML with original + translation (AI output) | `.xml` |

## How It Compares

U-Transkript is a **standalone alternative** to `youtube-transcript-api`:

| | u-transkript | youtube-transcript-api |
|---|:---:|:---:|
| AI Translation (Gemini) | ✅ | — |
| Method Chaining API | ✅ | — |
| Bulk Channel Download | ✅ | — |
| Colored CLI Output | ✅ | — |
| Progress Bars | ✅ | — |
| Disk-based Cache | ✅ | — |
| Config File Support | ✅ | — |
| SSRF Protection | ✅ | — |
| SRT / VTT / JSON Export | ✅ | ✅ |
| Transcript Extraction | ✅ | ✅ |

## Project Structure

```
u-transkript/
├── cli.py                     # CLI entry point
├── build.py                   # Package build script
├── setup.py                   # Package configuration
├── src/
│   ├── __init__.py            # Package init (v2.0.0)
│   ├── youtube_transcript.py  # YouTube API integration
│   ├── ai_translator.py       # Gemini AI translation engine
│   ├── fetched_transcript.py  # Transcript data processing
│   ├── transcript_list.py     # Transcript list management
│   ├── formatters.py          # Output formatters (SRT, VTT, JSON, ...)
│   ├── exceptions.py          # Custom exception classes
│   └── utils/
│       ├── retry.py           # Exponential backoff with jitter
│       ├── security.py        # SSRF / URL validation
│       ├── cache.py           # Disk-based transcript cache
│       ├── console.py         # Colored terminal output
│       └── config.py          # Config file loader
├── tests/
│   ├── conftest.py            # Shared test fixtures
│   └── unit/                  # 6 unit test modules
├── .github/workflows/
│   ├── ci.yml                 # Test + lint pipeline
│   └── release.yml            # Tag-based PyPI publishing
├── CHANGELOG.md
├── CONTRIBUTING.md
└── docs/
    ├── README.md              # This file
    └── example.md
```

## Supported Languages

English, Turkish, Spanish, French, German, Italian, Portuguese, Russian, Japanese, Korean, Chinese, Arabic, Hindi, and **50+ more** via Google Gemini AI.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **Video not found** | Make sure the video ID is exactly 11 characters. Use the full URL if unsure. |
| **No transcript available** | Not every video has subtitles. Run `--list-transcripts` to check. |
| **Rate limited (429)** | YouTube temporarily blocked your IP. Wait a few minutes or use `--proxy`. |
| **API key error** | Verify your Gemini key is valid. Get one at [Google AI Studio](https://ai.google.dev/). |
| **Language not found** | Use `--list-transcripts` to see what's available, then pass `--languages`. |
| **Empty transcript** | YouTube's API may have changed. Update with `pip install -U u-transkript`. |

## Links

- [Changelog](../CHANGELOG.md)
- [Contributing](../CONTRIBUTING.md)
- [Examples](example.md)
- [PyPI](https://pypi.org/project/u-transkript/)
- [GitHub](https://github.com/U-C4N/u-transkript)

## License

[MIT](../LICENSE)
