# M4 — Downloads Implementation Plan

**Goal:** `utmax.download()` and `Client.download()`: choose YouTube's best MP4 streams for a `.mp4`, `.mov`, `.m4a` or `.mp3` file, download them with parallel, resumable range requests, and assemble the file with the M3 muxer (or ffmpeg for MP3), with subtitles embedded as toggleable tracks and/or written as `.srt` files next to it.

**Architecture:** Pure core modules decide: `core/streams.py` parses and chooses streams, `core/downloads.py` does chunk, resume-state and rate arithmetic, `core/filenames.py` names files and resolves targets. Adapters do the I/O: `adapters/http.py` streams response bodies and can force IPv4, `adapters/downloader.py` runs the parallel resumable download into `.part` files, `adapters/ffmpeg.py` runs ffmpeg for MP3. `services/download.py` orchestrates player request → subtitles → stream choice → download → mux or convert → sidecars, and `Client.download` / `utmax.download` expose it.

**Tech Stack:** Python ≥ 3.11 standard library (`urllib`, `http.client`, `socket`, `threading`, `subprocess`, `json`) · pytest · ruff · mypy (strict) · uv · ffmpeg/ffprobe for the optional MP3 tests.

**Spec:** `docs/design/2026-09-27-u-transcript-max-design.md` — read §2 (verified stream facts), §4.1 (`download` signature), §4.3 (`Format`, `Progress`, `DownloadResult`), §4.5 (download targets), §5 ("InnerTube" stream fallback, "Stream selection", "Downloader", "ffmpeg (mp3 only)"), §6 (errors), §7 (`force_ipv4`, logging), §8 items 5 and 10, §9 row M4 and §10 before starting. Prerequisites: M1, M2 and M3 are merged into `v4` (M3's `plan_mux`, `write_mux_plan`, `FileByteSource` and `parse_progressive` are used as they are).

## Global Constraints

- `requires-python = ">=3.11"`; zero runtime dependencies; `src/utmax` imports only the standard library; M4 adds no runtime or dev dependency and does not touch `pyproject.toml` or `uv.lock` (the `live` and `ffmpeg` markers already exist).
- `utmax.core` stays pure: no network, subprocess, threads, clock or filesystem; `tests/test_architecture.py` bans `asyncio concurrent http.* socket ssl subprocess threading time shutil tempfile urllib.request urllib.error` and the outer layers. Adapters may import core and other adapters, never `utmax.services` or `utmax.client`; services may import adapters and core.
- M4 works on branch `m4-downloads` in the worktree `.worktrees/m4-downloads`, cut from `v4` after M3 was merged. It creates or edits only: `src/utmax/models.py`, `src/utmax/errors.py`, `src/utmax/__init__.py`, `src/utmax/client.py`, `src/utmax/transport.py`, `src/utmax/core/clients.py`, `src/utmax/core/player.py`, `src/utmax/core/streams.py`, `src/utmax/core/downloads.py`, `src/utmax/core/filenames.py`, `src/utmax/adapters/http.py`, `src/utmax/adapters/innertube.py`, `src/utmax/adapters/downloader.py`, `src/utmax/adapters/ffmpeg.py`, `src/utmax/services/transcripts.py`, `src/utmax/services/download.py`, `scripts/record_fixtures.py`, `tests/fixtures/youtube/streams_android_vr.json`, `tests/fixtures/youtube/README.md`, `tests/helpers/youtube.py`, `tests/helpers/http_server.py`, `tests/helpers/fake_media.py`, `tests/helpers/downloads.py`, and new test files under `tests/unit/**` and `tests/live/`. It does not edit `src/utmax/core/media/**`, `src/utmax/core/translate/**`, `src/utmax/adapters/providers/**`, `src/utmax/adapters/files.py`, `.github/workflows/**` (the existing `ffmpeg` CI job runs the new ffmpeg-marked test) or existing test files other than those named in a task.
- Errors: every failure raises a `utmax.errors` class with an English message; class-level suggestions end with a period; `video_id` is set whenever it is known. Download failures are `DownloadError` subclasses; bad arguments are `InvalidOption`, `UnsupportedFormat` or `InvalidVideoId` and are raised before any network request.
- Stream URLs are bound to the requester's IP and carry signatures: they never appear in log lines, error messages, `repr` output or `DownloadResult`. Log through `logging.getLogger("utmax.download")` (HTTP details through `utmax.http`, which already redacts). The library never prints.
- Files: every file utmax produces is written atomically (temporary file next to the target, `fsync`, `replace_with_retry`); `.part` files are deleted only after the output file is complete.
- Non-ASCII characters appear in Python source only as escapes. This plan writes them as `\xXX` or `\U0000XXXX` (eight hex digits) on purpose: some editing tools silently turn four-digit backslash-u escapes into raw characters. Copy the escapes exactly as written.
- Lint lessons from M1–M3, applied below: `itertools.pairwise`, `split(..., maxsplit=1)`, `pytest.raises` with a specific exception and `match=` whose pattern is raw or free of regex metacharacters (write `r"needs \.mp4"`), no unused `noqa`, at most five positional parameters (the rest keyword-only), `filterwarnings = error` (close every file and `FileByteSource`), `docs/` excluded from ruff. After writing a file run `uv run ruff format <file>`: the code below follows ruff's style, but formatter changes are never deviations.
- Gates after every task: `uv run ruff check .` · `uv run ruff format --check .` · `uv run mypy` · `uv run pytest` (branch coverage ≥ 90 %). At the end: `uv run pytest --cov` then `uv run coverage report --include="*/utmax/core/*" --fail-under=95`, and `uv run pytest -m ffmpeg` where ffmpeg exists. Each step gives the exact count of the new test file; the suite total grows by that count (the baseline on `v4` is 863 passed, 11 deselected with all extras and ffmpeg installed). If a count differs, find out why before moving on.
- Commits use a conventional prefix (`feat:`, `test:`, `fix:`), stage explicit paths only (never `git add -A` or `.`) and end with the trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Never push, merge or publish without the user's explicit approval.

## Review Focus

1. **Interrupted and repeated downloads** — a crash, Ctrl-C or `cancel` in the middle of a range, then the same call again, possibly after YouTube re-encoded the stream or with another `chunk_size` → finished ranges are reused only when video, itag, size, last-modified time and chunk size all match; a half-written range is fetched again; a changed stream starts over instead of producing a corrupt file; a damaged `.part.json` is ignored. Pinned in Task 4 (`test_damaged_state_files_are_ignored`, `test_states_match_only_for_the_same_stream_and_chunking`), Task 7 (`test_finished_ranges_are_reused_on_the_next_run`, `test_resume_starts_over_when_the_saved_state_does_not_fit`, `test_a_part_file_of_the_wrong_size_starts_over`, `test_cancel_keeps_the_finished_ranges_for_a_resume`) and Task 9 (`test_cancel_during_mux_keeps_the_parts_for_a_resume`).
2. **File names from real titles** — `/`, `:`, `?`, `"`, control characters, emoji, CJK, decomposed accents, Windows device names (`CON`, `nul.txt`), 300-character titles, titles that are only dots or spaces → a valid name on Windows, macOS and Linux, at most 150 characters and 180 UTF-8 bytes of title (Linux allows 255 bytes per name), never a path outside the chosen folder. Pinned in Task 5 (`test_safe_name`, `test_long_names_are_cut_by_characters_and_bytes`, `test_cutting_never_leaves_a_trailing_dot_or_space`, `test_default_filename`).
3. **Expired or IP-bound URLs mid-download** — some connections get 403 while others keep reading, a URL is about to expire, a refresh returns a different stream (re-encoded), refreshes keep failing → exactly one refresh per failure for all threads, every connection switches to the fresh URL, `StreamForbidden` with IP guidance after three refreshes, `DownloadIncomplete` when the stream changed. Pinned in Task 7 (`test_a_403_refreshes_the_urls_once_for_every_thread`, `test_forbidden_streams_give_up_after_three_refreshes`, `test_urls_about_to_expire_are_refreshed_before_use`, `test_a_refresh_that_changes_the_stream_is_reported`).
4. **Videos with unusual streams** — vertical (Shorts) videos, dubbed videos with several audio tracks, "stable volume" DRC variants that reuse an itag, 5.1 or 96 kHz AAC headed for `.mov`, live streams, WebM-only, HDR or ciphered formats → the right stream, or `FormatNotAvailable` that names what was missing and lists every stream with the reason it was skipped. Pinned in Task 2 (`test_vertical_videos_are_measured_on_the_short_side`, `test_audio_prefers_the_default_track_then_no_drc_then_bitrate`, `test_mov_needs_stereo_audio`, `test_problems_explain_why_a_stream_is_skipped`, `test_nothing_suitable_lists_every_stream`, `test_live_streams_and_empty_lists_have_their_own_message`).
5. **Mistyped options** — `subtitles="en"` (a string instead of a list), a `format` that contradicts the extension, `quality="max"` with `.mov`, `default_subtitle` for a track that is not embedded, an existing file or sidecar, an unknown subtitle language, `.mp3` without ffmpeg → a clear error before any request (or, for subtitle languages and folder targets, before any media byte). Pinned in Task 9 (`test_bad_options_fail_before_any_request`, `test_existing_files_are_refused_before_any_request`, `test_mp3_needs_ffmpeg_before_any_request`, `test_unknown_subtitle_languages_fail_before_any_media_byte`, `test_default_subtitle_must_name_an_embedded_track_before_download`, `test_existing_sidecars_are_refused_before_download`).

## Verified facts this plan relies on

**YouTube** (read-only probes on 2026-09-28):

- `dQw4w9WgXcQ` via ANDROID_VR: `streamingData` has `expiresInSeconds` ("21540"), one progressive format (itag 18, `avc1.42001E, mp4a.40.2`, no `contentLength`) and 26 adaptive formats: WebM VP9 313/271/248/247/244/243/242/278, MP4 AV1 `av01.0.XXM.08` 401 (2160p) 400/399/398/397/396/395/394, MP4 H.264 137 (1080p, `avc1.640028`) 136/135/134/133/160, AAC 139 (`mp4a.40.5`, 22.05 kHz) and 140 (`mp4a.40.2`, 44.1 kHz), Opus 249/251. Every adaptive format has `url`, `contentLength`, `lastModified` (a decimal string, the `lmt` URL parameter) and `indexRange`; AV1 and VP9 carry `colorInfo` (BT.709 here). Best picks: compat 137 + 140, max 401 + 140. The response also holds `serverAbrStreamingUrl` (not used; the recorder drops it).
- Stream URLs carry `expire` (Unix seconds, ≈6 h ahead), `c` (the InnerTube client that asked, e.g. `ANDROID_VR`), `itag`, `clen`, `lmt`, and secrets (`ip`, `ei`, `sig`, `lsig`); they are bound to the requesting IP.
- `jNQXAC9IVRw` ("Me at the zoo", 19 s): ANDROID_VR answers `LOGIN_REQUIRED` "Sign in to confirm you're not a bot"; ANDROID and IOS answer OK with manual `en` and `de` captions and H.264 133/134 (240p), 160, AV1 395, and audio 139, 140 and 599 **each listed twice**: once plain and once with `isDrc: true` (`xtags=drc=1`, different `contentLength` and `lastModified`). IOS writes codec strings in upper case (`avc1.4D400C`). Long AV1 codec strings exist (`av01.0.00M.08.0.110.05.01.06.0`): the bit depth is the fourth dot-separated field.
- Vertical videos report `width` < `height`; YouTube's quality label ("1080p") names the short side.

**Python** (3.11–3.14 standard library):

- `socket.create_connection(..., source_address=("0.0.0.0", 0))` binds each candidate socket before connecting; binding an AF_INET6 socket to `0.0.0.0` fails, so every IPv6 address is skipped and only IPv4 is tried. `urllib.request.AbstractHTTPHandler.do_open(http_class, req, **http_conn_args)` passes `source_address` to the connection; `build_opener` drops its default `HTTPHandler`/`HTTPSHandler` when a subclass instance is given.
- `urllib.error.HTTPError` is itself a readable response (`.code`, `.headers`, `.read()`).
- `http.client.HTTPResponse.read(n)` returns fewer bytes at the end of the body and raises `IncompleteRead` when the server closes early.
- `subprocess.Popen.communicate(timeout=...)` raises `TimeoutExpired` without losing output, so polling in a loop is safe; `CREATE_NO_WINDOW` exists only on Windows (`creationflags=0` is valid everywhere).
- ffmpeg picks the output format from the file name; a temporary name such as `.song.mp3.1a2b.tmp` needs `-f mp3`.

## Decisions (where the spec is silent or ambiguous)

1. **Ctrl-C** (`KeyboardInterrupt`) stops every thread, saves the resume state and then propagates unchanged, so scripts stop as users expect (M5's bulk helpers "re-raise" too); `DownloadCancelled` is raised only for the `cancel` event. Both leave the parts for a resume.
2. **MP3 command**: the spec's ffmpeg arguments plus `-f mp3` (see Verified facts).
3. **Sizes are measured on the short side** (`min(width, height)`), so a vertical 1080×1920 stream counts as 1080p for `"compat"`.
4. **Audio preference is an ordering, not a filter**: default audio track first, then streams without DRC, then bitrate; `.mov` additionally requires ≤ 2 channels and ≤ 65535 Hz (M3 decision 10).
5. **Media requests** send the User-Agent of the InnerTube client named by the URL's `c` parameter (desktop Chrome otherwise) and `Accept-Encoding: identity`.
6. **Streaming** is a public, optional extension of `utmax.transport`: `HttpStream` and `StreamingTransport`. `UrllibTransport` and `RetryingTransport` implement it; custom transports without `stream()` still work, with each range buffered in memory.
7. **Progress** phases are `"downloading"`, `"muxing"`, `"converting"` and `"finished"`; callbacks run at most four times a second, never in parallel (the downloader holds its lock while calling), the first report of each phase and the last one are always delivered, and an exception from a callback stops the download (the parts stay).
8. **Subtitles**: a single string (`subtitles="en"`) is refused with a hint; two subtitles with the same language code are refused (their sidecars would collide); a `Transcript` of another video is refused; `default_subtitle` without embedded subtitles is refused.
9. **Targets**: a path is a folder when it exists as a directory, is empty or ends with `/` or `\`; a path without a known extension gets `.{format}` appended when `format` is given; `format` that contradicts a known extension is refused.
10. **Title limits**: 150 characters and 180 UTF-8 bytes, which leaves room for ` [id]`, the extension and `.401.part.json` within Linux's 255-byte name limit.
11. **Parts** are `<target>.<itag>.part` with `<target>.<itag>.part.json`; the state is written when the download starts, at most once a second while ranges finish, and whenever the download stops.
12. **Resume matching** compares video ID, itag, size, `lastModified` **and chunk size** (finished chunk numbers mean nothing with another chunk size).
13. **HTTP 416** triggers one URL refresh and one retry of the range, then `DownloadIncomplete`; a proactive refresh (URL expiring within 300 s) never raises when the refresh budget is spent — the current URL is used instead.
14. **Live tests** use `jNQXAC9IVRw` (19 s, 240p, manual English subtitles) instead of the spec's "160+140" of `dQw4w9WgXcQ`: the spec asks for a small MP4, and `download()` has no itag override. It also exercises the ANDROID_VR → ANDROID fallback.
15. **`force_ipv4`** is implemented by binding outgoing sockets to `0.0.0.0` (see Verified facts); `Client(transport=..., force_ipv4=True)` is refused like `proxy`.
16. **Retries**: a range is retried up to 5 times in a row without progress (backoff 0.5 s … 8 s, `core.retry.backoff_delay`); a body that ends early after delivering data continues at once from the first missing byte; 408, 429 and 5xx are transient; other statuses end the download with `DownloadIncomplete`.

## File map

| File | Responsibility | Task |
|---|---|---|
| `src/utmax/models.py` | `Container`, `Quality`, `SubtitleMode`, `ProgressPhase`, `Codec`, `Format`, `Progress`, `DownloadResult` | 1 |
| `src/utmax/errors.py` | `FormatNotAvailable`, `StreamForbidden`, `DownloadIncomplete`, `DownloadCancelled`, `OutputExists`, `FFmpegError`, `FFmpegNotFound`, `FFmpegFailed` | 1 |
| `src/utmax/core/clients.py` | `PROFILES` (client profiles by name) | 2 |
| `src/utmax/core/streams.py` | `Stream`, `parse_streams`, `choose_streams`, `describe_stream` | 2 |
| `scripts/record_fixtures.py`, `tests/fixtures/youtube/streams_android_vr.json` | Record and keep the ANDROID_VR stream list | 2 |
| `src/utmax/core/player.py`, `src/utmax/adapters/innertube.py`, `src/utmax/services/transcripts.py` | `PlayerData.streams`, the streams fallback rule, `TranscriptService.track_list` | 3 |
| `src/utmax/core/downloads.py` | `Chunk`, `plan_chunks`, `range_header`, `content_range_total`, `expires_soon`, `PartState`, `RateMeter`, `Throttle` | 4 |
| `src/utmax/core/filenames.py` | `safe_name`, `default_filename`, `Target`, `resolve_target`, `sidecar_name`, `part_name` | 5 |
| `src/utmax/transport.py`, `src/utmax/adapters/http.py`, `src/utmax/client.py` | `HttpStream`, `StreamingTransport`, `UrllibTransport.stream`, `open_stream`, `BufferedStream`, `force_ipv4` | 6 |
| `tests/helpers/fake_media.py` | A fake googlevideo server with scripted faults | 7 |
| `src/utmax/adapters/downloader.py` | `ProgressReporter`, `Job`, `Downloader` | 7 |
| `src/utmax/adapters/ffmpeg.py` | `locate_ffmpeg`, `FFmpeg` | 8 |
| `tests/helpers/downloads.py` | A fake YouTube serving synthetic fragmented MP4 streams | 9 |
| `src/utmax/services/download.py` | `DownloadOptions`, `DownloadService` | 9 |
| `src/utmax/client.py`, `src/utmax/__init__.py` | `Client.download`, `utmax.download` | 10 |
| `tests/live/test_download_live.py` | Live downloads, M4 verification | 11 |

---

### Task 1: Download models and errors

**Files:**
- Modify: `src/utmax/models.py`, `src/utmax/errors.py`, `src/utmax/__init__.py`
- Test: `tests/unit/test_download_types.py`

**Interfaces:**
- Consumes: `utmax.models.VideoInfo`, `utmax.errors.DownloadError` and `MuxError` (earlier milestones).
- Produces (in `utmax.models`):
  - `Container = Literal["mp4", "mov", "m4a", "mp3"]`, `Quality = Literal["compat", "max"]`, `SubtitleMode = Literal["embed", "sidecar", "both"]`, `ProgressPhase = Literal["downloading", "muxing", "converting", "finished"]`, `Codec = Literal["h264", "av1", "vp9", "aac", "he-aac", "opus", "other"]`.
  - `Format(itag, kind, container, codec, codecs, width=None, height=None, fps=None, bitrate=0, content_length=None, audio_sample_rate=None, audio_channels=None, is_default_audio=True, is_drc=False, last_modified="")` with `.label`.
  - `Progress(video_id, phase, bytes_done, bytes_total, speed_bps=None, eta_seconds=None)` with `.fraction`.
  - `DownloadResult(path, video, container, video_format, audio_format, embedded_subtitles=(), sidecars=(), size_bytes=0, resumed=False)`.
- Produces (in `utmax.errors`, all under `DownloadError`): `FormatNotAvailable(message, *, available=(), ...)`, `StreamForbidden(message, *, itag, ...)`, `DownloadIncomplete`, `DownloadCancelled`, `OutputExists`, `FFmpegError` → `FFmpegNotFound`, `FFmpegFailed(message, *, returncode, stderr_tail, ...)`. All of them, plus `Container`, `DownloadResult`, `Format` and `Progress`, are exported from `utmax`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_download_types.py`:

```python
"""Tests for the download models and errors."""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

import utmax
from tests.helpers.builders import VIDEO
from utmax import errors
from utmax.models import DownloadResult, Format, Progress

H264 = Format(137, "video", "mp4", "h264", "avc1.640028", 1920, 1080, 25, 4334157, 80911999)
AAC = Format(
    140,
    "audio",
    "mp4",
    "aac",
    "mp4a.40.2",
    bitrate=130677,
    content_length=3449447,
    audio_sample_rate=44100,
    audio_channels=2,
)
HE_AAC_DRC = Format(
    139, "audio", "mp4", "he-aac", "mp4a.40.5", audio_sample_rate=22050, is_drc=True
)


@pytest.mark.parametrize(
    ("fmt", "label"),
    [
        (H264, "137 mp4 h264 1080p25"),
        (Format(248, "video", "webm", "vp9", "vp9", 1080, 1920, 30), "248 webm vp9 1080p30"),
        (Format(160, "video", "mp4", "h264", "avc1.4d400c", height=144), "160 mp4 h264 144p"),
        (AAC, "140 mp4 aac 44.1kHz"),
        (HE_AAC_DRC, "139 mp4 he-aac 22.05kHz drc"),
        (Format(251, "audio", "webm", "opus", "opus"), "251 webm opus"),
    ],
)
def test_format_labels(fmt: Format, label: str) -> None:
    assert fmt.label == label


def test_progress_fraction() -> None:
    assert Progress("v", "downloading", 50, 200).fraction == 0.25
    assert Progress("v", "downloading", 250, 200).fraction == 1.0
    assert Progress("v", "converting", 0, None).fraction is None
    assert Progress("v", "downloading", 0, 0).fraction is None


def test_download_result_defaults() -> None:
    result = DownloadResult(Path("rick.m4a"), VIDEO, "m4a", None, AAC)
    assert result.embedded_subtitles == ()
    assert result.sidecars == ()
    assert (result.size_bytes, result.resumed) == (0, False)


@pytest.mark.parametrize(
    ("child", "parent"),
    [
        (errors.FormatNotAvailable, errors.DownloadError),
        (errors.StreamForbidden, errors.DownloadError),
        (errors.DownloadIncomplete, errors.DownloadError),
        (errors.DownloadCancelled, errors.DownloadError),
        (errors.OutputExists, errors.DownloadError),
        (errors.MuxError, errors.DownloadError),
        (errors.FFmpegError, errors.DownloadError),
        (errors.FFmpegNotFound, errors.FFmpegError),
        (errors.FFmpegFailed, errors.FFmpegError),
    ],
)
def test_download_error_hierarchy(child: type[Exception], parent: type[Exception]) -> None:
    assert issubclass(child, parent)


def test_download_error_fields() -> None:
    missing = errors.FormatNotAvailable("none", available=["137 mp4 h264 1080p25"], video_id="v")
    assert (missing.available, missing.video_id) == (("137 mp4 h264 1080p25",), "v")
    assert errors.StreamForbidden("403", itag=137).itag == 137
    failed = errors.FFmpegFailed("bad", returncode=1, stderr_tail="Invalid data")
    assert (failed.returncode, failed.stderr_tail) == (1, "Invalid data")
    assert "winget install Gyan.FFmpeg" in errors.FFmpegNotFound.suggestion
    assert errors.OutputExists("exists").suggestion.startswith("Pass overwrite=True")


@pytest.mark.parametrize(
    "error",
    [
        errors.FormatNotAvailable("none", available=["18 mp4 h264 360p25"], video_id="v"),
        errors.StreamForbidden("403", itag=401, video_id="v"),
        errors.DownloadIncomplete("short", video_id="v"),
        errors.DownloadCancelled("stopped", video_id="v"),
        errors.OutputExists("exists", suggestion="Pick another name."),
        errors.FFmpegError("broken"),
        errors.FFmpegNotFound("missing"),
        errors.FFmpegFailed("exit 1", returncode=1, stderr_tail="tail", video_id="v"),
    ],
)
def test_download_errors_survive_pickling(error: errors.UTMaxError) -> None:
    clone = pickle.loads(pickle.dumps(error))
    assert type(clone) is type(error)
    assert str(clone) == str(error)
    assert clone.__dict__ == error.__dict__


def test_download_names_are_exported() -> None:
    for name in (
        "DownloadCancelled",
        "DownloadIncomplete",
        "FFmpegError",
        "FFmpegFailed",
        "FFmpegNotFound",
        "FormatNotAvailable",
        "OutputExists",
        "StreamForbidden",
    ):
        assert name in errors.__all__
        assert name in utmax.__all__
        assert getattr(utmax, name) is getattr(errors, name)
    for name in ("Container", "DownloadResult", "Format", "Progress"):
        assert name in utmax.__all__
        assert hasattr(utmax, name)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_download_types.py -q`
Expected: collection error — `ImportError: cannot import name 'DownloadResult' from 'utmax.models'`.

- [ ] **Step 3: Add the models**

In `src/utmax/models.py`, replace the `__all__` list and the `FormatName` line with:

```python
__all__ = [
    "Codec",
    "Container",
    "DownloadResult",
    "Format",
    "FormatName",
    "Language",
    "Progress",
    "ProgressPhase",
    "Quality",
    "Segment",
    "SubtitleMode",
    "Track",
    "TrackFetcher",
    "TrackList",
    "Transcript",
    "VideoInfo",
    "Word",
]

FormatName = Literal["txt", "srt", "vtt", "json", "pretty"]
Container = Literal["mp4", "mov", "m4a", "mp3"]
Quality = Literal["compat", "max"]
SubtitleMode = Literal["embed", "sidecar", "both"]
ProgressPhase = Literal["downloading", "muxing", "converting", "finished"]
Codec = Literal["h264", "av1", "vp9", "aac", "he-aac", "opus", "other"]
```

Append at the end of the file:

```python
@dataclass(frozen=True, slots=True)
class Format:
    """One stream YouTube offers for a video; its URL never leaves utmax."""

    itag: int
    kind: Literal["video", "audio"]
    container: Literal["mp4", "webm"]
    codec: Codec
    codecs: str
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    bitrate: int = 0
    content_length: int | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    is_default_audio: bool = True
    is_drc: bool = False
    last_modified: str = ""

    @property
    def label(self) -> str:
        """A short description such as ``"137 mp4 h264 1080p25"`` or ``"140 mp4 aac 44.1kHz"``."""
        words = [str(self.itag), self.container, self.codec]
        if self.kind == "video":
            side = min((n for n in (self.width, self.height) if n), default=0)
            words.append(f"{side}p{self.fps or ''}")
        else:
            if self.audio_sample_rate:
                words.append(f"{self.audio_sample_rate / 1000:g}kHz")
            if self.is_drc:
                words.append("drc")
        return " ".join(words)


@dataclass(frozen=True, slots=True)
class Progress:
    """How far a download has come; passed to ``download(progress=...)`` callbacks."""

    video_id: str
    phase: ProgressPhase
    bytes_done: int
    bytes_total: int | None
    speed_bps: float | None = None
    eta_seconds: float | None = None

    @property
    def fraction(self) -> float | None:
        """``bytes_done / bytes_total`` between 0 and 1; ``None`` while the total is unknown."""
        if not self.bytes_total:
            return None
        return min(1.0, self.bytes_done / self.bytes_total)


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """What :func:`utmax.download` produced."""

    path: Path
    video: VideoInfo
    container: Container
    video_format: Format | None
    audio_format: Format
    embedded_subtitles: tuple[str, ...] = ()
    sidecars: tuple[Path, ...] = ()
    size_bytes: int = 0
    resumed: bool = False
```

- [ ] **Step 4: Add the errors**

In `src/utmax/errors.py`, replace `__all__` with:

```python
__all__ = [
    "AgeRestricted",
    "DownloadCancelled",
    "DownloadError",
    "DownloadIncomplete",
    "FFmpegError",
    "FFmpegFailed",
    "FFmpegNotFound",
    "FailedToCreateConsentCookie",
    "FormatNotAvailable",
    "InvalidModelSpec",
    "InvalidOption",
    "InvalidVideoId",
    "IpBlocked",
    "MissingExtra",
    "MuxError",
    "NetworkError",
    "NoTranscriptFound",
    "NotTranslatable",
    "OutputExists",
    "PoTokenRequired",
    "ProviderAuthError",
    "ProviderError",
    "ProviderNotInstalled",
    "ProviderRateLimited",
    "RequestBlocked",
    "StreamForbidden",
    "TranscriptsDisabled",
    "TranslationError",
    "TranslationLanguageNotAvailable",
    "TranslationMismatch",
    "TranslationRefused",
    "UTMaxError",
    "UnsupportedFormat",
    "VideoUnavailable",
    "VideoUnplayable",
    "YouTubeDataUnparsable",
    "YouTubeError",
    "YouTubeRequestFailed",
]
```

Insert directly after the `MuxError` class:

```python
class FormatNotAvailable(DownloadError):
    """No stream of the video fits the requested file type and quality."""

    suggestion = (
        'Try quality="compat" or another file type; live streams can be downloaded after they end.'
    )

    def __init__(
        self,
        message: str,
        *,
        available: Sequence[str] = (),
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.available = tuple(available)


class StreamForbidden(DownloadError):
    """YouTube kept refusing a stream (HTTP 403) even with fresh URLs."""

    suggestion = (
        "Stream URLs only work from the IP address that requested them: avoid rotating proxies "
        "and VPN switches during a download, and try Client(force_ipv4=True)."
    )

    def __init__(
        self,
        message: str,
        *,
        itag: int,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.itag = itag


class DownloadIncomplete(DownloadError):
    """A stream could not be downloaded completely."""

    suggestion = "Run the same download again; finished parts are kept and it resumes."


class DownloadCancelled(DownloadError):
    """The download was stopped through its ``cancel`` event."""

    suggestion = "Run the same download again to resume where it stopped."


class OutputExists(DownloadError):
    """The target file (or a subtitle file next to it) already exists."""

    suggestion = "Pass overwrite=True to replace it, or choose another file name."


class FFmpegError(DownloadError):
    """ffmpeg, which utmax needs only for MP3 files, failed."""

    suggestion = "Check your ffmpeg installation, or download .m4a audio, which needs no ffmpeg."


class FFmpegNotFound(FFmpegError):
    """No usable ffmpeg executable was found."""

    suggestion = (
        "Install ffmpeg (winget install Gyan.FFmpeg | brew install ffmpeg | apt install ffmpeg), "
        'or pass ffmpeg="/path/to/ffmpeg".'
    )


class FFmpegFailed(FFmpegError):
    """ffmpeg exited with an error."""

    suggestion = "ffmpeg could not convert the audio; see stderr_tail, or download .m4a instead."

    def __init__(
        self,
        message: str,
        *,
        returncode: int,
        stderr_tail: str,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.returncode = returncode
        self.stderr_tail = stderr_tail
```

- [ ] **Step 5: Export them from `utmax`**

In `src/utmax/__init__.py`, add `DownloadCancelled`, `DownloadIncomplete`, `FFmpegError`, `FFmpegFailed`, `FFmpegNotFound`, `FormatNotAvailable`, `OutputExists` and `StreamForbidden` to the `from utmax.errors import (...)` list, and `Container`, `DownloadResult`, `Format` and `Progress` to the `from utmax.models import (...)` list (keep both lists alphabetical, as ruff's isort orders them). Replace `__all__` with:

```python
__all__ = [
    "AgeRestricted",
    "Client",
    "Container",
    "DownloadCancelled",
    "DownloadError",
    "DownloadIncomplete",
    "DownloadResult",
    "FFmpegError",
    "FFmpegFailed",
    "FFmpegNotFound",
    "FailedToCreateConsentCookie",
    "Format",
    "FormatName",
    "FormatNotAvailable",
    "InvalidModelSpec",
    "InvalidOption",
    "InvalidVideoId",
    "IpBlocked",
    "Language",
    "MissingExtra",
    "MuxError",
    "NetworkError",
    "NoTranscriptFound",
    "NotTranslatable",
    "OutputExists",
    "PoTokenRequired",
    "Progress",
    "ProviderAuthError",
    "ProviderError",
    "ProviderNotInstalled",
    "ProviderRateLimited",
    "RequestBlocked",
    "Segment",
    "StreamForbidden",
    "Track",
    "TrackList",
    "Transcript",
    "TranscriptsDisabled",
    "TranslationError",
    "TranslationLanguageNotAvailable",
    "TranslationMismatch",
    "TranslationRefused",
    "Translator",
    "UTMaxError",
    "UnsupportedFormat",
    "VideoInfo",
    "VideoUnavailable",
    "VideoUnplayable",
    "Word",
    "YouTubeDataUnparsable",
    "YouTubeError",
    "YouTubeRequestFailed",
    "__version__",
    "bilingual",
    "fetch",
    "list_tracks",
    "translate",
    "translator",
    "video_info",
]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_download_types.py tests/unit/test_errors.py tests/unit/test_facade.py -q`
Expected: the new file reports 27 passed; `test_every_public_error_has_a_real_suggestion` now also checks the eight new classes and passes.

- [ ] **Step 7: Gates and commit**

Run the four gates (all tests pass; the suite grows by 27).

```bash
git add src/utmax/models.py src/utmax/errors.py src/utmax/__init__.py tests/unit/test_download_types.py
git commit -m "feat: add download models and errors" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Stream parsing and selection

**Files:**
- Create: `src/utmax/core/streams.py`, `tests/fixtures/youtube/streams_android_vr.json`, `tests/unit/core/test_streams.py`
- Modify: `src/utmax/core/clients.py`, `scripts/record_fixtures.py`, `tests/fixtures/youtube/README.md`, `tests/helpers/youtube.py`

**Interfaces:**
- Consumes: `Format`, `Codec`, `Container`, `Quality` (Task 1); `FormatNotAvailable` (Task 1); `utmax.core.ytdata.items`/`mapping`; client profiles in `utmax.core.clients`.
- Produces:
  - `utmax.core.clients.PROFILES: Mapping[str, ClientProfile]` — profiles by name (`"ANDROID"`, `"IOS"`, `"ANDROID_VR"`, `"WEB"`).
  - `utmax.core.streams.Stream(format, url="", expires_at=None, user_agent=DESKTOP_USER_AGENT, bit_depth=8, hdr=False, drm=False, live=False, progressive=False)` with `.problem -> str | None`.
  - `parse_streams(streaming_data: Mapping[str, Any]) -> tuple[Stream, ...]` (progressive formats first, then adaptive; entries without an itag or a video/audio MP4/WebM MIME type are skipped).
  - `choose_streams(streams, *, container, quality, video_id) -> tuple[Stream | None, Stream]` (video is `None` for `m4a`/`mp3`; raises `FormatNotAvailable`).
  - `describe_stream(stream) -> str`.
  - `tests.helpers.youtube.streaming_data() -> dict[str, Any]` — the recorded ANDROID_VR `streamingData`.

- [ ] **Step 1: Add the recorded stream list**

Create `tests/fixtures/youtube/streams_android_vr.json` with exactly this content (recorded from `dQw4w9WgXcQ` via ANDROID_VR on 2026-09-28 and trimmed by the recorder code of Step 7; every URL is a placeholder):

```json
{
 "streamingData": {
  "expiresInSeconds": "21540",
  "formats": [
   {"itag": 18, "mimeType": "video/mp4; codecs=\"avc1.42001E, mp4a.40.2\"", "bitrate": 444226, "width": 640, "height": 360, "fps": 25, "qualityLabel": "360p", "lastModified": "1766960953317159", "audioQuality": "AUDIO_QUALITY_LOW", "audioSampleRate": "44100", "audioChannels": 2, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=18&c=ANDROID_VR"}
  ],
  "adaptiveFormats": [
   {"itag": 313, "mimeType": "video/webm; codecs=\"vp9\"", "bitrate": 18076636, "width": 3840, "height": 2160, "fps": 25, "qualityLabel": "2160p", "contentLength": "358608461", "lastModified": "1766963492248817", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=313&c=ANDROID_VR"},
   {"itag": 401, "mimeType": "video/mp4; codecs=\"av01.0.12M.08\"", "bitrate": 17400774, "width": 3840, "height": 2160, "fps": 25, "qualityLabel": "2160p", "contentLength": "240334643", "lastModified": "1766961226342025", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=401&c=ANDROID_VR"},
   {"itag": 271, "mimeType": "video/webm; codecs=\"vp9\"", "bitrate": 8978328, "width": 2560, "height": 1440, "fps": 25, "qualityLabel": "1440p", "contentLength": "151103346", "lastModified": "1766962756705951", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=271&c=ANDROID_VR"},
   {"itag": 400, "mimeType": "video/mp4; codecs=\"av01.0.12M.08\"", "bitrate": 7755221, "width": 2560, "height": 1440, "fps": 25, "qualityLabel": "1440p", "contentLength": "122168277", "lastModified": "1766961246255689", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=400&c=ANDROID_VR"},
   {"itag": 137, "mimeType": "video/mp4; codecs=\"avc1.640028\"", "bitrate": 4334157, "width": 1920, "height": 1080, "fps": 25, "qualityLabel": "1080p", "contentLength": "80911999", "lastModified": "1766957926174250", "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=137&c=ANDROID_VR"},
   {"itag": 248, "mimeType": "video/webm; codecs=\"vp9\"", "bitrate": 1549172, "width": 1920, "height": 1080, "fps": 25, "qualityLabel": "1080p", "contentLength": "30846580", "lastModified": "1766963494258902", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=248&c=ANDROID_VR"},
   {"itag": 399, "mimeType": "video/mp4; codecs=\"av01.0.08M.08\"", "bitrate": 1594543, "width": 1920, "height": 1080, "fps": 25, "qualityLabel": "1080p", "contentLength": "30415996", "lastModified": "1766970905427393", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=399&c=ANDROID_VR"},
   {"itag": 136, "mimeType": "video/mp4; codecs=\"avc1.4d401f\"", "bitrate": 1058310, "width": 1280, "height": 720, "fps": 25, "qualityLabel": "720p", "contentLength": "26455880", "lastModified": "1766958204135500", "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=136&c=ANDROID_VR"},
   {"itag": 247, "mimeType": "video/webm; codecs=\"vp9\"", "bitrate": 867871, "width": 1280, "height": 720, "fps": 25, "qualityLabel": "720p", "contentLength": "17686717", "lastModified": "1766962272813700", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=247&c=ANDROID_VR"},
   {"itag": 398, "mimeType": "video/mp4; codecs=\"av01.0.05M.08\"", "bitrate": 1012348, "width": 1280, "height": 720, "fps": 25, "qualityLabel": "720p", "contentLength": "17593076", "lastModified": "1766960928964543", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=398&c=ANDROID_VR"},
   {"itag": 135, "mimeType": "video/mp4; codecs=\"avc1.4d401e\"", "bitrate": 690764, "width": 854, "height": 480, "fps": 25, "qualityLabel": "480p", "contentLength": "14103519", "lastModified": "1766958212394312", "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=135&c=ANDROID_VR"},
   {"itag": 244, "mimeType": "video/webm; codecs=\"vp9\"", "bitrate": 466632, "width": 854, "height": 480, "fps": 25, "qualityLabel": "480p", "contentLength": "9381481", "lastModified": "1766961781254744", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=244&c=ANDROID_VR"},
   {"itag": 397, "mimeType": "video/mp4; codecs=\"av01.0.04M.08\"", "bitrate": 525728, "width": 854, "height": 480, "fps": 25, "qualityLabel": "480p", "contentLength": "9874826", "lastModified": "1766961026797508", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=397&c=ANDROID_VR"},
   {"itag": 134, "mimeType": "video/mp4; codecs=\"avc1.4d401e\"", "bitrate": 450863, "width": 640, "height": 360, "fps": 25, "qualityLabel": "360p", "contentLength": "8390921", "lastModified": "1766960771651324", "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=134&c=ANDROID_VR"},
   {"itag": 243, "mimeType": "video/webm; codecs=\"vp9\"", "bitrate": 288453, "width": 640, "height": 360, "fps": 25, "qualityLabel": "360p", "contentLength": "6014765", "lastModified": "1766962597390784", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=243&c=ANDROID_VR"},
   {"itag": 396, "mimeType": "video/mp4; codecs=\"av01.0.01M.08\"", "bitrate": 304466, "width": 640, "height": 360, "fps": 25, "qualityLabel": "360p", "contentLength": "5685561", "lastModified": "1766958935473272", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=396&c=ANDROID_VR"},
   {"itag": 133, "mimeType": "video/mp4; codecs=\"avc1.4d4015\"", "bitrate": 236224, "width": 426, "height": 240, "fps": 25, "qualityLabel": "240p", "contentLength": "4310122", "lastModified": "1766961065074107", "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=133&c=ANDROID_VR"},
   {"itag": 242, "mimeType": "video/webm; codecs=\"vp9\"", "bitrate": 131647, "width": 426, "height": 240, "fps": 25, "qualityLabel": "240p", "contentLength": "2706929", "lastModified": "1766963772564266", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=242&c=ANDROID_VR"},
   {"itag": 395, "mimeType": "video/mp4; codecs=\"av01.0.00M.08\"", "bitrate": 159709, "width": 426, "height": 240, "fps": 25, "qualityLabel": "240p", "contentLength": "3095447", "lastModified": "1766960927930211", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=395&c=ANDROID_VR"},
   {"itag": 160, "mimeType": "video/mp4; codecs=\"avc1.4d400c\"", "bitrate": 109973, "width": 256, "height": 144, "fps": 25, "qualityLabel": "144p", "contentLength": "2058142", "lastModified": "1766961162303498", "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=160&c=ANDROID_VR"},
   {"itag": 278, "mimeType": "video/webm; codecs=\"vp9\"", "bitrate": 68500, "width": 256, "height": 144, "fps": 25, "qualityLabel": "144p", "contentLength": "1540844", "lastModified": "1766962598503008", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=278&c=ANDROID_VR"},
   {"itag": 394, "mimeType": "video/mp4; codecs=\"av01.0.00M.08\"", "bitrate": 83289, "width": 256, "height": 144, "fps": 25, "qualityLabel": "144p", "contentLength": "1505504", "lastModified": "1766961689433204", "colorInfo": {"primaries": "COLOR_PRIMARIES_BT709", "transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_BT709", "matrixCoefficients": "COLOR_MATRIX_COEFFICIENTS_BT709"}, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=394&c=ANDROID_VR"},
   {"itag": 139, "mimeType": "audio/mp4; codecs=\"mp4a.40.5\"", "bitrate": 50152, "contentLength": "1300631", "lastModified": "1766955925459591", "audioQuality": "AUDIO_QUALITY_LOW", "audioSampleRate": "22050", "audioChannels": 2, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=139&c=ANDROID_VR"},
   {"itag": 140, "mimeType": "audio/mp4; codecs=\"mp4a.40.2\"", "bitrate": 130677, "contentLength": "3449447", "lastModified": "1766955925572207", "audioQuality": "AUDIO_QUALITY_MEDIUM", "audioSampleRate": "44100", "audioChannels": 2, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=140&c=ANDROID_VR"},
   {"itag": 249, "mimeType": "audio/webm; codecs=\"opus\"", "bitrate": 49496, "contentLength": "1231355", "lastModified": "1766955883595299", "audioQuality": "AUDIO_QUALITY_LOW", "audioSampleRate": "48000", "audioChannels": 2, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=249&c=ANDROID_VR"},
   {"itag": 251, "mimeType": "audio/webm; codecs=\"opus\"", "bitrate": 136544, "contentLength": "3433755", "lastModified": "1766955883819090", "audioQuality": "AUDIO_QUALITY_MEDIUM", "audioSampleRate": "48000", "audioChannels": 2, "url": "https://redacted.googlevideo.com/videoplayback?expire=REDACTED&itag=251&c=ANDROID_VR"}
  ]
 }
}
```

Add to `tests/helpers/youtube.py` (with `import json` and `from pathlib import Path` at the top):

```python
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "youtube"


def streaming_data() -> dict[str, Any]:
    """The recorded ANDROID_VR ``streamingData`` of dQw4w9WgXcQ (URLs are placeholders)."""
    data = json.loads((FIXTURES / "streams_android_vr.json").read_text(encoding="utf-8"))
    return dict(data["streamingData"])
```

- [ ] **Step 2: Write the failing tests**

`tests/unit/core/test_streams.py`:

```python
"""Tests for stream parsing and selection."""

from __future__ import annotations

from typing import Any

import pytest

from tests.helpers.youtube import streaming_data
from utmax.core.clients import ANDROID_VR, DESKTOP_USER_AGENT, IOS
from utmax.core.streams import Stream, choose_streams, describe_stream, parse_streams
from utmax.errors import FormatNotAvailable
from utmax.models import Container, Format, Quality

URL = "https://rr1.googlevideo.com/videoplayback?expire=1790604050&itag={itag}&c=IOS"


def raw(itag: int, mime: str, **fields: Any) -> dict[str, Any]:
    """One ``adaptiveFormats`` entry with a direct URL."""
    return {"itag": itag, "mimeType": mime, "url": URL.format(itag=itag), **fields}


def video(itag: int, codecs: str, width: int, height: int, **fields: Any) -> dict[str, Any]:
    container = "webm" if codecs.startswith(("vp9", "vp09")) else "mp4"
    fields.setdefault("fps", 25)
    fields.setdefault("bitrate", 1000)
    mime = f'video/{container}; codecs="{codecs}"'
    return raw(itag, mime, width=width, height=height, **fields)


def audio(itag: int, codecs: str = "mp4a.40.2", **fields: Any) -> dict[str, Any]:
    container = "webm" if codecs == "opus" else "mp4"
    fields.setdefault("audioSampleRate", "44100")
    fields.setdefault("audioChannels", 2)
    fields.setdefault("bitrate", 128000)
    return raw(itag, f'audio/{container}; codecs="{codecs}"', **fields)


def streams(*entries: dict[str, Any]) -> tuple[Stream, ...]:
    return parse_streams({"adaptiveFormats": list(entries)})


def choose(
    found: tuple[Stream, ...], container: Container = "mp4", quality: Quality = "compat"
) -> tuple[int | None, int]:
    picked, sound = choose_streams(found, container=container, quality=quality, video_id="v")
    return (picked.format.itag if picked else None, sound.format.itag)


def test_the_recorded_android_vr_streams_parse() -> None:
    found = parse_streams(streaming_data())
    assert len(found) == 27
    assert [stream.format.itag for stream in found][:3] == [18, 313, 401]
    by_itag = {stream.format.itag: stream for stream in found}
    assert by_itag[137].format == Format(
        itag=137,
        kind="video",
        container="mp4",
        codec="h264",
        codecs="avc1.640028",
        width=1920,
        height=1080,
        fps=25,
        bitrate=4334157,
        content_length=80911999,
        last_modified="1766957926174250",
    )
    assert by_itag[140].format == Format(
        itag=140,
        kind="audio",
        container="mp4",
        codec="aac",
        codecs="mp4a.40.2",
        bitrate=130677,
        content_length=3449447,
        audio_sample_rate=44100,
        audio_channels=2,
        last_modified="1766955925572207",
    )
    assert by_itag[137].user_agent == ANDROID_VR.user_agent
    assert by_itag[137].expires_at is None  # the recorded URLs carry expire=REDACTED
    assert by_itag[18].progressive
    assert by_itag[18].format.content_length is None


@pytest.mark.parametrize(
    ("container", "quality", "expected"),
    [
        ("mp4", "compat", (137, 140)),
        ("mp4", "max", (401, 140)),
        ("mov", "compat", (137, 140)),
        ("m4a", "compat", (None, 140)),
        ("mp3", "max", (None, 140)),
    ],
)
def test_the_recorded_streams_pick_the_expected_itags(
    container: Container, quality: Quality, expected: tuple[int | None, int]
) -> None:
    assert choose(parse_streams(streaming_data()), container, quality) == expected


@pytest.mark.parametrize(
    ("entry", "problem"),
    [
        (video(137, "avc1.640028", 1920, 1080), None),
        (video(137, "avc1.640028", 1920, 1080, drmFamilies=["WIDEVINE"]), "DRM-protected"),
        (video(137, "avc1.640028", 1920, 1080, targetDurationSec=5), "part of a live stream"),
        (
            {**video(137, "avc1.640028", 1920, 1080), "url": None, "signatureCipher": "s=1"},
            "needs a signature utmax cannot compute",
        ),
        (raw(18, 'video/mp4; codecs="avc1.42001E, mp4a.40.2"'), "audio and video combined"),
        (video(248, "vp9", 1920, 1080), "WebM"),
        (video(337, "vp09.02.51.10.01.09.16.09.00", 3840, 2160), "WebM"),
        (video(701, "av01.0.12M.10.0.110.09.16.09.0", 3840, 2160), "HDR or more than 8 bits"),
        (
            video(
                399,
                "av01.0.08M.08",
                1920,
                1080,
                colorInfo={"transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_SMPTEST2084"},
            ),
            "HDR or more than 8 bits",
        ),
        (
            video(400, "av01.0.12M.08", 2560, 1440, qualityLabel="1440p60 HDR"),
            "HDR or more than 8 bits",
        ),
        (audio(328, "ec-3"), "other codec"),
        (audio(251, "opus"), "WebM"),
    ],
)
def test_problems_explain_why_a_stream_is_skipped(
    entry: dict[str, Any], problem: str | None
) -> None:
    (stream,) = streams(entry)
    assert stream.problem == problem


@pytest.mark.parametrize(
    ("codecs", "codec"),
    [
        ("avc1.640028", "h264"),
        ("avc1.4D401F", "h264"),
        ("av01.0.08M.08", "av1"),
        ("vp9", "vp9"),
        ("vp09.00.51.08", "vp9"),
        ("mp4a.40.2", "aac"),
        ("mp4a.40.5", "he-aac"),
        ("mp4a.40.29", "he-aac"),
        ("opus", "opus"),
        ("ec-3", "other"),
        ("mp4a.a5", "other"),
    ],
)
def test_codec_families(codecs: str, codec: str) -> None:
    (stream,) = parse_streams({"adaptiveFormats": [raw(1, f'audio/mp4; codecs="{codecs}"')]})
    assert stream.format.codec == codec


def test_max_prefers_av1_at_equal_size_then_frame_rate_and_bitrate() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080, bitrate=4_000_000),
        video(399, "av01.0.08M.08", 1920, 1080, bitrate=1_600_000),
        video(299, "avc1.64002a", 1920, 1080, fps=50, bitrate=5_000_000),
        audio(140),
    )
    assert choose(found, quality="compat") == (299, 140)
    assert choose(found, quality="max") == (399, 140)


def test_quality_caps_the_size() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080),
        video(138, "avc1.640033", 7680, 4320),
        video(401, "av01.0.12M.08", 3840, 2160),
        video(571, "av01.0.16M.08", 7680, 4320),
        audio(140),
    )
    assert choose(found) == (137, 140)
    assert choose(found, quality="max") == (401, 140)


def test_vertical_videos_are_measured_on_the_short_side() -> None:
    found = streams(
        video(137, "avc1.640028", 1080, 1920),
        video(136, "avc1.4d401f", 720, 1280),
        audio(140),
    )
    assert choose(found) == (137, 140)


def test_audio_prefers_the_default_track_then_no_drc_then_bitrate() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080),
        audio(140, bitrate=130_000, isDrc=True),
        audio(140, bitrate=129_000),
        audio(139, "mp4a.40.5", bitrate=50_000),
        audio(141, bitrate=260_000, audioTrack={"audioIsDefault": False, "displayName": "Spanish"}),
    )
    _, chosen = choose_streams(found, container="mp4", quality="compat", video_id="v")
    assert (chosen.format.itag, chosen.format.is_drc, chosen.format.bitrate) == (140, False, 129_000)


def test_mov_needs_stereo_audio() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080),
        audio(256, "mp4a.40.5", audioChannels=6, bitrate=192_000),
        audio(140, bitrate=128_000),
        audio(327, audioSampleRate="96000", bitrate=300_000),
    )
    assert choose(found, "mp4") == (137, 327)
    assert choose(found, "mov") == (137, 140)


def test_nothing_suitable_lists_every_stream() -> None:
    found = streams(video(248, "vp9", 1920, 1080), audio(251, "opus"))
    with pytest.raises(FormatNotAvailable, match="has no AAC audio in MP4") as caught:
        choose_streams(found, container="mp4", quality="compat", video_id="abc")
    assert caught.value.available == (
        "248 webm vp9 1080p25 (WebM)",
        "251 webm opus 44.1kHz (WebM)",
    )
    assert caught.value.video_id == "abc"
    only_av1 = streams(video(399, "av01.0.08M.08", 1920, 1080), audio(140))
    with pytest.raises(FormatNotAvailable, match=r"has no H\.264 video up to 1080p"):
        choose_streams(only_av1, container="mp4", quality="compat", video_id="abc")


def test_live_streams_and_empty_lists_have_their_own_message() -> None:
    live = streams(
        video(137, "avc1.640028", 1920, 1080, targetDurationSec=5),
        audio(140, targetDurationSec=5),
    )
    with pytest.raises(FormatNotAvailable, match="is a live stream"):
        choose_streams(live, container="mp4", quality="compat", video_id="abc")
    with pytest.raises(FormatNotAvailable, match="offered no streams"):
        choose_streams((), container="m4a", quality="compat", video_id="abc")


def test_expiry_and_user_agent_come_from_the_url() -> None:
    (stream,) = streams(video(137, "avc1.640028", 1920, 1080))
    assert stream.expires_at == 1790604050
    assert stream.user_agent == IOS.user_agent
    unknown_client = {
        **video(137, "avc1.640028", 1920, 1080),
        "url": "https://rr1.googlevideo.com/videoplayback?c=TVHTML5",
    }
    (other,) = streams(unknown_client)
    assert (other.expires_at, other.user_agent) == (None, DESKTOP_USER_AGENT)


def test_malformed_entries_are_skipped() -> None:
    found = parse_streams(
        {
            "formats": "not a list",
            "adaptiveFormats": [
                {"itag": 1},
                {"mimeType": 'video/mp4; codecs="avc1"'},
                {"itag": True, "mimeType": 'video/mp4; codecs="avc1"'},
                {"itag": 2, "mimeType": "text/plain"},
                "not a dict",
                {
                    "itag": "3",
                    "mimeType": 'audio/mp4; codecs="mp4a.40.2"',
                    "bitrate": "fast",
                    "width": 1.5,
                },
            ],
        }
    )
    assert [stream.format.itag for stream in found] == [3]
    assert (found[0].format.bitrate, found[0].format.width) == (0, None)


def test_describe_stream() -> None:
    (webm,) = streams(video(248, "vp9", 1920, 1080))
    assert describe_stream(webm) == "248 webm vp9 1080p25 (WebM)"
    (usable,) = streams(audio(140))
    assert describe_stream(usable) == "140 mp4 aac 44.1kHz"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_streams.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'utmax.core.streams'`.

- [ ] **Step 4: Add the profile table**

In `src/utmax/core/clients.py`, add `"PROFILES"` to `__all__` right after `"ORDER"`, and append:

```python
PROFILES: Mapping[str, ClientProfile] = MappingProxyType(
    {profile.name: profile for profile in (ANDROID, IOS, ANDROID_VR, WEB)}
)
```

- [ ] **Step 5: Write `src/utmax/core/streams.py`**

```python
"""Read the streams of a player response and choose the ones to download.

YouTube lists every stream of a video in ``streamingData``: progressive ``formats`` (audio and
video together, at most 360p) and ``adaptiveFormats`` (video-only or audio-only). utmax
downloads one adaptive MP4 video stream and one AAC audio stream and muxes them itself.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit

from utmax.core.clients import DESKTOP_USER_AGENT, PROFILES
from utmax.core.ytdata import items, mapping
from utmax.errors import FormatNotAvailable
from utmax.models import Codec, Container, Format, Quality

__all__ = [
    "COMPAT_MAX_SIDE",
    "MAX_MAX_SIDE",
    "QUICKTIME_MAX_RATE",
    "Stream",
    "choose_streams",
    "describe_stream",
    "parse_streams",
]

COMPAT_MAX_SIDE = 1080
MAX_MAX_SIDE = 2160
QUICKTIME_MAX_RATE = 65535
_MIME = re.compile(r'(video|audio)/(mp4|webm)\s*;\s*codecs="([^"]*)"')
_KINDS: Mapping[str, Literal["video", "audio"]] = {"video": "video", "audio": "audio"}
_CONTAINERS: Mapping[str, Literal["mp4", "webm"]] = {"mp4": "mp4", "webm": "webm"}
_HDR_TRANSFERS = frozenset(
    {"COLOR_TRANSFER_CHARACTERISTICS_SMPTEST2084", "COLOR_TRANSFER_CHARACTERISTICS_ARIB_STD_B67"}
)
_MUXABLE: frozenset[str] = frozenset({"h264", "av1", "aac", "he-aac"})


@dataclass(frozen=True, slots=True)
class Stream:
    """A format plus what downloading it takes; internal, because the URL is bound to your IP."""

    format: Format
    url: str = ""
    expires_at: int | None = None
    user_agent: str = DESKTOP_USER_AGENT
    bit_depth: int = 8
    hdr: bool = False
    drm: bool = False
    live: bool = False
    progressive: bool = False

    @property
    def problem(self) -> str | None:
        """Why utmax cannot download and mux this stream, or ``None`` when it can."""
        if self.drm:
            return "DRM-protected"
        if self.live:
            return "part of a live stream"
        if not self.url:
            return "needs a signature utmax cannot compute"
        if self.progressive:
            return "audio and video combined"
        if self.format.container != "mp4":
            return "WebM"
        if self.hdr or self.bit_depth > 8:
            return "HDR or more than 8 bits"
        if self.format.codec not in _MUXABLE:
            return f"{self.format.codec} codec"
        return None


def parse_streams(streaming_data: Mapping[str, Any]) -> tuple[Stream, ...]:
    """Every stream of ``streamingData`` with a known type, progressive ones first."""
    raws = [*items(streaming_data.get("formats")), *items(streaming_data.get("adaptiveFormats"))]
    parsed = (_stream(mapping(raw)) for raw in raws)
    return tuple(stream for stream in parsed if stream is not None)


def describe_stream(stream: Stream) -> str:
    """``"313 webm vp9 2160p25 (WebM)"``: the label, plus why the stream cannot be used."""
    problem = stream.problem
    return stream.format.label if problem is None else f"{stream.format.label} ({problem})"


def choose_streams(
    streams: Sequence[Stream], *, container: Container, quality: Quality, video_id: str
) -> tuple[Stream | None, Stream]:
    """The video stream (``None`` for audio files) and the audio stream to download.

    Video: MP4 H.264 up to 1080p for ``"compat"``; MP4 H.264 or 8-bit AV1 up to 2160p for
    ``"max"``, AV1 first at the same size; then the higher frame rate and bitrate. Sizes are
    measured on the short side, so vertical videos count like their landscape twins. Audio: MP4
    AAC, preferring the video's default audio track, then streams without dynamic range
    compression, then the higher bitrate; ``.mov`` accepts only stereo at most 65535 Hz.

    Raises:
        FormatNotAvailable: nothing fits; the error lists every stream YouTube offered.
    """
    usable = [stream for stream in streams if stream.problem is None]
    audio = _best_audio(usable, container)
    if audio is None:
        wanted = "stereo AAC audio (needed for .mov)" if container == "mov" else "AAC audio in MP4"
        raise _not_available(streams, wanted, video_id)
    if container in ("m4a", "mp3"):
        return None, audio
    video = _best_video(usable, quality)
    if video is None:
        wanted = (
            "H.264 or 8-bit AV1 video up to 2160p in MP4"
            if quality == "max"
            else "H.264 video up to 1080p in MP4"
        )
        raise _not_available(streams, wanted, video_id)
    return video, audio


def _best_video(streams: Sequence[Stream], quality: Quality) -> Stream | None:
    limit = MAX_MAX_SIDE if quality == "max" else COMPAT_MAX_SIDE
    codecs = ("h264", "av1") if quality == "max" else ("h264",)
    candidates = [
        stream
        for stream in streams
        if stream.format.kind == "video"
        and stream.format.codec in codecs
        and 0 < _short_side(stream.format) <= limit
    ]
    return max(
        candidates,
        key=lambda stream: (
            _short_side(stream.format),
            stream.format.codec == "av1",
            stream.format.fps or 0,
            stream.format.bitrate,
        ),
        default=None,
    )


def _best_audio(streams: Sequence[Stream], container: Container) -> Stream | None:
    candidates = [
        stream
        for stream in streams
        if stream.format.kind == "audio" and stream.format.codec in ("aac", "he-aac")
    ]
    if container == "mov":
        candidates = [
            stream
            for stream in candidates
            if (stream.format.audio_channels or 2) <= 2
            and (stream.format.audio_sample_rate or 0) <= QUICKTIME_MAX_RATE
        ]
    return max(
        candidates,
        key=lambda stream: (
            stream.format.is_default_audio,
            not stream.format.is_drc,
            stream.format.bitrate,
        ),
        default=None,
    )


def _short_side(fmt: Format) -> int:
    return min((n for n in (fmt.width, fmt.height) if n), default=0)


def _not_available(streams: Sequence[Stream], wanted: str, video_id: str) -> FormatNotAvailable:
    if streams and all(stream.live for stream in streams):
        message = f"Video {video_id} is a live stream; it can be downloaded after it ends."
    elif not streams:
        message = f"YouTube offered no streams for video {video_id}."
    else:
        message = f"Video {video_id} has no {wanted}."
    return FormatNotAvailable(
        message, available=[describe_stream(stream) for stream in streams], video_id=video_id
    )


def _stream(raw: Mapping[str, Any]) -> Stream | None:
    match = _MIME.match(str(raw.get("mimeType") or ""))
    itag = _int(raw.get("itag"))
    if match is None or itag is None:
        return None
    codecs = match[3].strip()
    first = codecs.split(",", maxsplit=1)[0].strip()
    url = raw["url"] if isinstance(raw.get("url"), str) else ""
    query = dict(parse_qsl(urlsplit(url).query))
    profile = PROFILES.get(query.get("c", ""))
    track = mapping(raw.get("audioTrack"))
    return Stream(
        format=Format(
            itag=itag,
            kind=_KINDS[match[1]],
            container=_CONTAINERS[match[2]],
            codec=_codec(first),
            codecs=codecs,
            width=_int(raw.get("width")),
            height=_int(raw.get("height")),
            fps=_int(raw.get("fps")),
            bitrate=_int(raw.get("bitrate")) or 0,
            content_length=_int(raw.get("contentLength")),
            audio_sample_rate=_int(raw.get("audioSampleRate")),
            audio_channels=_int(raw.get("audioChannels")),
            is_default_audio=bool(track.get("audioIsDefault", True)),
            is_drc=bool(raw.get("isDrc", False)),
            last_modified=str(raw.get("lastModified") or ""),
        ),
        url=url,
        expires_at=_int(query.get("expire")),
        user_agent=profile.user_agent if profile is not None else DESKTOP_USER_AGENT,
        bit_depth=_bit_depth(first),
        hdr=_is_hdr(raw),
        drm=bool(raw.get("drmFamilies")),
        live="targetDurationSec" in raw,
        progressive="," in codecs,
    )


def _codec(codec: str) -> Codec:
    family, _, rest = codec.lower().partition(".")
    if family == "avc1":
        return "h264"
    if family == "av01":
        return "av1"
    if family in ("vp9", "vp09"):
        return "vp9"
    if family == "opus":
        return "opus"
    if family == "mp4a" and rest.startswith("40."):
        return "he-aac" if rest in ("40.5", "40.29") else "aac"
    return "other"


def _bit_depth(codec: str) -> int:
    """The bit depth of AV1 (``av01.P.LLT.DD``) and VP9 (``vp09.PP.LL.DD``) codec strings."""
    parts = codec.lower().split(".")
    if parts[0] in ("av01", "vp09") and len(parts) > 3 and parts[3].isascii() and parts[3].isdigit():
        return int(parts[3])
    return 8


def _is_hdr(raw: Mapping[str, Any]) -> bool:
    transfer = mapping(raw.get("colorInfo")).get("transferCharacteristics")
    return transfer in _HDR_TRANSFERS or "HDR" in str(raw.get("qualityLabel") or "")


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_streams.py -q`
Expected: 39 passed.

- [ ] **Step 7: Teach the recorder to keep the stream list**

In `scripts/record_fixtures.py`, add below `KEPT_DETAILS`:

```python
KEPT_FORMAT_FIELDS = (
    "itag",
    "mimeType",
    "bitrate",
    "width",
    "height",
    "fps",
    "qualityLabel",
    "contentLength",
    "lastModified",
    "audioQuality",
    "audioSampleRate",
    "audioChannels",
    "isDrc",
    "audioTrack",
    "colorInfo",
    "drmFamilies",
    "targetDurationSec",
)
```

add these functions after `trim_player`:

```python
def trim_format(raw: dict[str, Any]) -> dict[str, Any]:
    """The fields utmax reads; the URL becomes a placeholder keeping only the itag and client."""
    trimmed = {key: raw[key] for key in KEPT_FORMAT_FIELDS if key in raw}
    if "url" in raw:
        client = dict(parse_qsl(urlsplit(raw["url"]).query)).get("c", "")
        trimmed["url"] = (
            "https://redacted.googlevideo.com/videoplayback"
            f"?expire=REDACTED&itag={raw['itag']}&c={client}"
        )
    if "signatureCipher" in raw or "cipher" in raw:
        trimmed["signatureCipher"] = "REDACTED"
    return trimmed


def streams_fixture(data: dict[str, Any]) -> str:
    """``streamingData`` with one format per line (``serverAbrStreamingUrl`` is dropped)."""
    streaming = data.get("streamingData", {})
    expires = json.dumps(streaming.get("expiresInSeconds", ""))
    lines = ["{", ' "streamingData": {', f'  "expiresInSeconds": {expires},']
    for key in ("formats", "adaptiveFormats"):
        entries = [json.dumps(trim_format(raw), ensure_ascii=False) for raw in streaming.get(key, [])]
        lines.append(f'  "{key}": [')
        lines.extend(f"   {entry}," for entry in entries[:-1])
        lines.extend(f"   {entry}" for entry in entries[-1:])
        lines.append("  ]," if key == "formats" else "  ]")
    lines += [" }", "}"]
    return "\n".join(lines) + "\n"
```

and in `main()`, right after the loop that writes the three `player_*.json` files:

```python
    write("streams_android_vr.json", streams_fixture(players["android_vr"]))
```

Replace the `write("README.md", ...)` call at the end of `main()` with:

```python
    write(
        "README.md",
        f"# YouTube fixtures\n\nRecorded {date.today().isoformat()} from video `{VIDEO_ID}` with\n"
        "`uv run python scripts/record_fixtures.py`. URL parameters "
        f"{', '.join(sorted(SECRET_PARAMS))} are replaced with `REDACTED`.\n"
        "`streams_android_vr.json` keeps only the stream fields utmax reads; its URLs are\n"
        "placeholders that keep the itag and the client name.\n",
    )
```

Do **not** run the recorder (it would re-record every fixture). Update `tests/fixtures/youtube/README.md` by hand to the same text, keeping its existing date line and adding the two new lines.

- [ ] **Step 8: Gates and commit**

Run the four gates (the suite grows by 39).

```bash
git add src/utmax/core/streams.py src/utmax/core/clients.py tests/unit/core/test_streams.py tests/fixtures/youtube/streams_android_vr.json tests/fixtures/youtube/README.md tests/helpers/youtube.py scripts/record_fixtures.py
git commit -m "feat: parse YouTube's stream list and choose what to download" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 3: Streams in the player response

**Files:**
- Modify: `src/utmax/core/player.py`, `src/utmax/adapters/innertube.py`, `src/utmax/services/transcripts.py`, `tests/helpers/youtube.py`
- Test: `tests/unit/core/test_player.py`, `tests/unit/adapters/test_innertube.py`, `tests/unit/services/test_transcripts.py` (append)

**Interfaces:**
- Consumes: `parse_streams`, `Stream` (Task 2).
- Produces:
  - `PlayerData.streams: tuple[Stream, ...] = ()` (new last field), filled from `streamingData`.
  - `InnerTubeClient.player(video_id, purpose="streams")` moves on to the next profile when a response has no direct MP4 stream URL (raises `YouTubeDataUnparsable` "… no direct MP4 stream URLs …" when even the watch-page fallback has none). Other purposes are unchanged.
  - `TranscriptService.track_list(player: PlayerData) -> TrackList` — the tracks of an already fetched player response, bound to the service for fetching (empty when the video has no captions). `list_tracks` uses it.
  - `tests.helpers.youtube.player_payload(..., streaming_data: dict[str, Any] | None = None)`.

- [ ] **Step 1: Let the test payload carry streams**

In `tests/helpers/youtube.py`, add the keyword parameter `streaming_data: dict[str, Any] | None = None` to `player_payload` (after `length_seconds`) and, just before `return payload`:

```python
    if streaming_data is not None:
        payload["streamingData"] = streaming_data
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/unit/core/test_player.py` (add `from tests.helpers.youtube import streaming_data` to its imports):

```python
def test_streams_are_parsed_from_streaming_data() -> None:
    payload = player_payload(streaming_data=streaming_data())
    player = parse_player_response(payload, video_id=VIDEO_ID)
    assert len(player.streams) == 27
    assert player.streams[0].format.itag == 18


def test_players_without_streaming_data_have_no_streams() -> None:
    assert parse_player_response(player_payload(), video_id=VIDEO_ID).streams == ()
```

Append to `tests/unit/adapters/test_innertube.py` (add `from typing import Any` and `from tests.helpers.youtube import streaming_data` to its imports):

```python
def streams_payload(*, direct: bool) -> dict[str, Any]:
    data = streaming_data()
    if not direct:
        ciphered = [
            {key: value for key, value in entry.items() if key != "url"}
            | {"signatureCipher": "s=1"}
            for entry in data["adaptiveFormats"]
        ]
        data = {**data, "formats": [], "adaptiveFormats": ciphered}
    return player_payload(streaming_data=data)


def test_stream_players_skip_profiles_without_direct_mp4_urls() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        "/youtubei/v1/player",
        json_response(streams_payload(direct=False)),
        json_response(streams_payload(direct=True)),
    )
    player = InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert client_names(transport) == ["ANDROID_VR", "ANDROID"]
    assert any(stream.url for stream in player.streams)


def test_stream_players_fall_back_to_the_watch_page_then_give_up() -> None:
    transport = FakeTransport()
    transport.add(
        "POST", "/youtubei/v1/player", json_response(streams_payload(direct=False)), repeat=True
    )
    transport.add("GET", "/watch", text_response(WATCH_HTML))
    with pytest.raises(YouTubeDataUnparsable, match="no direct MP4 stream URLs"):
        InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert client_names(transport) == ["ANDROID_VR", "ANDROID", "IOS", "ANDROID"]


def test_caption_players_do_not_need_streams() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(player_payload()))
    assert InnerTubeClient(transport).player(VIDEO_ID).streams == ()


def test_a_bot_check_on_one_stream_profile_moves_on_to_the_next() -> None:
    blocked = player_payload(status="LOGIN_REQUIRED", reason="Sign in to confirm you're not a bot")
    transport = FakeTransport()
    transport.add(
        "POST",
        "/youtubei/v1/player",
        json_response(blocked),
        json_response(streams_payload(direct=True)),
    )
    InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert client_names(transport) == ["ANDROID_VR", "ANDROID"]
```

Append to `tests/unit/services/test_transcripts.py` (add `from tests.helpers.fake_transport import FakeTransport, json_response` if missing):

```python
def test_track_list_reuses_a_player_response_without_another_request() -> None:
    transport = standard_youtube()
    innertube = InnerTubeClient(transport)
    tracks = TranscriptService(innertube).track_list(innertube.player(VIDEO_ID))
    assert len(tracks) == 6
    assert len(transport.urls("POST")) == 1
    assert tracks[0].fetch().language_code == "en"


def test_track_list_is_empty_without_captions() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(player_payload(captions=False)))
    innertube = InnerTubeClient(transport)
    assert len(TranscriptService(innertube).track_list(innertube.player(VIDEO_ID))) == 0
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_player.py tests/unit/adapters/test_innertube.py tests/unit/services/test_transcripts.py -q`
Expected: 7 failed (`AttributeError: 'PlayerData' object has no attribute 'streams'`, `'TranscriptService' object has no attribute 'track_list'`, the first profile's ciphered response accepted); `test_a_bot_check_on_one_stream_profile_moves_on_to_the_next` already passes — it pins existing behaviour for the streams order.

- [ ] **Step 4: Parse the streams**

In `src/utmax/core/player.py`, import `from utmax.core.streams import Stream, parse_streams`, add the last field to `PlayerData`:

```python
    streams: tuple[Stream, ...] = ()
```

and pass it in `parse_player_response`:

```python
    return PlayerData(
        video=video,
        playability=parse_playability(data),
        caption_tracks=tracks or None,
        translation_languages=languages if tracks else (),
        streams=parse_streams(mapping(data.get("streamingData"))),
    )
```

- [ ] **Step 5: Require direct MP4 URLs when streams are the purpose**

In `src/utmax/adapters/innertube.py`, pass the purpose through (keyword-only) in both places `player()` builds a `partial`:

```python
                return self._with_block_retries(
                    partial(self._playable, profile, video_id, None, purpose=purpose)
                )
```

```python
            return self._with_block_retries(
                partial(self._playable, ANDROID, video_id, api_key, purpose=purpose)
            )
```

extend the `player()` docstring with "For ``"streams"``, a response without a direct MP4 stream URL counts as a failed profile." and replace `_playable` with:

```python
    def _playable(
        self, profile: ClientProfile, video_id: str, api_key: str | None, *, purpose: Purpose
    ) -> PlayerData:
        data = self.player_json(profile, video_id, api_key=api_key)
        player = parse_player_response(data, video_id=video_id)
        check_playability(player.playability, video_id=video_id)
        if purpose == "streams" and not any(
            stream.url and stream.format.container == "mp4" and not stream.drm
            for stream in player.streams
        ):
            raise YouTubeDataUnparsable(
                f"The {profile.name} client returned no direct MP4 stream URLs for {video_id}.",
                video_id=video_id,
            )
        return player
```

- [ ] **Step 6: Build track lists from a player response**

In `src/utmax/services/transcripts.py`, import `PlayerData` from `utmax.core.player` and replace `list_tracks` with:

```python
    def list_tracks(self, video: str) -> TrackList:
        video_id = parse_video_id(video)
        tracks = self.track_list(self._innertube.player(video_id, purpose="captions"))
        if not tracks:
            raise TranscriptsDisabled(f"Video {video_id} has no subtitles.", video_id=video_id)
        return tracks

    def track_list(self, player: PlayerData) -> TrackList:
        """The tracks of an already fetched player response, bound to this service."""
        tracks = tuple(
            Track(
                video=player.video,
                language_code=info.language_code,
                language=info.name,
                is_generated=info.is_generated,
                is_translatable=info.is_translatable,
                vss_id=info.vss_id,
                _url=info.base_url,
                _translation_languages=player.translation_languages,
                _fetcher=self,
            )
            for info in player.caption_tracks or ()
        )
        return TrackList(
            video=player.video, tracks=tracks, translation_languages=player.translation_languages
        )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_player.py tests/unit/adapters/test_innertube.py tests/unit/services/test_transcripts.py -q`
Expected: all pass (8 new).

- [ ] **Step 8: Gates and commit**

Run the four gates (the suite grows by 8).

```bash
git add src/utmax/core/player.py src/utmax/adapters/innertube.py src/utmax/services/transcripts.py tests/helpers/youtube.py tests/unit/core/test_player.py tests/unit/adapters/test_innertube.py tests/unit/services/test_transcripts.py
git commit -m "feat: read streams from player responses and fall back when URLs are missing" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Chunk, resume-state and rate arithmetic

**Files:**
- Create: `src/utmax/core/downloads.py`, `tests/unit/core/test_downloads.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (in `utmax.core.downloads`):
  - `MIB = 1 << 20`, `DEFAULT_CHUNK_SIZE = 8 * MIB`, `MIN_CHUNK_SIZE = 256 * 1024`, `REFRESH_MARGIN = 300.0`.
  - `Chunk(index, start, end)` (end exclusive) with `.size`; `plan_chunks(size, chunk_size) -> tuple[Chunk, ...]` (one chunk under two chunk sizes, none for size 0).
  - `range_header(start, end) -> str` (`"bytes=start-(end-1)"`); `content_range_total(value: str | None) -> int | None`.
  - `expires_soon(expires_at: int | None, now: float, margin: float = REFRESH_MARGIN) -> bool`.
  - `PartState(video_id, itag, content_length, last_modified, chunk_size, completed=frozenset())` with `to_json()`, `from_json(text) -> PartState | None` (classmethod), `matches(other) -> bool`.
  - `RateMeter(window=5.0).update(now, done, total) -> tuple[float | None, float | None]` (speed, seconds left).
  - `Throttle(interval=0.25).ready(now, *, force=False) -> bool`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/core/test_downloads.py`:

```python
"""Tests for chunk, resume-state and rate arithmetic."""

from __future__ import annotations

from itertools import pairwise

import pytest

from utmax.core.downloads import (
    MIB,
    Chunk,
    PartState,
    RateMeter,
    Throttle,
    content_range_total,
    expires_soon,
    plan_chunks,
    range_header,
)

STATE = PartState("dQw4w9WgXcQ", 137, 80_911_999, "1766957926174250", 8 * MIB, frozenset({0, 2}))


@pytest.mark.parametrize(
    ("size", "chunk_size", "expected"),
    [
        (0, 8, ()),
        (1, 8, (Chunk(0, 0, 1),)),
        (15, 8, (Chunk(0, 0, 15),)),
        (16, 8, (Chunk(0, 0, 8), Chunk(1, 8, 16))),
        (17, 8, (Chunk(0, 0, 8), Chunk(1, 8, 16), Chunk(2, 16, 17))),
    ],
)
def test_plan_chunks(size: int, chunk_size: int, expected: tuple[Chunk, ...]) -> None:
    assert plan_chunks(size, chunk_size) == expected


def test_chunks_tile_large_streams_exactly() -> None:
    chunks = plan_chunks(80_911_999, 8 * MIB)
    assert len(chunks) == 10
    assert chunks[0] == Chunk(0, 0, 8 * MIB)
    assert chunks[-1].end == 80_911_999
    assert all(first.end == second.start for first, second in pairwise(chunks))
    assert sum(chunk.size for chunk in chunks) == 80_911_999


def test_range_header() -> None:
    assert range_header(0, 1) == "bytes=0-0"
    assert range_header(8, 16) == "bytes=8-15"


@pytest.mark.parametrize(
    ("value", "total"),
    [
        ("bytes 0-0/3449447", 3449447),
        ("bytes */500", 500),
        ("BYTES 1-2/3", 3),
        ("bytes 0-0/*", None),
        ("items 0-0/5", None),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_content_range_total(value: str | None, total: int | None) -> None:
    assert content_range_total(value) == total


def test_expires_soon() -> None:
    assert expires_soon(1000, 701)
    assert not expires_soon(1000, 700)
    assert not expires_soon(None, 10.0**12)
    assert expires_soon(1000, 950, margin=60)


def test_part_state_round_trips_as_compact_json() -> None:
    text = STATE.to_json()
    assert text == (
        '{"version":1,"video_id":"dQw4w9WgXcQ","itag":137,"content_length":80911999,'
        '"last_modified":"1766957926174250","chunk_size":8388608,"completed":[0,2]}'
    )
    assert PartState.from_json(text) == STATE


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        '{"version": 2}',
        '{"version":1,"video_id":"v","itag":"x","content_length":1,"last_modified":"",'
        '"chunk_size":1,"completed":[]}',
        '{"version":1,"video_id":"v","itag":1,"content_length":1,"last_modified":"",'
        '"chunk_size":1}',
        '{"version":1,"video_id":"v","itag":1,"content_length":1,"last_modified":"",'
        '"chunk_size":1,"completed":5}',
    ],
)
def test_damaged_state_files_are_ignored(text: str) -> None:
    assert PartState.from_json(text) is None


def test_states_match_only_for_the_same_stream_and_chunking() -> None:
    assert STATE.matches(PartState("dQw4w9WgXcQ", 137, 80_911_999, "1766957926174250", 8 * MIB))
    for other in (
        PartState("otherVideo1", 137, 80_911_999, "1766957926174250", 8 * MIB),
        PartState("dQw4w9WgXcQ", 136, 80_911_999, "1766957926174250", 8 * MIB),
        PartState("dQw4w9WgXcQ", 137, 80_911_998, "1766957926174250", 8 * MIB),
        PartState("dQw4w9WgXcQ", 137, 80_911_999, "1766957926174251", 8 * MIB),
        PartState("dQw4w9WgXcQ", 137, 80_911_999, "1766957926174250", 4 * MIB),
    ):
        assert not STATE.matches(other)


def test_rate_meter_measures_speed_and_time_left() -> None:
    meter = RateMeter(window=5.0)
    assert meter.update(0.0, 0, 1000) == (None, None)
    assert meter.update(1.0, 100, 1000) == (100.0, 9.0)
    assert meter.update(2.0, 250, 1000) == (125.0, 6.0)
    assert meter.update(3.0, 300, None) == (100.0, None)


def test_rate_meter_forgets_samples_older_than_its_window() -> None:
    meter = RateMeter(window=2.0)
    meter.update(0.0, 0, None)
    meter.update(1.0, 1000, None)
    meter.update(2.0, 1100, None)
    assert meter.update(3.0, 1200, None) == (100.0, None)


def test_throttle_lets_one_event_through_per_interval() -> None:
    throttle = Throttle(0.25)
    assert throttle.ready(10.0)
    assert not throttle.ready(10.1)
    assert throttle.ready(10.25)
    assert not throttle.ready(10.3)
    assert throttle.ready(10.3, force=True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_downloads.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'utmax.core.downloads'`.

- [ ] **Step 3: Write `src/utmax/core/downloads.py`**

```python
"""Pure arithmetic of parallel, resumable downloads: chunks, saved state, speed and throttling."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "MIB",
    "MIN_CHUNK_SIZE",
    "REFRESH_MARGIN",
    "Chunk",
    "PartState",
    "RateMeter",
    "Throttle",
    "content_range_total",
    "expires_soon",
    "plan_chunks",
    "range_header",
]

MIB = 1 << 20
DEFAULT_CHUNK_SIZE = 8 * MIB
MIN_CHUNK_SIZE = 256 * 1024
REFRESH_MARGIN = 300.0
_STATE_VERSION = 1


@dataclass(frozen=True, slots=True)
class Chunk:
    """Bytes ``start`` to ``end`` (exclusive) of one stream."""

    index: int
    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start


def plan_chunks(size: int, chunk_size: int) -> tuple[Chunk, ...]:
    """Split ``size`` bytes into ``chunk_size`` pieces; streams under two pieces stay whole."""
    if size <= 0:
        return ()
    if size < 2 * chunk_size:
        return (Chunk(0, 0, size),)
    return tuple(
        Chunk(index, start, min(start + chunk_size, size))
        for index, start in enumerate(range(0, size, chunk_size))
    )


def range_header(start: int, end: int) -> str:
    """The ``Range`` header value for bytes ``start`` to ``end`` (exclusive)."""
    return f"bytes={start}-{end - 1}"


def content_range_total(value: str | None) -> int | None:
    """The total size in ``Content-Range: bytes 0-0/12345`` (or ``bytes */12345``)."""
    if not value:
        return None
    unit, _, rest = value.strip().partition(" ")
    total = rest.rpartition("/")[2]
    if unit.lower() != "bytes" or not (total.isascii() and total.isdigit()):
        return None
    return int(total)


def expires_soon(expires_at: int | None, now: float, margin: float = REFRESH_MARGIN) -> bool:
    """True when a URL expiring at ``expires_at`` (Unix seconds) has less than ``margin`` left."""
    return expires_at is not None and expires_at - now < margin


@dataclass(frozen=True, slots=True)
class PartState:
    """What a ``.part`` file holds; saved next to it as ``.part.json``."""

    video_id: str
    itag: int
    content_length: int
    last_modified: str
    chunk_size: int
    completed: frozenset[int] = frozenset()

    def to_json(self) -> str:
        """Compact JSON, finished chunk numbers sorted."""
        return json.dumps(
            {
                "version": _STATE_VERSION,
                "video_id": self.video_id,
                "itag": self.itag,
                "content_length": self.content_length,
                "last_modified": self.last_modified,
                "chunk_size": self.chunk_size,
                "completed": sorted(self.completed),
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, text: str) -> PartState | None:
        """The state saved in ``text``; ``None`` when it is damaged or from another version."""
        try:
            data = json.loads(text)
        except ValueError:
            return None
        if not isinstance(data, dict) or data.get("version") != _STATE_VERSION:
            return None
        try:
            return cls(
                video_id=str(data["video_id"]),
                itag=int(data["itag"]),
                content_length=int(data["content_length"]),
                last_modified=str(data["last_modified"]),
                chunk_size=int(data["chunk_size"]),
                completed=frozenset(int(index) for index in data["completed"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def matches(self, other: PartState) -> bool:
        """Same video, stream, size, version and chunking, so finished chunks can be reused."""
        return self._identity == other._identity

    @property
    def _identity(self) -> tuple[str, int, int, str, int]:
        return (self.video_id, self.itag, self.content_length, self.last_modified, self.chunk_size)


class RateMeter:
    """Download speed over the last ``window`` seconds, and the time left at that speed."""

    def __init__(self, window: float = 5.0) -> None:
        self._window = window
        self._samples: deque[tuple[float, int]] = deque()

    def update(self, now: float, done: int, total: int | None) -> tuple[float | None, float | None]:
        """Record ``done`` bytes at ``now``; return (bytes per second, seconds left)."""
        self._samples.append((now, done))
        while len(self._samples) > 2 and now - self._samples[1][0] >= self._window:
            self._samples.popleft()
        start, first = self._samples[0]
        if now <= start:
            return None, None
        speed = (done - first) / (now - start)
        if total is None or speed <= 0:
            return speed, None
        return speed, max(0.0, (total - done) / speed)


class Throttle:
    """Lets an event through at most once per ``interval`` seconds; the first always passes."""

    def __init__(self, interval: float = 0.25) -> None:
        self._interval = interval
        self._last: float | None = None

    def ready(self, now: float, *, force: bool = False) -> bool:
        if force or self._last is None or now - self._last >= self._interval:
            self._last = now
            return True
        return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_downloads.py -q`
Expected: 28 passed.

- [ ] **Step 5: Gates and commit**

Run the four gates (the suite grows by 28; `utmax.core.downloads` must show 100 % coverage).

```bash
git add src/utmax/core/downloads.py tests/unit/core/test_downloads.py
git commit -m "feat: add chunk, resume-state and rate arithmetic for downloads" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: File names and download targets

**Files:**
- Create: `src/utmax/core/filenames.py`, `tests/unit/core/test_filenames.py`

**Interfaces:**
- Consumes: `Container`, `VideoInfo` (models); `InvalidOption`, `UnsupportedFormat` (errors).
- Produces (in `utmax.core.filenames`):
  - `MAX_NAME_CHARS = 150`, `MAX_NAME_BYTES = 180`.
  - `safe_name(text, *, max_chars=MAX_NAME_CHARS, max_bytes=MAX_NAME_BYTES) -> str`.
  - `default_filename(video: VideoInfo, ext: str) -> str` (`"{title} [{video_id}].{ext}"`).
  - `Target(container, file=None, folder=None)` with `path_for(video) -> PurePath`.
  - `resolve_target(path, *, format: Container | None, is_dir: bool) -> Target`.
  - `sidecar_name(media: PurePath, language_code: str) -> PurePath`; `part_name(target: PurePath, itag: int) -> PurePath`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/core/test_filenames.py`:

```python
"""Tests for safe file names and download targets."""

from __future__ import annotations

from dataclasses import replace
from pathlib import PurePath

import pytest

from tests.helpers.builders import VIDEO
from utmax.core.filenames import (
    MAX_NAME_BYTES,
    Target,
    default_filename,
    part_name,
    resolve_target,
    safe_name,
    sidecar_name,
)
from utmax.errors import InvalidOption, UnsupportedFormat
from utmax.models import Container

TITLE = "Rick Astley - Never Gonna Give You Up (Official Video)"
TURKISH = "\xc7ok g\xfczel \U0000015fark\U00000131 \U0001F3B5"


@pytest.mark.parametrize(
    ("text", "safe"),
    [
        (TITLE, TITLE),
        ("AC/DC: Live at River Plate", "AC_DC_ Live at River Plate"),
        ('a<b>c"d|e?f*g\\h', "a_b_c_d_e_f_g_h"),
        ("tabs\tand\nnew  lines", "tabs and new lines"),
        ("\x00bell\x07", "_bell_"),
        ("  Ends with dots...  ", "Ends with dots"),
        ("...", ""),
        ("", ""),
        ("CON", "_CON"),
        ("nul.txt", "_nul.txt"),
        ("com1", "_com1"),
        ("Concert", "Concert"),
        (TURKISH, TURKISH),
        ("Cafe\U00000301", "Caf\xe9"),
    ],
)
def test_safe_name(text: str, safe: str) -> None:
    assert safe_name(text) == safe


@pytest.mark.parametrize(
    ("text", "length"),
    [("a" * 300, 150), ("\U0001F3B5" * 100, 45), ("\U0000015f" * 150, 90)],
)
def test_long_names_are_cut_by_characters_and_bytes(text: str, length: int) -> None:
    safe = safe_name(text)
    assert len(safe) == length
    assert len(safe.encode("utf-8")) <= MAX_NAME_BYTES


def test_cutting_never_leaves_a_trailing_dot_or_space() -> None:
    assert safe_name("a" * 149 + ". tail") == "a" * 149


def test_default_filename() -> None:
    assert default_filename(VIDEO, "mp4") == f"{TITLE} [dQw4w9WgXcQ].mp4"
    assert default_filename(replace(VIDEO, title="AC/DC?"), "mp3") == "AC_DC_ [dQw4w9WgXcQ].mp3"
    assert default_filename(replace(VIDEO, title=" ... "), "m4a") == "dQw4w9WgXcQ.m4a"


@pytest.mark.parametrize(
    ("path", "fmt", "is_dir", "expected"),
    [
        ("rick.mp4", None, False, Target("mp4", file=PurePath("rick.mp4"))),
        ("RICK.MOV", None, False, Target("mov", file=PurePath("RICK.MOV"))),
        ("song.mp3", "mp3", False, Target("mp3", file=PurePath("song.mp3"))),
        ("rick", "m4a", False, Target("m4a", file=PurePath("rick.m4a"))),
        ("My.Video", "mp4", False, Target("mp4", file=PurePath("My.Video.mp4"))),
        ("downloads/", None, False, Target("mp4", folder=PurePath("downloads"))),
        ("downloads", "m4a", True, Target("m4a", folder=PurePath("downloads"))),
        ("", None, False, Target("mp4", folder=PurePath("."))),
    ],
)
def test_resolve_target(
    path: str, fmt: Container | None, is_dir: bool, expected: Target
) -> None:
    assert resolve_target(path, format=fmt, is_dir=is_dir) == expected


@pytest.mark.parametrize(
    ("path", "fmt", "error", "match"),
    [
        ("notes.txt", None, UnsupportedFormat, "Cannot tell the file type"),
        ("song.mp3", "m4a", InvalidOption, "does not match the file name"),
        ("video.mp4", "avi", InvalidOption, "is not a download format"),
    ],
)
def test_bad_targets(path: str, fmt: str | None, error: type[Exception], match: str) -> None:
    with pytest.raises(error, match=match):
        resolve_target(path, format=fmt, is_dir=False)


def test_folder_targets_are_named_after_the_video() -> None:
    target = resolve_target("out/", format="mp3", is_dir=False)
    assert target.path_for(VIDEO) == PurePath("out") / f"{TITLE} [dQw4w9WgXcQ].mp3"
    assert Target("mp4", file=PurePath("x.mp4")).path_for(VIDEO) == PurePath("x.mp4")


def test_sidecar_and_part_names() -> None:
    media = PurePath("out") / "rick.mp4"
    assert sidecar_name(media, "tr") == PurePath("out") / "rick.tr.srt"
    assert sidecar_name(media, "en+tr") == PurePath("out") / "rick.en+tr.srt"
    assert part_name(media, 137) == PurePath("out") / "rick.mp4.137.part"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_filenames.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'utmax.core.filenames'`.

- [ ] **Step 3: Write `src/utmax/core/filenames.py`**

```python
"""Safe file names, and where ``download(video, path)`` writes its files."""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePath

from utmax.errors import InvalidOption, UnsupportedFormat
from utmax.models import Container, VideoInfo

__all__ = [
    "MAX_NAME_BYTES",
    "MAX_NAME_CHARS",
    "Target",
    "default_filename",
    "part_name",
    "resolve_target",
    "safe_name",
    "sidecar_name",
]

MAX_NAME_CHARS = 150
MAX_NAME_BYTES = 180
_SUFFIXES: dict[str, Container] = {".mp4": "mp4", ".mov": "mov", ".m4a": "m4a", ".mp3": "mp3"}
_WHITESPACE = re.compile(r"\s+")
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"{name}{n}" for name in ("COM", "LPT") for n in range(1, 10)}
)


def safe_name(
    text: str, *, max_chars: int = MAX_NAME_CHARS, max_bytes: int = MAX_NAME_BYTES
) -> str:
    """``text`` made safe as (part of) a file name on Windows, macOS and Linux.

    Accents are composed (NFC); runs of whitespace become one space; ``<>:"/\\|?*`` and other
    control characters become ``_``; leading and trailing dots and spaces go; the result is cut
    to ``max_chars`` characters and ``max_bytes`` UTF-8 bytes (Linux allows 255 bytes per name,
    the rest is left for suffixes); Windows device names such as ``CON`` or ``com1.txt`` get a
    leading ``_``. The result may be empty.
    """
    text = unicodedata.normalize("NFC", text)
    text = _FORBIDDEN.sub("_", _WHITESPACE.sub(" ", text))
    text = _shorten(text.strip(". "), max_chars, max_bytes).strip(". ")
    if text.split(".", maxsplit=1)[0].upper() in _DEVICE_NAMES:
        text = f"_{text}"
    return text


def default_filename(video: VideoInfo, ext: str) -> str:
    """``"{title} [{video_id}].{ext}"`` with a safe title; ``"{video_id}.{ext}"`` without one."""
    title = safe_name(video.title)
    return f"{title} [{video.video_id}].{ext}" if title else f"{video.video_id}.{ext}"


@dataclass(frozen=True, slots=True)
class Target:
    """Where a download goes: the caller's file name, or a folder plus the video's title."""

    container: Container
    file: PurePath | None = None
    folder: PurePath | None = None

    def path_for(self, video: VideoInfo) -> PurePath:
        """The output file for ``video``."""
        if self.file is not None:
            return self.file
        return (self.folder or PurePath(".")) / default_filename(video, self.container)


def resolve_target(
    path: str | os.PathLike[str], *, format: Container | None, is_dir: bool
) -> Target:
    """Decide the container and output name of ``download(video, path, format=...)``.

    ``path`` is a folder when ``is_dir`` (it exists as a directory), when it is empty, or when
    it ends with a path separator; the file is then named ``"{title} [{video_id}].{ext}"``
    inside it and the container is ``format`` (default ``"mp4"``). Otherwise the extension
    picks the container; ``format`` must agree with it, and is appended when ``path`` has no
    known extension.

    Raises:
        InvalidOption: ``format`` is unknown or contradicts the extension.
        UnsupportedFormat: the extension is not .mp4, .mov, .m4a or .mp3 and no format was given.
    """
    if format is not None and format not in _SUFFIXES.values():
        raise InvalidOption(
            f"format={format!r} is not a download format; use mp4, mov, m4a or mp3.",
            suggestion='Pass format="mp4", "mov", "m4a" or "mp3", or leave it out.',
        )
    text = os.fspath(path)
    pure = PurePath(text)
    if is_dir or not pure.name or text.endswith(("/", "\\")):
        return Target(format or "mp4", folder=pure)
    container = _SUFFIXES.get(pure.suffix.lower())
    if container is None:
        if format is None:
            raise UnsupportedFormat(
                f"Cannot tell the file type from {pure.name!r}.",
                suggestion=(
                    'Use a .mp4, .mov, .m4a or .mp3 file name or a folder, or pass format="mp4".'
                ),
            )
        return Target(format, file=pure.with_name(f"{pure.name}.{format}"))
    if format is not None and format != container:
        raise InvalidOption(
            f"format={format!r} does not match the file name {pure.name!r}.",
            suggestion="Leave format out, or give the file the matching extension.",
        )
    return Target(container, file=pure)


def sidecar_name(media: PurePath, language_code: str) -> PurePath:
    """``rick.mp4`` + ``"tr"`` gives ``rick.tr.srt``; ``"en+tr"`` gives ``rick.en+tr.srt``."""
    code = safe_name(language_code, max_chars=35, max_bytes=35)
    return media.with_name(f"{media.stem}.{code}.srt")


def part_name(target: PurePath, itag: int) -> PurePath:
    """Where stream ``itag`` of ``target`` is downloaded: ``rick.mp4`` gives ``rick.mp4.137.part``."""
    return target.with_name(f"{target.name}.{itag}.part")


def _shorten(text: str, max_chars: int, max_bytes: int) -> str:
    text = text[:max_chars]
    while len(text.encode("utf-8")) > max_bytes:
        text = text[:-1]
    return text
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_filenames.py -q`
Expected: 32 passed.

- [ ] **Step 5: Gates and commit**

Run the four gates (the suite grows by 32).

```bash
git add src/utmax/core/filenames.py tests/unit/core/test_filenames.py
git commit -m "feat: add safe file names and download targets" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Streamed responses and IPv4-only connections

**Files:**
- Modify: `src/utmax/transport.py`, `src/utmax/adapters/http.py`, `src/utmax/client.py`, `tests/helpers/http_server.py`
- Test: `tests/unit/adapters/test_http_stream.py`

**Interfaces:**
- Consumes: `NetworkError`, the existing `UrllibTransport`/`RetryingTransport`.
- Produces:
  - `utmax.transport.HttpStream` (runtime-checkable protocol: `status`, `header(name)`, `read(n)`, `close()`; `read` returns `b""` at the end and raises `NetworkError` when the connection fails mid-body) and `utmax.transport.StreamingTransport` (a `Transport` with `stream(request) -> HttpStream`).
  - `UrllibTransport(*, proxy=None, timeout=30.0, force_ipv4=False)` with `stream(request)`; `RetryingTransport.stream(request)` (delegates, no retries).
  - `utmax.adapters.http.open_stream(transport, request) -> HttpStream` and `BufferedStream(response)`.
  - `Client(..., force_ipv4: bool = False, transport=None)`; the transport the client uses is kept as `self._transport` (Task 10 needs it).
  - Test helpers: `MEDIA` (256 KiB served at `/media` with Range support), `/truncated` (promises 1000 bytes, sends 10 and closes), `/stall` (sends 10 of 1000 bytes, then waits a second), `local_server(*, ipv6=False)`, `ipv6_loopback_available()`.
  - Note: `http.client.HTTPResponse.read(n)` does **not** raise when a server closes before `Content-Length` bytes — it returns the short body (CPython keeps this for compatibility). The downloader (Task 7) therefore treats an early `b""` as a short read; `NetworkError` comes only from real connection failures such as resets and timeouts.

- [ ] **Step 1: Extend the test server**

In `tests/helpers/http_server.py`, add `import socket`, define below the imports:

```python
MEDIA = bytes(range(256)) * 1024  # 256 KiB served at /media, with Range support
```

add these branches to `_Handler.do_GET` before the final `else:`:

```python
        elif self.path == "/media":
            self._media()
        elif self.path == "/truncated":
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b"x" * 10)
            self.close_connection = True
        elif self.path == "/stall":
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b"x" * 10)
            self.wfile.flush()
            time.sleep(1.0)
```

add this method to `_Handler`:

```python
    def _media(self) -> None:
        header = self.headers.get("Range")
        if header is None:
            self._send(200, MEDIA, {"Content-Type": "video/mp4"})
            return
        first, _, last = header.removeprefix("bytes=").partition("-")
        start = int(first)
        end = min(int(last) if last else len(MEDIA) - 1, len(MEDIA) - 1)
        headers = {"Content-Type": "video/mp4", "Content-Range": f"bytes {start}-{end}/{len(MEDIA)}"}
        self._send(206, MEDIA[start : end + 1], headers)
```

and replace `local_server` with:

```python
class _Server6(_Server):
    address_family = socket.AF_INET6


def ipv6_loopback_available() -> bool:
    """True when this machine can listen on ``::1``."""
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
            probe.bind(("::1", 0))
    except OSError:
        return False
    return True


@contextmanager
def local_server(*, ipv6: bool = False) -> Iterator[str]:
    """Serve on 127.0.0.1 (or ``::1``) in a background thread and yield the base URL."""
    server = _Server6(("::1", 0), _Handler) if ipv6 else _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = "[::1]" if ipv6 else "127.0.0.1"
    try:
        yield f"http://{host}:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
```

- [ ] **Step 2: Write the failing tests**

`tests/unit/adapters/test_http_stream.py`:

```python
"""Tests for streamed responses and IPv4-only connections."""

from __future__ import annotations

import socket

import pytest

from tests.helpers.fake_transport import FakeTransport, text_response
from tests.helpers.http_server import MEDIA, ipv6_loopback_available, local_server
from utmax import Client
from utmax.adapters.http import BufferedStream, RetryingTransport, UrllibTransport, open_stream
from utmax.errors import InvalidOption, NetworkError
from utmax.transport import HttpRequest, HttpStream, StreamingTransport


def read_all(stream: HttpStream, piece: int = 1000) -> bytes:
    parts = []
    while data := stream.read(piece):
        parts.append(data)
    return b"".join(parts)


def test_streams_read_a_byte_range_in_pieces() -> None:
    with local_server() as base:
        request = HttpRequest("GET", f"{base}/media", {"Range": "bytes=10-4009"})
        stream = UrllibTransport().stream(request)
        try:
            assert stream.status == 206
            assert stream.header("Content-Range") == f"bytes 10-4009/{len(MEDIA)}"
            assert read_all(stream) == MEDIA[10:4010]
            assert stream.read(10) == b""
        finally:
            stream.close()


def test_streams_return_error_statuses_with_their_body() -> None:
    with local_server() as base:
        stream = UrllibTransport().stream(HttpRequest("GET", f"{base}/missing"))
        try:
            assert stream.status == 404
            assert read_all(stream) == b"nope"
        finally:
            stream.close()


def test_connection_failures_are_network_errors() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    request = HttpRequest("GET", f"http://127.0.0.1:{port}/media")
    with pytest.raises(NetworkError, match="Could not complete GET"):
        UrllibTransport(timeout=2).stream(request)


def test_bodies_that_end_early_come_back_short() -> None:
    with local_server() as base:
        stream = UrllibTransport().stream(HttpRequest("GET", f"{base}/truncated"))
        try:
            assert read_all(stream) == b"x" * 10
        finally:
            stream.close()


def test_connections_that_stall_mid_body_are_network_errors() -> None:
    with local_server() as base:
        stream = UrllibTransport(timeout=0.3).stream(HttpRequest("GET", f"{base}/stall"))
        try:
            with pytest.raises(NetworkError):
                read_all(stream)
        finally:
            stream.close()


def test_retrying_transport_streams_through_its_inner_transport() -> None:
    with local_server() as base:
        request = HttpRequest("GET", f"{base}/media", {"Range": "bytes=0-99"})
        stream = RetryingTransport(UrllibTransport()).stream(request)
        try:
            assert read_all(stream) == MEDIA[:100]
        finally:
            stream.close()


def test_open_stream_buffers_transports_that_cannot_stream() -> None:
    transport = FakeTransport()
    transport.add("GET", "/media", text_response("abcdef", status=206, content_type="video/mp4"))
    assert not isinstance(transport, StreamingTransport)
    stream = open_stream(transport, HttpRequest("GET", "https://media.test/media"))
    assert isinstance(stream, BufferedStream)
    assert (stream.status, stream.header("content-type")) == (206, "video/mp4")
    assert stream.read(4) + stream.read(4) + stream.read(4) == b"abcdef"
    stream.close()


def test_the_built_in_transports_can_stream() -> None:
    assert isinstance(UrllibTransport(), StreamingTransport)
    assert isinstance(RetryingTransport(FakeTransport()), StreamingTransport)


def test_force_ipv4_still_reaches_ipv4_servers() -> None:
    with local_server() as base:
        response = UrllibTransport(force_ipv4=True).send(HttpRequest("GET", f"{base}/json"))
    assert response.json() == {"ok": True}


def test_force_ipv4_refuses_ipv6_only_servers() -> None:
    if not ipv6_loopback_available():
        pytest.skip("this machine cannot listen on ::1")
    with local_server(ipv6=True) as base:
        request = HttpRequest("GET", f"{base}/json")
        assert UrllibTransport().send(request).status == 200
        ipv4_only = RetryingTransport(UrllibTransport(force_ipv4=True, timeout=2), retries=0)
        with pytest.raises(NetworkError):
            ipv4_only.send(request)


def test_client_force_ipv4_option() -> None:
    Client(force_ipv4=True)
    with pytest.raises(InvalidOption, match="force_ipv4"):
        Client(transport=FakeTransport(), force_ipv4=True)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/adapters/test_http_stream.py -q`
Expected: collection error — `ImportError: cannot import name 'BufferedStream' from 'utmax.adapters.http'`.

- [ ] **Step 4: Add the streaming protocols**

In `src/utmax/transport.py`, import `runtime_checkable` from `typing`, set `__all__ = ["HttpRequest", "HttpResponse", "HttpStream", "StreamingTransport", "Transport"]`, and append:

```python
@runtime_checkable
class HttpStream(Protocol):
    """A response whose body is read piece by piece (media downloads).

    ``read`` returns up to ``n`` bytes and ``b""`` at the end of the body; it raises
    :class:`utmax.errors.NetworkError` when the connection fails half-way.
    """

    @property
    def status(self) -> int: ...

    def header(self, name: str) -> str | None: ...

    def read(self, n: int) -> bytes: ...

    def close(self) -> None: ...


@runtime_checkable
class StreamingTransport(Transport, Protocol):
    """A :class:`Transport` that can also stream bodies; utmax buffers them for other ones."""

    def stream(self, request: HttpRequest) -> HttpStream: ...
```

- [ ] **Step 5: Stream with urllib and optionally force IPv4**

In `src/utmax/adapters/http.py`:

1. Add `import io` and `from typing import IO`; import `HttpStream` and `StreamingTransport` from `utmax.transport`; set `__all__ = ["BufferedStream", "RetryingTransport", "UrllibTransport", "open_stream", "redact"]`; below `_NETWORK_ERRORS` add:

```python
# Binding outgoing sockets here makes every IPv6 address fail, so only IPv4 is tried.
_IPV4_ONLY = ("0.0.0.0", 0)
```

2. Replace `UrllibTransport.__init__` and the first statement of `send` so both methods share `_prepare`, and add `stream`:

```python
class UrllibTransport:
    """Sends requests with the standard library; every request uses a fresh connection.

    ``force_ipv4=True`` connects over IPv4 only. Stream URLs are bound to the address that
    requested them, so machines whose IPv4 and IPv6 addresses differ may need it.
    """

    def __init__(
        self, *, proxy: str | None = None, timeout: float = 30.0, force_ipv4: bool = False
    ) -> None:
        context = ssl.create_default_context()
        handlers: list[urllib.request.BaseHandler] = (
            [_IPv4HTTPHandler(), _IPv4HTTPSHandler(context)]
            if force_ipv4
            else [urllib.request.HTTPSHandler(context=context)]
        )
        if proxy is not None:
            _check_proxy(proxy)
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self._opener = urllib.request.build_opener(*handlers)
        self._timeout = timeout

    def send(self, request: HttpRequest) -> HttpResponse:
        status: int
        headers: dict[str, str]
        body: bytes
        try:
            with self._opener.open(_prepare(request), timeout=self._timeout) as response:
                status = response.status
                headers = dict(response.headers.items())
                body = response.read()
        except urllib.error.HTTPError as error:
            with error:
                status = error.code
                headers = dict(error.headers.items()) if error.headers else {}
                body = error.read()
        if _header(headers, "content-encoding").lower() == "gzip":
            body = gzip.decompress(body)
        log.debug("%s %s -> %d", request.method, redact(request.url), status)
        return HttpResponse(status=status, url=request.url, headers=headers, body=body)

    def stream(self, request: HttpRequest) -> HttpStream:
        """Open ``request`` and hand back its body unread and never decompressed.

        Raises:
            NetworkError: the connection could not be made.
        """
        try:
            response = self._opener.open(_prepare(request), timeout=self._timeout)
        except urllib.error.HTTPError as error:
            log.debug("%s %s -> %d (stream)", request.method, redact(request.url), error.code)
            headers = dict(error.headers.items()) if error.headers else {}
            return _UrllibStream(error, error.code, headers, request)
        except _NETWORK_ERRORS as error:
            raise _network_error(error, request) from error
        log.debug("%s %s -> %d (stream)", request.method, redact(request.url), response.status)
        return _UrllibStream(response, response.status, dict(response.headers.items()), request)
```

3. Add to `RetryingTransport`:

```python
    def stream(self, request: HttpRequest) -> HttpStream:
        """Stream through the inner transport; the downloader retries byte ranges itself."""
        return open_stream(self._inner, request)
```

4. Add these module-level definitions (after `redact`):

```python
def open_stream(transport: Transport, request: HttpRequest) -> HttpStream:
    """Stream ``request`` when ``transport`` can; otherwise send it and serve the body from memory."""
    if isinstance(transport, StreamingTransport):
        return transport.stream(request)
    return BufferedStream(transport.send(request))


class BufferedStream:
    """An :class:`~utmax.transport.HttpStream` over a response that is already in memory."""

    def __init__(self, response: HttpResponse) -> None:
        self.status = response.status
        self._response = response
        self._body = io.BytesIO(response.body)

    def header(self, name: str) -> str | None:
        return self._response.header(name)

    def read(self, n: int) -> bytes:
        return self._body.read(n)

    def close(self) -> None:
        self._body.close()


class _UrllibStream:
    """A urllib response (or HTTP error response) whose body is read in pieces."""

    def __init__(
        self, body: IO[bytes], status: int, headers: Mapping[str, str], request: HttpRequest
    ) -> None:
        self.status = status
        self._body = body
        self._headers = {key.lower(): value for key, value in headers.items()}
        self._request = request

    def header(self, name: str) -> str | None:
        return self._headers.get(name.lower())

    def read(self, n: int) -> bytes:
        try:
            return self._body.read(n)
        except _NETWORK_ERRORS as error:
            raise _network_error(error, self._request) from error

    def close(self) -> None:
        self._body.close()


class _IPv4HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(http.client.HTTPConnection, req, source_address=_IPV4_ONLY)


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, context: ssl.SSLContext) -> None:
        super().__init__(context=context)
        self._tls_context = context

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(
            http.client.HTTPSConnection,
            req,
            context=self._tls_context,
            source_address=_IPV4_ONLY,
        )


def _prepare(request: HttpRequest) -> urllib.request.Request:
    return urllib.request.Request(
        request.url, data=request.body, headers=dict(request.headers), method=request.method
    )
```

If mypy rejects passing `HTTPError` as `IO[bytes]`, type `body` with a two-method protocol (`read(n) -> bytes`, `close() -> None`) instead and disclose it.

- [ ] **Step 6: Accept `force_ipv4` in the Client**

In `src/utmax/client.py`, add the keyword parameter `force_ipv4: bool = False` before `transport`, document it in the class docstring (`force_ipv4: connect over IPv4 only; try it when downloads fail with StreamForbidden on a machine with both IPv4 and IPv6, because stream URLs are bound to one address.`), and change the constructor body to:

```python
        if timeout <= 0:
            raise InvalidOption("timeout must be a positive number of seconds.")
        if retries < 0 or block_retries < 0:
            raise InvalidOption("retries and block_retries cannot be negative.")
        if transport is not None and proxy is not None:
            raise InvalidOption(
                "Pass either proxy= or transport=, not both; configure the proxy in your transport."
            )
        if transport is not None and force_ipv4:
            raise InvalidOption(
                "force_ipv4 applies to utmax's own HTTP stack; configure IPv4 in your transport."
            )
        if transport is None:
            transport = RetryingTransport(
                UrllibTransport(proxy=proxy, timeout=timeout, force_ipv4=force_ipv4),
                retries=retries,
            )
        self._transport = transport
        self._transcripts = TranscriptService(
            InnerTubeClient(transport, block_retries=block_retries)
        )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/adapters/test_http_stream.py tests/unit/adapters/test_http.py tests/unit/test_client.py -q`
Expected: the new file reports 11 passed (or 10 passed and 1 skipped where `::1` is unavailable); the older files still pass.

- [ ] **Step 8: Gates and commit**

Run the four gates (the suite grows by 11).

```bash
git add src/utmax/transport.py src/utmax/adapters/http.py src/utmax/client.py tests/helpers/http_server.py tests/unit/adapters/test_http_stream.py
git commit -m "feat: stream response bodies and optionally force IPv4" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 7: The parallel, resumable downloader

**Files:**
- Create: `tests/helpers/fake_media.py`, `src/utmax/adapters/downloader.py`
- Test: `tests/unit/adapters/test_downloader.py`, `tests/unit/adapters/test_downloader_recovery.py`

**Interfaces:**
- Consumes: `Stream` (Task 2); `Chunk`, `PartState`, `RateMeter`, `Throttle`, `plan_chunks`, `range_header`, `content_range_total`, `expires_soon`, `DEFAULT_CHUNK_SIZE` (Task 4); `HttpRequest`, `HttpStream` (Task 6); `write_text_atomic` (M1); `backoff_delay`, `is_transient_status` (M1); `Progress`, `ProgressPhase` (Task 1); `DownloadCancelled`, `DownloadIncomplete`, `StreamForbidden`, `NetworkError`.
- Produces (in `utmax.adapters.downloader`):
  - `Opener = Callable[[HttpRequest], HttpStream]`; `READ_SIZE = 256 * 1024`; `STATE_FLUSH_INTERVAL = 1.0`.
  - `ProgressReporter(video_id, callback, *, clock=time.monotonic, interval=0.25)` with `report(phase, done, total, *, force=False)`.
  - `Job(stream: Stream, part: Path)` with `state_path` (`part` + `.json`).
  - `Downloader(opener, *, connections=4, chunk_size=DEFAULT_CHUNK_SIZE, refresh=None, reporter=None, cancel=None, attempts=5, max_refreshes=3, clock=time.time, sleep=time.sleep, rng=None)` with `run(jobs, *, video_id, resume=True) -> bool` (``True`` when finished ranges of an earlier run were reused). `refresh` returns the streams of a fresh player response.
  - Test helpers (in `tests.helpers.fake_media`): `FakeMedia` (`add`, `fail`, `expired`, `requests`, `bodies`, `ranges(name)`, `stream`, `send`), `Fault(status, cut_after, reset_after, error, ignore_range)`, `pattern(size, seed=0)`, `media_stream(itag, url, size, *, audio=False, last_modified="1", expires_at=None)`.

- [ ] **Step 1: Write the fake media server**

`tests/helpers/fake_media.py`:

```python
"""A fake googlevideo server for download tests: byte ranges of in-memory streams, and faults.

Streams live at ``https://media.test/<name>``. The query string is ignored when looking up
the bytes, so a refreshed URL (``...?v=2``) serves the same stream, while URLs listed in
``expired`` answer 403.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlsplit

from utmax.core.streams import Stream
from utmax.errors import NetworkError
from utmax.models import Format
from utmax.transport import HttpRequest, HttpResponse

BASE = "https://media.test/"


def pattern(size: int, seed: int = 0) -> bytes:
    """``size`` bytes that differ at every offset within 256 bytes (and between seeds)."""
    return bytes((seed + index * 7) % 256 for index in range(size))


def media_stream(
    itag: int,
    url: str,
    size: int | None,
    *,
    audio: bool = False,
    last_modified: str = "1",
    expires_at: int | None = None,
) -> Stream:
    """A stream for downloader tests (codec details do not matter there)."""
    fmt = Format(
        itag,
        "audio" if audio else "video",
        "mp4",
        "aac" if audio else "h264",
        "mp4a.40.2" if audio else "avc1.640028",
        content_length=size,
        last_modified=last_modified,
    )
    return Stream(fmt, url=url, expires_at=expires_at, user_agent="test-agent")


@dataclass(frozen=True)
class Fault:
    """Something that goes wrong with one request."""

    status: int | None = None  # answer with this status and an empty body
    cut_after: int | None = None  # end the body early, after this many bytes
    reset_after: int | None = None  # raise NetworkError after this many bytes
    error: BaseException | None = None  # raise this when the request is opened
    ignore_range: bool = False  # answer 200 with the whole stream


class FakeBody:
    """One response body; remembers whether it was closed."""

    def __init__(
        self,
        status: int,
        headers: dict[str, str],
        data: bytes,
        *,
        reset_after: int | None = None,
    ) -> None:
        self.status = status
        self.headers = {key.lower(): value for key, value in headers.items()}
        self.closed = False
        self._data = data
        self._position = 0
        self._reset_after = reset_after

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())

    def read(self, n: int) -> bytes:
        end = min(self._position + n, len(self._data))
        if self._reset_after is not None and end > self._reset_after:
            if self._position >= self._reset_after:
                raise NetworkError("Could not complete GET https://media.test: connection reset")
            end = self._reset_after
        data = self._data[self._position : end]
        self._position = end
        return data

    def close(self) -> None:
        self.closed = True


class FakeMedia:
    """Serves streams by name; thread-safe; records every request and every body."""

    def __init__(self) -> None:
        self.requests: list[HttpRequest] = []
        self.bodies: list[FakeBody] = []
        self.expired: set[str] = set()
        self._streams: dict[str, bytes] = {}
        self._faults: dict[str, deque[Fault]] = {}
        self._lock = threading.Lock()

    def add(self, name: str, data: bytes) -> str:
        """Serve ``data`` as ``name`` and return its URL."""
        self._streams[name] = data
        return BASE + name

    def fail(self, name: str, *faults: Fault) -> None:
        """Apply ``faults`` to the next requests for ``name``, one fault per request."""
        self._faults.setdefault(name, deque()).extend(faults)

    def ranges(self, name: str) -> list[str]:
        """The ``Range`` headers of every request for ``name``, in order."""
        return [
            request.headers.get("Range", "")
            for request in self.requests
            if urlsplit(request.url).path == f"/{name}"
        ]

    def stream(self, request: HttpRequest) -> FakeBody:
        name = urlsplit(request.url).path.lstrip("/")
        with self._lock:
            self.requests.append(request)
            faults = self._faults.get(name)
            fault = faults.popleft() if faults else Fault()
        if fault.error is not None:
            raise fault.error
        body = self._answer(request, self._streams.get(name), fault)
        with self._lock:
            self.bodies.append(body)
        return body

    def send(self, request: HttpRequest) -> HttpResponse:
        """The whole answer at once, for code paths that cannot stream."""
        body = self.stream(request)
        data = body.read(1 << 40)
        body.close()
        return HttpResponse(status=body.status, url=request.url, headers=body.headers, body=data)

    def _answer(self, request: HttpRequest, data: bytes | None, fault: Fault) -> FakeBody:
        if data is None:
            return FakeBody(404, {}, b"")
        if request.url in self.expired:
            return FakeBody(403, {}, b"")
        if fault.status is not None:
            return FakeBody(fault.status, {}, b"")
        header = request.headers.get("Range")
        if header is None or fault.ignore_range:
            return FakeBody(200, {"Content-Length": str(len(data))}, data)
        first, _, last = header.removeprefix("bytes=").partition("-")
        start = int(first)
        end = min(int(last) + 1 if last else len(data), len(data))
        if start >= len(data):
            return FakeBody(416, {"Content-Range": f"bytes */{len(data)}"}, b"")
        body = data[start:end]
        if fault.cut_after is not None:
            body = body[: fault.cut_after]
        headers = {"Content-Range": f"bytes {start}-{end - 1}/{len(data)}"}
        return FakeBody(206, headers, body, reset_after=fault.reset_after)
```

- [ ] **Step 2: Write the failing tests for the normal path**

`tests/unit/adapters/test_downloader.py`:

```python
"""Tests for the parallel, resumable downloader: the normal path (fake media, real files)."""

from __future__ import annotations

import json
from itertools import count
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from tests.helpers.fake_media import FakeMedia, media_stream, pattern
from utmax.adapters.downloader import Downloader, Job, ProgressReporter
from utmax.models import Progress

CHUNK = 1000


def downloader(media: FakeMedia, **options: Any) -> Downloader:
    options.setdefault("chunk_size", CHUNK)
    options.setdefault("sleep", lambda _: None)
    return Downloader(media.stream, **options)


def state_of(job: Job) -> dict[str, Any]:
    return json.loads(job.state_path.read_text(encoding="utf-8"))


def test_a_stream_is_downloaded_in_ranges_into_its_part_file(tmp_path: Path) -> None:
    media = FakeMedia()
    data = pattern(4500)
    job = Job(media_stream(137, media.add("video", data), len(data)), tmp_path / "out" / "v.part")
    assert downloader(media, connections=3).run([job], video_id="v") is False
    assert job.part.read_bytes() == data
    assert sorted(media.ranges("video")) == [
        "bytes=0-999",
        "bytes=1000-1999",
        "bytes=2000-2999",
        "bytes=3000-3999",
        "bytes=4000-4499",
    ]
    assert state_of(job)["completed"] == [0, 1, 2, 3, 4]
    assert all(body.closed for body in media.bodies)


def test_small_streams_take_one_request(tmp_path: Path) -> None:
    media = FakeMedia()
    data = pattern(1999)
    stream = media_stream(140, media.add("audio", data), len(data), audio=True)
    job = Job(stream, tmp_path / "a.part")
    downloader(media).run([job], video_id="v")
    assert media.ranges("audio") == ["bytes=0-1998"]
    assert job.part.read_bytes() == data


def test_streams_share_one_queue_in_offset_order(tmp_path: Path) -> None:
    media = FakeMedia()
    video, audio = pattern(3000), pattern(2000, seed=3)
    jobs = [
        Job(media_stream(137, media.add("video", video), 3000), tmp_path / "v.part"),
        Job(media_stream(140, media.add("audio", audio), 2000, audio=True), tmp_path / "a.part"),
    ]
    downloader(media, connections=1).run(jobs, video_id="v")
    assert [(urlsplit(r.url).path, r.headers["Range"]) for r in media.requests] == [
        ("/video", "bytes=0-999"),
        ("/audio", "bytes=0-999"),
        ("/video", "bytes=1000-1999"),
        ("/audio", "bytes=1000-1999"),
        ("/video", "bytes=2000-2999"),
    ]
    assert (jobs[0].part.read_bytes(), jobs[1].part.read_bytes()) == (video, audio)


def test_many_connections_write_the_right_bytes(tmp_path: Path) -> None:
    media = FakeMedia()
    data = pattern(50_000)
    job = Job(media_stream(137, media.add("video", data), len(data)), tmp_path / "v.part")
    downloader(media, connections=8).run([job], video_id="v")
    assert job.part.read_bytes() == data
    assert len(media.requests) == 50


def test_unknown_sizes_are_probed_with_a_one_byte_request(tmp_path: Path) -> None:
    media = FakeMedia()
    data = pattern(2500)
    job = Job(media_stream(137, media.add("video", data), None), tmp_path / "v.part")
    downloader(media).run([job], video_id="v")
    ranges = media.ranges("video")
    assert ranges[0] == "bytes=0-0"
    assert sorted(ranges[1:]) == ["bytes=0-999", "bytes=1000-1999", "bytes=2000-2499"]
    assert job.part.read_bytes() == data


def test_media_requests_name_the_client_and_ask_for_raw_bytes(tmp_path: Path) -> None:
    media = FakeMedia()
    job = Job(media_stream(137, media.add("video", pattern(10)), 10), tmp_path / "v.part")
    downloader(media).run([job], video_id="v")
    (request,) = media.requests
    assert request.headers["User-Agent"] == "test-agent"
    assert request.headers["Accept-Encoding"] == "identity"


def test_progress_reports_are_monotonic_throttled_and_complete(tmp_path: Path) -> None:
    media = FakeMedia()
    data = pattern(20_000)
    job = Job(media_stream(137, media.add("video", data), len(data)), tmp_path / "v.part")
    ticks = count()
    seen: list[Progress] = []
    reporter = ProgressReporter("v", seen.append, clock=lambda: next(ticks) * 0.1)
    downloader(media, connections=4, reporter=reporter).run([job], video_id="v")
    done = [progress.bytes_done for progress in seen]
    assert done == sorted(done)
    assert (done[0], done[-1]) == (0, 20_000)
    assert {progress.phase for progress in seen} == {"downloading"}
    assert all(progress.bytes_total == 20_000 for progress in seen)
    assert len(seen) == 8  # 22 reports (start, 20 ranges, end) with 0.1 s ticks and a 0.25 s throttle


def test_a_failing_progress_callback_stops_the_download(tmp_path: Path) -> None:
    media = FakeMedia()
    data = pattern(4000)
    job = Job(media_stream(137, media.add("video", data), len(data)), tmp_path / "v.part")

    def explode(progress: Progress) -> None:
        if progress.bytes_done:
            raise ValueError("callback failed")

    reporter = ProgressReporter("v", explode, interval=0)
    with pytest.raises(ValueError, match="callback failed"):
        downloader(media, reporter=reporter).run([job], video_id="v")
    assert state_of(job)["completed"] == []
```

- [ ] **Step 3: Write the failing tests for resume, refresh, retries and cancel**

`tests/unit/adapters/test_downloader_recovery.py`:

```python
"""Tests for the downloader when things go wrong: resume, refresh, retries, cancel."""

from __future__ import annotations

import json
import random
import threading
from pathlib import Path
from typing import Any

import pytest

from tests.helpers.fake_media import FakeMedia, Fault, media_stream, pattern
from utmax.adapters.downloader import Downloader, Job, ProgressReporter
from utmax.core.downloads import PartState
from utmax.core.streams import Stream
from utmax.errors import (
    DownloadCancelled,
    DownloadIncomplete,
    IpBlocked,
    NetworkError,
    StreamForbidden,
)
from utmax.models import Progress

CHUNK = 1000


def downloader(media: FakeMedia, **options: Any) -> Downloader:
    options.setdefault("chunk_size", CHUNK)
    options.setdefault("sleep", lambda _: None)
    return Downloader(media.stream, **options)


def completed(job: Job) -> list[int]:
    return json.loads(job.state_path.read_text(encoding="utf-8"))["completed"]


def served(tmp_path: Path, size: int = 5000, **stream: Any) -> tuple[FakeMedia, bytes, Job]:
    """A media server with one video stream of ``size`` bytes, and a job for it."""
    media = FakeMedia()
    data = pattern(size)
    job = Job(media_stream(137, media.add("video", data), size, **stream), tmp_path / "v.part")
    return media, data, job


def save(job: Job, state: PartState) -> None:
    job.state_path.write_text(state.to_json(), encoding="utf-8")


def test_finished_ranges_are_reused_on_the_next_run(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, last_modified="7")
    job.part.write_bytes(data[:2000] + bytes(3000))
    save(job, PartState("v", 137, 5000, "7", CHUNK, frozenset({0, 1})))
    assert downloader(media).run([job], video_id="v") is True
    assert job.part.read_bytes() == data
    assert sorted(media.ranges("video")) == [
        "bytes=2000-2999",
        "bytes=3000-3999",
        "bytes=4000-4999",
    ]


@pytest.mark.parametrize(
    "saved",
    [
        PartState("v", 137, 5000, "6", CHUNK, frozenset({0, 1})).to_json(),
        PartState("v", 137, 5000, "7", 500, frozenset({0, 1})).to_json(),
        "{broken",
    ],
)
def test_resume_starts_over_when_the_saved_state_does_not_fit(tmp_path: Path, saved: str) -> None:
    media, data, job = served(tmp_path, last_modified="7")
    job.part.write_bytes(b"x" * 5000)
    job.state_path.write_text(saved, encoding="utf-8")
    assert downloader(media).run([job], video_id="v") is False
    assert job.part.read_bytes() == data
    assert len(media.ranges("video")) == 5


def test_a_part_file_of_the_wrong_size_starts_over(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, last_modified="7")
    job.part.write_bytes(data[:2000])
    save(job, PartState("v", 137, 5000, "7", CHUNK, frozenset({0, 1})))
    assert downloader(media).run([job], video_id="v") is False
    assert job.part.read_bytes() == data


def test_resume_false_ignores_the_saved_state(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, last_modified="7")
    job.part.write_bytes(data[:2000] + bytes(3000))
    save(job, PartState("v", 137, 5000, "7", CHUNK, frozenset({0, 1})))
    assert downloader(media).run([job], video_id="v", resume=False) is False
    assert len(media.ranges("video")) == 5
    assert job.part.read_bytes() == data


def test_a_403_refreshes_the_urls_once_for_every_thread(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=8000)
    media.expired.add(job.stream.url)
    calls: list[int] = []

    def refresh() -> list[Stream]:
        calls.append(1)
        return [media_stream(137, job.stream.url + "?v=2", 8000)]

    downloader(media, connections=4, refresh=refresh).run([job], video_id="v")
    assert calls == [1]
    assert job.part.read_bytes() == data


def test_forbidden_streams_give_up_after_three_refreshes(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=8000)
    media.expired.add(job.stream.url)
    calls: list[int] = []

    def refresh() -> list[Stream]:
        calls.append(1)
        url = f"{job.stream.url}?v={len(calls)}"
        media.expired.add(url)
        return [media_stream(137, url, 8000)]

    with pytest.raises(StreamForbidden, match="after 3 fresh URLs") as caught:
        downloader(media, refresh=refresh).run([job], video_id="v")
    assert caught.value.itag == 137
    assert len(calls) == 3
    assert completed(job) == []


def test_urls_about_to_expire_are_refreshed_before_use(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=3000, expires_at=1_000_100)
    fresh = media_stream(137, job.stream.url + "?v=2", 3000, expires_at=1_021_600)
    run = downloader(media, connections=1, refresh=lambda: [fresh], clock=lambda: 1_000_000.0)
    run.run([job], video_id="v")
    assert [request.url for request in media.requests] == [fresh.url] * 3
    assert job.part.read_bytes() == data


def test_a_refresh_that_changes_the_stream_is_reported(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=3000)
    media.expired.add(job.stream.url)
    changed = media_stream(137, job.stream.url + "?v=2", 3000, last_modified="2")
    with pytest.raises(DownloadIncomplete, match="changed on YouTube"):
        downloader(media, refresh=lambda: [changed]).run([job], video_id="v")


def test_a_failing_refresh_propagates(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=3000)
    media.expired.add(job.stream.url)

    def refresh() -> list[Stream]:
        raise IpBlocked("slow down", video_id="v")

    with pytest.raises(IpBlocked, match="slow down"):
        downloader(media, refresh=refresh).run([job], video_id="v")


def test_short_bodies_continue_from_the_first_missing_byte(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=3000)
    media.fail("video", Fault(cut_after=400))
    downloader(media, connections=1).run([job], video_id="v")
    assert media.ranges("video")[:2] == ["bytes=0-999", "bytes=400-999"]
    assert job.part.read_bytes() == data


def test_a_reset_after_progress_continues_at_once(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=3000)
    media.fail("video", Fault(reset_after=300))
    delays: list[float] = []
    downloader(media, connections=1, sleep=delays.append).run([job], video_id="v")
    assert media.ranges("video")[:2] == ["bytes=0-999", "bytes=300-999"]
    assert delays == []
    assert job.part.read_bytes() == data


def test_failures_without_progress_back_off(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=3000)
    media.fail("video", Fault(error=NetworkError("refused")), Fault(status=503), Fault(status=429))
    delays: list[float] = []
    run = downloader(media, connections=1, sleep=delays.append, rng=random.Random(1))
    run.run([job], video_id="v")
    assert len(delays) == 3
    assert delays == sorted(delays)
    assert 0.5 <= delays[0] <= 0.75
    assert 2.0 <= delays[2] <= 2.25
    assert job.part.read_bytes() == data


def test_network_failures_give_up_after_the_last_attempt(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=3000)
    media.fail("video", *[Fault(error=NetworkError("refused"))] * 5)
    with pytest.raises(NetworkError, match="refused"):
        downloader(media, connections=1).run([job], video_id="v")
    assert len(media.requests) == 5


def test_statuses_that_stay_bad_become_download_incomplete(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=3000)
    media.fail("video", *[Fault(status=503)] * 5)
    with pytest.raises(DownloadIncomplete, match="kept failing"):
        downloader(media, connections=1).run([job], video_id="v")


def test_a_416_refreshes_once_then_gives_up(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=3000)
    media.fail("video", Fault(status=416), Fault(status=416))
    calls: list[int] = []

    def refresh() -> list[Stream]:
        calls.append(1)
        return [job.stream]

    with pytest.raises(DownloadIncomplete, match="HTTP 416"):
        downloader(media, connections=1, refresh=refresh).run([job], video_id="v")
    assert calls == [1]


def test_a_single_416_recovers(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=3000)
    media.fail("video", Fault(status=416))
    downloader(media, connections=1).run([job], video_id="v")
    assert job.part.read_bytes() == data


def test_servers_that_ignore_ranges_are_rejected(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=3000)
    media.fail("video", Fault(ignore_range=True))
    with pytest.raises(DownloadIncomplete, match="ignored the byte range"):
        downloader(media, connections=1).run([job], video_id="v")


def test_whole_stream_requests_accept_a_plain_200(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=1500)
    media.fail("video", Fault(ignore_range=True))
    downloader(media).run([job], video_id="v")
    assert job.part.read_bytes() == data


def test_other_statuses_end_the_download(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=3000)
    media.fail("video", Fault(status=404))
    with pytest.raises(DownloadIncomplete, match="answered HTTP 404"):
        downloader(media, connections=1).run([job], video_id="v")


def test_cancel_keeps_the_finished_ranges_for_a_resume(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=6000)
    cancel = threading.Event()

    def watch(progress: Progress) -> None:
        if progress.bytes_done >= 2000:
            cancel.set()

    reporter = ProgressReporter("v", watch, interval=0)
    with pytest.raises(DownloadCancelled, match="cancelled"):
        downloader(media, connections=1, cancel=cancel, reporter=reporter).run([job], video_id="v")
    assert completed(job) == [0, 1]
    assert downloader(media, connections=1).run([job], video_id="v") is True
    assert job.part.read_bytes() == data


def test_ctrl_c_saves_the_state_and_propagates(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=6000)

    def interrupt(progress: Progress) -> None:
        if progress.bytes_done >= 2000:
            raise KeyboardInterrupt

    reporter = ProgressReporter("v", interrupt, interval=0)
    with pytest.raises(KeyboardInterrupt):
        downloader(media, connections=1, reporter=reporter).run([job], video_id="v")
    assert completed(job) == [0]
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/adapters/test_downloader.py tests/unit/adapters/test_downloader_recovery.py -q`
Expected: collection errors — `ModuleNotFoundError: No module named 'utmax.adapters.downloader'`.

- [ ] **Step 5: Write `src/utmax/adapters/downloader.py`**

```python
"""Parallel, resumable downloads of media streams into ``.part`` files.

Each stream is split into byte ranges (:func:`utmax.core.downloads.plan_chunks`); the ranges
of all streams form one queue in ascending offset order, served by up to ``connections``
threads that write through their own file handles. Finished ranges are recorded in
``<part>.json`` (when the download starts, at most once a second, and when it stops), so a
later run with the same stream reuses them. Rejected or expiring URLs are refreshed once for
all threads; a failed range is retried from its first missing byte.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import BinaryIO

from utmax.adapters.files import write_text_atomic
from utmax.core.downloads import (
    DEFAULT_CHUNK_SIZE,
    Chunk,
    PartState,
    RateMeter,
    Throttle,
    content_range_total,
    expires_soon,
    plan_chunks,
    range_header,
)
from utmax.core.retry import backoff_delay, is_transient_status
from utmax.core.streams import Stream
from utmax.errors import DownloadCancelled, DownloadIncomplete, NetworkError, StreamForbidden
from utmax.models import Progress, ProgressPhase
from utmax.transport import HttpRequest, HttpStream

__all__ = [
    "READ_SIZE",
    "STATE_FLUSH_INTERVAL",
    "Downloader",
    "Job",
    "Opener",
    "ProgressReporter",
]

log = logging.getLogger("utmax.download")

READ_SIZE = 256 * 1024
STATE_FLUSH_INTERVAL = 1.0
_JOIN_STEP = 0.1

Opener = Callable[[HttpRequest], HttpStream]


class ProgressReporter:
    """Turns byte counts into :class:`~utmax.models.Progress` callbacks.

    Calls are serialized and throttled to one per ``interval`` seconds; the first report of
    each phase and every ``force=True`` report always go through.
    """

    def __init__(
        self,
        video_id: str,
        callback: Callable[[Progress], None] | None,
        *,
        clock: Callable[[], float] = time.monotonic,
        interval: float = 0.25,
    ) -> None:
        self._video_id = video_id
        self._callback = callback
        self._clock = clock
        self._throttle = Throttle(interval)
        self._meter = RateMeter()
        self._phase: ProgressPhase | None = None
        self._lock = threading.Lock()

    def report(
        self, phase: ProgressPhase, done: int, total: int | None, *, force: bool = False
    ) -> None:
        """Report ``done`` of ``total`` bytes (``None`` when unknown) in ``phase``."""
        if self._callback is None:
            return
        with self._lock:
            now = self._clock()
            if phase != self._phase:
                self._phase, self._meter, force = phase, RateMeter(), True
            speed, eta = self._meter.update(now, done, total)
            if self._throttle.ready(now, force=force):
                self._callback(Progress(self._video_id, phase, done, total, speed, eta))


@dataclass(frozen=True, slots=True)
class Job:
    """One stream to download into ``part``; its resume state lives in ``part`` + ``.json``."""

    stream: Stream
    part: Path

    @property
    def state_path(self) -> Path:
        return self.part.with_name(f"{self.part.name}.json")


@dataclass(slots=True)
class _Target:
    """A job while it runs (``stream`` changes when URLs are refreshed)."""

    job: Job
    stream: Stream
    size: int
    chunks: tuple[Chunk, ...]
    state: PartState
    completed: set[int] = field(default_factory=set)
    reused: int = 0
    saved_at: float = 0.0


class Downloader:
    """Downloads streams completely, in parallel byte ranges and resumably (see module docs).

    One ``Downloader`` runs one download at a time; create one per download.
    """

    def __init__(
        self,
        opener: Opener,
        *,
        connections: int = 4,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        refresh: Callable[[], Sequence[Stream]] | None = None,
        reporter: ProgressReporter | None = None,
        cancel: threading.Event | None = None,
        attempts: int = 5,
        max_refreshes: int = 3,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._opener = opener
        self._connections = connections
        self._chunk_size = chunk_size
        self._fresh_streams = refresh
        self._reporter = reporter
        self._cancel = cancel
        self._attempts = attempts
        self._max_refreshes = max_refreshes
        self._clock = clock
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._stop = threading.Event()
        self._targets: list[_Target] = []
        self._queue: deque[tuple[_Target, Chunk]] = deque()
        self._errors: list[BaseException] = []
        self._video_id = ""
        self._generation = 0
        self._refreshes = 0
        self._done = 0
        self._total = 0

    def run(self, jobs: Sequence[Job], *, video_id: str, resume: bool = True) -> bool:
        """Download every job; return ``True`` when finished ranges of an earlier run were reused.

        Errors in any thread, and Ctrl-C, stop every thread and save the resume state before
        they propagate.

        Raises:
            DownloadCancelled: ``cancel`` was set; the parts stay for a resume.
            StreamForbidden: YouTube kept answering 403 after ``max_refreshes`` fresh URLs.
            DownloadIncomplete: a stream kept failing, changed on YouTube's side or answered
                an unexpected status.
            NetworkError: the connection kept failing.
        """
        self._video_id = video_id
        self._stop.clear()
        self._errors.clear()
        self._generation = self._refreshes = 0
        self._targets = [self._prepare(job, resume=resume) for job in jobs]
        self._total = sum(target.size for target in self._targets)
        self._done = sum(target.reused for target in self._targets)
        pending = [
            (chunk.start, number, target, chunk)
            for number, target in enumerate(self._targets)
            for chunk in target.chunks
            if chunk.index not in target.completed
        ]
        pending.sort(key=lambda item: (item[0], item[1]))
        self._queue = deque((target, chunk) for _, _, target, chunk in pending)
        self._report(force=True)
        workers = [
            threading.Thread(target=self._work, name=f"utmax-download-{number}", daemon=True)
            for number in range(min(self._connections, len(self._queue)))
        ]
        for worker in workers:
            worker.start()
        try:
            for worker in workers:
                while worker.is_alive():
                    worker.join(_JOIN_STEP)
        finally:
            self._stop.set()
            for worker in workers:
                worker.join()
            self._save_all()
        if self._errors:
            raise self._errors[0]
        if self._cancelled():
            raise DownloadCancelled(
                f"The download of video {video_id} was cancelled; run it again to resume.",
                video_id=video_id,
            )
        self._report(force=True)
        return any(target.reused for target in self._targets)

    def _prepare(self, job: Job, *, resume: bool) -> _Target:
        stream = job.stream
        size = stream.format.content_length
        if size is None:
            size = self._probe_size(stream)
        chunks = plan_chunks(size, self._chunk_size)
        state = PartState(
            self._video_id, stream.format.itag, size, stream.format.last_modified, self._chunk_size
        )
        target = _Target(job, stream, size, chunks, state)
        saved = self._load(job) if resume else None
        if saved is not None and saved.matches(state) and _size_of(job.part) == size:
            target.completed = {index for index in saved.completed if 0 <= index < len(chunks)}
            target.reused = sum(chunks[index].size for index in target.completed)
            log.info(
                "resuming stream %d of %s: %d of %d bytes are already here",
                stream.format.itag,
                self._video_id,
                target.reused,
                size,
            )
        else:
            job.part.parent.mkdir(parents=True, exist_ok=True)
            with job.part.open("wb") as handle:
                handle.truncate(size)
        self._save(target)
        return target

    def _probe_size(self, stream: Stream) -> int:
        """The size of a stream without ``contentLength``: ask for its first byte."""
        body = self._opener(self._request(stream, "bytes=0-0"))
        try:
            total = content_range_total(body.header("Content-Range")) if body.status == 206 else None
        finally:
            body.close()
        if total is None:
            raise DownloadIncomplete(
                f"Could not learn the size of stream {stream.format.itag} of video "
                f"{self._video_id} (HTTP {body.status}).",
                video_id=self._video_id,
            )
        return total

    def _work(self) -> None:
        try:
            while not self._should_stop():
                with self._lock:
                    if not self._queue:
                        return
                    target, chunk = self._queue.popleft()
                self._fetch(target, chunk)
        except BaseException as error:  # stop every thread; run() re-raises the first error
            with self._lock:
                self._errors.append(error)
            self._stop.set()

    def _fetch(self, target: _Target, chunk: Chunk) -> None:
        """Download one range, continuing from its first missing byte, then mark it finished."""
        position, failures, replanned = chunk.start, 0, False
        with target.job.part.open("r+b") as handle:
            while position < chunk.end:
                if self._should_stop():
                    return
                stream, generation = self._current(target)
                try:
                    body = self._opener(self._request(stream, range_header(position, chunk.end)))
                except NetworkError as error:
                    failures = self._retry(failures, error, target)
                    continue
                try:
                    status = body.status
                    whole = position == 0 and chunk.end == target.size
                    if status == 206 or (status == 200 and whole):
                        start = position
                        position, error = self._copy(body, handle, position, chunk.end)
                        if position > start:
                            failures = 0
                        elif not self._should_stop():
                            failures = self._retry(failures, error or self._short(target), target)
                    elif status == 403:
                        self._refresh(generation, target)
                    elif status == 416 and not replanned:
                        replanned = True
                        self._refresh(generation, target, required=False)
                    elif is_transient_status(status) or status == 429:
                        problem = self._bad_status(target, status, position, chunk.end)
                        failures = self._retry(failures, problem, target)
                    else:
                        raise self._bad_status(target, status, position, chunk.end)
                finally:
                    body.close()
        self._finish(target, chunk)

    def _copy(
        self, body: HttpStream, handle: BinaryIO, position: int, end: int
    ) -> tuple[int, NetworkError | None]:
        """Write the body at ``position``; return where it stopped and the error, if any."""
        handle.seek(position)
        try:
            while position < end and not self._should_stop():
                data = body.read(min(READ_SIZE, end - position))
                if not data:
                    break
                handle.write(data)
                position += len(data)
                self._advance(len(data))
        except NetworkError as error:
            return position, error
        return position, None

    def _current(self, target: _Target) -> tuple[Stream, int]:
        """The stream to use now, refreshed first when its URL is about to expire."""
        with self._lock:
            stream, generation = target.stream, self._generation
        if expires_soon(stream.expires_at, self._clock()):
            self._refresh(generation, target, required=False)
            with self._lock:
                stream, generation = target.stream, self._generation
        return stream, generation

    def _refresh(self, seen: int, target: _Target, *, required: bool = True) -> None:
        """Fetch fresh URLs for every stream, once for all threads that used generation ``seen``."""
        with self._refresh_lock:
            if self._generation != seen:
                return
            if self._fresh_streams is None or self._refreshes >= self._max_refreshes:
                if not required:
                    return
                itag = target.stream.format.itag
                raise StreamForbidden(
                    f"YouTube refused stream {itag} of video {self._video_id} (HTTP 403) "
                    f"after {self._refreshes} fresh URLs.",
                    itag=itag,
                    video_id=self._video_id,
                )
            self._refreshes += 1
            log.info(
                "getting fresh stream URLs for %s (%d/%d)",
                self._video_id,
                self._refreshes,
                self._max_refreshes,
            )
            fresh = self._fresh_streams()
            with self._lock:
                for each in self._targets:
                    each.stream = self._match(each, fresh)
                self._generation += 1

    def _match(self, target: _Target, fresh: Sequence[Stream]) -> Stream:
        """The fresh stream with the same itag, size and version as ``target``'s."""
        old = target.stream.format
        for stream in fresh:
            new = stream.format
            if (
                new.itag == old.itag
                and new.last_modified == old.last_modified
                and (new.content_length or target.size) == target.size
            ):
                return stream
        raise DownloadIncomplete(
            f"Stream {old.itag} of video {self._video_id} changed on YouTube during the "
            "download; run it again to start over.",
            video_id=self._video_id,
        )

    def _retry(self, failures: int, error: Exception, target: _Target) -> int:
        """Wait before the next attempt, or give up after ``attempts`` failures in a row."""
        itag = target.stream.format.itag
        if failures + 1 >= self._attempts:
            if isinstance(error, NetworkError):
                raise error
            raise DownloadIncomplete(
                f"Stream {itag} of video {self._video_id} kept failing: {error}",
                video_id=self._video_id,
            ) from error
        delay = backoff_delay(failures, self._rng)
        log.info("stream %d of %s: %s; retrying in %.1fs", itag, self._video_id, error, delay)
        self._sleep(delay)
        return failures + 1

    def _short(self, target: _Target) -> DownloadIncomplete:
        return DownloadIncomplete(
            f"Stream {target.stream.format.itag} of video {self._video_id} sent no data.",
            video_id=self._video_id,
        )

    def _bad_status(
        self, target: _Target, status: int, position: int, end: int
    ) -> DownloadIncomplete:
        detail = (
            "ignored the byte range request (HTTP 200)"
            if status == 200
            else f"answered HTTP {status} for bytes {position}-{end - 1}"
        )
        return DownloadIncomplete(
            f"Stream {target.stream.format.itag} of video {self._video_id} {detail}.",
            video_id=self._video_id,
        )

    def _advance(self, count: int) -> None:
        with self._lock:
            self._done += count
            self._report()

    def _finish(self, target: _Target, chunk: Chunk) -> None:
        with self._lock:
            target.completed.add(chunk.index)
            if self._clock() - target.saved_at >= STATE_FLUSH_INTERVAL:
                self._save(target)

    def _report(self, *, force: bool = False) -> None:
        if self._reporter is not None:
            self._reporter.report("downloading", self._done, self._total, force=force)

    def _save(self, target: _Target) -> None:
        state = replace(target.state, completed=frozenset(target.completed))
        write_text_atomic(target.job.state_path, state.to_json())
        target.saved_at = self._clock()

    def _save_all(self) -> None:
        with self._lock:
            for target in self._targets:
                try:
                    self._save(target)
                except OSError as error:
                    log.warning("could not save %s: %s", target.job.state_path.name, error)

    def _load(self, job: Job) -> PartState | None:
        try:
            return PartState.from_json(job.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            return None

    def _cancelled(self) -> bool:
        return self._cancel is not None and self._cancel.is_set()

    def _should_stop(self) -> bool:
        return self._stop.is_set() or self._cancelled()

    @staticmethod
    def _request(stream: Stream, byte_range: str) -> HttpRequest:
        headers = {
            "User-Agent": stream.user_agent,
            "Accept-Encoding": "identity",
            "Range": byte_range,
        }
        return HttpRequest("GET", stream.url, headers)


def _size_of(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return -1
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/adapters/test_downloader.py tests/unit/adapters/test_downloader_recovery.py -q`
Expected: 8 passed and 23 passed (31 in total). Run the two files five times in a row (`for i in 1 2 3 4 5; do uv run pytest tests/unit/adapters/test_downloader*.py -q -p no:randomly || break; done`) — they involve threads and must never flake.

- [ ] **Step 7: Gates and commit**

Run the four gates (the suite grows by 31; `adapters/downloader.py` should be at or near 100 % coverage — cover any gap with a focused test rather than a `pragma`).

```bash
git add src/utmax/adapters/downloader.py tests/helpers/fake_media.py tests/unit/adapters/test_downloader.py tests/unit/adapters/test_downloader_recovery.py
git commit -m "feat: download streams in parallel, resumable byte ranges" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: ffmpeg for MP3

**Files:**
- Create: `src/utmax/adapters/ffmpeg.py`
- Test: `tests/unit/adapters/test_ffmpeg_adapter.py`, `tests/unit/adapters/test_ffmpeg_mp3.py`

**Interfaces:**
- Consumes: `DownloadCancelled`, `FFmpegFailed`, `FFmpegNotFound` (Task 1).
- Produces (in `utmax.adapters.ffmpeg`):
  - `FFMPEG_ENV = "UTMAX_FFMPEG"`; `STDERR_TAIL = 2000`.
  - `locate_ffmpeg(explicit=None, *, environ=os.environ, which=shutil.which) -> str` (argument, then `$UTMAX_FFMPEG`, then `ffmpeg` on PATH; raises `FFmpegNotFound`).
  - `FFmpeg(executable, *, spawn=subprocess.Popen, poll_interval=0.1)` with `check_mp3()` (probes `-encoders` for `libmp3lame` once per executable; raises `FFmpegNotFound`) and `to_mp3(source: Path, target: Path, *, cancel=None)` (raises `FFmpegFailed`, `DownloadCancelled`; Ctrl-C stops ffmpeg and propagates).

- [ ] **Step 1: Write the failing tests**

`tests/unit/adapters/test_ffmpeg_adapter.py`:

```python
"""Tests for the ffmpeg adapter with fake processes (the real ffmpeg: test_ffmpeg_mp3.py)."""

from __future__ import annotations

import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any

import pytest

from utmax.adapters import ffmpeg as ffmpeg_module
from utmax.adapters.ffmpeg import FFMPEG_ENV, FFmpeg, locate_ffmpeg
from utmax.errors import DownloadCancelled, FFmpegFailed, FFmpegNotFound

ENCODERS = (
    b" A..... aac                  AAC (Advanced Audio Coding)\n"
    b" A..... libmp3lame           libmp3lame MP3 (MPEG audio layer 3) (codec mp3)\n"
)


class FakeProcess:
    """Enough of ``subprocess.Popen`` for the adapter."""

    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
        running: int = 0,
        interrupt: bool = False,
        stubborn: bool = False,
    ) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self._code = returncode
        self._output = (stdout, stderr)
        self._running = running
        self._interrupt = interrupt
        self._stubborn = stubborn

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes, bytes]:
        if self._interrupt:
            self._interrupt = False
            raise KeyboardInterrupt
        if self._running > 0:
            self._running -= 1
            raise subprocess.TimeoutExpired("ffmpeg", timeout or 0)
        self.returncode = self._code
        return self._output

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self._code = -15
        if not self._stubborn:
            self._running = 0

    def kill(self) -> None:
        self.killed = True
        self._running = 0


class FakeSpawn:
    """Records every command and hands out the given processes in order."""

    def __init__(self, *processes: FakeProcess | OSError) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self._processes = deque(processes)

    def __call__(self, args: list[str], **options: Any) -> FakeProcess:
        self.calls.append((args, options))
        process = self._processes.popleft()
        if isinstance(process, OSError):
            raise process
        return process


@pytest.fixture(autouse=True)
def fresh_probe_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg_module, "_mp3_support", {})


def test_locate_prefers_the_argument_then_the_environment_then_path() -> None:
    known = {"C:/tools/ffmpeg.exe": "C:/tools/ffmpeg.exe", "/opt/ff": "/opt/ff", "ffmpeg": "/bin/ff"}
    environ = {FFMPEG_ENV: "/opt/ff"}
    assert locate_ffmpeg("C:/tools/ffmpeg.exe", environ=environ, which=known.get) == (
        "C:/tools/ffmpeg.exe"
    )
    assert locate_ffmpeg(None, environ=environ, which=known.get) == "/opt/ff"
    assert locate_ffmpeg(None, environ={}, which=known.get) == "/bin/ff"
    assert locate_ffmpeg(Path("ffmpeg"), environ={}, which=known.get) == "/bin/ff"


@pytest.mark.parametrize(
    ("explicit", "environ", "origin"),
    [
        ("/nowhere/ffmpeg", {}, "the ffmpeg= argument"),
        (None, {FFMPEG_ENV: "/nowhere/ffmpeg"}, "$UTMAX_FFMPEG"),
        (None, {}, "PATH"),
    ],
)
def test_missing_ffmpeg_says_where_it_looked(
    explicit: str | None, environ: dict[str, str], origin: str
) -> None:
    with pytest.raises(FFmpegNotFound, match=r"needed only for \.mp3 files") as caught:
        locate_ffmpeg(explicit, environ=environ, which=lambda _: None)
    assert origin in str(caught.value)
    assert "winget install Gyan.FFmpeg" in caught.value.suggestion


def test_mp3_support_is_checked_once_per_executable() -> None:
    spawn = FakeSpawn(FakeProcess(stdout=ENCODERS))
    FFmpeg("ffmpeg", spawn=spawn).check_mp3()
    FFmpeg("ffmpeg", spawn=spawn).check_mp3()
    assert len(spawn.calls) == 1
    assert spawn.calls[0][0] == ["ffmpeg", "-hide_banner", "-encoders"]


def test_builds_without_lame_are_refused() -> None:
    spawn = FakeSpawn(FakeProcess(stdout=b" A..... aac  AAC (Advanced Audio Coding)\n"))
    with pytest.raises(FFmpegNotFound, match="built without libmp3lame"):
        FFmpeg("ffmpeg", spawn=spawn).check_mp3()


def test_to_mp3_runs_ffmpeg_quietly() -> None:
    spawn = FakeSpawn(FakeProcess(running=2))
    FFmpeg("/usr/bin/ffmpeg", spawn=spawn, poll_interval=0).to_mp3(
        Path("in.part"), Path("out.tmp")
    )
    args, options = spawn.calls[0]
    assert args == [
        "/usr/bin/ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-i",
        "in.part",
        "-map",
        "0:a:0",
        "-vn",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        "-map_metadata",
        "-1",
        "-f",
        "mp3",
        "out.tmp",
    ]
    assert options["stdin"] is subprocess.DEVNULL
    assert options["stdout"] is subprocess.PIPE
    assert options["stderr"] is subprocess.PIPE
    assert options["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_failures_keep_the_end_of_stderr() -> None:
    noise = b"x" * 5000 + b"\nin.part: Invalid data found when processing input\n"
    spawn = FakeSpawn(FakeProcess(returncode=1, stderr=noise))
    with pytest.raises(FFmpegFailed, match="exited with code 1") as caught:
        FFmpeg("ffmpeg", spawn=spawn).to_mp3(Path("in.part"), Path("out.tmp"))
    assert caught.value.returncode == 1
    assert caught.value.stderr_tail.endswith("Invalid data found when processing input")
    assert len(caught.value.stderr_tail) == 2000


def test_cancel_stops_ffmpeg() -> None:
    process = FakeProcess(running=1000)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DownloadCancelled, match="cancelled"):
        FFmpeg("ffmpeg", spawn=FakeSpawn(process), poll_interval=0).to_mp3(
            Path("a"), Path("b"), cancel=cancel
        )
    assert process.terminated
    assert not process.killed


def test_ffmpeg_that_ignores_terminate_is_killed() -> None:
    process = FakeProcess(running=1000, stubborn=True)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DownloadCancelled):
        FFmpeg("ffmpeg", spawn=FakeSpawn(process), poll_interval=0).to_mp3(
            Path("a"), Path("b"), cancel=cancel
        )
    assert process.killed


def test_ctrl_c_stops_ffmpeg_and_propagates() -> None:
    process = FakeProcess(interrupt=True)
    with pytest.raises(KeyboardInterrupt):
        FFmpeg("ffmpeg", spawn=FakeSpawn(process)).to_mp3(Path("a"), Path("b"))
    assert process.terminated


def test_executables_that_cannot_start_count_as_missing() -> None:
    with pytest.raises(FFmpegNotFound, match="Could not run"):
        FFmpeg("ffmpeg", spawn=FakeSpawn(PermissionError("denied"))).to_mp3(Path("a"), Path("b"))
```

`tests/unit/adapters/test_ffmpeg_mp3.py`:

```python
"""MP3 conversion with the real ffmpeg (``uv run pytest -m ffmpeg``)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from utmax.adapters.ffmpeg import FFmpeg, locate_ffmpeg

pytestmark = pytest.mark.ffmpeg


def test_fragmented_aac_becomes_mp3(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        if os.environ.get("UTMAX_REQUIRE_FFMPEG") == "1":
            pytest.fail("UTMAX_REQUIRE_FFMPEG=1 but ffmpeg or ffprobe is not on PATH")
        pytest.skip("ffmpeg and ffprobe are not installed")
    source = tmp_path / "song.mp3.140.part"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=2",
            "-ac",
            "2",
            "-c:a",
            "aac",
            "-movflags",
            "frag_keyframe+empty_moov+default_base_moof",
            "-frag_duration",
            "500000",
            "-f",
            "mp4",
            str(source),
        ],
        check=True,
    )
    tool = FFmpeg(locate_ffmpeg())
    tool.check_mp3()
    target = tmp_path / ".song.mp3.1a2b.tmp"
    tool.to_mp3(source, target)
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,channels:format=format_name,duration",
            "-of",
            "json",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    info = json.loads(probe.stdout)
    assert info["streams"] == [{"codec_name": "mp3", "channels": 2}]
    assert info["format"]["format_name"] == "mp3"
    assert 1.9 < float(info["format"]["duration"]) < 2.2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/adapters/test_ffmpeg_adapter.py tests/unit/adapters/test_ffmpeg_mp3.py -q`
Expected: collection errors — `ModuleNotFoundError: No module named 'utmax.adapters.ffmpeg'`.

- [ ] **Step 3: Write `src/utmax/adapters/ffmpeg.py`**

```python
"""ffmpeg, which utmax needs only to turn AAC audio into MP3."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from utmax.errors import DownloadCancelled, FFmpegFailed, FFmpegNotFound

__all__ = ["FFMPEG_ENV", "STDERR_TAIL", "FFmpeg", "Process", "Spawn", "locate_ffmpeg"]

log = logging.getLogger("utmax.download")

FFMPEG_ENV = "UTMAX_FFMPEG"
STDERR_TAIL = 2000
_NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_mp3_support: dict[str, bool] = {}
_mp3_lock = threading.Lock()


class Process(Protocol):
    """The part of :class:`subprocess.Popen` utmax uses (tests pass fakes)."""

    returncode: int | None

    def communicate(self, input: Any = None, timeout: float | None = None) -> tuple[Any, Any]: ...

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


Spawn = Callable[..., Process]


def locate_ffmpeg(
    explicit: str | os.PathLike[str] | None = None,
    *,
    environ: Mapping[str, str] = os.environ,
    which: Callable[[str], str | None] = shutil.which,
) -> str:
    """The ffmpeg to run: ``explicit``, else ``$UTMAX_FFMPEG``, else ``ffmpeg`` on ``PATH``.

    Raises:
        FFmpegNotFound: that executable does not exist.
    """
    if explicit is not None:
        name, origin = os.fspath(explicit), "the ffmpeg= argument"
    elif environ.get(FFMPEG_ENV):
        name, origin = environ[FFMPEG_ENV], f"${FFMPEG_ENV}"
    else:
        name, origin = "ffmpeg", "PATH"
    found = which(name)
    if found is None:
        raise FFmpegNotFound(
            f"ffmpeg was not found (looked for {name!r} from {origin}); "
            "it is needed only for .mp3 files."
        )
    return found


class FFmpeg:
    """One ffmpeg executable, run without a console window, stdin or terminal output."""

    def __init__(
        self, executable: str, *, spawn: Spawn = subprocess.Popen, poll_interval: float = 0.1
    ) -> None:
        self.executable = executable
        self._spawn = spawn
        self._poll = poll_interval

    def check_mp3(self) -> None:
        """Make sure this ffmpeg can write MP3 (probed once per executable).

        Raises:
            FFmpegNotFound: it cannot run, or it was built without ``libmp3lame``.
        """
        with _mp3_lock:
            supported = _mp3_support.get(self.executable)
            if supported is None:
                _, stdout, _ = self._run([self.executable, "-hide_banner", "-encoders"], None)
                supported = b"libmp3lame" in stdout
                _mp3_support[self.executable] = supported
        if not supported:
            raise FFmpegNotFound(
                f"{self.executable} cannot write MP3: it was built without libmp3lame.",
                suggestion="Install an ffmpeg build that includes libmp3lame, or download .m4a.",
            )

    def to_mp3(self, source: Path, target: Path, *, cancel: threading.Event | None = None) -> None:
        """Convert the first audio stream of ``source`` to MP3 (LAME VBR quality 2) at ``target``.

        Raises:
            FFmpegFailed: ffmpeg exited with an error; ``stderr_tail`` holds its last words.
            DownloadCancelled: ``cancel`` was set; ffmpeg was stopped.
        """
        args = [
            self.executable,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            "-map_metadata",
            "-1",
            "-f",
            "mp3",
            str(target),
        ]
        log.info("converting %s to MP3 with %s", source.name, self.executable)
        returncode, _, stderr = self._run(args, cancel)
        if returncode != 0:
            tail = stderr.decode("utf-8", errors="replace").strip()[-STDERR_TAIL:]
            raise FFmpegFailed(
                f"ffmpeg exited with code {returncode} while writing {target.name}.",
                returncode=returncode,
                stderr_tail=tail,
            )

    def _run(
        self, args: Sequence[str], cancel: threading.Event | None
    ) -> tuple[int, bytes, bytes]:
        try:
            process = self._spawn(
                list(args),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=_NO_WINDOW,
            )
        except OSError as error:
            raise FFmpegNotFound(f"Could not run {self.executable}: {error}") from error
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise DownloadCancelled(
                        "The MP3 conversion was cancelled; run the download again to finish it."
                    )
                try:
                    stdout, stderr = process.communicate(timeout=self._poll)
                except subprocess.TimeoutExpired:
                    continue
                code = process.returncode
                return (0 if code is None else code), stdout or b"", stderr or b""
        except BaseException:
            _stop(process)
            raise


def _stop(process: Process) -> None:
    """Stop a running ffmpeg, killing it when it ignores ``terminate``."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
```

In `test_ffmpeg_that_ignores_terminate_is_killed` the fake keeps "running" after `terminate()`, so `communicate(timeout=5)` raises `TimeoutExpired` and `kill()` follows. If mypy objects to `subprocess.Popen` as the default `Spawn`, annotate the default with a cast or a small wrapper function and disclose it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/adapters/test_ffmpeg_adapter.py tests/unit/adapters/test_ffmpeg_mp3.py -q`
Expected: 13 passed with ffmpeg installed (12 plus the real conversion); 12 passed and 1 skipped without it. `uv run pytest -m ffmpeg -q` also runs the real conversion.

- [ ] **Step 5: Gates and commit**

Run the four gates (the suite grows by 13 on machines with ffmpeg).

```bash
git add src/utmax/adapters/ffmpeg.py tests/unit/adapters/test_ffmpeg_adapter.py tests/unit/adapters/test_ffmpeg_mp3.py
git commit -m "feat: convert AAC audio to MP3 with ffmpeg" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 9: The download service

**Files:**
- Create: `src/utmax/services/download.py`, `tests/helpers/downloads.py`
- Test: `tests/unit/services/test_download_audio.py`, `tests/unit/services/test_download_video.py`

**Interfaces:**
- Consumes: everything above — `choose_streams` (Task 2), `PlayerData.streams`, `InnerTubeClient.player(purpose="streams")`, `TranscriptService.track_list` (Task 3), `DEFAULT_CHUNK_SIZE`, `MIN_CHUNK_SIZE` (Task 4), `resolve_target`, `part_name`, `sidecar_name` (Task 5), `Opener` (Tasks 6–7), `Downloader`, `Job`, `ProgressReporter` (Task 7), `FFmpeg`, `locate_ffmpeg` (Task 8); from M1–M3: `parse_video_id`, `select_track`, `plan_mux`, `Flavor`, `default_subtitle_index`, `FileByteSource`, `write_mux_plan`, `write_text_atomic`, `replace_with_retry`.
- Produces (in `utmax.services.download`):
  - `MAX_CONNECTIONS = 16`.
  - `DownloadOptions(format=None, quality="compat", subtitles=None, subtitle_mode="embed", default_subtitle=None, connections=4, chunk_size=DEFAULT_CHUNK_SIZE, resume=True, overwrite=False, ffmpeg=None, progress=None, cancel=None)` with `check()`.
  - `DownloadService(innertube, transcripts, opener, *, locate=locate_ffmpeg, make_ffmpeg=FFmpeg)` with `download(video, path, options) -> DownloadResult`.
  - Test helpers (in `tests.helpers.downloads`): `FakeYouTube(*, captions=True)` (`api`, `media`, `send`, `stream`, `service(**options)`), `VIDEO_BYTES`, `AV1_BYTES`, `AUDIO_BYTES`, `read_movie(path)`, `codec_of(track)`, `FakeFFmpegRuns`.

Order of checks inside `download` (the tests pin it): video ID → option values → target (extension, `format`) → `.mov` with `max` → `default_subtitle` for audio files → ffmpeg for `.mp3` → an existing named target → **player request** → the folder target's name → subtitles fetched (so `NoTranscriptFound` comes before any media byte) → where subtitles go (`default_subtitle` must match an embedded track) → existing sidecars → stream choice → **media download** → mux or MP3 conversion → parts deleted → sidecars written.

- [ ] **Step 1: Write the fake YouTube**

`tests/helpers/downloads.py`:

```python
"""A fake YouTube for download tests: InnerTube, captions and googlevideo behind one transport.

The streams are real fragmented MP4 files built by ``tests.helpers.fmp4_factory``: H.264
(itag 137) and AV1 (itag 399) video of 100 frames at 25 fps, and AAC audio (itag 140) of
172 frames at 44.1 kHz, so the muxer and ``parse_progressive`` run on genuine data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.helpers.fake_media import FakeBody, FakeMedia
from tests.helpers.fake_transport import FakeTransport, json_response
from tests.helpers.fmp4_factory import Sample, Track, simple_file
from tests.helpers.youtube import MANUAL_JSON3, json3_payload, player_payload
from utmax.adapters.ffmpeg import FFmpeg
from utmax.adapters.files import FileByteSource
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.media.progressive import ProgressiveFile, parse_progressive
from utmax.services.download import DownloadService
from utmax.services.transcripts import TranscriptService
from utmax.transport import HttpRequest, HttpResponse

VIDEO_BYTES = simple_file(
    [Sample(512, 600 + index % 50, sync=index % 25 == 0) for index in range(100)],
    track=Track(),
    per_fragment=25,
)
AV1_BYTES = simple_file(
    [Sample(512, 400 + index % 30, sync=index % 25 == 0) for index in range(100)],
    track=Track(codec="av01"),
    per_fragment=25,
)
AUDIO_BYTES = simple_file(
    [Sample(1024, 300 + index % 9) for index in range(172)],
    track=Track(handler="soun", codec="mp4a", timescale=44100),
    per_fragment=43,
)
LAST_MODIFIED = "1766957926174250"


def _format(itag: int, mime: str, url: str, size: int, **fields: Any) -> dict[str, Any]:
    return {
        "itag": itag,
        "mimeType": mime,
        "url": f"{url}?c=ANDROID_VR",
        "bitrate": 1000 * itag,
        "contentLength": str(size),
        "lastModified": LAST_MODIFIED,
        **fields,
    }


def streaming_data_for(media: FakeMedia) -> dict[str, Any]:
    """``streamingData`` whose URLs point at ``media``."""
    video = {"width": 1920, "height": 1080, "fps": 25}
    return {
        "expiresInSeconds": "21540",
        "adaptiveFormats": [
            _format(
                137,
                'video/mp4; codecs="avc1.640028"',
                media.add("137", VIDEO_BYTES),
                len(VIDEO_BYTES),
                **video,
            ),
            _format(
                399,
                'video/mp4; codecs="av01.0.08M.08"',
                media.add("399", AV1_BYTES),
                len(AV1_BYTES),
                **video,
            ),
            _format(
                140,
                'audio/mp4; codecs="mp4a.40.2"',
                media.add("140", AUDIO_BYTES),
                len(AUDIO_BYTES),
                audioSampleRate="44100",
                audioChannels=2,
            ),
        ],
    }


class FakeYouTube:
    """One transport: InnerTube and captions (``api``) plus googlevideo (``media``)."""

    def __init__(self, *, captions: bool = True) -> None:
        self.media = FakeMedia()
        self.api = FakeTransport()
        payload = player_payload(streaming_data=streaming_data_for(self.media), captions=captions)
        self.api.add("POST", "/youtubei/v1/player", json_response(payload), repeat=True)
        self.api.add("GET", "lang=en&fmt=json3", json_response(MANUAL_JSON3), repeat=True)
        german = json3_payload((1000, 2000, "Wir sind keine Fremden"))
        self.api.add("GET", "lang=de-DE", json_response(german), repeat=True)

    def send(self, request: HttpRequest) -> HttpResponse:
        return self.api.send(request)

    def stream(self, request: HttpRequest) -> FakeBody:
        return self.media.stream(request)

    def service(self, **options: Any) -> DownloadService:
        innertube = InnerTubeClient(self)
        return DownloadService(innertube, TranscriptService(innertube), self.stream, **options)


def read_movie(path: Path) -> ProgressiveFile:
    with FileByteSource(path) as source:
        return parse_progressive(source)


def codec_of(track: Any) -> bytes:
    """The sample entry type of a parsed track: ``b"avc1"``, ``b"av01"``, ``b"mp4a"``, ``b"tx3g"``."""
    entry: bytes = track.sample_entries[0]
    return entry[4:8]


class _Finished:
    """A process that has already exited successfully."""

    def __init__(self, stdout: bytes = b"") -> None:
        self.returncode: int | None = None
        self._stdout = stdout

    def communicate(self, input: Any = None, timeout: float | None = None) -> tuple[bytes, bytes]:
        self.returncode = 0
        return self._stdout, b""

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        """Nothing to stop."""

    def kill(self) -> None:
        """Nothing to stop."""


class FakeFFmpegRuns:
    """Stands in for ffmpeg: lists libmp3lame, and "converts" by writing an ID3 header."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], **options: Any) -> _Finished:
        self.calls.append(args)
        if "-encoders" in args:
            return _Finished(b" A..... libmp3lame           libmp3lame MP3 (MPEG audio layer 3)\n")
        Path(args[-1]).write_bytes(b"ID3" + bytes(100))
        return _Finished()

    def service(self, youtube: FakeYouTube) -> DownloadService:
        return youtube.service(
            locate=lambda _: "ffmpeg-for-tests",
            make_ffmpeg=lambda executable: FFmpeg(executable, spawn=self),
        )
```

- [ ] **Step 2: Write the failing tests for audio files, targets and early checks**

`tests/unit/services/test_download_audio.py`:

```python
"""Tests for audio downloads, targets and early checks (fake YouTube, real files and muxer)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from tests.helpers.downloads import FakeFFmpegRuns, FakeYouTube, read_movie
from tests.helpers.youtube import VIDEO_ID
from utmax.adapters import ffmpeg as ffmpeg_module
from utmax.errors import (
    DownloadCancelled,
    FFmpegNotFound,
    InvalidOption,
    InvalidVideoId,
    OutputExists,
    StreamForbidden,
    UnsupportedFormat,
)
from utmax.models import Progress
from utmax.services.download import DownloadOptions

TITLE_FILE = "Rick Astley - Never Gonna Give You Up (Official Video) [dQw4w9WgXcQ]"


@pytest.fixture(autouse=True)
def fresh_probe_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg_module, "_mp3_support", {})


def test_m4a_downloads_remux_the_aac_stream(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    result = youtube.service().download(VIDEO_ID, tmp_path / "rick.m4a", DownloadOptions())
    assert result.path == tmp_path / "rick.m4a"
    assert (result.container, result.video_format, result.audio_format.itag) == ("m4a", None, 140)
    assert (result.embedded_subtitles, result.sidecars, result.resumed) == ((), (), False)
    assert result.size_bytes == result.path.stat().st_size
    movie = read_movie(result.path)
    assert movie.major_brand == "M4A "
    assert [track.handler for track in movie.tracks] == ["soun"]
    assert len(movie.tracks[0].samples) == 172
    assert sorted(path.name for path in tmp_path.iterdir()) == ["rick.m4a"]
    assert youtube.api.urls("GET") == []


def test_missing_parent_folders_are_created(tmp_path: Path) -> None:
    target = tmp_path / "new" / "folder" / "rick.m4a"
    result = FakeYouTube().service().download(VIDEO_ID, target, DownloadOptions())
    assert result.path == target
    assert target.exists()


def test_folders_get_files_named_after_the_title(tmp_path: Path) -> None:
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path, DownloadOptions(format="m4a"))
    assert result.path == tmp_path / f"{TITLE_FILE}.m4a"


def test_existing_files_are_refused_before_any_request(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    (tmp_path / "rick.m4a").write_bytes(b"old")
    with pytest.raises(OutputExists, match="already exists"):
        youtube.service().download(VIDEO_ID, tmp_path / "rick.m4a", DownloadOptions())
    assert (youtube.api.requests, youtube.media.requests) == ([], [])


def test_overwrite_replaces_the_file(tmp_path: Path) -> None:
    (tmp_path / "rick.m4a").write_bytes(b"old")
    options = DownloadOptions(overwrite=True)
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.m4a", options)
    assert result.path.read_bytes()[4:8] == b"ftyp"


def test_folder_targets_are_checked_once_the_title_is_known(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    (tmp_path / f"{TITLE_FILE}.m4a").write_bytes(b"old")
    with pytest.raises(OutputExists):
        youtube.service().download(VIDEO_ID, tmp_path, DownloadOptions(format="m4a"))
    assert youtube.media.requests == []


@pytest.mark.parametrize(
    ("name", "options", "error", "match"),
    [
        ("rick.mp4", DownloadOptions(quality="best"), InvalidOption, "quality="),
        ("rick.mp4", DownloadOptions(subtitle_mode="burn"), InvalidOption, "subtitle_mode="),
        ("rick.mp4", DownloadOptions(connections=0), InvalidOption, "connections must be"),
        ("rick.mp4", DownloadOptions(connections=17), InvalidOption, "connections must be"),
        ("rick.mp4", DownloadOptions(chunk_size=1000), InvalidOption, "chunk_size must be"),
        ("rick.mp4", DownloadOptions(subtitles="en"), InvalidOption, "subtitles must be a list"),
        ("rick.mov", DownloadOptions(quality="max"), InvalidOption, r"needs \.mp4"),
        ("rick.m4a", DownloadOptions(default_subtitle="en"), InvalidOption, "cannot embed"),
        ("rick.avi", DownloadOptions(), UnsupportedFormat, "Cannot tell the file type"),
        ("rick.mp4", DownloadOptions(format="mp3"), InvalidOption, "does not match"),
    ],
)
def test_bad_options_fail_before_any_request(
    tmp_path: Path,
    name: str,
    options: DownloadOptions,
    error: type[Exception],
    match: str,
) -> None:
    youtube = FakeYouTube()
    with pytest.raises(error, match=match):
        youtube.service().download(VIDEO_ID, tmp_path / name, options)
    assert (youtube.api.requests, youtube.media.requests) == ([], [])


def test_invalid_video_ids_fail_first(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    with pytest.raises(InvalidVideoId):
        youtube.service().download("not a video", tmp_path / "x.mp4", DownloadOptions())
    assert youtube.api.requests == []


def test_mp3_needs_ffmpeg_before_any_request(tmp_path: Path) -> None:
    youtube = FakeYouTube()

    def missing(_: object) -> str:
        raise FFmpegNotFound("no ffmpeg here")

    with pytest.raises(FFmpegNotFound):
        youtube.service(locate=missing).download(VIDEO_ID, tmp_path / "song.mp3", DownloadOptions())
    assert youtube.api.requests == []


def test_mp3_downloads_convert_the_audio_with_ffmpeg(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    runs = FakeFFmpegRuns()
    result = runs.service(youtube).download(VIDEO_ID, tmp_path / "song.mp3", DownloadOptions())
    assert (result.container, result.video_format) == ("mp3", None)
    assert result.path.read_bytes().startswith(b"ID3")
    conversion = next(call for call in runs.calls if "-i" in call)
    assert conversion[conversion.index("-i") + 1] == str(tmp_path / "song.mp3.140.part")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["song.mp3"]


def test_audio_files_write_requested_subtitles_next_to_them(tmp_path: Path) -> None:
    options = DownloadOptions(subtitles=["en"])
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.m4a", options)
    assert result.sidecars == (tmp_path / "rick.en.srt",)
    assert result.embedded_subtitles == ()
    assert "We're no strangers to love" in result.sidecars[0].read_text(encoding="utf-8")


def test_progress_goes_through_download_mux_and_finish(tmp_path: Path) -> None:
    seen: list[Progress] = []
    options = DownloadOptions(progress=seen.append)
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.m4a", options)
    phases = [progress.phase for progress in seen]
    assert (phases[0], phases[-1]) == ("downloading", "finished")
    assert "muxing" in phases
    order = ["downloading", "muxing", "finished"]
    assert phases == sorted(phases, key=order.index)
    assert seen[-1].bytes_done == result.size_bytes


def test_cancel_during_mux_keeps_the_parts_for_a_resume(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    cancel = threading.Event()

    def watch(progress: Progress) -> None:
        if progress.phase == "muxing":
            cancel.set()

    options = DownloadOptions(progress=watch, cancel=cancel)
    with pytest.raises(DownloadCancelled):
        youtube.service().download(VIDEO_ID, tmp_path / "rick.m4a", options)
    assert (tmp_path / "rick.m4a.140.part").exists()
    assert not (tmp_path / "rick.m4a").exists()
    media_requests = len(youtube.media.requests)
    result = youtube.service().download(VIDEO_ID, tmp_path / "rick.m4a", DownloadOptions())
    assert result.resumed is True
    assert len(youtube.media.requests) == media_requests
    assert sorted(path.name for path in tmp_path.iterdir()) == ["rick.m4a"]


def test_failed_downloads_keep_their_parts(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    youtube.media.expired.add("https://media.test/140?c=ANDROID_VR")
    with pytest.raises(StreamForbidden):
        youtube.service().download(VIDEO_ID, tmp_path / "rick.m4a", DownloadOptions())
    assert (tmp_path / "rick.m4a.140.part").exists()
    assert (tmp_path / "rick.m4a.140.part.json").exists()
```

- [ ] **Step 3: Write the failing tests for videos and subtitles**

`tests/unit/services/test_download_video.py`:

```python
"""Tests for video downloads with subtitles (fake YouTube, real files and muxer)."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

import pytest

from tests.helpers.builders import VIDEO, make_transcript
from tests.helpers.downloads import FakeYouTube, codec_of, read_movie
from tests.helpers.youtube import VIDEO_ID
from utmax.errors import InvalidOption, NoTranscriptFound, OutputExists
from utmax.models import Segment
from utmax.services.download import DownloadOptions

TURKISH = replace(
    make_transcript(
        Segment(1.0, 2.0, "Merhaba"), language_code="tr", language="Turkish", is_generated=True
    ),
    translated_from="en",
    translator="claude=claude-opus-5",
)


def test_mp4_downloads_embed_the_spoken_language_by_default(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    result = youtube.service().download(VIDEO_ID, tmp_path / "rick.mp4", DownloadOptions())
    assert result.video_format is not None
    assert (result.video_format.itag, result.audio_format.itag) == (137, 140)
    assert result.embedded_subtitles == ("en",)
    movie = read_movie(result.path)
    assert [track.handler for track in movie.tracks] == ["vide", "soun", "sbtl"]
    assert [codec_of(track) for track in movie.tracks] == [b"avc1", b"mp4a", b"tx3g"]
    assert [len(track.samples) for track in movie.tracks[:2]] == [100, 172]
    subtitle = movie.tracks[2]
    assert (subtitle.extended_language, subtitle.name, subtitle.flags & 1) == ("en", "English", 1)
    assert len(youtube.api.urls("POST")) == 1  # one player response serves streams and captions


def test_an_empty_subtitle_list_embeds_nothing(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    options = DownloadOptions(subtitles=[])
    result = youtube.service().download(VIDEO_ID, tmp_path / "rick.mp4", options)
    assert result.embedded_subtitles == ()
    assert [track.handler for track in read_movie(result.path).tracks] == ["vide", "soun"]
    assert youtube.api.urls("GET") == []


def test_unknown_subtitle_languages_fail_before_any_media_byte(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    with pytest.raises(NoTranscriptFound):
        youtube.service().download(
            VIDEO_ID, tmp_path / "rick.mp4", DownloadOptions(subtitles=["xx"])
        )
    assert youtube.media.requests == []


def test_codes_and_transcripts_mix_and_default_subtitle_picks_the_enabled_track(
    tmp_path: Path,
) -> None:
    options = DownloadOptions(subtitles=["en", TURKISH], default_subtitle="tr")
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.mp4", options)
    assert result.embedded_subtitles == ("en", "tr")
    english, turkish = read_movie(result.path).tracks[2:]
    assert (english.flags & 1, turkish.flags & 1) == (0, 1)
    assert turkish.name == "Turkish (AI: claude=claude-opus-5)"


def test_sidecar_mode_writes_srt_files_instead(tmp_path: Path) -> None:
    options = DownloadOptions(subtitle_mode="sidecar")
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.mp4", options)
    assert result.embedded_subtitles == ()
    assert result.sidecars == (tmp_path / "rick.en.srt",)
    assert "We're no strangers to love" in result.sidecars[0].read_text(encoding="utf-8")
    assert [track.handler for track in read_movie(result.path).tracks] == ["vide", "soun"]


def test_both_mode_embeds_and_writes(tmp_path: Path) -> None:
    options = DownloadOptions(subtitles=["en", "de"], subtitle_mode="both")
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.mp4", options)
    assert result.embedded_subtitles == ("en", "de-DE")
    assert result.sidecars == (tmp_path / "rick.en.srt", tmp_path / "rick.de-DE.srt")


def test_default_subtitle_must_name_an_embedded_track_before_download(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    service = youtube.service()
    with pytest.raises(InvalidOption, match="matches no embedded subtitle track"):
        service.download(
            VIDEO_ID, tmp_path / "rick.mp4", DownloadOptions(subtitles=["en"], default_subtitle="de")
        )
    with pytest.raises(InvalidOption, match="no subtitles are embedded"):
        service.download(
            VIDEO_ID,
            tmp_path / "rick.mp4",
            DownloadOptions(subtitle_mode="sidecar", default_subtitle="en"),
        )
    assert youtube.media.requests == []


def test_videos_without_captions_download_without_subtitles(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    youtube = FakeYouTube(captions=False)
    with caplog.at_level(logging.INFO, logger="utmax.download"):
        result = youtube.service().download(VIDEO_ID, tmp_path / "rick.mp4", DownloadOptions())
    assert result.embedded_subtitles == ()
    assert "has no subtitles" in caplog.text


def test_mov_downloads_use_the_quicktime_flavor(tmp_path: Path) -> None:
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.mov", DownloadOptions())
    assert result.container == "mov"
    assert read_movie(result.path).major_brand == "qt  "


def test_max_quality_prefers_av1(tmp_path: Path) -> None:
    options = DownloadOptions(quality="max")
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.mp4", options)
    assert result.video_format is not None
    assert result.video_format.itag == 399
    assert codec_of(read_movie(result.path).tracks[0]) == b"av01"


def test_transcripts_of_other_videos_are_refused(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    other = replace(TURKISH, video=replace(VIDEO, video_id="aaaaaaaaaaa"))
    with pytest.raises(InvalidOption, match="belongs to video aaaaaaaaaaa"):
        youtube.service().download(
            VIDEO_ID, tmp_path / "rick.mp4", DownloadOptions(subtitles=[other])
        )
    assert youtube.media.requests == []


def test_duplicate_subtitle_languages_are_refused(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    with pytest.raises(InvalidOption, match="own language code"):
        youtube.service().download(
            VIDEO_ID, tmp_path / "rick.mp4", DownloadOptions(subtitles=["en", "EN"])
        )
    assert youtube.media.requests == []


def test_existing_sidecars_are_refused_before_download(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    (tmp_path / "rick.en.srt").write_text("old", encoding="utf-8")
    with pytest.raises(OutputExists, match=r"rick\.en\.srt"):
        youtube.service().download(
            VIDEO_ID, tmp_path / "rick.mp4", DownloadOptions(subtitle_mode="sidecar")
        )
    assert youtube.media.requests == []
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/services/test_download_audio.py tests/unit/services/test_download_video.py -q`
Expected: collection errors — `ModuleNotFoundError: No module named 'utmax.services.download'` (raised through `tests.helpers.downloads`).

- [ ] **Step 5: Write `src/utmax/services/download.py`**

```python
"""Download a video or its audio: choose the streams, fetch them resumably, then mux them (or
convert to MP3), embedding the subtitles or writing them next to the file."""

from __future__ import annotations

import logging
import os
import secrets
import threading
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from utmax.adapters.downloader import Downloader, Job, Opener, ProgressReporter
from utmax.adapters.ffmpeg import FFmpeg, locate_ffmpeg
from utmax.adapters.files import (
    FileByteSource,
    replace_with_retry,
    write_mux_plan,
    write_text_atomic,
)
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.downloads import DEFAULT_CHUNK_SIZE, MIN_CHUNK_SIZE
from utmax.core.filenames import part_name, resolve_target, sidecar_name
from utmax.core.ids import parse_video_id
from utmax.core.media.moov import Flavor
from utmax.core.media.mux import plan_mux
from utmax.core.media.tx3g import default_subtitle_index
from utmax.core.player import PlayerData
from utmax.core.selection import select_track
from utmax.core.streams import choose_streams
from utmax.errors import DownloadCancelled, InvalidOption, OutputExists
from utmax.models import (
    Container,
    DownloadResult,
    Progress,
    Quality,
    SubtitleMode,
    TrackList,
    Transcript,
)
from utmax.services.transcripts import TranscriptService

__all__ = ["MAX_CONNECTIONS", "DownloadOptions", "DownloadService"]

log = logging.getLogger("utmax.download")

MAX_CONNECTIONS = 16
_QUALITIES = ("compat", "max")
_SUBTITLE_MODES = ("embed", "sidecar", "both")


@dataclass(frozen=True, slots=True)
class DownloadOptions:
    """Everything :func:`utmax.download` accepts besides the video and the path."""

    format: Container | None = None
    quality: Quality = "compat"
    subtitles: Sequence[str | Transcript] | None = None
    subtitle_mode: SubtitleMode = "embed"
    default_subtitle: str | None = None
    connections: int = 4
    chunk_size: int = DEFAULT_CHUNK_SIZE
    resume: bool = True
    overwrite: bool = False
    ffmpeg: str | os.PathLike[str] | None = None
    progress: Callable[[Progress], None] | None = None
    cancel: threading.Event | None = None

    def check(self) -> None:
        """Reject option values that can never work, before anything is requested."""
        if self.quality not in _QUALITIES:
            raise InvalidOption(f'quality={self.quality!r} is not "compat" or "max".')
        if self.subtitle_mode not in _SUBTITLE_MODES:
            raise InvalidOption(
                f'subtitle_mode={self.subtitle_mode!r} is not "embed", "sidecar" or "both".'
            )
        if not 1 <= self.connections <= MAX_CONNECTIONS:
            raise InvalidOption(
                f"connections must be between 1 and {MAX_CONNECTIONS}, not {self.connections}."
            )
        if self.chunk_size < MIN_CHUNK_SIZE:
            raise InvalidOption(
                f"chunk_size must be at least {MIN_CHUNK_SIZE} bytes, not {self.chunk_size}."
            )
        if isinstance(self.subtitles, str):
            raise InvalidOption(
                f"subtitles must be a list, such as subtitles=[{self.subtitles!r}].",
                suggestion=f"Pass subtitles=[{self.subtitles!r}]: a list of codes or transcripts.",
            )


class DownloadService:
    """The download use case: InnerTube for streams and captions, an opener for media bytes."""

    def __init__(
        self,
        innertube: InnerTubeClient,
        transcripts: TranscriptService,
        opener: Opener,
        *,
        locate: Callable[[str | os.PathLike[str] | None], str] = locate_ffmpeg,
        make_ffmpeg: Callable[[str], FFmpeg] = FFmpeg,
    ) -> None:
        self._innertube = innertube
        self._transcripts = transcripts
        self._opener = opener
        self._locate = locate
        self._make_ffmpeg = make_ffmpeg

    def download(
        self, video: str, path: str | os.PathLike[str], options: DownloadOptions
    ) -> DownloadResult:
        """Download ``video`` to ``path``; :func:`utmax.download` documents the rules."""
        video_id = parse_video_id(video)
        options.check()
        target = resolve_target(path, format=options.format, is_dir=Path(path).is_dir())
        container = target.container
        if container == "mov" and options.quality == "max":
            raise InvalidOption(
                'quality="max" needs .mp4: QuickTime .mov files cannot hold AV1 video.',
                suggestion='Save max quality as .mp4, or use quality="compat" for .mov.',
            )
        audio_only = container in ("m4a", "mp3")
        if audio_only and options.default_subtitle is not None:
            raise InvalidOption(
                f".{container} files cannot embed subtitles, so default_subtitle has no effect.",
                suggestion="Leave default_subtitle out for audio files.",
            )
        ffmpeg = self._ffmpeg(options.ffmpeg) if container == "mp3" else None
        if target.file is not None:
            _check_free(Path(target.file), options.overwrite, video_id)
        player = self._innertube.player(video_id, purpose="streams")
        final = Path(target.path_for(player.video))
        if target.file is None:
            _check_free(final, options.overwrite, video_id)
        subtitles = self._subtitles(player, options.subtitles, audio_only=audio_only)
        embedded, sidecars = _placement(subtitles, final, options, audio_only=audio_only)
        for sidecar, _ in sidecars:
            _check_free(sidecar, options.overwrite, video_id)
        video_stream, audio_stream = choose_streams(
            player.streams, container=container, quality=options.quality, video_id=video_id
        )
        streams = [stream for stream in (video_stream, audio_stream) if stream is not None]
        log.info(
            "downloading %s of %s to %s",
            " + ".join(stream.format.label for stream in streams),
            video_id,
            final.name,
        )
        jobs = [Job(stream, Path(part_name(final, stream.format.itag))) for stream in streams]
        reporter = ProgressReporter(video_id, options.progress)
        downloader = Downloader(
            self._opener,
            connections=options.connections,
            chunk_size=options.chunk_size,
            refresh=lambda: self._innertube.player(video_id, purpose="streams").streams,
            reporter=reporter,
            cancel=options.cancel,
        )
        resumed = downloader.run(jobs, video_id=video_id, resume=options.resume)
        if ffmpeg is not None:
            reporter.report("converting", 0, None, force=True)
            _convert(ffmpeg, jobs[-1].part, final, options.cancel)
        else:
            _mux(
                jobs,
                final,
                flavor=_flavor(container),
                embedded=embedded,
                options=options,
                reporter=reporter,
                video_id=video_id,
            )
        for job in jobs:
            job.part.unlink(missing_ok=True)
            job.state_path.unlink(missing_ok=True)
        written = tuple(write_text_atomic(path, t.to_srt()) for path, t in sidecars)
        size = final.stat().st_size
        reporter.report("finished", size, size, force=True)
        return DownloadResult(
            path=final,
            video=player.video,
            container=container,
            video_format=video_stream.format if video_stream is not None else None,
            audio_format=audio_stream.format,
            embedded_subtitles=tuple(transcript.language_code for transcript in embedded),
            sidecars=written,
            size_bytes=size,
            resumed=resumed,
        )

    def _ffmpeg(self, explicit: str | os.PathLike[str] | None) -> FFmpeg:
        tool = self._make_ffmpeg(self._locate(explicit))
        tool.check_mp3()
        return tool

    def _subtitles(
        self,
        player: PlayerData,
        requested: Sequence[str | Transcript] | None,
        *,
        audio_only: bool,
    ) -> list[Transcript]:
        """Fetch every subtitle before any media byte, so a wrong language fails fast."""
        video_id = player.video.video_id
        if requested is None:
            if audio_only:
                return []
            spoken = self._transcripts.track_list(player)
            if not spoken:
                log.info("video %s has no subtitles; downloading it without", video_id)
                return []
            return [spoken.find().fetch()]
        tracks: TrackList | None = None
        subtitles: list[Transcript] = []
        for item in requested:
            if isinstance(item, Transcript):
                if item.video.video_id != video_id:
                    raise InvalidOption(
                        f"A subtitle transcript belongs to video {item.video.video_id}, "
                        f"not {video_id}."
                    )
                subtitles.append(item)
                continue
            if tracks is None:
                tracks = self._transcripts.track_list(player)
            subtitles.append(select_track(tracks.tracks, item).fetch())
        codes = [transcript.language_code.lower() for transcript in subtitles]
        if len(set(codes)) != len(codes):
            raise InvalidOption(
                f"Each subtitle needs its own language code; got {', '.join(codes)}."
            )
        return subtitles


def _placement(
    subtitles: list[Transcript], final: Path, options: DownloadOptions, *, audio_only: bool
) -> tuple[list[Transcript], list[tuple[Path, Transcript]]]:
    """Which subtitles go into the file, and which are written next to it (and where)."""
    if audio_only:
        return [], [(Path(sidecar_name(final, t.language_code)), t) for t in subtitles]
    mode = options.subtitle_mode
    embedded = subtitles if mode in ("embed", "both") else []
    beside = subtitles if mode in ("sidecar", "both") else []
    if embedded:
        default_subtitle_index([t.language_code for t in embedded], options.default_subtitle)
    elif options.default_subtitle is not None:
        raise InvalidOption(
            "default_subtitle picks an embedded track, but no subtitles are embedded.",
            suggestion='Use subtitle_mode="embed" or "both", or leave default_subtitle out.',
        )
    return embedded, [(Path(sidecar_name(final, t.language_code)), t) for t in beside]


def _check_free(path: Path, overwrite: bool, video_id: str) -> None:
    if path.exists() and not overwrite:
        raise OutputExists(f"{path} already exists.", video_id=video_id)


def _flavor(container: Container) -> Flavor:
    if container == "mov":
        return "mov"
    if container == "m4a":
        return "m4a"
    return "mp4"


def _mux(
    jobs: Sequence[Job],
    final: Path,
    *,
    flavor: Flavor,
    embedded: Sequence[Transcript],
    options: DownloadOptions,
    reporter: ProgressReporter,
    video_id: str,
) -> None:
    """Assemble ``final`` from the parts, atomically; the parts stay when this fails."""

    def progress(written: int, total: int) -> None:
        if options.cancel is not None and options.cancel.is_set():
            raise DownloadCancelled(
                f"The download of video {video_id} was cancelled; run it again to finish it.",
                video_id=video_id,
            )
        reporter.report("muxing", written, total)

    with ExitStack() as stack:
        sources = [stack.enter_context(FileByteSource(job.part)) for job in jobs]
        plan = plan_mux(
            sources, flavor=flavor, subtitles=embedded, default_subtitle=options.default_subtitle
        )
        write_mux_plan(plan, sources, final, progress=progress)


def _convert(ffmpeg: FFmpeg, audio: Path, final: Path, cancel: threading.Event | None) -> None:
    """Convert to MP3 in a temporary file next to ``final``, then move it into place."""
    temporary = final.with_name(f".{final.name}.{secrets.token_hex(4)}.tmp")
    try:
        ffmpeg.to_mp3(audio, temporary, cancel=cancel)
        with temporary.open("rb+") as handle:
            os.fsync(handle.fileno())
        replace_with_retry(temporary, final)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/services/test_download_audio.py tests/unit/services/test_download_video.py -q`
Expected: 23 passed and 13 passed (36 in total).

- [ ] **Step 7: Gates and commit**

Run the four gates (the suite grows by 36).

```bash
git add src/utmax/services/download.py tests/helpers/downloads.py tests/unit/services/test_download_audio.py tests/unit/services/test_download_video.py
git commit -m "feat: download videos and audio with embedded or sidecar subtitles" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: `utmax.download` and `Client.download`

**Files:**
- Modify: `src/utmax/client.py`, `src/utmax/__init__.py`
- Test: `tests/unit/test_download_api.py`

**Interfaces:**
- Consumes: `DownloadService`, `DownloadOptions` (Task 9); `open_stream` (Task 6); `Client._transport` (Task 6).
- Produces: `Client.download(video, path, *, format=None, quality="compat", subtitles=None, subtitle_mode="embed", default_subtitle=None, connections=4, chunk_size=8 * 2**20, resume=True, overwrite=False, ffmpeg=None, progress=None, cancel=None) -> DownloadResult` and the same `utmax.download(...)` (spec §4.1), exported in `utmax.__all__`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_download_api.py`:

```python
"""Tests for utmax.download and Client.download."""

from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import utmax
from tests.helpers.downloads import FakeYouTube
from tests.helpers.youtube import VIDEO_ID
from utmax import Client
from utmax.transport import HttpRequest, HttpResponse

PARAMETERS = [
    "video",
    "path",
    "format",
    "quality",
    "subtitles",
    "subtitle_mode",
    "default_subtitle",
    "connections",
    "chunk_size",
    "resume",
    "overwrite",
    "ffmpeg",
    "progress",
    "cancel",
]


class SendOnly:
    """A custom transport without ``stream()``: downloads fall back to buffered ranges."""

    def __init__(self, youtube: FakeYouTube) -> None:
        self._youtube = youtube

    def send(self, request: HttpRequest) -> HttpResponse:
        if request.url.startswith("https://media.test/"):
            return self._youtube.media.send(request)
        return self._youtube.api.send(request)


def test_client_downloads_through_its_transport(tmp_path: Path) -> None:
    with Client(transport=FakeYouTube()) as client:
        result = client.download(VIDEO_ID, tmp_path / "rick.mp4")
    assert result.embedded_subtitles == ("en",)
    assert result.path.exists()


def test_the_facade_uses_the_default_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(utmax, "_default_client", Client(transport=FakeYouTube()))
    result = utmax.download(f"https://youtu.be/{VIDEO_ID}", tmp_path / "rick.m4a")
    assert result.audio_format.itag == 140


def test_download_signature_matches_the_spec() -> None:
    parameters = inspect.signature(utmax.download).parameters
    assert list(parameters) == PARAMETERS
    assert parameters["chunk_size"].default == 8 * 2**20
    assert (parameters["quality"].default, parameters["subtitle_mode"].default) == (
        "compat",
        "embed",
    )
    assert list(inspect.signature(Client.download).parameters)[1:] == PARAMETERS


def test_download_is_exported() -> None:
    assert "download" in utmax.__all__
    assert callable(utmax.download)


def test_one_client_downloads_in_parallel_threads(tmp_path: Path) -> None:
    client = Client(transport=FakeYouTube())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda n: client.download(VIDEO_ID, tmp_path / f"rick{n}.m4a"), range(4))
        )
    assert [result.path.name for result in results] == [f"rick{n}.m4a" for n in range(4)]
    assert len({result.size_bytes for result in results}) == 1


def test_custom_transports_without_streaming_still_download(tmp_path: Path) -> None:
    result = Client(transport=SendOnly(FakeYouTube())).download(VIDEO_ID, tmp_path / "rick.m4a")
    assert result.size_bytes > 0


def test_downloads_print_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    Client(transport=FakeYouTube()).download(VIDEO_ID, tmp_path / "rick.mp4")
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_download_api.py -q`
Expected: 7 failed — `AttributeError: 'Client' object has no attribute 'download'` / `module 'utmax' has no attribute 'download'`.

- [ ] **Step 3: Add `Client.download`**

In `src/utmax/client.py`, add the imports:

```python
import os
import threading
from collections.abc import Callable, Sequence
from functools import partial

from utmax.adapters.http import RetryingTransport, UrllibTransport, open_stream
from utmax.core.downloads import DEFAULT_CHUNK_SIZE
from utmax.models import (
    Container,
    DownloadResult,
    Progress,
    Quality,
    SubtitleMode,
    TrackList,
    Transcript,
    VideoInfo,
)
from utmax.services.download import DownloadOptions, DownloadService
```

(merge them with the existing import lines), replace the last two statements of `__init__` (`self._transport = transport` and the `self._transcripts = ...` assignment from Task 6) with:

```python
        self._transport = transport
        innertube = InnerTubeClient(transport, block_retries=block_retries)
        self._transcripts = TranscriptService(innertube)
        self._downloads = DownloadService(
            innertube, self._transcripts, partial(open_stream, transport)
        )
```

and add after `bilingual`:

```python
    def download(
        self,
        video: str,
        path: str | os.PathLike[str],
        *,
        format: Container | None = None,
        quality: Quality = "compat",
        subtitles: Sequence[str | Transcript] | None = None,
        subtitle_mode: SubtitleMode = "embed",
        default_subtitle: str | None = None,
        connections: int = 4,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        resume: bool = True,
        overwrite: bool = False,
        ffmpeg: str | os.PathLike[str] | None = None,
        progress: Callable[[Progress], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> DownloadResult:
        """Download a video or its audio; see :func:`utmax.download`."""
        options = DownloadOptions(
            format=format,
            quality=quality,
            subtitles=subtitles,
            subtitle_mode=subtitle_mode,
            default_subtitle=default_subtitle,
            connections=connections,
            chunk_size=chunk_size,
            resume=resume,
            overwrite=overwrite,
            ffmpeg=ffmpeg,
            progress=progress,
            cancel=cancel,
        )
        return self._downloads.download(video, path, options)
```

- [ ] **Step 4: Add `utmax.download`**

In `src/utmax/__init__.py`: add `import os` and `from collections.abc import Callable, Sequence` (next to the existing `Sequence` import), import `DEFAULT_CHUNK_SIZE` from `utmax.core.downloads`, add `Quality` and `SubtitleMode` to the `utmax.models` import, insert `"download",` into `__all__` between `"bilingual"` and `"fetch"`, extend the module docstring's quick start with:

```python
    utmax.download("dQw4w9WgXcQ", "rick.mp4")  # H.264 + AAC + English subtitles
```

and append:

```python
def download(
    video: str,
    path: str | os.PathLike[str],
    *,
    format: Container | None = None,
    quality: Quality = "compat",
    subtitles: Sequence[str | Transcript] | None = None,
    subtitle_mode: SubtitleMode = "embed",
    default_subtitle: str | None = None,
    connections: int = 4,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    resume: bool = True,
    overwrite: bool = False,
    ffmpeg: str | os.PathLike[str] | None = None,
    progress: Callable[[Progress], None] | None = None,
    cancel: threading.Event | None = None,
) -> DownloadResult:
    """Download a video (``.mp4``, ``.mov``) or its audio (``.m4a``, ``.mp3``) with subtitles.

    Examples::

        utmax.download("dQw4w9WgXcQ", "rick.mp4")  # H.264 up to 1080p, AAC, English subtitles
        utmax.download("dQw4w9WgXcQ", "rick.m4a")  # audio only; no ffmpeg needed
        utmax.download("dQw4w9WgXcQ", "videos/", quality="max")  # AV1 up to 4K, named by title
        utmax.download("dQw4w9WgXcQ", "rick.mp4", subtitles=[english, turkish])

    Args:
        video: a video ID or any YouTube URL.
        path: the output file; its extension picks the type (``.mp4``, ``.mov``, ``.m4a``,
            ``.mp3``). A folder (an existing one, or a path ending with ``/``) gets
            ``"{title} [{video_id}].{ext}"``.
        format: the file type when ``path`` is a folder or has no extension; it must match the
            extension otherwise.
        quality: ``"compat"`` (H.264 up to 1080p, plays everywhere) or ``"max"`` (AV1 or
            H.264 up to 2160p; ``.mp4`` only).
        subtitles: language codes and/or transcripts (translations and bilingual ones too).
            ``None`` embeds the spoken-language track in videos and adds nothing to audio;
            ``[]`` adds none. Codes are chosen like :func:`fetch`, never with YouTube's own
            translation.
        subtitle_mode: ``"embed"`` (toggleable tracks in the video), ``"sidecar"`` (``.srt``
            files next to it) or ``"both"``; audio files always get sidecar files.
        default_subtitle: the language code of the embedded track shown by default (else the
            first one).
        connections: parallel connections, 1 to 16.
        chunk_size: bytes per range request, at least 256 KiB.
        resume: continue an interrupted download from its ``.part`` files.
        overwrite: replace existing files instead of raising :class:`OutputExists`.
        ffmpeg: the ffmpeg executable for ``.mp3`` (default: ``$UTMAX_FFMPEG``, then ``PATH``).
        progress: called with a :class:`Progress` at most four times a second, never in
            parallel; keep it quick. An exception it raises stops the download.
        cancel: set this event to stop; the ``.part`` files stay, so a new call resumes.

    Streams are downloaded into ``<file>.<itag>.part`` files next to the target and then
    combined, so the disk briefly holds about twice the file size; the parts are deleted only
    after success. Stream URLs work only from the IP address that requested them, so do not
    switch proxies or VPNs during a download.

    Raises:
        InvalidVideoId, InvalidOption, UnsupportedFormat: bad arguments (before any request).
        OutputExists: the file or a subtitle file exists and ``overwrite`` is false.
        FFmpegNotFound: ``.mp3`` without a usable ffmpeg (before any request).
        NoTranscriptFound: a requested subtitle language does not exist (before any media byte).
        FormatNotAvailable: no stream fits the type and quality (live streams, for example).
        StreamForbidden, DownloadIncomplete, NetworkError: the download failed; call again to
            resume.
        DownloadCancelled: ``cancel`` was set.
        MuxError, FFmpegFailed: the file could not be assembled.
        VideoUnavailable, VideoUnplayable, AgeRestricted, RequestBlocked: YouTube refused.
    """
    return _client().download(
        video,
        path,
        format=format,
        quality=quality,
        subtitles=subtitles,
        subtitle_mode=subtitle_mode,
        default_subtitle=default_subtitle,
        connections=connections,
        chunk_size=chunk_size,
        resume=resume,
        overwrite=overwrite,
        ffmpeg=ffmpeg,
        progress=progress,
        cancel=cancel,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_download_api.py tests/unit/test_facade.py tests/unit/test_client.py tests/test_architecture.py -q`
Expected: the new file reports 7 passed; the facade, client and architecture tests still pass (`import utmax` still loads only the standard library).

- [ ] **Step 6: Gates and commit**

Run the four gates (the suite grows by 7).

```bash
git add src/utmax/client.py src/utmax/__init__.py tests/unit/test_download_api.py
git commit -m "feat: add utmax.download and Client.download" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Live downloads and M4 verification

**Files:**
- Create: `tests/live/test_download_live.py`
- Modify: nothing else unless a check below fails.

**Interfaces:**
- Consumes: `utmax.download`, `parse_progressive`, `FileByteSource`, `MIN_CHUNK_SIZE`.
- Produces: live tests (marked `live`, deselected by default) and the milestone's verification record.

- [ ] **Step 1: Write the live tests**

`tests/live/test_download_live.py`:

```python
"""Live download checks against YouTube (``uv run pytest -m live``); files go to tmp_path.

They use "Me at the zoo" (jNQXAC9IVRw): 19 seconds, 240p H.264, manual English subtitles, and
ANDROID_VR asks for a bot check on it, so the stream-client fallback is exercised too.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

import utmax
from utmax.adapters.files import FileByteSource
from utmax.core.downloads import MIN_CHUNK_SIZE
from utmax.core.media.progressive import parse_progressive
from utmax.errors import DownloadCancelled

pytestmark = pytest.mark.live

ZOO = "jNQXAC9IVRw"


def handlers(path: Path) -> list[str]:
    with FileByteSource(path) as source:
        return [track.handler for track in parse_progressive(source).tracks]


def test_m4a_download(tmp_path: Path) -> None:
    result = utmax.download(ZOO, tmp_path / "zoo.m4a")
    assert result.audio_format.codec == "aac"
    assert result.size_bytes > 100_000
    assert handlers(result.path) == ["soun"]


def test_mp4_download_with_embedded_english(tmp_path: Path) -> None:
    result = utmax.download(ZOO, tmp_path)
    assert result.path.name == "Me at the zoo [jNQXAC9IVRw].mp4"
    assert result.video_format is not None
    assert result.video_format.codec == "h264"
    assert result.embedded_subtitles == ("en",)
    assert handlers(result.path) == ["vide", "soun", "sbtl"]
    if shutil.which("ffprobe"):
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "json",
             str(result.path)],
            capture_output=True,
            text=True,
            check=True,
        )
        codecs = [stream["codec_name"] for stream in json.loads(probe.stdout)["streams"]]
        assert codecs == ["h264", "aac", "mov_text"]


def test_a_download_cancelled_while_muxing_resumes_without_downloading_again(
    tmp_path: Path,
) -> None:
    cancel = threading.Event()

    def stop_while_muxing(progress: utmax.Progress) -> None:
        if progress.phase == "muxing":
            cancel.set()

    with pytest.raises(DownloadCancelled):
        utmax.download(
            ZOO,
            tmp_path / "zoo.mp4",
            chunk_size=MIN_CHUNK_SIZE,
            progress=stop_while_muxing,
            cancel=cancel,
        )
    assert list(tmp_path.glob("zoo.mp4.*.part"))
    result = utmax.download(ZOO, tmp_path / "zoo.mp4", chunk_size=MIN_CHUNK_SIZE)
    assert result.resumed
    assert not list(tmp_path.glob("*.part*"))


def test_mp3_download(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    result = utmax.download(ZOO, tmp_path / "zoo.mp3")
    assert result.container == "mp3"
    assert result.size_bytes > 50_000
```

- [ ] **Step 2: Run the live tests**

Run: `uv run pytest -m live tests/live/test_download_live.py -v`
Expected: 4 passed (a few MB of traffic). `RequestBlocked` from YouTube is reported as a skip by `tests/live/conftest.py`, not a failure; report skips as such.

- [ ] **Step 3: Run every gate**

```
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov --cov-report=term-missing
uv run coverage report --include="*/utmax/core/*" --fail-under=95
uv run pytest -m ffmpeg -q
uv sync --locked            # then, without the AI extras:
uv run pytest -q
uv sync --locked --all-extras
uv build --out-dir <a scratch folder outside the repository>
```

Expected: ruff, format and mypy clean; the full suite passes with total coverage ≥ 90 % and core coverage ≥ 95 %; `-m ffmpeg` passes where ffmpeg exists (M3's five tests plus the new MP3 test); the run without extras passes with the provider tests skipped; the wheel contains only `utmax/` and the dist-info. Record every count in the report.

- [ ] **Step 4: Check the spec's acceptance list for M4**

Write a table in the report mapping each item of spec §9 row M4 to the tests that prove it:

| Acceptance item | Proven by |
|---|---|
| Resume after a simulated crash | Task 7 `test_finished_ranges_are_reused_on_the_next_run`, `test_ctrl_c_saves_the_state_and_propagates`; Task 9 `test_cancel_during_mux_keeps_the_parts_for_a_resume`; live `test_a_download_cancelled_while_muxing_resumes_without_downloading_again` |
| 403 refresh | Task 7 `test_a_403_refreshes_the_urls_once_for_every_thread`, `test_forbidden_streams_give_up_after_three_refreshes`, `test_urls_about_to_expire_are_refreshed_before_use` |
| Cancel → resumable | Task 7 `test_cancel_keeps_the_finished_ranges_for_a_resume`; Task 8 `test_cancel_stops_ffmpeg`; Task 9 cancel test |
| `FFmpegNotFound` | Task 8 `test_missing_ffmpeg_says_where_it_looked`, `test_builds_without_lame_are_refused`; Task 9 `test_mp3_needs_ffmpeg_before_any_request` |
| Windows rename retry | `replace_with_retry` (M1 tests `test_replace_waits_out_transient_locks`, `test_replace_gives_up_after_the_last_delay`) is used by `write_mux_plan` and the MP3 path (`_convert`) |
| Live m4a + mp4 | Task 11 `test_m4a_download`, `test_mp4_download_with_embedded_english` |

- [ ] **Step 5: Hand the manual checks to the user**

Do not push. List these as pending user actions in the report (the user runs them; nothing is needed from the agent):

1. `utmax.download("dQw4w9WgXcQ", "rick.mp4")` and open it in VLC, mpv, QuickTime/IINA, Films & TV: English subtitles toggle on and off.
2. `utmax.download("dQw4w9WgXcQ", "rick-4k.mp4", quality="max")` (≈240 MB of AV1): plays; press Ctrl-C half-way, run it again, and check that it resumes (`result.resumed is True`).
3. `.mov`, `.m4a` and `.mp3` downloads of the same video open in the players above.
4. Approval to push `v4` after M4 is merged.

- [ ] **Step 6: Commit**

```bash
git add tests/live/test_download_live.py
git commit -m "test: add live download checks" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
