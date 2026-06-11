<h1 align="center">U-Transkript</h1>

<p align="center"><strong>Extract YouTube transcripts and translate them with AI — no official API, no API keys for extraction, one dependency.</strong></p>

<p align="center">
  <a href="https://pypi.org/project/u-transkript/"><img src="https://img.shields.io/pypi/v/u-transkript?color=blue&label=PyPI" alt="PyPI"></a>
  <a href="https://pypi.org/project/u-transkript/"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python"></a>
  <a href="https://github.com/U-C4N/u-transkript/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License"></a>
</p>

U-Transkript is a standalone alternative to `youtube-transcript-api` with built-in AI translation. It talks to YouTube's InnerTube endpoint directly using the ANDROID client, so transcript extraction needs no official API key and no PoToken.

- **Transcript extraction** via YouTube's InnerTube ANDROID client, with watch-page scraping as a fallback
- **AI translation** to any language via Google Gemini (`gemini-3.5-flash` by default)
- **YouTube server-side translation** (`transcript.translate("es")`) — free, no AI key needed
- **Output formats**: pretty text, plain text, JSON, SRT, WebVTT
- **CLI** with single-video and bulk channel mode, plus an optional Flask HTTP API
- **Transparent disk cache** (24h) on the CLI's fetch paths — repeated fetches of the same video are instant
- **Python 3.10+**, a single runtime dependency (`requests`), resilient retries with backoff

## Installation

```bash
pip install u-transkript
```

Optional extras:

```bash
pip install "u-transkript[api]"   # Flask HTTP API wrapper
pip install "u-transkript[dev]"   # pytest, pytest-cov, ruff
```

## Quick start

```bash
u-transkript dQw4w9WgXcQ
```

```python
from youtube_transcript import YouTubeTranscriptApi

transcript = YouTubeTranscriptApi.get_transcript("dQw4w9WgXcQ")
for entry in transcript:
    print(f"[{entry['start']:7.2f}] {entry['text']}")
```

`get_transcript` returns a list of `{"text", "start", "duration"}` dicts.

## CLI

```bash
# Single video — pretty-printed transcript to stdout
u-transkript dQw4w9WgXcQ
u-transkript "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Language preference (first available wins)
u-transkript dQw4w9WgXcQ -l de en

# Output formats: pretty (default), json, text, srt, vtt
u-transkript dQw4w9WgXcQ -f srt -o subtitles.srt

# See which transcript languages a video offers
u-transkript dQw4w9WgXcQ --list-transcripts

# Translate with Gemini AI (reads GEMINI_API_KEY from the environment)
u-transkript dQw4w9WgXcQ --translate Turkish -o ceviri.txt

# Channel mode — downloads recent videos as 1_<videoId>.srt, 2_<videoId>.srt, ...
u-transkript @MrBeast -f srt -o transcripts/ -n 25

# From a source checkout (no install needed)
python run.py dQw4w9WgXcQ -f json
```

| Flag | Description |
|---|---|
| `target` | Video URL/ID, or `@handle` / channel URL for bulk download |
| `-l, --languages` | Language codes in order of preference (e.g. `en es fr`) |
| `-f, --format` | `pretty` (default), `json`, `text`, `srt`, `vtt` |
| `-o, --output` | Output file (single video) or directory (channel mode) |
| `-n, --count` | How many recent videos to download in channel mode (default: 10) |
| `--list-transcripts` | List available transcript languages and exit |
| `--translate LANGUAGE` | Translate with Gemini AI (needs `GEMINI_API_KEY`; not for `srt`/`vtt`) |
| `--no-cache` | Bypass the 24-hour transcript disk cache (cache applies to fetching, not `--translate`) |
| `--version` | Print version and exit |

Fetched transcripts are cached for 24 hours in `~/.cache/u-transkript` (single-video and channel modes; `--translate` always fetches fresh). Exit codes: `0` success, `1` user error, `2` network error, `3` transcript/API error.

<details>
<summary><strong>Config file</strong></summary>

Defaults can be set in `~/.u-transkriptrc`:

```ini
language = en
format = srt
```

or `~/.config/u-transkript/config.toml`:

```toml
language = "en"
format = "srt"
```

The first file found wins entirely. Only `language` and `format` are recognized; explicit CLI flags override.

</details>

## Python library

### Pick a language, list what's available

```python
from youtube_transcript import YouTubeTranscriptApi

# Preferred languages, in order
transcript = YouTubeTranscriptApi.get_transcript("dQw4w9WgXcQ", languages=["de", "en"])

# Inspect everything YouTube offers for a video
transcripts = YouTubeTranscriptApi.list_transcripts("dQw4w9WgXcQ")
for t in transcripts:
    print(t.language_code, t.language, "(auto)" if t.is_generated else "(manual)")

# Let YouTube translate server-side — no AI key required
english = transcripts.find_transcript(["en"])
if english.is_translatable:
    spanish_entries = english.translate("es").fetch()
```

### Export to subtitle formats

```python
from formatters import SRTFormatter, get_formatter
from youtube_transcript import YouTubeTranscriptApi

entries = YouTubeTranscriptApi.get_transcript("dQw4w9WgXcQ")

srt = SRTFormatter().format_transcript(entries)
vtt = get_formatter("vtt").format_transcript(entries)  # registry: pretty, json, text, srt, vtt

with open("subtitles.srt", "w", encoding="utf-8") as f:
    f.write(srt)
```

### Batch fetch

```python
results = YouTubeTranscriptApi.get_transcripts(
    ["dQw4w9WgXcQ", "jNQXAC9IVRw"],
    languages=["en"],
    continue_on_failure=True,
)
for r in results:
    status = f"{len(r['transcript'])} entries" if r["error"] is None else f"failed: {r['error']}"
    print(r["video_id"], status)
```

