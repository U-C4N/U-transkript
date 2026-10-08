# u-transcript max (`utmax`) — Design Spec & Roadmap

> Status: approved by the user on 2026-09-27. Implementation plans, one per milestone, live in `docs/design/plans/`.

## Context

The user deleted the entire 3.x codebase (and an abandoned v4 spec/plan) to rebuild from scratch under a new
name, **u-transcript max**: a professional, fully English Python library that is better than — and completely
independent of — `youtube-transcript-api`. It fetches YouTube subtitles, translates them with AI while keeping
timing, builds bilingual subtitles, downloads video/audio (mp4/mov/m4a/mp3) with embedded subtitles, works on whole
playlists/channels, ships a drop-in `youtube-transcript-api` compatibility layer and an MCP server. "Max" = a
Chrome extension follows later as a separate sub-project in the same repo.

Hard constraint: **zero runtime dependencies** (stdlib only). Only optional extras may add dependencies: the
official AI SDKs and the official MCP SDK. `ffmpeg` is an optional external program used only for mp3.

Outcome: `pip install u-transcript-max` → `import utmax` → one-liners for every feature; offline-testable layered
architecture; green quality gates; a minimal, beautiful README with an ASCII architecture diagram.

## 1. Decisions (Q&A, 2026-09-27)

| Topic | Decision |
|---|---|
| Names | PyPI `u-transcript-max` · import `utmax` · **no CLI** · only console script `utmax-mcp` (+ `python -m utmax.mcp`) |
| Dependencies | Core: stdlib only. Extras: `claude` (anthropic), `openai`, `gemini` (google-genai), `openrouter` (= openai SDK), `ai` (all), `mcp` |
| v0.1.0 scope | Transcripts · AI translation · bilingual subtitles · downloads · playlist/channel bulk · compat layer · MCP server |
| Audio | `.m4a` (AAC, native, zero deps) always; `.mp3` only when an `ffmpeg` executable is found, else typed error + hint |
| Video | `.mp4` / `.mov` with audio + subtitles; default best **H.264 ≤ 1080p**; `quality="max"` → **AV1 ≤ 2160p** (`.mp4` only) |
| Merging | **Own pure-Python MP4/MOV muxer** (no ffmpeg); WebM/VP9 sources not supported |
| Subtitles in video | Embedded soft toggleable tx3g track(s) (multi-language, translations, bilingual) and/or sidecar `.srt` |
| Subtitle default | Video downloads embed the spoken-language track (manual preferred); `subtitles=[]` disables; explicit list overrides; sidecars only on request |
| Bilingual layout | Original line on top, translation below (default; `translation_first=True` flips) |
| Download extras | Parallel range (chunked) downloads + resume. Not in 0.1.0: metadata/cover art, chapters, hardsub |
| AI providers | Claude · OpenAI + compatible via `base_url` (Ollama, LM Studio, Groq, DeepSeek…) · Gemini · OpenRouter |
| AI rules | Official SDKs, lazily imported; model always `"provider=model-id"`; **no default model**; every format works for translations |
| Compat | `from utmax.compat import YouTubeTranscriptApi` drop-in, plus opt-in `utmax.compat.install()` for transitive users (LangChain…) |
| MCP | Official `mcp` SDK (extra), stdio; tools: list tracks, get transcript (in parts), list playlist/channel videos, download; no AI provider and no API key: the assistant translates (decided 2026-10-08) |
| Architecture | Layered: interfaces → services → pure core (no I/O) + adapters (all I/O) |
| README | Minimal, English, **ASCII** architecture diagram (same on GitHub and PyPI), legal/ToS note |
| Repo & release | Repo stays `U-C4N/U-transkript`, branch `v4` · first release **0.1.0** · MIT `Copyright (c) 2024-2026 U-C4N` |
| Docs | Spec + milestone plans committed under `docs/design/` |
| Extension | After the library; own spec→plan cycle; reuses `core/translate/data/*`; subtitle/translation only (Web Store bans YouTube downloaders) |
| Defaults (mine) | Python ≥ 3.11 · hatchling + uv · ruff + mypy --strict + pytest (coverage ≥ 90 %, branch) · CI Linux/Windows (+macOS 3.14) · nightly live tests · Trusted Publishing, publish only on user approval |
| Small calls (mine) | `quality="max"` + `.mov` → `InvalidOption` · MCP download dir default `~/Downloads/utmax` · OpenRouter via openai SDK (official SDK pins `pydantic<2.13`) |

## 2. Verified facts (stdlib-only probes, 2026-09-27)

- **Player**: `POST /youtubei/v1/player` (no key) with `ANDROID` / `IOS` / `ANDROID_VR` → 200 OK, captions, and
  `streamingData` with **direct URLs** (no `signatureCipher`, `n`, `pot`); `WEB` / `TVHTML5` → UNPLAYABLE.
  ANDROID and IOS return `translationLanguages` (18); **ANDROID_VR returns none**.
- **Captions**: `fmt=json3` → 200 JSON (manual: no `tOffsetMs`; asr: word offsets + whitespace-only `aAppend`
  events). `tlang=` → **429** today. Legacy XML (no `fmt`) has double-escaped entities.
- **Streams**: Range GET → 206, ~13–21 MB/s, no throttling; URLs expire after ~6 h and are **bound to the
  requester's IP** (`ip=` param); bad `sig` → 403; past EOF → 416. Progressive only itag 18 (360p, no
  `contentLength`; `Range: bytes=0-0` reveals size). H.264 133–137/160 (≤1080p), AV1-in-MP4 394–401 (≤2160p),
  VP9 WebM, AAC 139 (HE) / 140 (LC 44.1 kHz), Opus 249/251.
- **Containers**: adaptive MP4 = fragmented (`ftyp·moov(mvex)·sidx·moof·mdat…`); itag 137 has `edts/elst`
  (media_time 512) and signed-cto `trun`; 140 is plain AAC; 399 is `av01`. itag 18 is classic MP4.
- **Browse**: ANDROID_VR `browse` (no key, no PoToken) → `playlistVideoRenderer`, 20/page, continuation via
  `nextContinuationData` (183/183 items in 10 pages, 2 s). WEB → `lockupViewModel`, 100/page,
  `continuationItemViewModel`; WEB shows a channel's Shorts as `shortsLockupViewModel` items, at most 100 and
  without a continuation, and hides an occasional video. `navigation/resolve_url` maps `@handle`, `/channel/`,
  `/c/`, `/user/` → `UC…` (unknown handle: WEB 404, ANDROID_VR 200 with only a `urlEndpoint`). Channel lists:
  `UU` (all) / `UULF` (videos) / `UUSH` (shorts) / `UULV` (live) + `id[2:]`; a list a channel lacks answers 404
  (ANDROID_VR) or only the alert "The playlist does not exist." (WEB). Nonexistent playlist → 400; `RD…` mixes
  unviewable (WEB alert "This playlist type is unviewable."); YouTube Music's `RDCLAK5uy_…` playlists list on WEB,
  but ANDROID_VR pages them endlessly (verified 2026-09-29).
- **youtube-transcript-api 1.2.4** (2026-01-29) public surface read from source (see §4.6); legacy static methods
  were removed in 1.2.0 (0.6.3 had them with `cookies`, 1.1.1 behind `DeprecationWarning`s). Side by side on
  2026-10-08, utmax.compat and 1.2.4 gave identical snippets, formatter output and list texts on two live videos.
- **SDKs**: `mcp` 2.2.0 and 2.3.0 (`from mcp.server import MCPServer`; FastMCP renamed; stdio re-wraps UTF-8 and
  diverts stray fd-1 writes to stderr; sync tools run in threads; a pydantic return model gives structured output;
  `ToolError` → an `is_error` result; MCP sampling is not documented for Claude Code or Claude Desktop);
  `anthropic` 1.8.0 (`output_config={"format":{"type":"json_schema",…}}` GA; no `fallbacks`);
  `openai` 3.19.2; `google-genai` 2.25.0 (**retries off by default**). PyPI names `u-transcript-max`, `utmax`: free.
- **ffmpeg** 9.0 with `libmp3lame` present locally. cp1254 console crashes on `♪` → the library never prints.

## 3. Architecture

```
+----------------------------------------------------------------------+
| Interfaces   utmax (facade)      utmax.compat         utmax.mcp       |
|              fetch/translate/    YouTubeTranscriptApi stdio server    |
|              download/list_...   drop-in              [mcp] extra     |
+-----------------------------------+----------------------------------+
                                    |
+-----------------------------------v----------------------------------+
| Services     transcripts   translation   download   collections      |
+------------------+------------------------------------+--------------+
                   | uses                               | uses
+------------------v-----------------+  +---------------v--------------+
| Pure core (no I/O)                 |  | Adapters (all I/O)           |
|  ids player playability captions   |  |  http: urllib, retry, proxy  |
|  selection formats segmentation    |  |  innertube  watch_page       |
|  bilingual streams browse retry    |  |  downloader: parallel+resume |
|  media: boxes fmp4 tables tx3g mux |  |  files  ffmpeg               |
|  translate: protocol data, batches |  |  providers: claude openai    |
|                                    |  |   openrouter gemini          |
+------------------------------------+  +------------------------------+
```

**Dependency rules** (enforced by `tests/test_architecture.py` via `ast`): interfaces → services → core/adapters;
adapters may import core; `core` never imports services/adapters/compat/mcp nor `urllib`, `http`, `socket`, `ssl`,
`subprocess`, `threading`, `concurrent`, `asyncio` (time is passed in; reading its own package data is allowed).
`import utmax` loads zero third-party modules (subprocess test on `sys.modules`).

### Package layout

```
pyproject.toml  README.md  LICENSE  CHANGELOG.md  CONTRIBUTING.md  CLAUDE.md  .gitignore  .gitattributes
.github/workflows/  ci.yml  live.yml  release.yml
docs/design/        this spec + one implementation plan per milestone
scripts/            record_fixtures.py (record+trim+REDACT)  make_media_fixtures.py  compat_manifest.py
src/utmax/
  __init__.py  _version.py  py.typed      facade bound to a lazily created default Client; NullHandler
  client.py                               Client: immutable config + one Transport; delegates to services
  models.py  errors.py                    frozen dataclasses (§4.3) · hierarchy (§6)
  transport.py  providers.py              public Transport protocol · public translator classes
  core/                                   PURE
    ids.py clients.py player.py playability.py captions.py selection.py formats.py segmentation.py
    bilingual.py streams.py browse.py retry.py downloads.py filenames.py languages.py
    media/      boxes.py fmp4.py progressive.py tables.py tx3g.py mux.py
    translate/  spec.py protocol.py batching.py
                data/  protocol.json system_prompt.txt request.schema.json response.schema.json  (language-neutral)
  services/     transcripts.py translation.py download.py collections.py
  adapters/     http.py innertube.py watch_page.py downloader.py files.py ffmpeg.py
                providers/  base.py claude.py openai.py openrouter.py gemini.py
  compat/       __init__.py _api.py _transcripts.py _errors.py _settings.py formatters.py proxies.py _bridge.py
  mcp/          __init__.py __main__.py config.py server.py
tests/  conftest.py  helpers/ (fake_transport, fmp4_factory, hollow_source)  fixtures/{youtube,media,translate,compat}
        unit/{core,media,services,adapters}  compat/  mcp/  live/  test_architecture.py
```

**pyproject**: `hatchling>=1.32`; `requires-python=">=3.11"`; `license="MIT"`; `dependencies=[]`; extras
`claude=anthropic>=1.8,<2` · `openai=openai>=3.19,<4` · `gemini=google-genai>=2.25,<3` · `openrouter=openai>=3.19,<4`
· `ai` (all three SDKs) · `mcp=mcp>=2.2,<3 anyio>=4.11,<5`; script `utmax-mcp="utmax.mcp:main"`; PEP 735 `dev` group (pytest,
pytest-cov, ruff, mypy); pytest `-m 'not live'`, markers `live`, `ffmpeg`; mypy strict; coverage branch, fail_under 90.

## 4. Public API

### 4.1 Facade (`import utmax`; same methods on `utmax.Client`)