### Error handling

Every exception derives from `TranscriptRetrievalError` and carries a `.suggestion` with an actionable hint:

```python
from exceptions import NoTranscriptFound, TooManyRequests, TranscriptRetrievalError
from youtube_transcript import YouTubeTranscriptApi

try:
    transcript = YouTubeTranscriptApi.get_transcript("dQw4w9WgXcQ", languages=["fi"])
except NoTranscriptFound as e:
    print(e)             # includes the languages that ARE available
    print(e.suggestion)
except TooManyRequests as e:
    print(e.suggestion)  # rate-limited: wait, or route through a proxy
except TranscriptRetrievalError:
    ...                  # base class for all transcript errors
```

`get_transcript` also accepts `proxies={"https": "..."}`, `cookies="..."` and `preserve_formatting=True`. For many fetches in a row, use the context-manager form (`with YouTubeTranscriptApi() as api: ...`) so the shared HTTP session is closed when you are done.

## AI translation with Gemini

Translation requires a Gemini API key from [Google AI Studio](https://aistudio.google.com/); extraction itself never needs a key.

```python
from ai_translator import AITranscriptTranslator

translator = AITranscriptTranslator("GEMINI_API_KEY")  # default model: gemini-3.5-flash
text = translator.set_lang("German").translate_transcript("dQw4w9WgXcQ")
```

```python
# Fluent configuration; output types: "txt" (default), "json", "xml"
result = (
    AITranscriptTranslator("GEMINI_API_KEY")
    .set_model("gemini-3.5-flash")
    .set_lang("Spanish")
    .set_type("json")
    .translate_transcript("dQw4w9WgXcQ")
)
```

```python
# Custom prompts: a str.format template with {text} and {language} placeholders.
# Literal braces must be doubled ({{ }}).
summary = AITranscriptTranslator("GEMINI_API_KEY").translate_transcript(
    "dQw4w9WgXcQ",
    target_language="English",
    custom_prompt="Summarize this transcript in {language} as 5 bullet points:\n\n{text}",
)
```

Or the one-line shortcut:

```python
from ai_translator import quick_translate

text = quick_translate("dQw4w9WgXcQ", "GEMINI_API_KEY", target_language="French")
```

Long transcripts are automatically split into chunks (at entry boundaries) and translated chunk by chunk, so long videos don't silently truncate at the model output limit.

## HTTP API

`api.py` ships in the repository (not in the PyPI package), so run it from a checkout:

```bash
git clone https://github.com/U-C4N/u-transkript.git
cd u-transkript
pip install -e ".[api]"
python api.py            # binds 0.0.0.0:8080 — env vars: PORT, HOST, DEBUG
```

```bash
curl "http://localhost:8080/api?url=dQw4w9WgXcQ"
curl "http://localhost:8080/api?url=dQw4w9WgXcQ&format=srt" -o subtitles.srt
curl "http://localhost:8080/api?url=https://youtu.be/dQw4w9WgXcQ&languages=en,es&format=vtt"
```

| Endpoint | Description |
|---|---|
| `GET /` | Usage info |
| `GET /health` | Health check |
| `GET /api` | Fetch a transcript |

`GET /api` parameters: `url` (required), `format` (`json` default, `pretty`, `text`, `srt`, `vtt`), `languages` (comma-separated), `proxy`, `preserve_formatting` (`1`/`true`).

Errors come back as JSON with a `type` and an actionable `suggestion`; CORS is enabled. On Replit/Render/Railway-style platforms, set the run command to `python api.py` — the server binds to `$PORT`.

## How it compares

| | u-transkript | youtube-transcript-api |
|---|:---:|:---:|
| Transcript extraction / SRT / VTT / JSON | ✓ | ✓ |
| Built-in AI translation (Gemini) | ✓ | — |
| Bulk channel download (CLI) | ✓ | — |
| HTTP API wrapper included | ✓ | — |
| ANDROID InnerTube client (no PoToken) | ✓ | — |
| Retry with exponential backoff built in | ✓ | — |
| 24h transcript disk cache (CLI) | ✓ | — |
| Single runtime dependency | ✓ | — |

## How it works

- Talks to YouTube's InnerTube API using the ANDROID client first (no PoToken required), falling back to watch-page scraping and finally a bare timedtext URL.
- Parses all three transcript wire formats YouTube serves: srv3 XML, legacy XML, and json3.
- Retries transient failures with exponential backoff and honors HTTP 429 rate-limit responses with escalating waits.

## Limitations and disclaimer

- Not affiliated with or endorsed by YouTube or Google.
- Relies on undocumented YouTube endpoints that can change without notice.
- Respect YouTube's Terms of Service and the rights of content owners.
- Heavy use can get your IP rate-limited (HTTP 429).
- Channel mode scrapes the channel page HTML, so it can only see the videos that page exposes (roughly the most recent ones); `-n` is capped by what the page yields.

<details>
<summary><strong>Development</strong></summary>

```bash
git clone https://github.com/U-C4N/u-transkript.git
cd u-transkript
pip install -e ".[dev]"

python run.py dQw4w9WgXcQ -f json   # run the CLI from source
pytest                              # test suite
ruff check src/ tests/              # lint
```

</details>

## Links

- [Changelog](https://github.com/U-C4N/u-transkript/blob/main/CHANGELOG.md)
- [Contributing](https://github.com/U-C4N/u-transkript/blob/main/CONTRIBUTING.md)
- [Issue tracker](https://github.com/U-C4N/u-transkript/issues)
- [PyPI](https://pypi.org/project/u-transkript/)

## License

MIT — see [LICENSE](https://github.com/U-C4N/u-transkript/blob/main/LICENSE). Built by [U-C4N](https://github.com/U-C4N).