```python
FormatName = Literal["txt", "srt", "vtt", "json", "pretty"]
Container  = Literal["mp4", "mov", "m4a", "mp3"]

fetch(video, languages=None, *, include_manual=True, include_generated=True,
      preserve_formatting=False, youtube_translation: str | None = None) -> Transcript
list_tracks(video) -> TrackList
video_info(video) -> VideoInfo
translator(model: str, **options) -> Translator                      # "provider=model-id"
translate(transcript, to, *, model: str | Translator, instructions=None, resegment=None, **options) -> Transcript
bilingual(original, translation, *, translation_first=False) -> Transcript
download(video, path, *, format: Container | None = None, quality: Literal["compat", "max"] = "compat",
         subtitles: Sequence[str | Transcript] | None = None,          # None = spoken-language track; [] = none
         subtitle_mode: Literal["embed", "sidecar", "both"] = "embed", default_subtitle=None,
         connections=4, chunk_size=8 * 2**20, resume=True, overwrite=False, ffmpeg=None,
         progress: Callable[[Progress], None] | None = None, cancel: threading.Event | None = None) -> DownloadResult
list_videos(source, *, kind: Literal["all", "videos", "shorts", "live"] | None = None,  # None: a channel
            limit=None) -> VideoList                                    # link's tab (/videos /shorts /streams), else all
fetch_many(videos: Iterable[str | VideoEntry], *, out_dir=None, format: FormatName = "srt", languages=None,
           include_manual=True, include_generated=True, concurrency=4, skip_existing=True,
           filename="{video_id}.{language_code}.{ext}", progress=None) -> BulkReport[Transcript]
translate_many(videos, to, *, model: str | Translator, out_dir=None, format: FormatName = "srt", languages=None,
               bilingual=False, instructions=None, resegment=None, concurrency=2, skip_existing=True,
               filename="{video_id}.{language_code}.{ext}", progress=None,
               **options) -> BulkReport[Transcript]                   # files named by target (or src+dst) language
download_many(videos, out_dir, *, format: Container = "mp4", quality="compat", subtitles: Sequence[str] | None = None,
              subtitle_mode="embed", concurrency=2, skip_existing=True, filename="{title} [{video_id}].{ext}",
              ffmpeg=None, progress=None) -> BulkReport[DownloadResult]
# out_dir=None → results in memory only; progress callbacks receive one BulkResult per finished item, and an
# exception they raise stops the run like Ctrl-C

Client(*, proxy=None, timeout=30.0, retries=2, block_retries=0, force_ipv4=False, transport=None)  # thread-safe; close()/with
```

### 4.2 Usage

```python
import utmax
t = utmax.fetch("https://youtu.be/dQw4w9WgXcQ")          # spoken language, manual before auto
t.save("rick.srt"); t.save("rick.txt", format="pretty")
tr = utmax.translate(t, "tr", model="claude=claude-opus-5")
tr = utmax.translate(t, "tr", model="openai=llama3.1:8b", base_url="http://localhost:11434/v1")  # Ollama, free
utmax.bilingual(t, tr).save("rick.en+tr.vtt")            # every format works for translations
utmax.download("dQw4w9WgXcQ", "rick.mp4")                # H.264 ≤1080p + AAC + embedded English track
utmax.download("dQw4w9WgXcQ", "rick.mov", subtitles=[t, tr], subtitle_mode="both")
utmax.download("dQw4w9WgXcQ", "rick.m4a"); utmax.download("dQw4w9WgXcQ", "rick.mp3")  # mp3 needs ffmpeg
vids = utmax.list_videos("https://www.youtube.com/@RickAstleyYT", kind="videos", limit=100)
report = utmax.fetch_many(vids, out_dir="subs"); print(len(report.ok), len(report.failed))
from utmax.compat import YouTubeTranscriptApi           # one-line migration
```

### 4.3 Models (all `@dataclass(frozen=True, slots=True)`)

- `Word(text, start)` · `Segment(start, duration, text, words=())` (+`end`) · `Language(code, name)`
- `VideoInfo(video_id, title, channel, channel_id, duration, is_live_content)` (+`url`)
- `Track(video_id, language_code, language, is_generated, is_translatable, vss_id)` with private `_url`/`_client`;
  `fetch()`, `translate(code)` (YouTube tlang). `TrackList(Sequence[Track])`: `video`, `translation_languages`
  (may be empty), `find(languages, include_manual, include_generated)`, `manual`, `generated`.
- `Transcript(Sequence[Segment])`: `video, language_code, language, is_generated, segments, translated_from,
  translator, source` (1:1 source cues of an AI translation; not compared); `text`, `to(format)`, `to_srt/…`,
  `to_dicts()`, `save(path, format=None) -> Path`, `merge_sentences()`, `is_bilingual` (`"+"` in code).
- `Format(itag, kind: video|audio, container: mp4|webm, codec: h264|av1|vp9|aac|he-aac|opus, codecs, width,
  height, fps, bitrate, content_length, audio_sample_rate, audio_channels, is_default_audio, is_drc)` ·
  `Progress(video_id, phase, bytes_done, bytes_total, speed_bps, eta_seconds)` ·
  `DownloadResult(path, video, container, video_format, audio_format, embedded_subtitles, sidecars, size_bytes, resumed)`
- `VideoEntry(video_id, title, duration, channel, channel_id, index)` (+`url`; `duration` is `None` when YouTube
  shows none; `index` is the 1-based position in the list) · `VideoList(Sequence[VideoEntry])`: `title, source_id,
  kind, video_count, entries` (`video_count` is YouTube's own count; `count()` is the `Sequence` method) ·
  `BulkResult[T](video_id, status: ok|skipped|failed|not_attempted, value, path, error)` ·
  `BulkReport[T](Sequence[BulkResult[T]])` (`ok`, `skipped`, `failed`, `not_attempted`, `raise_for_errors()`)

### 4.4 Translators (`utmax.providers`)

`Translator` ABC (engine options `batch_chars=4000, batch_items=50, context_items=3, concurrency=4,
max_attempts=2`; subclasses implement `name` + `generate_json(system, prompt, schema) -> str`):
`ClaudeTranslator(model, *, api_key, effort, max_tokens=16000, client)` · `OpenAITranslator(model, *, api_key,
base_url, json_mode="auto", client)` · `OpenRouterTranslator(model, *, api_key, app_name, client)` ·
`GeminiTranslator(model, *, api_key, retry_attempts=5, client)`. Spec = `claude|openai|gemini|openrouter` `=`
model-id (first `=` only) else `InvalidModelSpec`; `base_url` with non-`openai` → `InvalidOption`.

### 4.5 File format by extension

- `Transcript.save`: `.srt .vtt .json .txt` (`format=` always wins, e.g. `pretty`); unknown → `UnsupportedFormat`;
  UTF-8, `newline="\n"`, atomic write; identical for originals, translations and bilingual transcripts.
- `download` targets:

| Target | Result |
|---|---|
| `.mp4` | best H.264 ≤1080p (`max`: AV1/H.264 ≤2160p, 8-bit) + AAC; tx3g tracks when mode includes embed |
| `.mov` | same H.264 + AAC, QuickTime flavor; `quality="max"` → `InvalidOption` |
| `.m4a` | AAC (itag 140 preferred) remuxed to non-fragmented M4A; subtitles only as sidecars |
| `.mp3` | AAC → ffmpeg `libmp3lame -q:a 2`; `FFmpegNotFound` with install hint |
| directory / trailing separator | `format` (default mp4) + `"{title} [{video_id}].{ext}"` (sanitized) |

  String subtitles are resolved with `select_track` (never tlang) **before** any media bytes → fail fast with
  `NoTranscriptFound`; with `subtitles=None` and no captions the video downloads without subtitles (INFO log).
  For `.m4a`/`.mp3`, `subtitles=None` means none and explicit subtitles are always written as sidecars.
  `default_subtitle` = language code (e.g. `"tr"`, `"en+tr"`) of the embedded track enabled by default; `None` = first.
  Sidecars: `{stem}.{lang}.srt` / `{stem}.{src}+{dst}.srt`. Existing target → `OutputExists` unless `overwrite`.

### 4.6 `utmax.compat` (drop-in for youtube-transcript-api 1.2.4)

- Mirrors module paths (`utmax.compat`, `.formatters`, `.proxies`, `._errors`, `._transcripts`, `._api`,
  `._settings`), exact names, constructor signatures, attributes, `__str__` formats and exception hierarchy:
  `YouTubeTranscriptApi(proxy_config=None, http_client=None)` with `fetch(video_id, languages=("en",),
  preserve_formatting=False)` / `list(video_id)`; `TranscriptList.find_transcript / find_manually_created_transcript
  / find_generated_transcript`; `Transcript.fetch / translate / is_translatable`; `FetchedTranscript` (+`snippets`,
  `to_raw_data()`); formatters `JSON/Text/SRT/WebVTT/PrettyPrint` + `FormatterLoader`; proxies `GenericProxyConfig`,
  `WebshareProxyConfig`; all 19 exceptions + 0.6 aliases `TooManyRequests`, `NoTranscriptAvailable`, `CookiesInvalid`.
- Legacy classmethods `get_transcript`, `get_transcripts`, `list_transcripts` with 0.6.3's signatures
  (1.1.1's `DeprecationWarning` texts, `stacklevel=2`; dict output; `proxies` a `ProxyConfig` or requests-style
  dict; `cookies` accepted and ignored with a `UserWarning`).
- Messages: every exception message and class attribute is 1.2.4's word for word, its GitHub, README and Webshare
  links included (user's choice, 2026-10-08); `utmax/compat/__init__.py` carries upstream's MIT notice.
- Fidelity: default `("en",)`, exact-code matching, last-duplicate-wins, legacy XML captions (utmax's keyless
  captions clients, ANDROID first, so `translation_languages` are populated; `fetch_captions(..., fmt=None)`),
  upstream's parser regexes and timestamp rounding, `exp=xpe` → `PoTokenRequired`. Supersets: URLs accepted,
  thread-safe, formatters accept 0.6 `list[dict]`, snippets also read like 0.6's dicts (`snippet["text"]`, `get`,
  `keys`, `items`, `dict(snippet)`). Input that cannot be a video ID → `VideoUnavailable` without a request (a URL
  without a video → `InvalidVideoId`). Errors are upstream's classes with the utmax error as `__cause__`.
- Transports: `http_client` = any `requests.Session`-like object (enables SOCKS/HTTPS proxies and custom certs
  without us depending on requests); the constructor sets its `Accept-Language`, `proxies` and `Connection: close`
  as upstream does. Without one, utmax's urllib stack takes the configuration's `https` (else `http`) proxy, which
  must be `http://` (else `InvalidProxyConfig` naming `http_client`); `retries_when_blocked` → `block_retries` (per
  client profile).
- `utmax.compat.install()` (opt-in): registers the compat modules as `youtube_transcript_api.*` in `sys.modules`
  so libraries importing it (LangChain loaders…) run on utmax; call it before they import it (it also replaces a
  real installation for imports that follow).
- Parity: `scripts/compat_manifest.py` records 1.2.4's surface from the wheel into
  `tests/fixtures/compat/youtube_transcript_api-1.2.4.json`; a test compares `utmax.compat` with it.

### 4.7 MCP tools (`utmax-mcp`, stdio, `MCPServer`)

| Tool | Arguments | Returns (structured) |
|---|---|---|
| `list_tracks` | `video` | video (id, title, channel, channel_id, duration_seconds, url) + tracks (code, name, is_generated, is_translatable) |
| `get_transcript` | `video, languages=None, format="txt", source="any", offset=0, max_chars=None` | video_id, title, language_code, language, is_generated, format, content, total_chars, offset, next_offset |
| `list_videos` | `source, kind=None (the link's tab, else all), limit=50 (1..5000)` | title, source_id, kind, count, videos[] |
| `download` | `video, format="mp4", quality="compat", subtitles=None, subtitle_mode="embed"` | path, size_bytes, video_id, title, container, embedded_subtitles, sidecars, skipped |

The server calls no AI provider and needs no API key (user's decision, 2026-10-08): its instructions tell the
assistant to translate the text lines of an srt or vtt transcript itself; AI translation with keys stays in the
library. Long transcripts are read in parts: `max_chars` cuts after the last line or word end in the window and
`next_offset` (null at the end) continues; the last eight transcripts are kept, so a part costs no request.
Env: `UTMAX_DOWNLOAD_DIR` (default `~/Downloads/utmax`; `~` and variables expanded, made absolute), `UTMAX_PROXY`,
`UTMAX_FFMPEG` (read by utmax). The model never chooses paths: utmax names the file `"{title} [{id}].{ext}"` (or
`"{id}.{ext}"`), an existing one returns `skipped=true` without a request, and a subtitle file an earlier download
left is replaced. `download` runs in a worker thread with one progress bar per call (the download fills the first
half, muxing the second, an MP3 conversion waits at half); cancelling the call stops the download, which resumes on
the next call. `UTMaxError` and `OSError` → `ToolError("<message> Suggestion: <suggestion>")`; tool descriptions are
cleaned of docstring indentation; nothing but the SDK writes to stdout; `utmax-mcp` switches stderr to UTF-8 and logs
at INFO there, and without the SDK it exits with the install command.

## 5. Key rules

**Identifiers**: bare 11-char id, watch (`v` anywhere), youtu.be, shorts, live, embed, `/v/`, m./music./www.,
nocookie, scheme-less → else `InvalidVideoId` before any request. `parse_source`: `list=` / bare `PL|UU|OLAK5uy_|FL`
→ playlist; `@h`, `/channel/UC…`, bare `UC`+22, `/c/`, `/user/` → channel (a `/videos`, `/shorts` or `/streams`
tab becomes the default `kind`); `RD…` → `CollectionUnavailable` (Mixes, and YouTube Music's `RDCLAK5uy_…`
playlists, which are not supported yet); a single video → `InvalidSource` pointing to `fetch()`/`download()`.

**InnerTube** (`core/clients.py`, one constant; all add `hl=en`, `gl=US`): ANDROID `20.10.38` (UA
`com.google.android.youtube/20.10.38 (Linux; U; Android 11) gzip`), IOS `20.10.4`, ANDROID_VR `1.62.27` (Oculus
Quest 3), WEB `2.20260925.01.00`. `POST /youtubei/v1/{player|browse|navigation/resolve_url}?prettyPrint=false`, no
key, headers UA + `X-YouTube-Client-Name/Version` + `Accept-Language: en-US` + gzip. Fallback orders:
`captions: ANDROID→IOS→ANDROID_VR`, `streams: ANDROID_VR→ANDROID→IOS`, `browse/resolve: ANDROID_VR→WEB`. Next
profile on 4xx≠429, non-JSON, UNPLAYABLE, or no direct-URL MP4 formats (streams); final on 429 (`IpBlocked`),
"unavailable" (`VideoUnavailable`), age gate (`AgeRestricted`). All profiles fail at HTTP level → watch-page fallback
once (per-call consent cookie, `INNERTUBE_API_KEY`, reCAPTCHA → `IpBlocked`). A download reuses its player response
for captions and `VideoInfo`.

**Playability** (case-insensitive substring): LOGIN_REQUIRED + "not a bot" → `RequestBlocked`; + "confirm your age" /
"inappropriate" → `AgeRestricted`; other LOGIN_REQUIRED → `VideoUnplayable` (private/members-only, auth
unsupported); ERROR + "unavailable" → `VideoUnavailable`; else `VideoUnplayable(reason, sub_reasons)`.

**Captions & selection** (from the old spec's domain rules): host allowlist `*.youtube.com`; `exp=xpe` →
`PoTokenRequired`; `fmt=json3`, skip whitespace-only events, word time `tStartMs+tOffsetMs`, `html.unescape`, asr
newlines → spaces; XML fallback (reject DOCTYPE/ENTITY; srv3 then legacy). Selection: per requested language, manual
exact code → manual same base language → auto exact code → auto same base language; no languages → spoken language
(the original audio's language when YouTube marks it — videos with dubbed audio name it "<language> original" and tag
its streams `acont=original`, and list an asr track per dub — else the first asr track) manual→auto, then first
manual, then first auto; `NoTranscriptFound` lists available tracks. **Never tlang implicitly**; explicit tlang is
best-effort (429 → `IpBlocked` "use AI translation or a proxy").

**Formats & segmentation**: SRT/VTT overlap clamp, zero-length cues dropped, VTT escaping, JSON `ensure_ascii=False`,
pretty `[MM:SS]` → `[HH:MM:SS]` past 1 h; bilingual keeps line breaks. `merge_sentences`: word units when timed;
close cue on `. ! ? … 。 ！ ？` (+closing quotes), gap ≥1.0 s, ≥7.0 s, ≥100 chars; `[…]` stands alone; thresholds in
`protocol.json`.

**Translation engine**: resegment auto tracks by default → items `{id,text}` → batches ≤4000 chars/50 items →
3 source context lines each side (never translated ones, so batches run in parallel, pool of 4) → strict JSON schema
→ validate (exact id set, non-empty) → retry ×2 → split in half recursively → `TranslationMismatch`; never silent
partial output. Result keeps source timings, `language_code=to`, `language` = English name when known (else `to`),
`is_generated=True`, `translated_from`, `translator` (e.g. `"claude=claude-opus-5"`), `source`.
Provider errors are mapped, never retried by the engine (SDKs retry).

| Provider | Call | Refusal / truncation |
|---|---|---|
| Claude | `messages.create(model, max_tokens=16000, system, messages, output_config={"format":{"type":"json_schema","schema":S}[,"effort"]})` | `stop_reason` `refusal` (checked first) / `max_tokens` → invalid |
| OpenAI (+compatible) | `chat.completions.create(..., response_format=json_schema strict)`; `auto` falls back to `json_object` → `prompt` on 400, remembered | `message.refusal` / `finish_reason=="length"` |
| OpenRouter | OpenAI path, `base_url=https://openrouter.ai/api/v1`, `extra_body={"provider":{"require_parameters":True}}` | same |
| Gemini | `models.generate_content(config=GenerateContentConfig(system_instruction, response_mime_type="application/json", response_json_schema=S))`, we set `HttpRetryOptions(attempts=5)` | SAFETY/block reasons / `MAX_TOKENS` |

Missing SDK → `ProviderNotInstalled` with `pip install "u-transcript-max[<extra>]"`; keys never logged or in `repr`.

**Bilingual**: zip 1:1 with `translation.source` when present, else align by segment midpoints; text
`orig + "\n" + trans`; code `"en+tr"`, name `"English + Turkish"`.

**Stream selection**: exclude ciphered, DRM, WebM/VP9/Opus, HDR/10-bit, itag 18. `compat`: MP4 `avc1` ≤1080p by
(height, fps, bitrate). `max`: MP4 `avc1` or 8-bit `av01` ≤2160p, AV1 preferred at equal height. Audio: MP4 AAC,
default track, non-DRC, highest bitrate (140 > 139). None eligible → `FormatNotAvailable(reason, available)`.

**Downloader**: size from `content_length` or first 206 `Content-Range`; 8 MiB chunks in an ascending FIFO shared by
video+audio, 4 connections, single GET under 2 chunks; `<target>.<itag>.part` + `.part.json` state
(`video_id, itag, content_length, last_modified, chunk_size, completed[]`, atomic, throttled). Workers use own `r+b`
handles, 256 KiB reads, short-read retry. Resume: fresh player response, match by itag + size + lmt, else restart.
403/expiry: single-flight URL refresh (proactive when <300 s left), max 3 → `StreamForbidden` (IP-bound URLs,
`force_ipv4`, no rotating proxies), or `PoTokenRequired` when the stream's first byte still comes (without a
proof-of-origin token YouTube serves only the first ~1 MiB of some videos' ANDROID/IOS streams; seen 2026-10-08 when
ANDROID_VR asked for a bot check). 416 → re-plan once → `DownloadIncomplete`. Cancel via Event/KeyboardInterrupt →
state flushed, `DownloadCancelled`, resumable. Progress aggregated, serialized, ≤4/s. Output `.tmp` → fsync →
`os.replace` with Windows retries; parts deleted only after a successful mux (~2× disk peak, documented).
Filenames: Windows reserved names, `<>:"/\|?*`, control chars, trailing dots/spaces, 150-char titles.

**Muxer** (pure; reads via `ByteSource.read(offset, n)`, outputs `MuxPlan(ops=[CopyOp|Blob])` streamed by
`adapters/files.py`): index each fMP4 input (every `tfhd`/`trun` flag, `tfdt` v0/v1, default chain
trun→tfhd→trex, samples inside `mdat`) → build tx3g tracks → chunks ≤1 s (subtitles ~10 s) interleaved by time →
tables `stts/ctts(v1 if negative)/stss/stsz/stsc/stco|co64` → keep source timescales, movie timescale 1000, convert
`elst` → faststart `ftyp|moov|mdat` (64-bit mdat header when needed), deterministic output.

| | mp4 | mov | m4a |
|---|---|---|---|
| ftyp | `isom` · `isom iso2 avc1/av01 mp41` | `qt  ` | `M4A ` · `M4A isom iso2 mp41` |
| Audio entry | source `mp4a+esds` | SoundDescription v1 + `wave(frma, mp4a, esds)` | source |
| hdlr / language | C-string · ISO 639-2/T | Pascal + `minf` dhlr · Mac code if mapped | C-string · ISO |

**tx3g**: normalized cues (sorted, overlaps clamped, ms timescale), empty samples for gaps and after the
last cue until the media ends (FFmpeg < 7 stretches a track's last sample to the end of the file), sample =
`u16 length + UTF-8` (`"\n"` line breaks), ffmpeg `mov_text` default sample entry (size 18, white, `ftab`
Sans-Serif), handler `sbtl`, `nmhd`, `elng` with the BCP-47 tag, `alternate_group=3`, exactly one enabled track
(`default_subtitle` else first), track names like "Turkish (AI: claude=…)" / "English + Turkish".

**ffmpeg (mp3 only)**: locate `ffmpeg=` → `UTMAX_FFMPEG` → `shutil.which`; probe `-version` + `libmp3lame` once;
run `ffmpeg -hide_banner -nostdin -loglevel error -y -i <audio.part> -map 0:a:0 -vn -c:a libmp3lame -q:a 2
-map_metadata -1 <out.mp3.tmp>` (stdin DEVNULL, `CREATE_NO_WINDOW` on Windows, cancel → terminate) →
`FFmpegFailed(returncode, stderr_tail)` / `FFmpegNotFound` ("winget install Gyan.FFmpeg | brew install ffmpeg |
apt install ffmpeg, or pass ffmpeg=…").

**Collections**: resolve channel (skip for `UC…`; ANDROID_VR, then WEB) → uploads-playlist id by `kind` (default:
the link's tab, else all; playlists take only `"all"`) → browse loop ANDROID_VR (WEB lists the whole playlist again
when ANDROID_VR fails), parser accepts `playlistVideoRenderer`, `lockupViewModel`,
`richItemRenderer`/`shortsLockupViewModel` and all three continuation shapes; stop on limit, repeated token, 1000
pages or empty page; dedupe ids; a listing that ends short of YouTube's count (WEB shows at most 100 Shorts) is
returned with a WARNING. 400/404 → `CollectionNotFound`; alert-only → `CollectionNotFound` when it says "does not
exist", else `CollectionUnavailable(reason)`; a channel's missing videos/Shorts/live list → an empty `VideoList`
when its `UU` list exists. Bulk helpers: shared `Client`, `ThreadPoolExecutor(concurrency)`, one `BulkResult` per
input in input order; skip-existing via filename-template glob (no request): templates must contain `{video_id}`
as it is, title, channel and `{index}` match anything, the language matches the requested base languages (or
anything without `languages`), and parts, state and temporary files never count; per-item errors captured,
**circuit breaker** after `RequestBlocked`/`IpBlocked` (+`ProviderAuthError` for `translate_many`; remaining →
`not_attempted`), Ctrl-C or a progress exception cancels pending items and running downloads, then re-raises.

## 6. Errors (`utmax.errors`; every class has `.suggestion` and `.video_id`, is raised somewhere and tested)

```
UTMaxError
├── InvalidVideoId  InvalidSource  InvalidModelSpec  InvalidOption  UnsupportedFormat   (all ValueError)
├── MissingExtra(ImportError)
├── NetworkError
├── YouTubeError
│   ├── VideoUnavailable  VideoUnplayable(reason, sub_reasons)  AgeRestricted
│   ├── RequestBlocked ── IpBlocked
│   ├── PoTokenRequired  FailedToCreateConsentCookie  YouTubeRequestFailed(status_code)  YouTubeDataUnparsable
│   ├── TranscriptsDisabled  NoTranscriptFound(requested, available)  NotTranslatable
│   ├── TranslationLanguageNotAvailable(available)
│   └── CollectionNotFound(source)  CollectionUnavailable(source, reason)
├── DownloadError
│   ├── FormatNotAvailable  StreamForbidden(itag)  DownloadIncomplete  DownloadCancelled  OutputExists  MuxError
│   └── FFmpegError ── FFmpegNotFound  FFmpegFailed(returncode, stderr_tail)
└── TranslationError(provider)
    ├── ProviderNotInstalled(MissingExtra)  ProviderAuthError  ProviderRateLimited  ProviderError(status_code)
    └── TranslationRefused  TranslationMismatch(ids, raw_excerpt)
```
Compat maps same-named errors 1:1 (upstream constructors); `NetworkError` → `YouTubeRequestFailed` (documented).

## 7. Networking & logging

- `UrllibTransport`: one opener per `Client`, shared `ssl` context, gzip for JSON, identity for media, fresh
  connection per request (rotates rotating proxies naturally). `RetryingTransport` uses pure `core.retry`.
- Transient (retried `1 + retries`, `min(8, 0.5·2ⁿ)+jitter`, `Retry-After` ≤30 s): resets (incl. WinError 10054),
  timeouts, `RemoteDisconnected`, `IncompleteRead`, temporary DNS, 408/5xx. TLS verification errors are not retried.
  429 → `IpBlocked` at once unless `block_retries>0` (new connection each try; also `RequestBlocked`).
- Proxies: `http://user:pass@host:port` for both schemes (CONNECT); env proxies honored; `https://`/`socks*` URLs →
  `InvalidOption` (use a custom `Transport` / compat `http_client`). Downloads need a sticky IP (IP-bound URLs).
- `force_ipv4=True` → AF_INET-only connections (avoids v4/v6 mismatch 403s). `Client` is thread-safe (immutable
  config; per-call state local; tested with 8 threads).
- Logging: `logging.getLogger("utmax")` (+`.http .youtube .download .translate .bulk .mcp`), `NullHandler`; stream/caption
  query strings, keys and proxy credentials redacted; **the library never prints**; `utmax-mcp` only reconfigures
  stderr to UTF-8.

## 8. Testing (offline by default; coverage ≥ 90 % with branches)

1. Pure core: table-driven tests for every rule (ids, playability rows, json3/XML, selection flags, formats,
   segmentation, bilingual, streams, browse shapes, retry/backoff with seeded RNG, filenames, chunk/resume math, spec parser).
2. Recorded fixtures via `scripts/record_fixtures.py`: trimmed real responses (player ×3, json3 manual/asr, legacy XML,
   browse pages + continuations of both clients, a WEB Shorts page, resolve of a handle and of an unknown handle)
   with `ip/ei/sig/lsig/signature/key/expire` **redacted**; synthetic fixtures labeled (age gate, bot check, private,
   consent HTML, reCAPTCHA, playlist 400/404, WEB resolve 404, mix and missing-list alerts).
3. Media: "hollow" real streams (real `ftyp/moov/sidx/moof` of itags 137/140/399 + mdat sizes, zero payloads, a few
   KB) and `fmp4_factory` synthetic fragments for every flag path. Muxer invariants re-parsed with
   `progressive.py`: box layout, per-track sample counts/durations/cto/sync, **per-sample payload hashes**, chunk
   bounds, `co64`/64-bit mdat exactly when needed (virtual 5 GB source), `elst`, languages, MOV specifics, tx3g round-trip.
4. `@pytest.mark.ffmpeg` (CI Ubuntu): lavfi-generated DASH fragments → utmax mux → `ffprobe` streams/packets,
   `ffmpeg -v error -f null` decode clean, subtitle extraction round-trips; mp4, mov, m4a.
5. Fake transport (scripted responses/exceptions): retries, Retry-After, 429, block_retries, client fallback orders,
   watch-page + consent, browse pagination, 403 refresh, 416, short reads, cancel, resume, circuit breaker.
   Local `ThreadingHTTPServer` for real sockets: gzip, Range/206, tiny forward proxy, timeouts, `force_ipv4`.
6. Providers with fake SDK clients via `client=` (exact kwargs, refusal/truncation, json_mode fallback, real SDK
   exception classes mapped). Engine with a deterministic fake translator (retry → split → mismatch, order, context, `source`).
7. Compat: `scripts/compat_manifest.py` AST-extracts upstream 1.2.4 surface → manifest parity test via `inspect`;
   ported upstream behavior tests (byte-exact formatters, legacy classmethods, `__str__`); `install()` test.
8. MCP: in-memory `mcp.Client(build_server(client, config), raise_exceptions=True)` under `anyio.run` — schemas,
   outputs, paging, `ToolError`s, env vars, path confinement, progress, cancellation, no stdout writes; one stdio
   round trip through `python -m utmax.mcp`; the SDK's tests are not collected without the extra.
9. Architecture test (core purity; adapters and services never import compat or mcp) + zero third-party imports on
   `import utmax`, `import utmax.compat` and `import utmax.mcp`.
10. Live (`@pytest.mark.live`, nightly `live.yml`): manual English 2nd segment `♪ We're no strangers to love ♪`,
    `["tr","en"]` → manual en without tlang, `["de"]` → `de-DE`, 6 tracks, `merge_sentences` monotonic, playlist
    count = header, `@RickAstleyYT` → `UCuAXFkgsw1L7xaCfnd5JJOw`, m4a download, small mp4 (160+140) + ffprobe;
    AI only with secrets; cloud-IP `RequestBlocked` reported as skipped, not failed.

## 9. Milestones (one spec; a separate implementation plan per milestone via writing-plans)

| # | Milestone | Deliverables | Acceptance |
|---|---|---|---|
| M1 | Foundation & transcripts | Scaffold (pyproject, layout, errors/models, architecture test, `ci.yml`, LICENSE, `.gitattributes`, `.gitignore`, CLAUDE.md, README stub); core transcript modules; fixture recorder; `UrllibTransport` + retry; InnerTube adapter + watch-page fallback; transcripts service; `Client` + facade `fetch/list_tracks/video_info/save`; tlang | All gates green on Linux/Windows; core coverage ≥95 %; 8-thread test; live transcript checks pass; wheel contains only `utmax/` |
| M2 | AI translation & bilingual | Protocol data files, batching, spec parser, engine, 4 providers, `translate/translator/bilingual` | Offline retry → split → mismatch; order under concurrency; `translator("openai=llama3.1:8b")`; bad specs raise; manual smoke test with the user's keys before release |
| M3 | Media muxer | boxes, fmp4, progressive, tables, tx3g, languages, mux (mp4/mov/m4a), plan executor, hollow + synthetic fixtures, ffmpeg CI job | All invariants; ffprobe decode clean; tx3g round-trip; co64 path; manual player matrix (VLC, mpv, QuickTime/IINA, Films & TV, Chrome) recorded |
| M4 | Downloads | streams selection, `ParallelDownloader`, download service (m4a remux, mp4/mov + subtitles embed/sidecar, mp3 via ffmpeg), `download()` | Resume after simulated crash; 403 refresh; cancel → resumable; `FFmpegNotFound`; Windows rename retry; live m4a + mp4 |
| M5 | Collections | `parse_source`, resolve, browse parsers (VR + WEB), `list_videos`, `fetch_many/translate_many/download_many` | Both continuation styles; skip-existing; circuit breaker; live playlist + channel kinds |
| M6 | Compat | manifest script, full `utmax.compat`, session transport, error bridge, `install()` | 100 % manifest parity; ported upstream tests pass |
| M7 | MCP server | config, 4 tools (no AI provider), paging, progress, entry points | In-memory and stdio tests; manual run in Claude Code/Desktop with a config snippet |
| M8 | Docs & release 0.1.0 | Minimal README (ASCII diagram, install/extras, quickstart, features, MCP setup, compat one-liner, legal/ToS note), CHANGELOG, CONTRIBUTING, `live.yml`, `release.yml` (approval-gated Trusted Publishing) | All gates green; `uv build` + `twine check`; release job waits for approval; publish only when the user says so |

## 10. Risks

| Risk | Mitigation |
|---|---|
| YouTube changes clients / adds PoToken to ANDROID/VR/IOS | One constant, per-purpose fallback chains, watch-page fallback, typed `PoTokenRequired`, nightly live alarms |
| WEB browse shape churn | ANDROID_VR classic renderers first; WEB parser accepts old + new shapes; fixtures for both |
| Muxer correctness / player compatibility (MOV least verified) | Spec-complete fMP4 parsing, verbatim sample entries, ffmpeg-parity conventions, invariant + ffprobe tests, manual player matrix |
| URL expiry, IP binding, v4/v6 mismatch | itag refresh with size/lmt check, proactive refresh, `force_ipv4`, `StreamForbidden` guidance |
| IP blocking (incl. cloud CI) | `block_retries`, bulk circuit breaker, conservative concurrency, neutral live CI + optional proxy secret |
| Provider / MCP SDK drift | Version-ranged extras, lowest-direct CI job, thin adapters, contract tests with fakes; MCP isolated in `utmax.mcp` |
| OpenAI-compatible servers without json_schema | auto fallback json_object → prompt, remembered per instance |
| Prompt injection via captions | Protocol rules, schema output, id validation, output used only as subtitle text |
| Legal / ToS | README disclaimer (personal use, content you have rights to, YouTube ToS); DRM formats excluded; extension subtitle-only |

**Deferred (not in 0.1.0)**: Chrome extension (next sub-project), async API, AI summary/chapters, metadata/cover art,
YouTube chapters, hardsub, cookies/auth (age-restricted, members-only), SOCKS/HTTPS proxies (via custom transport
only), 10-bit/HDR AV1, VP9/WebM sources, REST API, CLI.

## 11. Verification (end-to-end)

- Gates per milestone: `uv run ruff check .` · `uv run ruff format --check .` · `uv run mypy --strict src` ·
  `uv run pytest` (coverage ≥ 90 %) on Linux + Windows CI; `uv run pytest -m ffmpeg` where ffprobe exists.
- Live: `uv run pytest -m live` (transcripts, tracks, playlist/channel, m4a, small mp4 + ffprobe).
- Manual before 0.1.0: translate with the user's keys (Claude, OpenAI/Ollama, Gemini, OpenRouter) and save all
  formats + bilingual; download `.mp4` (default, embedded English track toggles in VLC/QuickTime), `.mov`,
  `.m4a`, `.mp3` (ffmpeg); `quality="max"` 4K AV1; interrupt and resume a download; `fetch_many` on a small
  playlist; a youtube-transcript-api script switched by one import; `utmax.compat.install()` with a LangChain-style
  import; `utmax-mcp` registered in Claude Code, all 4 tools called; Windows cp1254 console shows no crash.
- Packaging: `uv build` + `twine check`; `pip install dist/*.whl` in a clean venv → `import utmax` pulls no
  third-party modules.

## 12. After approval

1. Update memory: replace the stale v4 memory with the u-transcript max decisions (old v4 plan and ledger are obsolete).
2. Commit this spec to `docs/design/2026-09-27-u-transcript-max-design.md` on branch `v4` (the old
   v4 spec deletion goes in the same commit; LICENSE/.gitattributes are recreated in M1).
3. Invoke **writing-plans** for M1 → `docs/design/plans/2026-09-27-m1-foundation-transcripts.md`; the user reviews
   it and picks the execution method (subagent-driven development recommended). Repeat per milestone
   (`docs/design/plans/<date>-m<N>-<name>.md`), each plan written after the previous milestone is complete on `v4`.
4. Never merge to `main` or publish to PyPI without the user's explicit approval.
