# M3 — Media Muxer Implementation Plan

**Goal:** A pure-Python muxer (`utmax.core.media`) that turns YouTube's fragmented MP4 streams plus transcripts into faststart MP4, MOV and M4A files with toggleable tx3g subtitle tracks, planned as byte copies (`MuxPlan`) and written atomically by `utmax.adapters.files`.

**Architecture:** Pure core modules, each with one job: `boxes` (byte sources, box headers, readers and writers) → `fmp4` (index fragmented inputs through `ByteSource.read(offset, n)`) → `tables`, `tx3g`, `moov` (sample tables, subtitle tracks, `ftyp`/`moov` per flavor) → `mux` (chunking, interleaving, edit lists, co64 and faststart layout into `MuxPlan(ops=[CopyOp | Blob])`), plus `progressive`, which reads finished files back so every invariant is checked on real output. The only I/O lives in `adapters/files.py` (`FileByteSource`, `write_mux_plan`). The public facade does not change; M4 wires the muxer into `download()`.

**Tech Stack:** Python ≥ 3.11 standard library (`struct`, `array`, `fractions`, `bisect`) · pytest · ruff · mypy (strict) · uv · ffmpeg/ffprobe for the optional integration tests and their CI job.

**Spec:** `docs/design/2026-09-27-u-transcript-max-design.md` — read §2 (verified container facts), §3 (architecture and purity rules), §4.5 (download targets), §5 ("Muxer", the flavor table, "tx3g"), §6 (errors), §8 items 3–4, §9 row M3 and §10 before starting. Prerequisite: `docs/design/plans/2026-09-27-m2m3-shared-prep.md` is complete on `v4` (it adds `utmax.core.languages` and `MuxError`; `InvalidOption` exists since M1).

## Global Constraints

- `requires-python = ">=3.11"`; zero runtime dependencies; `src/utmax` imports only the standard library; M3 adds no runtime or dev dependency.
- `utmax.core` (and so `utmax.core.media`) is pure: no network, subprocess, threads, clock or filesystem; `tests/test_architecture.py` bans `asyncio concurrent http.* socket ssl subprocess threading time shutil tempfile urllib.request urllib.error` and outer layers. All inputs are read through `ByteSource.read(offset, n)`.
- **Parallel execution.** M3 runs in its own git worktree on branch `m3-muxer` (cut from `v4` after the shared prep) while M2 runs in another worktree. M3 must NOT create or edit: `src/utmax/core/languages.py`, `src/utmax/errors.py`, `src/utmax/core/translate/**`, `src/utmax/core/formats.py`, `src/utmax/core/bilingual.py`, `src/utmax/services/**`, `src/utmax/adapters/providers/**`, `src/utmax/providers.py`, `src/utmax/__init__.py`, `src/utmax/client.py`, `uv.lock`. M3 owns: `src/utmax/core/media/**`, the MuxPlan executor and `FileByteSource` in `src/utmax/adapters/files.py`, `scripts/make_media_fixtures.py`, `tests/helpers/fmp4_factory.py`, `tests/helpers/hollow_source.py`, `tests/fixtures/media/**`, `tests/unit/media/**`, `tests/unit/adapters/test_mux_executor.py`, the `ffmpeg` marker entry in `pyproject.toml` and one job appended to `.github/workflows/ci.yml`. Every task below stays inside that list.
- The muxer is internal in M3: nothing is added to `utmax.__all__`, `Client` or the facade.
- Errors: every muxing failure raises `utmax.errors.MuxError` (a `DownloadError`) with an English message and, where useful, a specific `suggestion=`; an unknown `default_subtitle` raises `utmax.errors.InvalidOption` before any input is read.
- Languages come only from `utmax.core.languages` (`english_name`, `iso639_2t`, `mac_language_code`).
- Byte layouts follow ISO/IEC 14496-12 and Apple's QuickTime File Format; values follow FFmpeg `libavformat/movenc.c` at master `b87602a63a52b0f7f968fd314f02be14acde16b7` (see "Verified facts"). Every integer is written big-endian with explicit `struct` formats (`">I"`, `">Q"`, `">i"` …) or `int.to_bytes(n, "big")`.
- Deterministic output: zero creation/modification times, no clock, no randomness in core — the same inputs always give the same bytes.
- Non-ASCII characters appear in Python source only as escapes. This plan writes them as `\xXX` or `\U0000XXXX` (eight hex digits) on purpose: some editing tools silently turn four-digit backslash-u escapes into raw characters (which corrupted files twice in M1). Copy the escapes exactly as written.
- Lint lessons from M1, already applied to every line below: `itertools.pairwise` (RUF007), `split(..., maxsplit=1)` (PLC0207), `pytest.raises` with a specific exception and `match=` (PT011) whose pattern is raw or free of regex metacharacters (RUF043), no unused `noqa` (RUF100), no redundant casts, at most five positional parameters (PLR0917 — the rest keyword-only), `list.extend` over append loops (PERF401), code already formatted for ruff's 100 columns, `filterwarnings = error` (so every `FileByteSource` is closed with `with` or `close()`), `docs/` excluded from ruff.
- Gates after every task: `uv run ruff check .` · `uv run ruff format --check .` · `uv run mypy` · `uv run pytest` (branch coverage ≥ 90 %). At the end: `uv run pytest --cov` then `uv run coverage report --include="*/utmax/core/*" --fail-under=95`, and `uv run pytest -m ffmpeg` where ffprobe exists. Every "Expected" line gives exact counts; if yours differ, find out why before moving on.
- Commits use a conventional prefix (`feat:`, `test:`, `ci:`), stage explicit paths only (never `git add -A` or `.`) and end with the trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Never push, merge or publish without the user's explicit approval.

## Review Focus

1. **Non-ASCII and oversized subtitle text** — Turkish, CJK, emoji and ♪ in cues, and absurdly long cues → UTF-8 round-trips byte-exactly through the tx3g samples, and text beyond the 16-bit length limit is cut at a character boundary instead of crashing or producing invalid UTF-8. Pinned in Task 6 (`test_samples_round_trip`, `test_overlong_text_is_cut_at_a_character_boundary`) and Task 13 (`test_mp4_with_two_subtitle_tracks` extracts Turkish text with ffmpeg).
2. **Messy caption timing** — overlapping, unsorted, zero-length and same-start cues, cues that run past the end of the video, transcripts without any cue → the embedded track shows exactly the cues the `.srt` sidecar shows, stops with the media, and an empty transcript still yields a (silent) track. Pinned in Task 6 (`test_cues_are_timed_exactly_like_the_srt_sidecar`, `test_transcripts_without_cues_still_make_a_track`) and Task 11 (`test_subtitles_end_with_the_media`, `test_a_transcript_without_cues_still_gets_a_track`).
3. **Damaged or unsuitable inputs** — a truncated `.part` file, a WebM or classic (non-fragmented) MP4, H.265/Opus/encrypted tracks, 5.1 or 96 kHz AAC headed for `.mov`, AV1 in `.mov` → a `MuxError` that says what is wrong and what to do; a failed write never leaves a half-written or temporary file and never clobbers an existing target. Pinned in Task 3 (`test_broken_init_segments`, `test_truncated_inputs_are_reported`), Task 7 (`test_audio_quicktime_cannot_describe_is_refused`), Task 9 (`test_unsupported_tracks_are_refused`, `test_mov_refuses_av1`) and Task 12 (`test_a_truncated_input_fails_and_leaves_nothing_behind`).
4. **Outputs above 4 GiB** (long 4K AV1 downloads) → `co64` and a 64-bit `mdat` size exactly when an offset or size needs them, and samples beyond 4 GiB copied from the right source offsets. Pinned in Task 10 (all four tests, on a virtual 5.4 GB source that is never allocated or written).
5. **Streams that do not start at zero** — DASH fragments whose first `tfdt` is not 0, gaps between fragments, audio that starts later than video → the output timeline starts at 0, gaps stretch the preceding sample, and a later start becomes a leading empty edit so audio and video stay in sync. Pinned in Task 3 (`test_a_later_tfdt_turns_a_gap_into_a_longer_previous_sample`, `test_duration_is_empty_fragments_stretch_the_previous_sample`) and Task 9 (`test_a_later_start_becomes_a_leading_empty_edit`, `test_streams_are_rebased_to_start_at_zero`).

## Verified facts this plan relies on

**FFmpeg** — master `b87602a63a52b0f7f968fd314f02be14acde16b7` (2026-09-27), read-only copies of `libavformat/movenc.c`, `movenc.h`, `isom.c`, `isom.h`, `mov.c`, `libavcodec/movtextenc.c`, `movtextdec.c`. Checked against them:

- `stco`/`co64` is chosen per track (`co64_required`: last chunk offset > `UINT32_MAX`); the `mdat` size switches to the 64-bit form when `mdat_size + 8 > UINT32_MAX`.
- `stbl` order `stsd, stts, stss (only if some samples are not sync), ctts, stsc, stsz, stco|co64`; run-length `stts`/`ctts`/`stsc`; `stsz` with one shared size when all are equal. FFmpeg writes `ctts` version 1 only with `negative_cts_offsets`; the spec asks for version 1 whenever an offset is negative, which is what this plan does.
- `minf` = `vmhd`/`smhd`/`nmhd`, then (MOV only) a data-handler `hdlr` (`dhlr`, `url `, Pascal name "DataHandler"), then `dinf{dref{url  flags 1}}`, then `stbl`. `vmhd` flags 1 with graphics mode 0; `smhd` balance 0; `nmhd` for tx3g.
- `hdlr`: MP4 = pre-defined 0, handler type, 12 zero bytes, C string; MOV = `mhlr`, handler type, 12 zero bytes, Pascal string. Track names: FFmpeg uses the `handler_name` as the `hdlr` name ("used by some players to identify the content title") and writes a `udta/name` box with the raw UTF-8 title for MP4 and MOV; subtitle handler type `sbtl` for tx3g.
- `tkhd` flags = "in movie" (2) plus "enabled" (1) for enabled tracks; alternate group = the media type (video 0, audio 1, subtitle 3); volume 0x0100 for audio only; unity matrix; width/height 16.16 (0 for audio and subtitles).
- `mvhd`: rate 1.0, volume 1.0, 10 reserved bytes, unity matrix, 24 bytes of QuickTime preview/poster/selection fields, next track ID. `mdhd`/`tkhd`/`mvhd` switch to version 1 only when a duration reaches `INT32_MAX`; in MOV mode FFmpeg then logs "FATAL error … not playable with QuickTime" — this plan raises `MuxError` for MOV instead.
- `ftyp`: MP4 `isom`, minor 0x200, compatible `isom iso2 avc1 mp41` (FFmpeg adds `av01` for AV1, before `iso2`); MOV `qt  `, minor 0x200, compatible `qt  `; iPod mode `M4A `, minor 0x200.
- MOV audio (`mov_write_audio_tag`): AAC is VBR, so SoundDescription version 1 with channel count, 16 bits, compression ID −2, packet size 0, rate 16.16, then samples per packet (frame size), bytes per packet 0, bytes per frame 0, bytes per sample 2; then `wave{frma(mp4a), mp4a(4 zero bytes), esds, 8-byte terminator (size 8, type 0)}`. FFmpeg uses version 2 for more than two channels or rates above 65535 Hz — not implemented here, so those raise `MuxError` (and the optional `chan` box is not written).
- tx3g sample description (`movtextenc.c` `encode_sample_description` without an ASS style): display flags 0, justification 0x01/0xFF (centre, bottom), background RGBA 0, default text box 0, style record (chars 0–0, font 1, face 0, size 18, text RGBA 0xFFFFFFFF), `ftab` with one font; FFmpeg's default font name is "Serif" — the spec asks for "Sans-Serif" (see Decisions). A sample is a 16-bit length plus text; `movtextdec` shows empty samples as nothing.
- Demuxer semantics (`mov.c`) that the indexer mirrors: `tfhd` defaults fall back to `trex`; base data offset = explicit value, else the `moof` start with `default-base-is-moof`, else the implicit offset (end of the previous run's data); a sample is a keyframe unless flagged non-sync or "depends on others"; per-sample flags override `first_sample_flags`; composition offsets are stored signed whatever the `trun` version.
- `mov_mdhd_language_map` (the QuickTime language codes) is transcribed in the shared-prep plan's `utmax.core.languages`. FFmpeg writes 32767 ("unspecified") in MOV when a language has no QuickTime code; QuickTime also accepts packed ISO codes (values ≥ 0x400), which this plan uses instead (see Decisions).

**ISO/IEC 14496-12** layouts used: `tfhd` §8.8.7, `trun` §8.8.8, `tfdt` §8.8.12, `trex` §8.8.3, sample table boxes §8.5–8.7, `elst` §8.6.6, `elng` §8.4.6 (full box, NUL-terminated BCP 47 string, inside `mdia` after `hdlr`), `hdlr` §8.4.3, `tkhd` §8.3.2. QuickTime documents `elng` the same way.

**YouTube** (read-only Range probes via ANDROID_VR on 2026-09-27, `dQw4w9WgXcQ`):

- itag 137 (H.264): `ftyp dash` (`iso6 avc1 mp41`), `mvhd`/`mdhd` timescale 12800, `tkhd` 1920×1080, one `elst` entry (segment 2 727 936 ticks = 213.12 s, `media_time` 512), `tfhd` 0x02000a (base is moof, description index, default duration 512), `tfdt` v0, `trun` 0x000e01 **version 0** (composition offsets 0/512/1024/1536, all non-negative), fragments ≈5.2 s, `moof` ≈1.6 KB. The spec's "signed-cto trun" was not seen today; the indexer handles both.
- itag 140 (AAC-LC 44.1 kHz stereo): timescale 44100, no `elst`, `tfhd` 0x02002a (default duration 1024, default flags 0), `trun` 0x000201, 430 samples per ≈10 s fragment; the `moov` also carries `udta/meta` (ignored).
- itag 399 (AV1): `av01` with `av1C` and `colr`, no `elst`, `trun` 0x000601.
- Handler names read "ISO Media file produced by Google Inc."; `minf` children come as `dinf, stbl, vmhd` (the indexer does not depend on order). `sidx` follows the init segment with `first_offset` 0.

**ffmpeg 9.0 fragmented output** (`-movflags frag_keyframe+empty_moov+default_base_moof`): `ftyp iso5`, `tfhd` 0x020038, `tfdt` version 1, H.264 `trun` 0x000a05 v0 with first-sample flags and no edit list (first frame at pts 1024/12800); `+negative_cts_offsets` gives `trun` version 1 with negative offsets; AAC-only output needs `-frag_duration` to produce more than one fragment. Negative offsets make FFmpeg's fragmented and progressive readers shift timestamps differently, so the integration test compares relative presentation times for that case.

## Decisions (where the spec is silent or ambiguous)

1. **tx3g font** — the spec says "ffmpeg `mov_text` default sample entry (size 18, white, `ftab` Sans-Serif)"; FFmpeg's default name is "Serif". The spec's explicit value wins: "Sans-Serif", every other byte FFmpeg's.
2. **Bilingual tracks** (`"en+tr"`) are not a BCP 47 language: `mdhd` gets `mul`, `elng` gets `mul`, and the name ("English + Turkish") says what it holds; language-based auto-selection in players then keeps picking the monolingual tracks.
3. **MOV languages without a QuickTime code** are written as packed ISO 639-2/T codes (QuickTime accepts values ≥ 0x400) rather than FFmpeg's 32767, so no language is lost.
4. **Subtitle length** — cues are clipped to the longest media track, so the movie is never longer than its video; an empty transcript becomes one empty sample lasting the movie; `<b>`, `<i>`, `<u>` tags are removed (tx3g styling is out of scope).
5. **Track names**: `language` of the transcript (falling back to English names from its code); AI translations append ` (AI: <translator>)`; bilingual transcripts keep their name without the suffix.
6. **Edit lists**: source `media_time` is kept (shifted when a stream is rebased), durations are converted to milliseconds rounding up and cut to the media that exists (a hollow or partial download still describes itself honestly); source `segment_duration` 0 means "the rest". Every input is rebased so its first sample decodes at 0; a track that starts later than the earliest one gets a leading empty edit (rounded down, like FFmpeg's delay edit).
7. **Composition offsets** are read as signed in both `trun` versions (FFmpeg's behaviour); `ctts` is version 1 exactly when an offset is negative (the spec).
8. **Chunks**: a new chunk starts when a sample decodes 1 s (subtitles 10 s) or more after the chunk's first sample, or when the sample description changes; chunks are stored in (start time, track order) order.
9. **Track order and flags**: media tracks in input order, then subtitles in the given order; IDs 1…n; the first track of each media kind is enabled; exactly one subtitle track is enabled — `default_subtitle` matched case-insensitively against `Transcript.language_code`, else the first.
10. **MOV limits** raise `MuxError` with a ".mp4" suggestion: AV1, AAC with more than two channels or above 65535 Hz, durations reaching 2^31 − 1 ticks. M4 should pick stereo AAC for `.mov`.
11. **Not written** (optional boxes the spec does not ask for): `iods`, `btrt`, movie-level `udta/meta`, AAC `sgpd`/`sbgp` roll groups, `chan`, `sdtp`. The `ftyp` brand order is the spec's (`isom iso2 av01 mp41`; FFmpeg puts `av01` first — order carries no meaning), and `M4A ` files list `mp41` as the spec says.
12. **Hollow fixture format**: `<video>_<itag>.hollow.bin` is the stream's first bytes with every `mdat` payload left out (headers kept). The `.bin` extension reuses the existing `*.bin binary` rule in `.gitattributes`, which M3 must not edit. `manifest.json` stores facts the recorder reads with its own tiny parser, so tests compare utmax against an independent reading.
13. **Tests of the ffmpeg job** skip when ffmpeg or ffprobe is missing, unless `UTMAX_REQUIRE_FFMPEG=1` (set in the CI job), which turns the skip into a failure; the AV1 test skips when the ffmpeg build has no `libaom-av1`.

## File map

| File | Responsibility | Task |
|---|---|---|
| `src/utmax/core/media/__init__.py` | Package docstring | 1 |
| `src/utmax/core/media/boxes.py` | `ByteSource`, `BytesSource`, box headers, `Reader`, big-endian writers | 1 |
| `tests/helpers/fmp4_factory.py` | Synthetic fragmented MP4s for every flag path; virtual multi-GB sources | 2 |
| `src/utmax/core/media/fmp4.py` | Index fragmented inputs: tracks, defaults, edits, every sample | 3 |
| `scripts/make_media_fixtures.py`, `tests/fixtures/media/*` | Record hollow YouTube streams and their manifest | 4 |
| `tests/helpers/hollow_source.py` | Replay hollow fixtures as byte sources | 4 |
| `src/utmax/core/media/tables.py` | `stts ctts stss stsz stsc stco/co64`, chunking, `edts` | 5 |
| `src/utmax/core/media/tx3g.py` | Cue normalization, tx3g samples and sample entry, names, languages | 6 |
| `src/utmax/core/media/moov.py` | `ftyp`, `moov`/`trak` boxes, flavor rules, QuickTime audio entry | 7 |
| `src/utmax/core/media/progressive.py` | Read progressive files back (verification) | 8 |
| `src/utmax/core/media/mux.py` | `plan_mux`, `MuxPlan`, `CopyOp`, `Blob`, `PlanSource`, `convert_edits` | 9, 10, 11 |
| `tests/unit/media/invariants.py` | Shared invariant checks over re-parsed output | 9 |
| `src/utmax/adapters/files.py` | `FileByteSource`, `write_mux_plan` (plus the M1 helpers, unchanged) | 12 |
| `tests/unit/media/test_ffmpeg.py`, `pyproject.toml` (marker), `.github/workflows/ci.yml` (job) | ffmpeg/ffprobe integration | 13 |
| `tests/unit/media/test_*.py`, `tests/unit/adapters/test_mux_executor.py` | Unit tests | 1–12 |

---

### Task 1: Box primitives

**Files:**
- Create: `src/utmax/core/media/__init__.py`, `src/utmax/core/media/boxes.py`
- Test: `tests/unit/media/__init__.py`, `tests/unit/media/test_boxes.py`

**Interfaces:**
- Consumes: `utmax.errors.MuxError` (shared prep).
- Produces (in `utmax.core.media.boxes`):
  - `ByteSource` — `Protocol` with `size: int` (read-only property) and `read(offset: int, n: int) -> bytes` (fewer bytes only at the end).
  - `BytesSource(data: bytes)` — in-memory `ByteSource`.
  - `BoxHeader(kind: str, offset: int, size: int, header_size: int)` with `.payload_offset`, `.payload_size`, `.end`.
  - `read_exact(source, offset, n) -> bytes` (short read → `MuxError` "The input ends early …").
  - `iter_boxes(source, start=0, end=None) -> Iterator[BoxHeader]` (32-bit, 64-bit and to-the-end sizes; broken headers → `MuxError`).
  - `child_boxes(payload, *, context) -> list[tuple[str, bytes]]`, `find_child(payload, kind, *, context) -> bytes | None`, `require_child(payload, kind, *, context) -> bytes`.
  - `Reader(data, context)` with `u8 u16 u24 u32 u64 i16 i32 i64 fourcc take skip rest` and `.remaining`; reading past the end → `MuxError` "The '<context>' box is truncated."
  - Writers `u8 u16 u24 u32 u64 i16 i32 i64`, `box(kind, *parts) -> bytes`, `full_box(kind, version, flags, *parts) -> bytes`; constants `U32_MAX = 0xFFFF_FFFF`, `I32_MAX = 0x7FFF_FFFF`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/media/__init__.py`:

```python
"""Tests for the MP4/MOV muxer (offline; the ffmpeg-marked ones need ffmpeg and ffprobe)."""
```

`tests/unit/media/test_boxes.py`:

```python
"""Tests for the box primitives."""

from __future__ import annotations

import pytest

from utmax.core.media.boxes import (
    BoxHeader,
    BytesSource,
    Reader,
    box,
    child_boxes,
    find_child,
    full_box,
    i16,
    i32,
    i64,
    iter_boxes,
    read_exact,
    require_child,
    u8,
    u16,
    u24,
    u32,
    u64,
)
from utmax.errors import MuxError


def test_integer_writers_are_big_endian() -> None:
    assert u8(0xAB) == b"\xab"
    assert u16(0x0102) == b"\x01\x02"
    assert u24(0x010203) == b"\x01\x02\x03"
    assert u32(0x01020304) == b"\x01\x02\x03\x04"
    assert u64(1) == b"\x00" * 7 + b"\x01"
    assert i16(-2) == b"\xff\xfe"
    assert i32(-1) == b"\xff\xff\xff\xff"
    assert i64(-1) == b"\xff" * 8


def test_box_and_full_box_layout() -> None:
    assert box("free") == b"\x00\x00\x00\x08free"
    assert box("abcd", b"xy", b"z") == b"\x00\x00\x00\x0babcdxyz"
    assert full_box("mfhd", 1, 0x020304, u32(7)) == (
        b"\x00\x00\x00\x10mfhd\x01\x02\x03\x04\x00\x00\x00\x07"
    )


def test_iter_boxes_reads_32_bit_64_bit_and_to_the_end_sizes() -> None:
    wide = u32(1) + b"mdat" + u64(20) + b"abcd"
    to_end = u32(0) + b"free" + b"rest"
    data = box("ftyp", b"isom") + wide + to_end
    headers = list(iter_boxes(BytesSource(data)))
    assert headers == [
        BoxHeader("ftyp", 0, 12, 8),
        BoxHeader("mdat", 12, 20, 16),
        BoxHeader("free", 32, 12, 8),
    ]
    assert headers[1].payload_offset == 28
    assert headers[1].payload_size == 4
    assert headers[1].end == 32


def test_iter_boxes_honours_start_and_end() -> None:
    data = box("aaaa") + box("bbbb") + box("cccc")
    assert [h.kind for h in iter_boxes(BytesSource(data), 8, 16)] == ["bbbb"]


@pytest.mark.parametrize(
    "data",
    [
        b"\x00\x00\x00",  # shorter than a header
        u32(1) + b"mdat" + b"\x00\x00",  # truncated 64-bit size
        u32(4) + b"free",  # smaller than its own header
        u32(64) + b"moov" + bytes(8),  # runs past the end
    ],
)
def test_iter_boxes_rejects_broken_headers(data: bytes) -> None:
    with pytest.raises(MuxError):
        list(iter_boxes(BytesSource(data)))


def test_child_boxes_and_lookups() -> None:
    payload = box("mvhd", b"1") + u32(1) + b"trak" + u64(17) + b"x" + u32(0) + b"udta" + b"yz"
    assert child_boxes(payload, context="moov") == [("mvhd", b"1"), ("trak", b"x"), ("udta", b"yz")]
    assert find_child(payload, "trak", context="moov") == b"x"
    assert find_child(payload, "mvex", context="moov") is None
    assert require_child(payload, "udta", context="moov") == b"yz"
    with pytest.raises(MuxError, match="'moov' box has no 'mvex'"):
        require_child(payload, "mvex", context="moov")


@pytest.mark.parametrize(
    "payload",
    [b"\x00\x00\x00\x09tra", u32(1) + b"trak" + b"\x00", u32(3) + b"trak", u32(99) + b"trak"],
)
def test_child_boxes_rejects_broken_children(payload: bytes) -> None:
    with pytest.raises(MuxError, match="'moov'"):
        child_boxes(payload, context="moov")


def test_reader_reads_every_width_and_stops_at_the_end() -> None:
    data = b"\x01" + b"\x00\x02" + b"\x00\x00\x03" + u32(4) + u64(5) + i16(-6) + i32(-7)
    data += i64(-8) + b"moov" + b"tail"
    reader = Reader(data, "test")
    values = [reader.u8(), reader.u16(), reader.u24(), reader.u32(), reader.u64()]
    values += [reader.i16(), reader.i32(), reader.i64()]
    assert values == [1, 2, 3, 4, 5, -6, -7, -8]
    assert reader.fourcc() == "moov"
    reader.skip(1)
    assert reader.remaining == 3
    assert reader.rest() == b"ail"
    with pytest.raises(MuxError, match="'test' box is truncated"):
        reader.u8()


def test_read_exact_reports_truncated_inputs() -> None:
    source = BytesSource(b"0123456789")
    assert read_exact(source, 2, 3) == b"234"
    assert read_exact(source, 10, 0) == b""
    with pytest.raises(MuxError, match="needed 4 bytes at offset 8, got 2"):
        read_exact(source, 8, 4)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/media/test_boxes.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'utmax.core.media'`.

- [ ] **Step 3: Implement the package and `boxes.py`**

`src/utmax/core/media/__init__.py`:

```python
"""A pure-Python MP4/MOV muxer: fragmented YouTube streams plus subtitles into one file.

``fmp4`` indexes fragmented inputs, ``tx3g`` turns transcripts into subtitle tracks,
``tables`` and ``moov`` write the sample tables and track boxes, ``mux`` plans the output as a
list of byte copies and literal blobs, and ``progressive`` reads finished files back (used to
verify the output). Nothing here performs I/O: inputs are read through ``ByteSource``.
"""
```

`src/utmax/core/media/boxes.py`:

```python
"""ISO base media file format primitives: byte sources, box headers, readers and writers.

MP4, M4A and QuickTime files are trees of boxes: a 32-bit big-endian size, a four-character
type and a payload. Size 1 means a 64-bit size follows the type; size 0 means the box runs to
the end of the file. Every integer is big-endian.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from utmax.errors import MuxError

__all__ = [
    "I32_MAX",
    "U32_MAX",
    "BoxHeader",
    "ByteSource",
    "BytesSource",
    "Reader",
    "box",
    "child_boxes",
    "find_child",
    "full_box",
    "i16",
    "i32",
    "i64",
    "iter_boxes",
    "read_exact",
    "require_child",
    "u8",
    "u16",
    "u24",
    "u32",
    "u64",
]

U32_MAX = 0xFFFF_FFFF
I32_MAX = 0x7FFF_FFFF


class ByteSource(Protocol):
    """Random read access to one input file, such as a downloaded stream."""

    @property
    def size(self) -> int:
        """Total number of bytes."""
        ...

    def read(self, offset: int, n: int) -> bytes:
        """Up to ``n`` bytes starting at ``offset`` (fewer only at the end of the data)."""
        ...


@dataclass(frozen=True, slots=True)
class BytesSource:
    """A :class:`ByteSource` over bytes held in memory."""

    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)

    def read(self, offset: int, n: int) -> bytes:
        return self.data[offset : offset + n]


@dataclass(frozen=True, slots=True)
class BoxHeader:
    """Where one box sits in a file: its type, first byte, total size and header size."""

    kind: str
    offset: int
    size: int
    header_size: int

    @property
    def payload_offset(self) -> int:
        """The first byte after the header."""
        return self.offset + self.header_size

    @property
    def payload_size(self) -> int:
        """The number of bytes after the header."""
        return self.size - self.header_size

    @property
    def end(self) -> int:
        """The first byte after the box."""
        return self.offset + self.size


def read_exact(source: ByteSource, offset: int, n: int) -> bytes:
    """Exactly ``n`` bytes at ``offset``; a short read means the input is truncated."""
    data = source.read(offset, n) if n > 0 else b""
    if len(data) != n:
        raise MuxError(
            f"The input ends early: needed {n} bytes at offset {offset}, got {len(data)}."
        )
    return data


def iter_boxes(source: ByteSource, start: int = 0, end: int | None = None) -> Iterator[BoxHeader]:
    """The boxes laid end to end in ``source[start:end]`` (the top level by default)."""
    limit = source.size if end is None else end
    offset = start
    while offset < limit:
        if limit - offset < 8:
            raise MuxError(f"A box header at offset {offset} is truncated.")
        size, raw = struct.unpack(">I4s", read_exact(source, offset, 8))
        header_size = 8
        if size == 1:
            if limit - offset < 16:
                raise MuxError(f"A 64-bit box header at offset {offset} is truncated.")
            (size,) = struct.unpack(">Q", read_exact(source, offset + 8, 8))
            header_size = 16
        elif size == 0:
            size = limit - offset
        kind = raw.decode("latin-1")
        if size < header_size or offset + size > limit:
            raise MuxError(f"The {kind!r} box at offset {offset} has an impossible size ({size}).")
        yield BoxHeader(kind, offset, size, header_size)
        offset += size


def child_boxes(payload: bytes, *, context: str) -> list[tuple[str, bytes]]:
    """The boxes inside a container's ``payload`` as ``(type, payload)`` pairs, in order."""
    children: list[tuple[str, bytes]] = []
    offset = 0
    while offset < len(payload):
        if len(payload) - offset < 8:
            raise MuxError(f"A box inside {context!r} is truncated.")
        size, raw = struct.unpack_from(">I4s", payload, offset)
        header_size = 8
        if size == 1:
            if len(payload) - offset < 16:
                raise MuxError(f"A 64-bit box inside {context!r} is truncated.")
            (size,) = struct.unpack_from(">Q", payload, offset + 8)
            header_size = 16
        elif size == 0:
            size = len(payload) - offset
        kind = raw.decode("latin-1")
        if size < header_size or offset + size > len(payload):
            raise MuxError(f"The {kind!r} box inside {context!r} has an impossible size ({size}).")
        children.append((kind, payload[offset + header_size : offset + size]))
        offset += size
    return children


def find_child(payload: bytes, kind: str, *, context: str) -> bytes | None:
    """The payload of the first ``kind`` box inside ``payload``, or ``None``."""
    return next(
        (body for name, body in child_boxes(payload, context=context) if name == kind), None
    )


def require_child(payload: bytes, kind: str, *, context: str) -> bytes:
    """Like :func:`find_child`, but a missing box is an error."""
    body = find_child(payload, kind, context=context)
    if body is None:
        raise MuxError(f"The {context!r} box has no {kind!r} box inside.")
    return body


class Reader:
    """A big-endian cursor over a box payload; reading past the end raises :class:`MuxError`."""

    def __init__(self, data: bytes, context: str) -> None:
        self._data = data
        self._offset = 0
        self._context = context

    @property
    def remaining(self) -> int:
        """Bytes left to read."""
        return len(self._data) - self._offset

    def take(self, n: int) -> bytes:
        """The next ``n`` bytes."""
        if n < 0 or n > self.remaining:
            raise MuxError(f"The {self._context!r} box is truncated.")
        chunk = self._data[self._offset : self._offset + n]
        self._offset += n
        return chunk

    def skip(self, n: int) -> None:
        """Skip ``n`` bytes."""
        self.take(n)

    def rest(self) -> bytes:
        """Everything that has not been read yet."""
        return self.take(self.remaining)

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return int.from_bytes(self.take(2), "big")

    def u24(self) -> int:
        return int.from_bytes(self.take(3), "big")

    def u32(self) -> int:
        return int.from_bytes(self.take(4), "big")

    def u64(self) -> int:
        return int.from_bytes(self.take(8), "big")

    def i16(self) -> int:
        return int.from_bytes(self.take(2), "big", signed=True)

    def i32(self) -> int:
        return int.from_bytes(self.take(4), "big", signed=True)

    def i64(self) -> int:
        return int.from_bytes(self.take(8), "big", signed=True)

    def fourcc(self) -> str:
        return self.take(4).decode("latin-1")


def u8(value: int) -> bytes:
    return struct.pack(">B", value)


def u16(value: int) -> bytes:
    return struct.pack(">H", value)


def u24(value: int) -> bytes:
    return value.to_bytes(3, "big")


def u32(value: int) -> bytes:
    return struct.pack(">I", value)


def u64(value: int) -> bytes:
    return struct.pack(">Q", value)


def i16(value: int) -> bytes:
    return struct.pack(">h", value)


def i32(value: int) -> bytes:
    return struct.pack(">i", value)


def i64(value: int) -> bytes:
    return struct.pack(">q", value)


def box(kind: str, *parts: bytes) -> bytes:
    """A box with a 32-bit size header around the concatenated ``parts``."""
    payload = b"".join(parts)
    return struct.pack(">I4s", len(payload) + 8, kind.encode("latin-1")) + payload


def full_box(kind: str, version: int, flags: int, *parts: bytes) -> bytes:
    """A "full box": a box whose payload starts with a version byte and 24 bits of flags."""
    return box(kind, u8(version), u24(flags), *parts)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/media/test_boxes.py -q`
Expected: `15 passed`.

- [ ] **Step 5: Gates and full suite**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected: `All checks passed!`, `… files already formatted`, `Success: no issues found in 29 source files`, `425 passed, 6 deselected`.

- [ ] **Step 6: Commit**

```bash
git add src/utmax/core/media/__init__.py src/utmax/core/media/boxes.py tests/unit/media/__init__.py tests/unit/media/test_boxes.py
git commit -m "feat: add ISO base media box primitives for the muxer

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Synthetic fragment factory

**Files:**
- Create: `tests/helpers/fmp4_factory.py`
- Test: `tests/unit/media/test_fmp4_factory.py`

**Interfaces:**
- Consumes: `box`, `full_box`, `i16`, `i32`, `u16`, `u32`, `u64` from `utmax.core.media.boxes` (Task 1).
- Produces (in `tests.helpers.fmp4_factory`; later tasks rely on every name):
  - `Sample(duration, size, sync=True, cto=0)` — what a parser must report.
  - `Track(track_id=1, handler="vide", codec="avc1", timescale=12800, language="und", width=640, height=360, edits=(), entries=1, trex=(1, 0, 0, 0), channels=2, sample_rate=44100, extra_audio_box=b"")` — `edits` are `(duration in movie ticks, media time)` pairs; `trex` is `(description, duration, size, flags)`; `codec` may be `avc1`, `av01`, `mp4a` or any other four characters (a generic entry).
  - `Run(samples, flags=0x000F01, version=0, shift=0)` — one `trun`; `shift` is added to the written `data_offset` to build broken files.
  - `Traf(track_id, runs, flags=0x020000, description=1, default_duration=0, default_size=0, default_flags=0, tfdt=0, tfdt_version=0)` — `tfdt=None` omits the box.
  - `payload(track_id, index, size) -> bytes` — the 8-byte pattern stored for each sample.
  - `sample_entry(track) -> bytes`, `init_segment(tracks, *, movie_timescale=1000, fragmented=True, samples_in_moov=False, header_version=0, mvex_extra=b"") -> bytes`.
  - `fragmented_file(tracks, fragments, *, movie_timescale=1000, after_moov=b"", between=b"", header_version=0) -> bytes` — `fragments` is a list of fragments, each a list of `Traf`.
  - `virtual_file(tracks, fragments, *, movie_timescale=1000) -> VirtualSource` — same bytes, payloads computed on read.
  - `simple_file(samples, *, track=None, per_fragment=10, run_flags=0x000F01, run_version=0) -> bytes` — one track, one run per fragment, with `tfdt`.
  - Constants `SYNC_FLAGS = 0x02000000`, `NON_SYNC_FLAGS = 0x01010000`, `UNITY`, `AVCC`, `AV1C`, `ESDS` (the last three are real YouTube configuration boxes' payloads).
- Layout rules the factory follows: explicit `base_data_offset` = the `mdat` payload start; `default-base-is-moof` = the `moof` start; otherwise the implicit base (the `moof` start, then the end of the previous track fragment's data). Runs are stored back to back in `mdat` in traf/run order; a run without `data_offset` must start where the previous one ended (else `AssertionError`). Omitted per-sample values must equal the `tfhd`/`trex` defaults, or the factory raises `AssertionError` — so a spec's samples are exactly what a correct parser reports.

- [ ] **Step 1: Write the failing tests**

`tests/unit/media/test_fmp4_factory.py`:

```python
"""The synthetic fragment factory must itself be trustworthy: layout, payloads and guards."""

from __future__ import annotations

import pytest

from tests.helpers.fmp4_factory import (
    Run,
    Sample,
    Track,
    Traf,
    fragmented_file,
    init_segment,
    payload,
    sample_entry,
    simple_file,
    virtual_file,
)
from utmax.core.media.boxes import BytesSource, box, child_boxes, find_child, iter_boxes

VIDEO = Track()
AUDIO = Track(track_id=2, handler="soun", codec="mp4a", timescale=44100)


def two_track_fragments() -> list[list[Traf]]:
    video = (Sample(512, 700), Sample(512, 300, sync=False, cto=512))
    audio = (Sample(1024, 20), Sample(1024, 21), Sample(1024, 22))
    return [
        [Traf(1, (Run(video),)), Traf(2, (Run(audio),))],
        [Traf(1, (Run(video),), tfdt=1024), Traf(2, (Run(audio),), tfdt=3072)],
    ]


def test_layout_is_ftyp_moov_then_moof_mdat_pairs() -> None:
    data = fragmented_file([VIDEO, AUDIO], two_track_fragments(), after_moov=box("sidx"))
    kinds = [header.kind for header in iter_boxes(BytesSource(data))]
    assert kinds == ["ftyp", "moov", "sidx", "moof", "mdat", "moof", "mdat"]


def test_mdat_holds_each_run_in_order_with_unique_patterns() -> None:
    data = fragmented_file([VIDEO], [[Traf(1, (Run((Sample(512, 10), Sample(512, 7))),))]])
    mdat = next(h for h in iter_boxes(BytesSource(data)) if h.kind == "mdat")
    assert data[mdat.payload_offset : mdat.end] == payload(1, 0, 10) + payload(1, 1, 7)


def test_payload_patterns_differ_per_track_and_sample() -> None:
    assert len(payload(1, 0, 13)) == 13
    assert payload(1, 0, 16)[:8] == payload(1, 0, 16)[8:]
    assert len({payload(1, 0, 16), payload(1, 1, 16), payload(2, 0, 16)}) == 3


def test_virtual_file_reads_exactly_like_the_materialized_file() -> None:
    fragments = two_track_fragments()
    data = fragmented_file([VIDEO, AUDIO], fragments)
    virtual = virtual_file([VIDEO, AUDIO], fragments)
    assert virtual.size == len(data)
    assert virtual.read(0, virtual.size) == data
    for offset, length in ((0, 3), (5, 1000), (len(data) - 50, 49), (900, 1234)):
        assert virtual.read(offset, length) == data[offset : offset + length]
    assert virtual.read(len(data), 10) == b""


def test_init_segment_options() -> None:
    moov = child_boxes(init_segment([VIDEO], fragmented=False), context="file")[1][1]
    assert find_child(moov, "mvex", context="moov") is None
    wide = child_boxes(init_segment([VIDEO], header_version=1), context="file")[1][1]
    mvhd = find_child(wide, "mvhd", context="moov")
    assert mvhd is not None
    assert mvhd[0] == 1
    assert b"stsz" in init_segment([VIDEO], samples_in_moov=True)


@pytest.mark.parametrize(
    ("track", "marker"),
    [
        (VIDEO, b"avcC"),
        (Track(codec="av01"), b"av1C"),
        (AUDIO, b"esds"),
        (Track(codec="hvc1"), b"hvc1"),
    ],
)
def test_sample_entries(track: Track, marker: bytes) -> None:
    entry = sample_entry(track)
    assert entry[4:8] == track.codec.encode()
    assert marker in entry


def test_simple_file_splits_samples_into_fragments() -> None:
    data = simple_file([Sample(512, 5)] * 25, per_fragment=10)
    assert [h.kind for h in iter_boxes(BytesSource(data))].count("moof") == 3


@pytest.mark.parametrize(
    ("run", "traf_flags", "message"),
    [
        (Run((Sample(512, 5),), flags=0x000201), 0x020000, "omitted duration"),
        (Run((Sample(0, 5),), flags=0x000101), 0x020000, "omitted size"),
        (Run((Sample(0, 0, sync=False),), flags=0x000001), 0x020000, "omitted sample flags"),
        (Run((Sample(0, 0, cto=5),), flags=0x000001), 0x020000, "omitted composition"),
        (Run((Sample(0, 0),), flags=0x000000), 0x020000, "must start where"),
    ],
)
def test_impossible_specs_are_refused(run: Run, traf_flags: int, message: str) -> None:
    with pytest.raises(AssertionError, match=message):
        fragmented_file([VIDEO], [[Traf(1, (run,), flags=traf_flags)]])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/media/test_fmp4_factory.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'tests.helpers.fmp4_factory'`.

- [ ] **Step 3: Write the factory**

`tests/helpers/fmp4_factory.py`:

```python
"""Build synthetic fragmented MP4 files for tests, down to every tfhd and trun flag.

A test lists each track's samples and how every fragment encodes them; the factory computes
the offsets and writes the boxes. It refuses specs a real muxer could not produce (a trun that
omits sample sizes while the samples differ from the default size, for example), so the
samples in a spec are exactly what a correct parser must report. Every sample is filled with
an 8-byte pattern unique to (track, sample number); :func:`virtual_file` returns a ByteSource
that computes payloads on demand, for multi-gigabyte inputs that are never allocated.
"""

from __future__ import annotations

import struct
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import accumulate

from utmax.core.media.boxes import box, full_box, i16, i32, u16, u32, u64

SYNC_FLAGS = 0x0200_0000  # sample_depends_on = 2: decodable on its own
NON_SYNC_FLAGS = 0x0101_0000  # depends on other samples, flagged non-sync
UNITY = b"".join(u32(value) for value in (0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x4000_0000))
AVCC = bytes.fromhex(
    "01640028ffe1001e67640028acd100780227e5c05a808080a0000003002000000641e306224001000468ebef2c"
)
AV1C = bytes.fromhex("81080c000a0e00000042abbfc377ebe240404041")
ESDS = bytes.fromhex(
    "000000000327000100041f40150000000000000000000000051012100000000000000000000000000000060102"
)


@dataclass(frozen=True)
class Sample:
    """What a parser must report for one sample."""

    duration: int
    size: int
    sync: bool = True
    cto: int = 0


@dataclass(frozen=True)
class Track:
    """One track of the init segment."""

    track_id: int = 1
    handler: str = "vide"
    codec: str = "avc1"
    timescale: int = 12800
    language: str = "und"
    width: int = 640
    height: int = 360
    edits: tuple[tuple[int, int], ...] = ()  # (duration in movie ticks, media time)
    entries: int = 1
    trex: tuple[int, int, int, int] = (1, 0, 0, 0)  # description, duration, size, flags
    channels: int = 2
    sample_rate: int = 44100
    extra_audio_box: bytes = b""


@dataclass(frozen=True)
class Run:
    """One trun box."""

    samples: tuple[Sample, ...]
    flags: int = 0x000F01  # data offset + per-sample duration, size, flags and cto
    version: int = 0
    shift: int = 0  # added to the written data_offset, to break a file on purpose


@dataclass(frozen=True)
class Traf:
    """One track fragment: tfhd flags and defaults, tfdt and runs."""

    track_id: int
    runs: tuple[Run, ...]
    flags: int = 0x020000  # default-base-is-moof
    description: int = 1
    default_duration: int = 0
    default_size: int = 0
    default_flags: int = 0
    tfdt: int | None = 0
    tfdt_version: int = 0


@dataclass(frozen=True)
class _Payload:
    track_id: int
    first_index: int
    sizes: tuple[int, ...]


def payload(track_id: int, index: int, size: int) -> bytes:
    """The bytes the factory stores for sample ``index`` of ``track_id``."""
    pattern = struct.pack(">HIH", track_id, index, 0xA55A)
    return (pattern * (size // 8 + 1))[:size]


def sample_entry(track: Track) -> bytes:
    """A plausible sample description for ``track.codec``."""
    if track.codec in ("avc1", "av01"):
        config = box("avcC", AVCC) if track.codec == "avc1" else box("av1C", AV1C)
        return box(
            track.codec,
            bytes(6),
            u16(1),
            bytes(16),
            u16(track.width),
            u16(track.height),
            u32(0x0048_0000),
            u32(0x0048_0000),
            u32(0),
            u16(1),
            bytes(32),
            u16(0x0018),
            i16(-1),
            config,
        )
    if track.codec == "mp4a":
        return box(
            "mp4a",
            bytes(6),
            u16(1),
            bytes(8),
            u16(track.channels),
            u16(16),
            u32(0),
            u32((track.sample_rate << 16) & 0xFFFF_FFFF),
            box("esds", ESDS),
            track.extra_audio_box,
        )
    return box(track.codec, bytes(6), u16(1), bytes(70))


def init_segment(
    tracks: Sequence[Track],
    *,
    movie_timescale: int = 1000,
    fragmented: bool = True,
    samples_in_moov: bool = False,
    header_version: int = 0,
    mvex_extra: bytes = b"",
) -> bytes:
    """``ftyp`` + ``moov`` (``mvex`` unless ``fragmented`` is false)."""
    wide = header_version == 1
    mvhd = full_box(
        "mvhd",
        header_version,
        0,
        bytes(16 if wide else 8),
        u32(movie_timescale),
        u64(0) if wide else u32(0),
        u32(0x10000),
        u16(0x100),
        bytes(10),
        UNITY,
        bytes(24),
        u32(len(tracks) + 1),
    )
    parts = [mvhd]
    parts += [_trak(track, samples_in_moov=samples_in_moov, wide=wide) for track in tracks]
    if fragmented:
        trex = [
            full_box("trex", 0, 0, u32(track.track_id), *(u32(value) for value in track.trex))
            for track in tracks
        ]
        parts.append(box("mvex", mvex_extra, *trex))
    return box("ftyp", b"dash", u32(0), b"iso6", b"mp41") + box("moov", *parts)


def fragmented_file(
    tracks: Sequence[Track],
    fragments: Sequence[Sequence[Traf]],
    *,
    movie_timescale: int = 1000,
    after_moov: bytes = b"",
    between: bytes = b"",
    header_version: int = 0,
) -> bytes:
    """A complete fragmented MP4 in memory."""
    init = init_segment(tracks, movie_timescale=movie_timescale, header_version=header_version)
    pieces = _pieces(init + after_moov, tracks, fragments, between)
    return b"".join(p if isinstance(p, bytes) else _materialize(p) for p in pieces)


def virtual_file(
    tracks: Sequence[Track], fragments: Sequence[Sequence[Traf]], *, movie_timescale: int = 1000
) -> VirtualSource:
    """Like :func:`fragmented_file`, but payload bytes are only computed when read."""
    init = init_segment(tracks, movie_timescale=movie_timescale)
    return VirtualSource(_pieces(init, tracks, fragments, b""))


def simple_file(
    samples: Sequence[Sample],
    *,
    track: Track | None = None,
    per_fragment: int = 10,
    run_flags: int = 0x000F01,
    run_version: int = 0,
) -> bytes:
    """One track in fragments of ``per_fragment`` samples, one run each, with tfdt."""
    spec = track or Track()
    fragments: list[list[Traf]] = []
    decode_time = 0
    for start in range(0, len(samples), per_fragment):
        chunk = tuple(samples[start : start + per_fragment])
        run = Run(chunk, flags=run_flags, version=run_version)
        fragments.append([Traf(spec.track_id, (run,), tfdt=decode_time)])
        decode_time += sum(sample.duration for sample in chunk)
    return fragmented_file([spec], fragments)


class VirtualSource:
    """A ByteSource whose sample payloads are computed on demand."""

    def __init__(self, pieces: list[bytes | _Payload]) -> None:
        self._pieces = pieces
        lengths = [len(p) if isinstance(p, bytes) else sum(p.sizes) for p in pieces]
        self._starts = list(accumulate(lengths, initial=0))
        self.size = self._starts[-1]

    def read(self, offset: int, n: int) -> bytes:
        end = min(offset + n, self.size)
        out = bytearray()
        index = bisect_right(self._starts, offset) - 1
        while offset < end:
            piece, start = self._pieces[index], self._starts[index]
            take = min(end, self._starts[index + 1]) - offset
            if isinstance(piece, bytes):
                out += piece[offset - start : offset - start + take]
            else:
                out += _payload_window(piece, offset - start, take)
            offset += take
            index += 1
        return bytes(out)


def _payload_window(piece: _Payload, offset: int, n: int) -> bytes:
    starts = list(accumulate(piece.sizes, initial=0))
    out = bytearray()
    while n > 0:
        sample = bisect_right(starts, offset) - 1
        within = offset - starts[sample]
        take = min(n, piece.sizes[sample] - within)
        pattern = struct.pack(">HIH", piece.track_id, piece.first_index + sample, 0xA55A)
        repeated = pattern * ((within % 8 + take) // 8 + 1)
        out += repeated[within % 8 : within % 8 + take]
        offset += take
        n -= take
    return bytes(out)


def _materialize(piece: _Payload) -> bytes:
    return b"".join(
        payload(piece.track_id, piece.first_index + index, size)
        for index, size in enumerate(piece.sizes)
    )


def _pieces(
    head: bytes, tracks: Sequence[Track], fragments: Sequence[Sequence[Traf]], between: bytes
) -> list[bytes | _Payload]:
    by_id = {track.track_id: track for track in tracks}
    pieces: list[bytes | _Payload] = [head]
    position = len(head)
    counters = dict.fromkeys(by_id, 0)
    for number, trafs in enumerate(fragments, start=1):
        if number > 1 and between:
            pieces.append(between)
            position += len(between)
        payloads: list[_Payload] = []
        for traf in trafs:
            for run in traf.runs:
                sizes = tuple(sample.size for sample in run.samples)
                payloads.append(_Payload(traf.track_id, counters[traf.track_id], sizes))
                counters[traf.track_id] += len(sizes)
        data_size = sum(sum(p.sizes) for p in payloads)
        if data_size + 8 <= 0xFFFF_FFFF:
            header = u32(data_size + 8) + b"mdat"
        else:
            header = u32(1) + b"mdat" + u64(data_size + 16)
        draft = _moof(number, trafs, by_id, moof_start=position, data_start=None)
        data_start = position + len(draft) + len(header)
        moof = _moof(number, trafs, by_id, moof_start=position, data_start=data_start)
        pieces += [moof, header, *payloads]
        position += len(moof) + len(header) + data_size
    return pieces


def _moof(
    number: int,
    trafs: Sequence[Traf],
    tracks: dict[int, Track],
    *,
    moof_start: int,
    data_start: int | None,
) -> bytes:
    """The moof box; ``data_start=None`` drafts it (same size, offsets not yet known)."""
    draft = data_start is None
    boxes = [full_box("mfhd", 0, 0, u32(number))]
    position = data_start or 0
    previous_end = moof_start
    for traf in trafs:
        track = tracks[traf.track_id]
        if traf.flags & 0x000001:
            base = position if draft else data_start or 0
        elif traf.flags & 0x020000:
            base = moof_start
        else:
            base = previous_end
        fields = [u32(traf.track_id)]
        if traf.flags & 0x000001:
            fields.append(u64(base))
        for bit, value in (
            (0x000002, traf.description),
            (0x000008, traf.default_duration),
            (0x000010, traf.default_size),
            (0x000020, traf.default_flags),
        ):
            if traf.flags & bit:
                fields.append(u32(value))
        children = [full_box("tfhd", 0, traf.flags, *fields)]
        if traf.tfdt is not None:
            decode_time = u64(traf.tfdt) if traf.tfdt_version else u32(traf.tfdt)
            children.append(full_box("tfdt", traf.tfdt_version, 0, decode_time))
        defaults = (
            traf.default_duration if traf.flags & 0x000008 else track.trex[1],
            traf.default_size if traf.flags & 0x000010 else track.trex[2],
            traf.default_flags if traf.flags & 0x000020 else track.trex[3],
        )
        expected = base
        for run in traf.runs:
            if not draft and not run.flags & 0x000001 and position != expected:
                raise AssertionError("a run without data_offset must start where the last ended")
            offset = 0 if draft else position - base + run.shift
            children.append(_trun(run, data_offset=offset, defaults=defaults))
            position += sum(sample.size for sample in run.samples)
            expected = position
        previous_end = position
        boxes.append(box("traf", *children))
    return box("moof", *boxes)


def _trun(run: Run, *, data_offset: int, defaults: tuple[int, int, int]) -> bytes:
    default_duration, default_size, default_flags = defaults
    fields = [u32(len(run.samples))]
    if run.flags & 0x000001:
        fields.append(i32(data_offset))
    if run.flags & 0x000004:
        fields.append(u32(_flags(run.samples[0])))
    for index, sample in enumerate(run.samples):
        if run.flags & 0x000100:
            fields.append(u32(sample.duration))
        elif sample.duration != default_duration:
            raise AssertionError("an omitted duration must equal the default duration")
        if run.flags & 0x000200:
            fields.append(u32(sample.size))
        elif sample.size != default_size:
            raise AssertionError("an omitted size must equal the default size")
        if run.flags & 0x000400:
            fields.append(u32(_flags(sample)))
        else:
            first = index == 0 and run.flags & 0x000004
            implied = _flags(sample) if first else default_flags
            if (not implied & 0x0101_0000) != sample.sync:
                raise AssertionError("omitted sample flags must match the sample's sync state")
        if run.flags & 0x000800:
            fields.append(i32(sample.cto))
        elif sample.cto:
            raise AssertionError("an omitted composition offset must be zero")
    return full_box("trun", run.version, run.flags, *fields)


def _flags(sample: Sample) -> int:
    return SYNC_FLAGS if sample.sync else NON_SYNC_FLAGS


def _trak(track: Track, *, samples_in_moov: bool, wide: bool) -> bytes:
    visual = track.handler == "vide"
    tkhd = full_box(
        "tkhd",
        1 if wide else 0,
        3,
        bytes(16 if wide else 8),
        u32(track.track_id),
        u32(0),
        u64(0) if wide else u32(0),
        bytes(8),
        u16(0),
        u16(0 if visual else 1),
        u16(0 if visual else 0x100),
        u16(0),
        UNITY,
        u32(track.width << 16 if visual else 0),
        u32(track.height << 16 if visual else 0),
    )
    parts = [tkhd]
    if track.edits:
        entries = [
            u32(length) + i32(media_time) + u32(0x10000) for length, media_time in track.edits
        ]
        parts.append(box("edts", full_box("elst", 0, 0, u32(len(entries)), *entries)))
    language = 0
    for letter in track.language:
        language = language << 5 | (ord(letter) - 0x60)
    mdhd = full_box(
        "mdhd",
        1 if wide else 0,
        0,
        bytes(16 if wide else 8),
        u32(track.timescale),
        u64(0) if wide else u32(0),
        u16(language),
        u16(0),
    )
    hdlr = full_box("hdlr", 0, 0, u32(0), track.handler.encode("ascii"), bytes(12), b"Handler\x00")
    header = full_box("vmhd", 0, 1, bytes(8)) if visual else full_box("smhd", 0, 0, bytes(4))
    dinf = box("dinf", full_box("dref", 0, 0, u32(1), full_box("url ", 0, 1)))
    stbl = box(
        "stbl",
        full_box("stsd", 0, 0, u32(track.entries), *[sample_entry(track)] * track.entries),
        full_box("stts", 0, 0, u32(0)),
        full_box("stsc", 0, 0, u32(0)),
        full_box("stsz", 0, 0, u32(0), u32(1 if samples_in_moov else 0)),
        full_box("stco", 0, 0, u32(0)),
    )
    parts.append(box("mdia", mdhd, hdlr, box("minf", header, dinf, stbl)))
    return box("trak", *parts)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/media/test_fmp4_factory.py -q`
Expected: `15 passed`.

- [ ] **Step 5: Gates and full suite**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected: clean gates (mypy checks `src` only: 29 source files), `440 passed, 6 deselected`.

- [ ] **Step 6: Commit**

```bash
git add tests/helpers/fmp4_factory.py tests/unit/media/test_fmp4_factory.py
git commit -m "test: add a synthetic fragmented MP4 factory

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Fragmented MP4 indexer

**Files:**
- Create: `src/utmax/core/media/fmp4.py`
- Test: `tests/unit/media/test_fmp4.py`

**Interfaces:**
- Consumes: `ByteSource`, `Reader`, `child_boxes`, `find_child`, `iter_boxes`, `read_exact`, `require_child` (Task 1); `MuxError`; the factory (Task 2) in tests.
- Produces (in `utmax.core.media.fmp4`):
  - `Edit(duration: int, media_time: int, rate: int = 0x00010000)` — `media_time` −1 is an empty edit; `rate` is the raw 16.16 field.
  - `TrackHeader(track_id, handler, timescale, language, matrix, width, height, sample_entries, edits, movie_timescale)` with `.codec` (fourcc of the first sample description); `language` is the raw 15-bit `mdhd` field; `width`/`height` are the raw 16.16 `tkhd` values; `sample_entries` are complete boxes, byte for byte.
  - `SampleTable` — parallel `array("q")` columns `offsets`, `sizes`, `dts`, `durations`, `ctos` plus `sync: bytearray` (1 = sync) and `descriptions` (1-based); `len(table)`. `durations` are the decode-time steps (a later `tfdt` stretches the previous sample), so `dts[i+1] - dts[i] == durations[i]`.
  - `IndexedTrack(header: TrackHeader, samples: SampleTable)`.
  - `index_fragments(source: ByteSource) -> tuple[IndexedTrack, ...]` — tracks in `moov` order.
  - `parse_elst(payload) -> tuple[Edit, ...]`, `parse_stsd(payload) -> tuple[bytes, ...]` (used again by `progressive`).
- Errors (`MuxError`): no `moov`; two `moov`s; `moof` before `moov`; no `mvex` ("not a fragmented MP4"); samples inside `moov`; no tracks; duplicate track IDs; zero timescale; no sample descriptions; a description index out of range; a fragment for an unknown track; a `traf` without `tfhd`; a `trun` shorter than its sample count; data before the file start or outside every `mdat`; decode times going backwards; a track without samples; any truncated box.

- [ ] **Step 1: Write the failing tests**

`tests/unit/media/test_fmp4.py`:

```python
"""Tests for indexing fragmented MP4 streams, flag path by flag path."""

from __future__ import annotations

import pytest

from tests.helpers.fmp4_factory import (
    NON_SYNC_FLAGS,
    SYNC_FLAGS,
    Run,
    Sample,
    Track,
    Traf,
    fragmented_file,
    init_segment,
    payload,
    simple_file,
)
from utmax.core.media.boxes import BytesSource, box, full_box, i32, i64, u32, u64
from utmax.core.media.fmp4 import Edit, IndexedTrack, index_fragments, parse_elst
from utmax.errors import MuxError

VIDEO = Track()
AUDIO = Track(track_id=2, handler="soun", codec="mp4a", timescale=44100)


def index_one(data: bytes) -> IndexedTrack:
    (track,) = index_fragments(BytesSource(data))
    return track


def assert_samples(
    data: bytes, track: IndexedTrack, expected: list[Sample], first_dts: int = 0
) -> None:
    table = track.samples
    assert list(table.sizes) == [sample.size for sample in expected]
    assert list(table.ctos) == [sample.cto for sample in expected]
    assert [bool(flag) for flag in table.sync] == [sample.sync for sample in expected]
    decode_time = first_dts
    for index, sample in enumerate(expected):
        assert table.dts[index] == decode_time
        decode_time += sample.duration
        start = table.offsets[index]
        assert data[start : start + sample.size] == payload(
            track.header.track_id, index, sample.size
        )
    assert list(table.durations) == [sample.duration for sample in expected]


def test_youtube_h264_layout_default_duration_and_signed_offsets() -> None:
    # itag 137: tfhd 0x02000a (base is moof, sample description, default duration),
    # trun 0x000e01 (data offset, per-sample size, flags and composition offset).
    samples = [Sample(512, 900 + i, sync=i == 0, cto=(0, 512, 1536, 0)[i % 4]) for i in range(8)]
    fragments = [
        [
            Traf(
                1,
                (Run(tuple(samples[:4]), flags=0x000E01),),
                flags=0x02000A,
                default_duration=512,
            )
        ],
        [
            Traf(
                1,
                (Run(tuple(samples[4:]), flags=0x000E01),),
                flags=0x02000A,
                default_duration=512,
                tfdt=2048,
            )
        ],
    ]
    data = fragmented_file([VIDEO], fragments)
    track = index_one(data)
    assert track.header.codec == "avc1"
    assert (track.header.handler, track.header.timescale) == ("vide", 12800)
    assert_samples(data, track, samples)


def test_youtube_aac_layout_uses_tfhd_default_flags() -> None:
    # itag 140: tfhd 0x02002a (default duration and flags), trun 0x000201 (sizes only).
    samples = [Sample(1024, 300 + i) for i in range(5)]
    traf = Traf(
        2,
        (Run(tuple(samples), flags=0x000201),),
        flags=0x02002A,
        default_duration=1024,
        default_flags=SYNC_FLAGS,
    )
    data = fragmented_file([AUDIO], [[traf]])
    track = index_one(data)
    assert track.header.codec == "mp4a"
    assert_samples(data, track, samples)


def test_youtube_av1_layout_with_per_sample_flags() -> None:
    # itag 399: trun 0x000601 (data offset, sizes, flags), duration from tfhd.
    samples = [Sample(512, 50 + i, sync=i == 0) for i in range(4)]
    traf = Traf(1, (Run(tuple(samples), flags=0x000601),), flags=0x02000A, default_duration=512)
    data = fragmented_file([Track(codec="av01")], [[traf]])
    assert_samples(data, index_one(data), samples)


def test_values_fall_back_to_trex_defaults() -> None:
    samples = [Sample(1000, 40, sync=False) for _ in range(3)]
    track = Track(trex=(1, 1000, 40, NON_SYNC_FLAGS))
    data = fragmented_file([track], [[Traf(1, (Run(tuple(samples), flags=0x000001),))]])
    assert_samples(data, index_one(data), samples)


def test_first_sample_flags_mark_only_the_first_sample() -> None:
    samples = [Sample(512, 10, sync=i == 0) for i in range(4)]
    run = Run(tuple(samples), flags=0x000205)  # data offset, first-sample flags, sizes
    traf = Traf(1, (run,), flags=0x020028, default_duration=512, default_flags=NON_SYNC_FLAGS)
    data = fragmented_file([VIDEO], [[traf]])
    assert_samples(data, index_one(data), samples)


def test_version_1_runs_carry_negative_composition_offsets() -> None:
    samples = [Sample(512, 10, cto=cto) for cto in (0, 1024, -512, -512)]
    data = simple_file(samples, run_version=1)
    assert_samples(data, index_one(data), samples)


def test_version_0_runs_are_read_as_signed_like_ffmpeg_does() -> None:
    samples = [Sample(512, 10, cto=cto) for cto in (0, 1024, -512, -512)]
    data = simple_file(samples, run_version=0)
    assert_samples(data, index_one(data), samples)


def test_tfdt_version_1_keeps_64_bit_decode_times() -> None:
    samples = [Sample(512, 10) for _ in range(3)]
    base = 2**33
    traf = Traf(1, (Run(tuple(samples)),), tfdt=base, tfdt_version=1)
    data = fragmented_file([VIDEO], [[traf]])
    assert_samples(data, index_one(data), samples, first_dts=base)


def test_without_tfdt_decode_time_continues_from_the_previous_fragment() -> None:
    samples = [Sample(512, 10) for _ in range(4)]
    fragments = [
        [Traf(1, (Run(tuple(samples[:2])),), tfdt=None)],
        [Traf(1, (Run(tuple(samples[2:])),), tfdt=None)],
    ]
    data = fragmented_file([VIDEO], fragments)
    assert_samples(data, index_one(data), samples)


def test_runs_without_data_offset_follow_the_previous_run() -> None:
    samples = [Sample(512, 10 + i) for i in range(6)]
    runs = (
        Run(tuple(samples[:2])),
        Run(tuple(samples[2:4]), flags=0x000F00),
        Run(tuple(samples[4:]), flags=0x000F00),
    )
    data = fragmented_file([VIDEO], [[Traf(1, runs)]])
    assert_samples(data, index_one(data), samples)


def test_explicit_base_data_offset() -> None:
    samples = [Sample(512, 10 + i) for i in range(3)]
    traf = Traf(1, (Run(tuple(samples), flags=0x000F00),), flags=0x000001)
    data = fragmented_file([VIDEO], [[traf]])
    assert_samples(data, index_one(data), samples)


def test_implicit_base_of_a_second_track_fragment_is_the_end_of_the_first() -> None:
    video = [Sample(512, 100), Sample(512, 110)]
    audio = [Sample(1024, 7), Sample(1024, 8)]
    fragment = [
        Traf(1, (Run(tuple(video)),), flags=0),
        Traf(2, (Run(tuple(audio), flags=0x000F00),), flags=0),
    ]
    data = fragmented_file([VIDEO, AUDIO], [fragment])
    video_track, audio_track = index_fragments(BytesSource(data))
    assert_samples(data, video_track, video)
    assert_samples(data, audio_track, audio)


def test_duration_is_empty_fragments_stretch_the_previous_sample() -> None:
    fragments = [
        [Traf(1, (Run((Sample(512, 10), Sample(512, 11))),))],
        [Traf(1, (), flags=0x030008, default_duration=2000, tfdt=None)],
        [Traf(1, (Run((Sample(512, 12),)),), tfdt=None)],
    ]
    track = index_one(fragmented_file([VIDEO], fragments))
    assert list(track.samples.dts) == [0, 512, 3024]
    assert list(track.samples.durations) == [512, 2512, 512]


def test_a_later_tfdt_turns_a_gap_into_a_longer_previous_sample() -> None:
    fragments = [
        [Traf(1, (Run((Sample(512, 10), Sample(512, 11))),))],
        [Traf(1, (Run((Sample(512, 12),)),), tfdt=5000)],
    ]
    track = index_one(fragmented_file([VIDEO], fragments))
    assert list(track.samples.durations) == [512, 4488, 512]


def test_decode_times_going_backwards_are_an_error() -> None:
    fragments = [
        [Traf(1, (Run((Sample(512, 10), Sample(512, 11))),), tfdt=1000)],
        [Traf(1, (Run((Sample(512, 12),)),), tfdt=100)],
    ]
    with pytest.raises(MuxError, match="go backwards in track 1"):
        index_fragments(BytesSource(fragmented_file([VIDEO], fragments)))


def test_sample_description_index_is_recorded_and_checked() -> None:
    track = Track(entries=2)
    good = Traf(1, (Run((Sample(512, 10),)),), flags=0x020002, description=2)
    indexed = index_one(fragmented_file([track], [[good]]))
    assert list(indexed.samples.descriptions) == [2]
    assert len(indexed.header.sample_entries) == 2
    bad = Traf(1, (Run((Sample(512, 10),)),), flags=0x020002, description=3)
    with pytest.raises(MuxError, match="sample description 3, but only 2 exist"):
        index_fragments(BytesSource(fragmented_file([track], [[bad]])))


@pytest.mark.parametrize(
    "noise",
    [
        box("styp", b"msdh"),
        box("sidx", bytes(24)),
        box("emsg", bytes(12)),
        box("prft", bytes(20)),
        box("free", b"x"),
        box("uuid", bytes(16)),
        box("abcd", b"unknown"),
    ],
)
def test_other_top_level_boxes_are_skipped(noise: bytes) -> None:
    samples = [Sample(512, 10 + i) for i in range(4)]
    fragments = [
        [Traf(1, (Run(tuple(samples[:2])),))],
        [Traf(1, (Run(tuple(samples[2:])),), tfdt=1024)],
    ]
    data = fragmented_file([VIDEO], fragments, after_moov=noise, between=noise)
    assert_samples(data, index_one(data), samples)


def test_track_headers() -> None:
    track = Track(width=1920, height=1080, language="eng", edits=((5000, 512),))
    data = fragmented_file([track], [[Traf(1, (Run((Sample(512, 10),)),))]], movie_timescale=600)
    header = index_one(data).header
    assert header.track_id == 1
    assert (header.width, header.height) == (1920 << 16, 1080 << 16)
    assert header.language == 0x15C7  # "eng" packed as three 5-bit letters
    assert header.edits == (Edit(5000, 512),)
    assert header.movie_timescale == 600
    assert len(header.matrix) == 36


def test_version_1_movie_track_and_media_headers() -> None:
    fragments = [[Traf(1, (Run((Sample(512, 10),)),))]]
    header = index_one(fragmented_file([VIDEO], fragments, header_version=1)).header
    assert (header.timescale, header.movie_timescale) == (12800, 1000)


def test_parse_elst_versions_0_and_1() -> None:
    version_0 = full_box(
        "elst", 0, 0, u32(2), u32(100), i32(-1), u32(0x10000), u32(9), i32(3), u32(0x10000)
    )
    assert parse_elst(version_0[8:]) == (Edit(100, -1), Edit(9, 3))
    version_1 = full_box("elst", 1, 0, u32(1), u64(2**40), i64(2**33), u32(0x8000))
    assert parse_elst(version_1[8:]) == (Edit(2**40, 2**33, 0x8000),)


def patched(data: bytes, marker: bytes, offset: int, value: bytes) -> bytes:
    position = data.index(marker) + offset
    return data[:position] + value + data[position + len(value) :]


ONE_SAMPLE = [[Traf(1, (Run((Sample(512, 10),)),))]]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (box("ftyp", b"isom"), "no 'moov' box"),
        (bytes.fromhex("1a45dfa3") + bytes(60), "impossible size"),  # a WebM (EBML) file
        (
            box("moof") + init_segment([VIDEO]),
            "'moof' box before its 'moov' box",
        ),
        (init_segment([VIDEO]) + init_segment([VIDEO])[24:], "two 'moov' boxes"),
        (init_segment([VIDEO], fragmented=False), "not a fragmented MP4"),
        (init_segment([VIDEO], samples_in_moov=True), "keeps samples in its 'moov'"),
        (init_segment([VIDEO]), "Track 1 of the input has no samples"),
        (init_segment([]), "has no tracks"),
        (init_segment([VIDEO, VIDEO]), "declares track 1 twice"),
        (init_segment([Track(timescale=0)]), "zero timescale"),
        (init_segment([Track(entries=0)]), "no sample descriptions"),
    ],
)
def test_broken_init_segments(data: bytes, message: str) -> None:
    with pytest.raises(MuxError, match=message):
        index_fragments(BytesSource(data))


def test_fragments_must_name_a_known_track() -> None:
    data = patched(fragmented_file([VIDEO], ONE_SAMPLE), b"tfhd", 8, u32(9))
    with pytest.raises(MuxError, match="refers to track 9"):
        index_fragments(BytesSource(data))


def test_track_fragments_need_a_tfhd() -> None:
    data = patched(fragmented_file([VIDEO], ONE_SAMPLE), b"tfhd", 0, b"xxxx")
    with pytest.raises(MuxError, match="no 'tfhd' box"):
        index_fragments(BytesSource(data))


def test_truncated_runs_are_an_error() -> None:
    data = patched(fragmented_file([VIDEO], ONE_SAMPLE), b"trun", 8, u32(99))
    with pytest.raises(MuxError, match="lists 99 samples but is too short"):
        index_fragments(BytesSource(data))


def test_sample_descriptions_with_impossible_sizes_are_an_error() -> None:
    data = patched(init_segment([VIDEO]), b"avc1", -4, u32(4))
    with pytest.raises(MuxError, match="impossible size"):
        index_fragments(BytesSource(data))


@pytest.mark.parametrize(
    ("shift", "message"), [(-50, "outside every 'mdat'"), (-(10**6), "before the start")]
)
def test_sample_data_must_lie_inside_an_mdat(shift: int, message: str) -> None:
    data = fragmented_file([VIDEO], [[Traf(1, (Run((Sample(512, 10),), shift=shift),))]])
    with pytest.raises(MuxError, match=message):
        index_fragments(BytesSource(data))


def test_truncated_inputs_are_reported() -> None:
    data = fragmented_file([VIDEO], ONE_SAMPLE)
    with pytest.raises(MuxError, match="impossible size"):
        index_fragments(BytesSource(data[:-3]))


def test_empty_runs_and_other_mvex_children_are_ignored() -> None:
    samples = [Sample(512, 10)]
    init = init_segment([VIDEO], mvex_extra=full_box("mehd", 0, 0, u32(0)))
    body = fragmented_file([VIDEO], [[Traf(1, (Run(()), Run(tuple(samples))))]])
    data = init + body[len(init_segment([VIDEO])) :]
    assert_samples(data, index_one(data), samples)


def test_a_moov_without_stsz_is_accepted() -> None:
    data = patched(fragmented_file([VIDEO], ONE_SAMPLE), b"stsz", 0, b"stz2")
    assert len(index_one(data).samples) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/media/test_fmp4.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'utmax.core.media.fmp4'`.

- [ ] **Step 3: Implement `fmp4.py`**

`src/utmax/core/media/fmp4.py`:

```python
"""Index fragmented MP4 streams (YouTube's DASH format) without reading sample data.

:func:`index_fragments` walks the top-level boxes of one input, parses ``moov`` (tracks, sample
descriptions, edit lists, ``trex`` defaults) and every ``moof`` (``tfhd``, ``tfdt``, ``trun``)
into per-track sample tables. Rules follow ISO/IEC 14496-12 section 8.8: per-sample values fall
back from ``trun`` to ``tfhd`` to ``trex``; the data of a run starts at its ``data_offset`` from
the fragment's base, else right after the previous run; the base is the explicit
``base_data_offset``, else the ``moof`` start when ``default-base-is-moof`` is set, else the
``moof`` start for the first track fragment and the end of the previous one's data after that.
"""

from __future__ import annotations

import struct
from array import array
from bisect import bisect_right
from dataclasses import dataclass
from itertools import accumulate

from utmax.core.media.boxes import (
    ByteSource,
    Reader,
    child_boxes,
    find_child,
    iter_boxes,
    read_exact,
    require_child,
)
from utmax.errors import MuxError

__all__ = [
    "Edit",
    "IndexedTrack",
    "SampleTable",
    "TrackHeader",
    "index_fragments",
    "parse_elst",
    "parse_stsd",
]

_TFHD_BASE_DATA_OFFSET = 0x000001
_TFHD_DESCRIPTION_INDEX = 0x000002
_TFHD_DEFAULT_DURATION = 0x000008
_TFHD_DEFAULT_SIZE = 0x000010
_TFHD_DEFAULT_FLAGS = 0x000020
_TFHD_DURATION_IS_EMPTY = 0x010000
_TFHD_DEFAULT_BASE_IS_MOOF = 0x020000

_TRUN_DATA_OFFSET = 0x000001
_TRUN_FIRST_SAMPLE_FLAGS = 0x000004
_TRUN_FIELDS = (("duration", 0x000100), ("size", 0x000200), ("flags", 0x000400), ("cto", 0x000800))

# A sample is a sync sample unless it is flagged non-sync or "depends on others" (as FFmpeg).
_NOT_SYNC = 0x0101_0000


@dataclass(frozen=True, slots=True)
class Edit:
    """One edit list entry: ``duration`` in movie ticks, ``media_time`` (-1 = empty edit)."""

    duration: int
    media_time: int
    rate: int = 0x0001_0000


@dataclass(frozen=True, slots=True)
class TrackHeader:
    """What the ``moov`` box says about one track."""

    track_id: int
    handler: str
    timescale: int
    language: int
    matrix: bytes
    width: int
    height: int
    sample_entries: tuple[bytes, ...]
    edits: tuple[Edit, ...]
    movie_timescale: int

    @property
    def codec(self) -> str:
        """The four-character code of the first sample description, e.g. ``"avc1"``."""
        return self.sample_entries[0][4:8].decode("latin-1")


class SampleTable:
    """Parallel arrays with one entry per sample, in decode order."""

    __slots__ = ("ctos", "descriptions", "dts", "durations", "offsets", "sizes", "sync")

    def __init__(self) -> None:
        self.offsets: array[int] = array("q")
        self.sizes: array[int] = array("q")
        self.dts: array[int] = array("q")
        self.durations: array[int] = array("q")
        self.ctos: array[int] = array("q")
        self.sync = bytearray()
        self.descriptions: array[int] = array("q")

    def __len__(self) -> int:
        return len(self.sizes)


@dataclass(frozen=True, slots=True)
class IndexedTrack:
    """One track of a fragmented input: its header and every sample."""

    header: TrackHeader
    samples: SampleTable


@dataclass(frozen=True, slots=True)
class _Defaults:
    description: int
    duration: int
    size: int
    flags: int


_NO_DEFAULTS = _Defaults(description=1, duration=0, size=0, flags=0)


class _Indexer:
    def __init__(self, headers: dict[int, TrackHeader], defaults: dict[int, _Defaults]) -> None:
        self.headers = headers
        self.defaults = defaults
        self.tables = {track_id: SampleTable() for track_id in headers}
        self.next_dts: dict[int, int] = {}
        self.runs: list[tuple[int, int]] = []

    def moof(self, payload: bytes, moof_offset: int) -> None:
        implicit_base = moof_offset
        for kind, body in child_boxes(payload, context="moof"):
            if kind == "traf":
                implicit_base = self.traf(body, moof_offset, implicit_base)

    def traf(self, payload: bytes, moof_offset: int, implicit_base: int) -> int:
        children = child_boxes(payload, context="traf")
        tfhd = next((body for kind, body in children if kind == "tfhd"), None)
        if tfhd is None:
            raise MuxError("A track fragment has no 'tfhd' box.")
        reader = Reader(tfhd, "tfhd")
        reader.skip(1)
        flags = reader.u24()
        track_id = reader.u32()
        header = self.headers.get(track_id)
        if header is None:
            raise MuxError(f"A fragment refers to track {track_id}, which the moov box lacks.")
        trex = self.defaults.get(track_id, _NO_DEFAULTS)
        if flags & _TFHD_BASE_DATA_OFFSET:
            base = reader.u64()
        elif flags & _TFHD_DEFAULT_BASE_IS_MOOF:
            base = moof_offset
        else:
            base = implicit_base
        description = reader.u32() if flags & _TFHD_DESCRIPTION_INDEX else trex.description
        defaults = _Defaults(
            description=description,
            duration=reader.u32() if flags & _TFHD_DEFAULT_DURATION else trex.duration,
            size=reader.u32() if flags & _TFHD_DEFAULT_SIZE else trex.size,
            flags=reader.u32() if flags & _TFHD_DEFAULT_FLAGS else trex.flags,
        )
        if not 1 <= description <= len(header.sample_entries):
            raise MuxError(
                f"Track {track_id} uses sample description {description}, "
                f"but only {len(header.sample_entries)} exist."
            )
        table = self.tables[track_id]
        tfdt = next((body for kind, body in children if kind == "tfdt"), None)
        dts = self.next_dts.get(track_id, 0) if tfdt is None else _base_media_decode_time(tfdt)
        if len(table):
            gap = dts - table.dts[-1]
            if gap < 0:
                raise MuxError(f"Decode times go backwards in track {track_id}.")
            table.durations[-1] = gap
        position = base
        for kind, body in children:
            if kind == "trun":
                position, dts = self.trun(
                    body, base=base, position=position, dts=dts, defaults=defaults, table=table
                )
        if flags & _TFHD_DURATION_IS_EMPTY:
            dts += defaults.duration
        self.next_dts[track_id] = dts
        return position

    def trun(
        self,
        payload: bytes,
        *,
        base: int,
        position: int,
        dts: int,
        defaults: _Defaults,
        table: SampleTable,
    ) -> tuple[int, int]:
        reader = Reader(payload, "trun")
        reader.skip(1)  # version: offsets are read as signed either way
        flags = reader.u24()
        count = reader.u32()
        start = base + reader.i32() if flags & _TRUN_DATA_OFFSET else position
        first_flags = reader.u32() if flags & _TRUN_FIRST_SAMPLE_FLAGS else None
        names = [name for name, bit in _TRUN_FIELDS if flags & bit]
        width = len(names)
        if width * 4 * count > reader.remaining:
            raise MuxError(f"The 'trun' box lists {count} samples but is too short for them.")
        values = struct.unpack(f">{width * count}I", reader.take(width * 4 * count))
        columns = {name: values[index::width] for index, name in enumerate(names)}
        durations = columns.get("duration", [defaults.duration] * count)
        sizes = columns.get("size", [defaults.size] * count)
        if "flags" in columns:
            sample_flags = list(columns["flags"])
        else:
            sample_flags = [defaults.flags] * count
            if first_flags is not None and count:
                sample_flags[0] = first_flags
        # Composition offsets are signed in version 1; like FFmpeg, read version 0 the same way.
        ctos = [
            value - 0x1_0000_0000 if value & 0x8000_0000 else value
            for value in columns.get("cto", [0] * count)
        ]
        if start < 0:
            raise MuxError("A 'trun' box points before the start of the file.")
        offsets = list(accumulate(sizes, initial=start))
        decode_times = list(accumulate(durations, initial=dts))
        table.offsets.extend(offsets[:-1])
        table.sizes.extend(sizes)
        table.dts.extend(decode_times[:-1])
        table.durations.extend(durations)
        table.ctos.extend(ctos)
        table.sync.extend(0 if value & _NOT_SYNC else 1 for value in sample_flags)
        table.descriptions.extend([defaults.description] * count)
        self.runs.append((start, offsets[-1]))
        return offsets[-1], decode_times[-1]


def index_fragments(source: ByteSource) -> tuple[IndexedTrack, ...]:
    """Every track of a fragmented MP4 in ``source``, with all of its samples.

    Raises:
        MuxError: the input is not a fragmented MP4, is truncated or is inconsistent.
    """
    indexer: _Indexer | None = None
    mdats: list[tuple[int, int]] = []
    for header in iter_boxes(source):
        if header.kind == "moov":
            if indexer is not None:
                raise MuxError("The input has two 'moov' boxes.")
            payload = read_exact(source, header.payload_offset, header.payload_size)
            indexer = _Indexer(*_parse_moov(payload))
        elif header.kind == "moof":
            if indexer is None:
                raise MuxError("The input has a 'moof' box before its 'moov' box.")
            payload = read_exact(source, header.payload_offset, header.payload_size)
            indexer.moof(payload, header.offset)
        elif header.kind == "mdat":
            mdats.append((header.payload_offset, header.end))
    if indexer is None:
        raise MuxError("The input has no 'moov' box, so it is not an MP4 file.")
    _check_runs_inside_mdat(indexer.runs, mdats)
    tracks: list[IndexedTrack] = []
    for track_id, track_header in indexer.headers.items():
        table = indexer.tables[track_id]
        if not len(table):
            raise MuxError(f"Track {track_id} of the input has no samples.")
        tracks.append(IndexedTrack(track_header, table))
    return tuple(tracks)


def _parse_moov(payload: bytes) -> tuple[dict[int, TrackHeader], dict[int, _Defaults]]:
    mvhd = Reader(require_child(payload, "mvhd", context="moov"), "mvhd")
    version = mvhd.u8()
    mvhd.skip(3 + (16 if version == 1 else 8))
    movie_timescale = mvhd.u32()
    mvex = find_child(payload, "mvex", context="moov")
    if mvex is None:
        raise MuxError("The input is not a fragmented MP4: its 'moov' box has no 'mvex' box.")
    defaults: dict[int, _Defaults] = {}
    for kind, body in child_boxes(mvex, context="mvex"):
        if kind == "trex":
            reader = Reader(body, "trex")
            reader.skip(4)
            track_id = reader.u32()
            defaults[track_id] = _Defaults(reader.u32(), reader.u32(), reader.u32(), reader.u32())
    headers: dict[int, TrackHeader] = {}
    for kind, body in child_boxes(payload, context="moov"):
        if kind == "trak":
            header = _parse_trak(body, movie_timescale)
            if header.track_id in headers:
                raise MuxError(f"The input declares track {header.track_id} twice.")
            headers[header.track_id] = header
    if not headers:
        raise MuxError("The input's 'moov' box has no tracks.")
    return headers, defaults


def _parse_trak(payload: bytes, movie_timescale: int) -> TrackHeader:
    tkhd = Reader(require_child(payload, "tkhd", context="trak"), "tkhd")
    version = tkhd.u8()
    tkhd.skip(3 + (16 if version == 1 else 8))
    track_id = tkhd.u32()
    # reserved, duration, reserved, layer, alternate group, volume, reserved
    tkhd.skip(4 + (8 if version == 1 else 4) + 8 + 8)
    matrix = tkhd.take(36)
    width, height = tkhd.u32(), tkhd.u32()
    edits: tuple[Edit, ...] = ()
    edts = find_child(payload, "edts", context="trak")
    elst = find_child(edts, "elst", context="edts") if edts is not None else None
    if elst is not None:
        edits = parse_elst(elst)
    mdia = require_child(payload, "mdia", context="trak")
    mdhd = Reader(require_child(mdia, "mdhd", context="mdia"), "mdhd")
    version = mdhd.u8()
    mdhd.skip(3 + (16 if version == 1 else 8))
    timescale = mdhd.u32()
    mdhd.skip(8 if version == 1 else 4)
    language = mdhd.u16()
    if timescale == 0:
        raise MuxError(f"Track {track_id} has a zero timescale.")
    hdlr = Reader(require_child(mdia, "hdlr", context="mdia"), "hdlr")
    hdlr.skip(8)
    handler = hdlr.fourcc()
    minf = require_child(mdia, "minf", context="mdia")
    stbl = require_child(minf, "stbl", context="minf")
    stsz = find_child(stbl, "stsz", context="stbl")
    if stsz is not None:
        sizes = Reader(stsz, "stsz")
        sizes.skip(8)  # version, flags, shared sample size
        if sizes.u32():
            raise MuxError("The input keeps samples in its 'moov' box, which is not supported.")
    entries = parse_stsd(require_child(stbl, "stsd", context="stbl"))
    return TrackHeader(
        track_id=track_id,
        handler=handler,
        timescale=timescale,
        language=language,
        matrix=matrix,
        width=width,
        height=height,
        sample_entries=entries,
        edits=edits,
        movie_timescale=movie_timescale,
    )


def parse_stsd(payload: bytes) -> tuple[bytes, ...]:
    """The sample descriptions of an ``stsd`` payload, each as a complete box."""
    reader = Reader(payload, "stsd")
    reader.skip(4)
    count = reader.u32()
    entries: list[bytes] = []
    for _ in range(count):
        head = reader.take(8)
        (size,) = struct.unpack(">I", head[:4])
        if size < 8:
            raise MuxError("A sample description has an impossible size.")
        entries.append(head + reader.take(size - 8))
    if not entries:
        raise MuxError("A track has no sample descriptions.")
    return tuple(entries)


def parse_elst(payload: bytes) -> tuple[Edit, ...]:
    """The entries of an ``elst`` payload (version 0 or 1)."""
    reader = Reader(payload, "elst")
    version = reader.u8()
    reader.skip(3)
    edits: list[Edit] = []
    for _ in range(reader.u32()):
        if version == 1:
            duration, media_time = reader.u64(), reader.i64()
        else:
            duration, media_time = reader.u32(), reader.i32()
        edits.append(Edit(duration, media_time, reader.u32()))
    return tuple(edits)


def _base_media_decode_time(payload: bytes) -> int:
    reader = Reader(payload, "tfdt")
    version = reader.u8()
    reader.skip(3)
    return reader.u64() if version == 1 else reader.u32()


def _check_runs_inside_mdat(runs: list[tuple[int, int]], mdats: list[tuple[int, int]]) -> None:
    mdats.sort()
    starts = [start for start, _ in mdats]
    for start, end in runs:
        if end <= start:
            continue
        index = bisect_right(starts, start) - 1
        if index < 0 or end > mdats[index][1]:
            raise MuxError(f"Sample data at bytes {start}-{end} lies outside every 'mdat' box.")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/media/test_fmp4.py -q`
Expected: `46 passed`.

- [ ] **Step 5: Gates and full suite**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected: clean gates (30 source files), `486 passed, 6 deselected`.

- [ ] **Step 6: Commit**

```bash
git add src/utmax/core/media/fmp4.py tests/unit/media/test_fmp4.py
git commit -m "feat: index fragmented MP4 streams through byte sources

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Hollow YouTube stream fixtures

**Files:**
- Create: `scripts/make_media_fixtures.py`, `tests/helpers/hollow_source.py`
- Create (generated by the script): `tests/fixtures/media/dQw4w9WgXcQ_137.hollow.bin`, `dQw4w9WgXcQ_140.hollow.bin`, `dQw4w9WgXcQ_399.hollow.bin`, `manifest.json`, `README.md`
- Test: `tests/unit/media/test_hollow.py`

**Interfaces:**
- Consumes: `index_fragments` (Task 3); M1's `InnerTubeClient.player_json`, `RetryingTransport`, `UrllibTransport`, `HttpRequest`, `ANDROID_VR` (script only).
- Produces:
  - `tests.helpers.hollow_source`: `MEDIA` (the fixture folder), `HollowSource(data: bytes)` with `.size`, `.read(offset, n)` and `HollowSource.load(itag)`; `manifest() -> dict`, `stream_facts(itag) -> dict`.
  - Fixture files: each `.hollow.bin` holds the stream's real `ftyp`, `moov`, `sidx` and the first two fragments' `moof` boxes plus each `mdat` header — a few KB standing for 0.3–3 MB. `manifest.json` records per itag: `file`, `mime_type`, `content_length`, `timescale`, `sidx_references`, `elst_media_time`, `virtual_size` and per fragment `tfhd_flags`, `tfdt_version`, `trun_version`, `trun_flags`, `samples`, `sample_bytes`, `size`, `mdat_payload` — all read by the script's own small parser, independent of `utmax.core.media`.
  - No stream URL and no URL parameter (`ip`, `ei`, `sig`, `lsig`, `signature`, `key`, `expire`) is ever written; the test checks the fixture folder for `http`, `googlevideo`, `signature` and `lsig=`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/media/test_hollow.py`:

```python
"""YouTube's real stream structure (hollow fixtures) through the indexer."""

from __future__ import annotations

import pytest

from tests.helpers.hollow_source import MEDIA, HollowSource, manifest, stream_facts
from utmax.core.media.fmp4 import index_fragments


def test_the_recording_shows_the_stream_layout_the_spec_describes() -> None:
    video, audio, av1 = stream_facts(137), stream_facts(140), stream_facts(399)
    assert manifest()["video_id"] == "dQw4w9WgXcQ"
    assert video["elst_media_time"] == 512
    assert {fragment["tfhd_flags"] for fragment in video["fragments"]} == {0x02000A}
    assert {fragment["trun_flags"] for fragment in video["fragments"]} == {0x000E01}
    assert {fragment["tfhd_flags"] for fragment in audio["fragments"]} == {0x02002A}
    assert {fragment["trun_flags"] for fragment in audio["fragments"]} == {0x000201}
    assert {fragment["trun_flags"] for fragment in av1["fragments"]} == {0x000601}


@pytest.mark.parametrize(
    ("itag", "codec", "handler"),
    [(137, "avc1", "vide"), (140, "mp4a", "soun"), (399, "av01", "vide")],
)
def test_hollow_streams_index_as_the_manifest_says(itag: int, codec: str, handler: str) -> None:
    facts = stream_facts(itag)
    source = HollowSource.load(itag)
    assert source.size == facts["virtual_size"]
    (track,) = index_fragments(source)
    header, samples = track.header, track.samples
    assert (header.codec, header.handler, header.timescale) == (codec, handler, facts["timescale"])
    assert len(samples) == sum(fragment["samples"] for fragment in facts["fragments"])
    assert sum(samples.sizes) == sum(fragment["mdat_payload"] for fragment in facts["fragments"])
    assert samples.offsets[-1] + samples.sizes[-1] <= source.size
    media_time = facts["elst_media_time"]
    assert [edit.media_time for edit in header.edits] == (
        [] if media_time is None else [media_time]
    )


@pytest.mark.parametrize("itag", [137, 399])
def test_every_video_fragment_starts_with_a_sync_sample(itag: int) -> None:
    (track,) = index_fragments(HollowSource.load(itag))
    first = 0
    for fragment in stream_facts(itag)["fragments"]:
        assert track.samples.sync[first] == 1
        first += fragment["samples"]
    assert 0 < sum(track.samples.sync) < len(track.samples)


def test_hollow_sources_read_zeros_inside_mdat_payloads() -> None:
    source = HollowSource.load(140)
    (track,) = index_fragments(source)
    assert source.read(track.samples.offsets[0], 16) == bytes(16)
    assert source.read(0, 8)[4:] == b"ftyp"
    assert source.read(source.size, 4) == b""


def test_fixtures_store_no_stream_urls() -> None:
    for path in MEDIA.iterdir():
        data = path.read_bytes()
        for secret in (b"http", b"googlevideo", b"signature", b"lsig="):
            assert secret not in data, (path.name, secret)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/media/test_hollow.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'tests.helpers.hollow_source'`.

- [ ] **Step 3: Write the replay helper**

`tests/helpers/hollow_source.py`:

```python
"""Replay hollow media fixtures (recorded by scripts/make_media_fixtures.py) as byte sources."""

from __future__ import annotations

import json
import struct
from bisect import bisect_right
from functools import cache
from pathlib import Path
from typing import Any

MEDIA = Path(__file__).resolve().parent.parent / "fixtures" / "media"


class HollowSource:
    """A ByteSource over a hollow fixture: the real boxes, with zero-filled mdat payloads."""

    def __init__(self, data: bytes) -> None:
        self._starts: list[int] = []
        self._pieces: list[bytes | int] = []  # stored bytes, or the length of a run of zeros
        stored = virtual = 0
        while stored < len(data):
            size, kind = struct.unpack_from(">I4s", data, stored)
            header = 8
            if size == 1:
                (size,) = struct.unpack_from(">Q", data, stored + 8)
                header = 16
            kept = header if kind == b"mdat" else size
            self._starts.append(virtual)
            self._pieces.append(data[stored : stored + kept])
            if kind == b"mdat":
                self._starts.append(virtual + header)
                self._pieces.append(size - header)
            stored += kept
            virtual += size
        self.size = virtual

    @classmethod
    def load(cls, itag: int) -> HollowSource:
        """The recorded fixture of ``itag`` (137, 140 or 399)."""
        return cls((MEDIA / stream_facts(itag)["file"]).read_bytes())

    def read(self, offset: int, n: int) -> bytes:
        end = min(offset + n, self.size)
        out = bytearray()
        index = bisect_right(self._starts, offset) - 1
        while offset < end:
            piece, start = self._pieces[index], self._starts[index]
            length = piece if isinstance(piece, int) else len(piece)
            take = min(end, start + length) - offset
            if isinstance(piece, int):
                out += bytes(take)
            else:
                out += piece[offset - start : offset - start + take]
            offset += take
            index += 1
        return bytes(out)


@cache
def manifest() -> dict[str, Any]:
    """Facts about the recorded streams, read independently of utmax at recording time."""
    data: dict[str, Any] = json.loads((MEDIA / "manifest.json").read_text(encoding="utf-8"))
    return data


def stream_facts(itag: int) -> dict[str, Any]:
    """The manifest entry of one itag."""
    facts: dict[str, Any] = manifest()["streams"][str(itag)]
    return facts
```

Run: `uv run pytest tests/unit/media/test_hollow.py -q`
Expected: `8 failed`, each with `FileNotFoundError` for `tests/fixtures/media/manifest.json` or the missing folder — the fixtures do not exist yet.

- [ ] **Step 4: Write the recorder**

`scripts/make_media_fixtures.py`:

```python
"""Record "hollow" YouTube stream fixtures into tests/fixtures/media/.

A hollow fixture is the beginning of a real DASH stream (itags 137, 140 and 399 of
dQw4w9WgXcQ) with every mdat payload left out: the real ftyp, moov, sidx and moof boxes plus
the header of each mdat. tests/helpers/hollow_source.py replays it with zero-filled payloads,
so the muxer meets YouTube's exact box structure offline, in a few kilobytes.

Run from the repository root (needs network access):

    uv run python scripts/make_media_fixtures.py

Stream URLs, and with them their ip/ei/sig/lsig/signature/key/expire parameters, are never
written anywhere. Re-run when YouTube changes its streams and review the diff before committing.
"""

from __future__ import annotations

import json
import struct
from datetime import date
from pathlib import Path
from typing import Any

from utmax.adapters.http import RetryingTransport, UrllibTransport
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.clients import ANDROID_VR
from utmax.transport import HttpRequest, Transport

VIDEO_ID = "dQw4w9WgXcQ"
ITAGS = (137, 140, 399)
FRAGMENTS = 2
HEAD_BYTES = 64 * 1024
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "media"


def fetch(transport: Transport, url: str, start: int, length: int) -> bytes:
    headers = {"Range": f"bytes={start}-{start + length - 1}", "User-Agent": ANDROID_VR.user_agent}
    response = transport.send(HttpRequest("GET", url, headers))
    if response.status not in (200, 206):
        raise SystemExit(f"a stream request failed with HTTP {response.status}")
    return response.body[:length]


def children(data: bytes) -> list[tuple[str, bytes]]:
    found: list[tuple[str, bytes]] = []
    offset = 0
    while offset + 8 <= len(data):
        size, kind = struct.unpack_from(">I4s", data, offset)
        header = 8
        if size == 1:
            (size,) = struct.unpack_from(">Q", data, offset + 8)
            header = 16
        found.append((kind.decode("latin-1"), data[offset + header : offset + size]))
        offset += size
    return found


def child(data: bytes, *path: str) -> bytes:
    for name in path:
        data = next(body for kind, body in children(data) if kind == name)
    return data


def sidx_references(sidx: bytes) -> tuple[int, list[int]]:
    version = sidx[0]
    (timescale,) = struct.unpack_from(">I", sidx, 8)
    position = 12 + (8 if version == 0 else 16)
    (count,) = struct.unpack_from(">H", sidx, position + 2)
    sizes = [
        struct.unpack_from(">I", sidx, position + 4 + 12 * index)[0] & 0x7FFF_FFFF
        for index in range(count)
    ]
    return timescale, sizes


def fragment_facts(moof: bytes) -> dict[str, Any]:
    traf = child(moof, "traf")
    tfhd, tfdt, trun = child(traf, "tfhd"), child(traf, "tfdt"), child(traf, "trun")
    trun_flags = int.from_bytes(trun[1:4], "big")
    if not trun_flags & 0x200:
        raise SystemExit("YouTube's trun boxes no longer list sample sizes; update this script")
    (count,) = struct.unpack_from(">I", trun, 4)
    start = 8 + (4 if trun_flags & 0x1 else 0) + (4 if trun_flags & 0x4 else 0)
    width = sum(4 for bit in (0x100, 0x200, 0x400, 0x800) if trun_flags & bit)
    size_column = 4 if trun_flags & 0x100 else 0
    sizes = [
        struct.unpack_from(">I", trun, start + index * width + size_column)[0]
        for index in range(count)
    ]
    return {
        "tfhd_flags": int.from_bytes(tfhd[1:4], "big"),
        "tfdt_version": tfdt[0],
        "trun_version": trun[0],
        "trun_flags": trun_flags,
        "samples": count,
        "sample_bytes": sum(sizes),
    }


def record(transport: Transport, fmt: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    url = fmt["url"]
    init_start, init_end = int(fmt["initRange"]["start"]), int(fmt["initRange"]["end"])
    index_start, index_end = int(fmt["indexRange"]["start"]), int(fmt["indexRange"]["end"])
    init = fetch(transport, url, init_start, init_end - init_start + 1)
    index = fetch(transport, url, index_start, index_end - index_start + 1)
    sidx = child(index, "sidx")
    timescale, sizes = sidx_references(sidx)
    hollow = bytearray(init + index)
    position = index_end + 1
    fragments: list[dict[str, Any]] = []
    for size in sizes[:FRAGMENTS]:
        head = fetch(transport, url, position, min(size, HEAD_BYTES))
        (moof_size,) = struct.unpack_from(">I", head, 0)
        mdat_size, mdat_kind = struct.unpack_from(">I4s", head, moof_size)
        if head[4:8] != b"moof" or mdat_kind != b"mdat" or moof_size + mdat_size != size:
            raise SystemExit("a fragment is not one moof followed by one mdat")
        facts = fragment_facts(head[8:moof_size])
        if facts["sample_bytes"] != mdat_size - 8:
            raise SystemExit("the trun sample sizes do not add up to the mdat size")
        hollow += head[: moof_size + 8]
        fragments.append({**facts, "size": size, "mdat_payload": mdat_size - 8})
        position += size
    trak = child(init, "moov", "trak")
    edits = next((body for kind, body in children(trak) if kind == "edts"), None)
    media_time = None
    if edits is not None:
        elst = child(edits, "elst")
        (media_time,) = struct.unpack_from(">q" if elst[0] == 1 else ">i", elst, 12 + 4 * elst[0])
    facts = {
        "file": f"{VIDEO_ID}_{fmt['itag']}.hollow.bin",
        "mime_type": fmt["mimeType"],
        "content_length": int(fmt["contentLength"]),
        "timescale": timescale,
        "sidx_references": len(sizes),
        "elst_media_time": media_time,
        "virtual_size": position,
        "fragments": fragments,
    }
    return bytes(hollow), facts


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    transport = RetryingTransport(UrllibTransport(timeout=30.0))
    player = InnerTubeClient(transport).player_json(ANDROID_VR, VIDEO_ID)
    formats = {
        fmt.get("itag"): fmt for fmt in player.get("streamingData", {}).get("adaptiveFormats", [])
    }
    manifest: dict[str, Any] = {
        "video_id": VIDEO_ID,
        "recorded": date.today().isoformat(),
        "client": ANDROID_VR.name,
        "streams": {},
    }
    for itag in ITAGS:
        if itag not in formats or "url" not in formats[itag]:
            raise SystemExit(f"itag {itag} is not offered with a direct URL; try again later")
        hollow, facts = record(transport, formats[itag])
        (OUT / facts["file"]).write_bytes(hollow)
        manifest["streams"][str(itag)] = facts
        print(f"wrote {facts['file']} ({len(hollow)} bytes standing for {facts['virtual_size']})")
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    (OUT / "README.md").write_text(
        "# Hollow media fixtures\n\n"
        f"Recorded {manifest['recorded']} from video `{VIDEO_ID}` (itags "
        f"{', '.join(map(str, ITAGS))}, first {FRAGMENTS} fragments) with\n"
        "`uv run python scripts/make_media_fixtures.py`. Each `.hollow.bin` file holds the real\n"
        "`ftyp`, `moov`, `sidx` and `moof` boxes and every `mdat` header, without payloads;\n"
        "`tests/helpers/hollow_source.py` replays them with zero-filled payloads. No stream URL\n"
        "or URL parameter is stored. `manifest.json` lists facts read independently of utmax.\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Record the fixtures and inspect them**

Run (needs network access): `uv run python scripts/make_media_fixtures.py`
Expected: three lines like `wrote dQw4w9WgXcQ_137.hollow.bin (4550 bytes standing for 2974911)` (on 2026-09-27: 137 → 4550/2 974 911, 140 → 4667/324 634, 399 → 3468/1 204 720; small differences are fine if YouTube re-encoded the video). Then check `git status --short tests/fixtures/media` (five new files, each `.hollow.bin` under 10 KB) and open `manifest.json`: no URL, `"client": "ANDROID_VR"`, two fragments per itag. If YouTube answers "not a bot"/HTTP 403, try again later or from another network — never commit a partial recording.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/media/test_hollow.py -q`
Expected: `8 passed`. If `test_the_recording_shows_the_stream_layout_the_spec_describes` fails, YouTube changed the stream layout of spec §2 (flags or the 512 edit): stop and report the new values to the user instead of editing the expectations.

- [ ] **Step 7: Gates and full suite**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected: clean gates (30 source files), `494 passed, 6 deselected`.

- [ ] **Step 8: Commit**

`git` stores the `.hollow.bin` files as binary through the existing `*.bin binary` rule (check that `git diff --cached --stat` shows `Bin`).

```bash
git add scripts/make_media_fixtures.py tests/helpers/hollow_source.py tests/unit/media/test_hollow.py tests/fixtures/media/README.md tests/fixtures/media/manifest.json tests/fixtures/media/dQw4w9WgXcQ_137.hollow.bin tests/fixtures/media/dQw4w9WgXcQ_140.hollow.bin tests/fixtures/media/dQw4w9WgXcQ_399.hollow.bin
git commit -m "test: record hollow YouTube stream fixtures for the muxer

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Sample tables, chunks and edit lists

**Files:**
- Create: `src/utmax/core/media/tables.py`
- Test: `tests/unit/media/test_tables.py`

**Interfaces:**
- Consumes: `box`, `full_box`, `i32`, `i64`, `u32`, `u64`, `I32_MAX` (Task 1); `Edit` (Task 3).
- Produces (in `utmax.core.media.tables`, all returning complete boxes):
  - `run_lengths(values) -> list[tuple[int, int]]` — `(count, value)` runs.
  - `stts_box(durations) -> bytes`; `ctts_box(offsets) -> bytes | None` (`None` when all zero, version 1 exactly when one is negative); `stss_box(sync: bytes | bytearray) -> bytes | None` (`None` when all are sync); `stsz_box(sizes) -> bytes`; `stsc_box(chunks: Sequence[tuple[int, int]]) -> bytes` (`(samples in chunk, description)` per chunk); `chunk_offsets_box(offsets, *, wide: bool) -> bytes` (`co64` when `wide`, else `stco`).
  - `chunk_ranges(dts, descriptions, *, span: int) -> list[tuple[int, int]]` — `(first sample, count)`; a chunk ends before the first sample `span` ticks or more after its first sample, or where the description changes.
  - `edts_box(edits) -> bytes` — `elst` version 1 only when a value reaches `I32_MAX`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/media/test_tables.py`:

```python
"""Tests for sample tables, chunking and edit lists."""

from __future__ import annotations

from utmax.core.media.boxes import box, full_box, i32, i64, u32, u64
from utmax.core.media.fmp4 import Edit
from utmax.core.media.tables import (
    chunk_offsets_box,
    chunk_ranges,
    ctts_box,
    edts_box,
    run_lengths,
    stsc_box,
    stss_box,
    stsz_box,
    stts_box,
)


def test_run_lengths() -> None:
    assert run_lengths([]) == []
    assert run_lengths([5, 5, 7, 5]) == [(2, 5), (1, 7), (1, 5)]


def test_stts_is_run_length_encoded() -> None:
    assert stts_box([512, 512, 512, 1024]) == full_box(
        "stts", 0, 0, u32(2), u32(3), u32(512), u32(1), u32(1024)
    )


def test_ctts_is_omitted_unsigned_or_signed_as_needed() -> None:
    assert ctts_box([0, 0, 0]) is None
    assert ctts_box([512, 512, 0]) == full_box(
        "ctts", 0, 0, u32(2), u32(2), u32(512), u32(1), u32(0)
    )
    assert ctts_box([1024, -512]) == full_box(
        "ctts", 1, 0, u32(2), u32(1), i32(1024), u32(1), i32(-512)
    )


def test_stss_lists_sync_samples_only_when_some_are_not() -> None:
    assert stss_box(bytearray([1, 1, 1])) is None
    assert stss_box(bytearray([1, 0, 0, 1])) == full_box("stss", 0, 0, u32(2), u32(1), u32(4))


def test_stsz_shares_one_size_when_all_are_equal() -> None:
    assert stsz_box([6, 6, 6]) == full_box("stsz", 0, 0, u32(6), u32(3))
    assert stsz_box([6, 7]) == full_box("stsz", 0, 0, u32(0), u32(2), u32(6), u32(7))
    assert stsz_box([]) == full_box("stsz", 0, 0, u32(0), u32(0))


def test_stsc_starts_an_entry_whenever_count_or_description_changes() -> None:
    chunks = [(10, 1), (10, 1), (4, 1), (4, 2), (4, 2)]
    assert stsc_box(chunks) == full_box(
        "stsc",
        0,
        0,
        u32(3),
        u32(1) + u32(10) + u32(1),
        u32(3) + u32(4) + u32(1),
        u32(4) + u32(4) + u32(2),
    )


def test_chunk_offsets_use_co64_only_when_asked() -> None:
    assert chunk_offsets_box([48, 1000], wide=False) == full_box(
        "stco", 0, 0, u32(2), u32(48), u32(1000)
    )
    assert chunk_offsets_box([48, 2**32], wide=True) == full_box(
        "co64", 0, 0, u32(2), u64(48), u64(2**32)
    )


def test_chunks_span_less_than_the_limit_and_split_on_new_descriptions() -> None:
    dts = [0, 400, 800, 1200, 1600, 2000, 2400]
    assert chunk_ranges(dts, [1] * 7, span=1000) == [(0, 3), (3, 3), (6, 1)]
    assert chunk_ranges(dts, [1, 1, 2, 2, 2, 2, 2], span=1000) == [(0, 2), (2, 3), (5, 2)]
    assert chunk_ranges([], [], span=1000) == []


def test_edit_lists_use_64_bit_fields_only_when_needed() -> None:
    entries = [u32(500) + i32(-1) + u32(0x10000), u32(1000) + i32(512) + u32(0x10000)]
    assert edts_box([Edit(500, -1), Edit(1000, 512)]) == box(
        "edts", full_box("elst", 0, 0, u32(2), *entries)
    )
    wide = u64(2**31) + i64(5) + u32(0x8000)
    assert edts_box([Edit(2**31, 5, 0x8000)]) == box("edts", full_box("elst", 1, 0, u32(1), wide))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/media/test_tables.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'utmax.core.media.tables'`.

- [ ] **Step 3: Implement `tables.py`**

`src/utmax/core/media/tables.py`:

```python
"""Sample tables (``stbl`` children), chunking and edit lists for progressive MP4/MOV files.

Box layouts follow ISO/IEC 14496-12 (section 8.6 and 8.7); the writing conventions (run-length
``stts``/``ctts``/``stsc``, ``stss`` only when some samples are not sync samples, ``co64``
only when an offset needs it) match FFmpeg's ``libavformat/movenc.c``.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable, Sequence

from utmax.core.media.boxes import I32_MAX, box, full_box, i32, i64, u32, u64
from utmax.core.media.fmp4 import Edit

__all__ = [
    "chunk_offsets_box",
    "chunk_ranges",
    "ctts_box",
    "edts_box",
    "run_lengths",
    "stsc_box",
    "stss_box",
    "stsz_box",
    "stts_box",
]


def run_lengths(values: Iterable[int]) -> list[tuple[int, int]]:
    """``(count, value)`` pairs for consecutive equal values: ``[5, 5, 7]`` -> ``[(2, 5), (1, 7)]``."""
    runs: list[tuple[int, int]] = []
    for value in values:
        if runs and runs[-1][1] == value:
            runs[-1] = (runs[-1][0] + 1, value)
        else:
            runs.append((1, value))
    return runs


def stts_box(durations: Sequence[int]) -> bytes:
    """Decoding time to sample: run-length encoded sample durations."""
    runs = run_lengths(durations)
    return full_box(
        "stts", 0, 0, u32(len(runs)), *(u32(count) + u32(value) for count, value in runs)
    )


def ctts_box(offsets: Sequence[int]) -> bytes | None:
    """Composition offsets, or ``None`` when every offset is zero.

    Version 1 (signed offsets) is used exactly when an offset is negative.
    """
    if not any(offsets):
        return None
    signed = min(offsets) < 0
    pack = i32 if signed else u32
    runs = run_lengths(offsets)
    return full_box(
        "ctts",
        1 if signed else 0,
        0,
        u32(len(runs)),
        *(u32(count) + pack(value) for count, value in runs),
    )


def stss_box(sync: bytes | bytearray) -> bytes | None:
    """1-based numbers of the sync samples, or ``None`` when every sample is a sync sample."""
    if all(sync):
        return None
    numbers = [index + 1 for index, flag in enumerate(sync) if flag]
    return full_box("stss", 0, 0, u32(len(numbers)), struct.pack(f">{len(numbers)}I", *numbers))


def stsz_box(sizes: Sequence[int]) -> bytes:
    """Sample sizes: one shared size when all are equal, else one entry per sample."""
    if sizes and all(size == sizes[0] for size in sizes):
        return full_box("stsz", 0, 0, u32(sizes[0]), u32(len(sizes)))
    return full_box("stsz", 0, 0, u32(0), u32(len(sizes)), struct.pack(f">{len(sizes)}I", *sizes))


def stsc_box(chunks: Sequence[tuple[int, int]]) -> bytes:
    """Sample to chunk from ``(samples in chunk, sample description index)`` per chunk."""
    entries: list[bytes] = []
    previous: tuple[int, int] | None = None
    for number, chunk in enumerate(chunks, start=1):
        if chunk != previous:
            entries.append(u32(number) + u32(chunk[0]) + u32(chunk[1]))
            previous = chunk
    return full_box("stsc", 0, 0, u32(len(entries)), *entries)


def chunk_offsets_box(offsets: Sequence[int], *, wide: bool) -> bytes:
    """``co64`` (64-bit offsets) when ``wide``, else ``stco``."""
    if wide:
        return full_box("co64", 0, 0, u32(len(offsets)), struct.pack(f">{len(offsets)}Q", *offsets))
    return full_box("stco", 0, 0, u32(len(offsets)), struct.pack(f">{len(offsets)}I", *offsets))


def chunk_ranges(
    dts: Sequence[int], descriptions: Sequence[int], *, span: int
) -> list[tuple[int, int]]:
    """Group samples into chunks as ``(first sample, count)`` pairs.

    A chunk ends before the first sample whose decode time is ``span`` ticks or more after the
    chunk's first sample, and wherever the sample description changes.
    """
    chunks: list[tuple[int, int]] = []
    first = 0
    for index in range(1, len(dts)):
        if dts[index] - dts[first] >= span or descriptions[index] != descriptions[first]:
            chunks.append((first, index - first))
            first = index
    if dts:
        chunks.append((first, len(dts) - first))
    return chunks


def edts_box(edits: Sequence[Edit]) -> bytes:
    """An ``edts`` box holding one ``elst``; version 1 (64-bit fields) only when needed."""
    wide = any(edit.duration >= I32_MAX or edit.media_time >= I32_MAX for edit in edits)
    entries = [_edit_entry(edit, wide=wide) for edit in edits]
    return box("edts", full_box("elst", 1 if wide else 0, 0, u32(len(entries)), *entries))


def _edit_entry(edit: Edit, *, wide: bool) -> bytes:
    if wide:
        return u64(edit.duration) + i64(edit.media_time) + u32(edit.rate)
    return u32(edit.duration) + i32(edit.media_time) + u32(edit.rate)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/media/test_tables.py -q`
Expected: `9 passed`.

- [ ] **Step 5: Gates and full suite**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected: clean gates (31 source files), `503 passed, 6 deselected`.

- [ ] **Step 6: Commit**

```bash
git add src/utmax/core/media/tables.py tests/unit/media/test_tables.py
git commit -m "feat: write MP4 sample tables, chunk maps and edit lists

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: tx3g subtitle tracks

**Files:**
- Create: `src/utmax/core/media/tx3g.py`
- Test: `tests/unit/media/test_tx3g.py`

**Interfaces:**
- Consumes: `english_name`, `iso639_2t` (`utmax.core.languages`, shared prep); `box`, `u8`, `u16`, `u32` (Task 1); `InvalidOption`, `MuxError`; `Segment`, `Transcript` (`utmax.models`); tests also use `utmax.core.formats.to_srt` (read-only — M3 does not edit `formats.py`) and `tests.helpers.builders.make_transcript`.
- Produces (in `utmax.core.media.tx3g`):
  - `TIMESCALE = 1000`; `Cue(start: int, end: int, text: str)` in milliseconds.
  - `SubtitleTrack(code: str, name: str, language: str, tag: str, samples: tuple[tuple[int, bytes], ...])` — `language` is the ISO 639-2/T code for `mdhd`, `tag` the BCP 47 tag for `elng`, `samples` are `(duration_ms, payload)`.
  - `normalize_cues(segments) -> tuple[Cue, ...]` — the same cues `utmax.core.formats.to_srt` prints (blank segments skipped, lines whitespace-collapsed, sorted, same-start cues merged, each cue cut at the next start, zero-length cues dropped). It re-implements `formats._cues` because M3 must not touch `formats.py`; `test_cues_are_timed_exactly_like_the_srt_sidecar` keeps the two identical.
  - `encode_sample(text) -> bytes`, `decode_sample(payload) -> str`, `sample_entry() -> bytes` (69 bytes).
  - `track_name(transcript) -> str`, `track_languages(code) -> tuple[str, str]`.
  - `subtitle_track(transcript, *, limit: int | None = None) -> SubtitleTrack` — gaps become empty samples from time 0; `limit` (ms) drops later cues and cuts crossing ones; no cues → one empty sample of `max(limit or 0, 1)` ms; `<b>`/`<i>`/`<u>` tags removed.
  - `default_subtitle_index(codes, default) -> int | None` — `None` without subtitles, else the index of `default` (case-insensitive, surrounding spaces ignored) or 0; unknown → `InvalidOption` listing the embedded codes.

- [ ] **Step 1: Write the failing tests**

`tests/unit/media/test_tx3g.py`:

```python
"""Tests for tx3g subtitle tracks."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from tests.helpers.builders import make_transcript
from utmax.core.formats import to_srt
from utmax.core.media.tx3g import (
    Cue,
    decode_sample,
    default_subtitle_index,
    encode_sample,
    normalize_cues,
    sample_entry,
    subtitle_track,
    track_languages,
    track_name,
)
from utmax.errors import InvalidOption, MuxError
from utmax.models import Segment

MESSY = (
    Segment(5.0, 1.0, "late"),
    Segment(0.0, 5.0, "  first \n  line  "),
    Segment(3.0, 2.0, "overlaps the first"),
    Segment(4.0, 0.0, "zero length"),
    Segment(6.5, 1.0, "   "),
    Segment(8.0, 2.0, "SPEAKER A: hi"),
    Segment(8.0, 1.0, "SPEAKER B: hello"),
    Segment(12.0004, 1.0006, "rounded"),
)
TURKISH = "T\xfcrk\xe7e \U0000011f\xfc\U0000015f\U00000131\xf6\xe7"
JAPANESE = "\U000065e5\U0000672c\U00008a9e"
EMOJI_AND_NOTE = "\U0001f600 \U0000266a"


def srt_cues(srt: str) -> list[Cue]:
    cues: list[Cue] = []
    for block in srt.strip().split("\n\n"):
        lines = block.split("\n")
        start, end = (
            int(h) * 3_600_000 + int(m) * 60_000 + int(s) * 1000 + int(ms)
            for h, m, s, ms in re.findall(r"(\d+):(\d+):(\d+),(\d+)", lines[1])
        )
        cues.append(Cue(start, end, "\n".join(lines[2:])))
    return cues


def test_cues_are_timed_exactly_like_the_srt_sidecar() -> None:
    assert list(normalize_cues(MESSY)) == srt_cues(to_srt(MESSY))
    assert normalize_cues(MESSY)[0] == Cue(0, 3000, "first\nline")


@pytest.mark.parametrize("text", ["", "hello", "two\nlines", TURKISH, JAPANESE, EMOJI_AND_NOTE])
def test_samples_round_trip(text: str) -> None:
    sample = encode_sample(text)
    assert int.from_bytes(sample[:2], "big") == len(text.encode("utf-8"))
    assert decode_sample(sample) == text


def test_overlong_text_is_cut_at_a_character_boundary() -> None:
    sample = encode_sample("\U0000011f" * 40_000)  # 80 000 UTF-8 bytes
    assert int.from_bytes(sample[:2], "big") == 65_534
    assert decode_sample(sample) == "\U0000011f" * 32_767


@pytest.mark.parametrize("payload", [b"", b"\x00", b"\x00\x05abc"])
def test_short_samples_are_rejected(payload: bytes) -> None:
    with pytest.raises(MuxError, match="shorter than its length"):
        decode_sample(payload)


def test_sample_entry_is_ffmpegs_mov_text_default_with_a_sans_serif_font() -> None:
    header = bytes.fromhex("00000045") + b"tx3g" + bytes(6) + bytes.fromhex("0001")
    display = bytes.fromhex("00000000")  # display flags
    justification = bytes.fromhex("01ff")  # centred horizontally, at the bottom
    background = bytes(4)  # transparent
    text_box = bytes(8)  # top, left, bottom, right
    style = bytes.fromhex("0000000000010012ffffffff")  # chars 0-0, font 1, regular, 18 pt, white
    fonts = bytes.fromhex("00000017") + b"ftab" + bytes.fromhex("0001" + "0001" + "0a")
    expected = header + display + justification + background + text_box + style + fonts
    assert sample_entry() == expected + b"Sans-Serif"


def test_track_names() -> None:
    manual = make_transcript(language_code="en", language="English")
    assert track_name(manual) == "English"
    auto = make_transcript(language="English (auto-generated)", is_generated=True)
    assert track_name(auto) == "English (auto-generated)"
    translated = make_transcript(language_code="tr", language="Turkish")
    ai = replace(translated, translated_from="en", translator="claude=claude-opus-5")
    assert track_name(ai) == "Turkish (AI: claude=claude-opus-5)"
    assert track_name(make_transcript(language_code="tr", language="")) == "Turkish"
    assert track_name(make_transcript(language_code="xx", language=" ")) == "xx"
    both = make_transcript(language_code="en+tr", language="English + Turkish")
    assert track_name(replace(both, translator="claude=claude-opus-5")) == "English + Turkish"
    assert track_name(make_transcript(language_code="en+tr", language="")) == "English + Turkish"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("tr", ("tur", "tr")),
        ("pt-BR", ("por", "pt-BR")),
        ("zh_Hant", ("zho", "zh-Hant")),
        ("es-419", ("spa", "es-419")),
        ("en+tr", ("mul", "mul")),
        ("xx", ("und", "xx")),
        ("not a code", ("und", "und")),
    ],
)
def test_track_languages(code: str, expected: tuple[str, str]) -> None:
    assert track_languages(code) == expected


def texts(samples: tuple[tuple[int, bytes], ...]) -> list[tuple[int, str]]:
    return [(duration, decode_sample(payload)) for duration, payload in samples]


def test_gaps_become_empty_samples_from_time_zero() -> None:
    track = subtitle_track(make_transcript(Segment(1.0, 1.0, "a"), Segment(3.0, 0.5, "b")))
    assert texts(track.samples) == [(1000, ""), (1000, "a"), (1000, ""), (500, "b")]


def test_a_cue_at_zero_needs_no_leading_empty_sample() -> None:
    track = subtitle_track(make_transcript(Segment(0.0, 1.0, "a")))
    assert texts(track.samples) == [(1000, "a")]


def test_a_limit_drops_and_cuts_cues_past_the_end() -> None:
    transcript = make_transcript(
        Segment(0.0, 1.0, "a"), Segment(1.5, 2.0, "b"), Segment(4.0, 1.0, "c")
    )
    track = subtitle_track(transcript, limit=2500)
    assert texts(track.samples) == [(1000, "a"), (500, ""), (1000, "b")]


def test_transcripts_without_cues_still_make_a_track() -> None:
    assert subtitle_track(make_transcript(), limit=4000).samples == ((4000, b"\x00\x00"),)
    assert subtitle_track(make_transcript(Segment(0, 1, "  "))).samples == ((1, b"\x00\x00"),)


def test_formatting_tags_are_removed() -> None:
    text = "<i>soft</i> <b>loud</b> <u>x</u> <font>kept</font>"
    track = subtitle_track(make_transcript(Segment(0.0, 1.0, text)))
    assert decode_sample(track.samples[0][1]) == "soft loud x <font>kept</font>"


def test_subtitle_track_labels() -> None:
    transcript = make_transcript(Segment(0, 1, "merhaba"), language_code="tr", language="Turkish")
    track = subtitle_track(replace(transcript, translator="openai=gpt-5"))
    assert (track.code, track.name, track.language, track.tag) == (
        "tr",
        "Turkish (AI: openai=gpt-5)",
        "tur",
        "tr",
    )


def test_default_subtitle_index() -> None:
    assert default_subtitle_index([], None) is None
    assert default_subtitle_index(["en", "tr"], None) == 0
    assert default_subtitle_index(["en", "tr", "en+tr"], "EN+TR") == 2
    assert default_subtitle_index(["en", "tr"], " tr ") == 1


@pytest.mark.parametrize(("codes", "listed"), [(["en", "tr"], "en, tr"), ([], "none")])
def test_an_unknown_default_subtitle_is_an_invalid_option(codes: list[str], listed: str) -> None:
    with pytest.raises(InvalidOption, match=rf"no embedded subtitle track \(embedded: {listed}\)"):
        default_subtitle_index(codes, "de")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/media/test_tx3g.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'utmax.core.media.tx3g'`.

- [ ] **Step 3: Implement `tx3g.py`**

`src/utmax/core/media/tx3g.py`:

```python
"""3GPP timed text (``tx3g``) subtitle tracks, the format FFmpeg calls ``mov_text``.

A sample is a 16-bit big-endian byte length followed by UTF-8 text (``"\\n"`` between lines).
Samples cover the timeline without holes: the time between cues is an empty sample. The
sample description is FFmpeg's ``mov_text`` default (libavcodec/movtextenc.c): centred at the
bottom, transparent background, font 1 at 18 points in opaque white; its font table names
"Sans-Serif" (FFmpeg's own default name is "Serif").
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from utmax.core.languages import english_name, iso639_2t
from utmax.core.media.boxes import box, u8, u16, u32
from utmax.errors import InvalidOption, MuxError
from utmax.models import Segment, Transcript

__all__ = [
    "TIMESCALE",
    "Cue",
    "SubtitleTrack",
    "decode_sample",
    "default_subtitle_index",
    "encode_sample",
    "normalize_cues",
    "sample_entry",
    "subtitle_track",
    "track_languages",
    "track_name",
]

TIMESCALE = 1000
_MAX_TEXT_BYTES = 0xFFFF
_FONT = b"Sans-Serif"
_FORMATTING_TAG = re.compile(r"</?[biu]>")
_LANGUAGE_TAG = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*")


@dataclass(frozen=True, slots=True)
class Cue:
    """One subtitle shown from ``start`` to ``end`` (milliseconds)."""

    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class SubtitleTrack:
    """A tx3g track ready to mux: labels plus ``(duration_ms, payload)`` samples."""

    code: str
    name: str
    language: str
    tag: str
    samples: tuple[tuple[int, bytes], ...]


def normalize_cues(segments: Sequence[Segment]) -> tuple[Cue, ...]:
    """Millisecond cues timed exactly like the SRT and WebVTT output of ``utmax.core.formats``.

    Blank segments are skipped and each line is whitespace-collapsed; cues are sorted by start,
    cues that start together are merged, every cue ends no later than the next one starts,
    and cues left without duration are dropped.
    """
    timed: list[tuple[int, int, str]] = []
    for segment in segments:
        lines = [" ".join(line.split()) for line in segment.text.splitlines() if line.strip()]
        if lines:
            start = round(segment.start * 1000)
            timed.append((start, start + round(segment.duration * 1000), "\n".join(lines)))
    timed.sort(key=lambda cue: cue[0])
    merged: list[tuple[int, int, str]] = []
    for start, end, text in timed:
        if merged and merged[-1][0] == start:
            merged[-1] = (start, max(merged[-1][1], end), f"{merged[-1][2]}\n{text}")
        else:
            merged.append((start, end, text))
    cues: list[Cue] = []
    for index, (start, end, text) in enumerate(merged):
        stop = min(end, merged[index + 1][0]) if index + 1 < len(merged) else end
        if stop > start:
            cues.append(Cue(start, stop, text))
    return tuple(cues)


def encode_sample(text: str) -> bytes:
    """A tx3g sample: 16-bit length plus UTF-8 text, cut at a character boundary at 64 KiB."""
    data = text.encode("utf-8")
    if len(data) > _MAX_TEXT_BYTES:
        data = data[:_MAX_TEXT_BYTES].decode("utf-8", errors="ignore").encode("utf-8")
    return u16(len(data)) + data


def decode_sample(payload: bytes) -> str:
    """The text of a tx3g sample (the inverse of :func:`encode_sample`)."""
    if len(payload) < 2 or len(payload) < 2 + int.from_bytes(payload[:2], "big"):
        raise MuxError("A tx3g sample is shorter than its length field says.")
    return payload[2 : 2 + int.from_bytes(payload[:2], "big")].decode("utf-8", errors="replace")


def sample_entry() -> bytes:
    """The ``tx3g`` sample description (FFmpeg's ``mov_text`` default, font "Sans-Serif")."""
    font_table = box("ftab", u16(1), u16(1), u8(len(_FONT)), _FONT)
    return box(
        "tx3g",
        bytes(6),  # reserved
        u16(1),  # data reference index
        u32(0),  # display flags
        b"\x01\xff",  # justification: horizontally centred, vertically at the bottom
        bytes(4),  # background colour (RGBA): transparent
        bytes(8),  # default text box: top, left, bottom, right
        u16(0) + u16(0),  # style record: first and last character
        u16(1) + u8(0) + u8(18),  # font ID 1, regular face, 18 points
        b"\xff\xff\xff\xff",  # text colour (RGBA): opaque white
        font_table,
    )


def track_name(transcript: Transcript) -> str:
    """The track title players show, e.g. ``"Turkish (AI: claude=...)"`` or ``"English + Turkish"``."""
    label = transcript.language.strip() or " + ".join(
        english_name(part) or part for part in transcript.language_code.split("+")
    )
    if transcript.translator and not transcript.is_bilingual:
        return f"{label} (AI: {transcript.translator})"
    return label


def track_languages(code: str) -> tuple[str, str]:
    """``(ISO 639-2/T code for mdhd, BCP-47 tag for elng)``; bilingual codes become ``mul``."""
    if "+" in code:
        return "mul", "mul"
    tag = code.strip().replace("_", "-")
    return iso639_2t(tag), (tag if _LANGUAGE_TAG.fullmatch(tag) else "und")


def subtitle_track(transcript: Transcript, *, limit: int | None = None) -> SubtitleTrack:
    """The tx3g track of ``transcript``; with ``limit`` (ms) no cue runs past it.

    ``<b>``/``<i>``/``<u>`` tags are removed. A transcript without cues becomes one empty sample
    lasting ``limit`` (at least 1 ms), so the requested track still exists.
    """
    cues = normalize_cues(transcript.segments)
    if limit is not None:
        cues = tuple(Cue(c.start, min(c.end, limit), c.text) for c in cues if c.start < limit)
    timeline: list[tuple[int, str]] = []
    position = 0
    for cue in cues:
        if cue.start > position:
            timeline.append((cue.start - position, ""))
        timeline.append((cue.end - cue.start, _FORMATTING_TAG.sub("", cue.text)))
        position = cue.end
    if not timeline:
        timeline.append((max(limit or 0, 1), ""))
    language, tag = track_languages(transcript.language_code)
    return SubtitleTrack(
        code=transcript.language_code,
        name=track_name(transcript),
        language=language,
        tag=tag,
        samples=tuple((duration, encode_sample(text)) for duration, text in timeline),
    )


def default_subtitle_index(codes: Sequence[str], default: str | None) -> int | None:
    """The embedded subtitle track enabled by default: the one whose code is ``default``
    (case-insensitive), else the first; ``None`` when there are no subtitle tracks.

    Raises:
        InvalidOption: ``default`` matches none of ``codes``.
    """
    if default is None:
        return 0 if codes else None
    wanted = default.strip().lower()
    for index, code in enumerate(codes):
        if code.lower() == wanted:
            return index
    raise InvalidOption(
        f"default_subtitle={default!r} matches no embedded subtitle track "
        f"(embedded: {', '.join(codes) or 'none'}).",
        suggestion="Pass the language code of one of the subtitles being embedded, or None.",
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/media/test_tx3g.py -q`
Expected: `29 passed`.

- [ ] **Step 5: Gates and full suite**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected: clean gates (32 source files), `532 passed, 6 deselected`.

- [ ] **Step 6: Commit**

```bash
git add src/utmax/core/media/tx3g.py tests/unit/media/test_tx3g.py
git commit -m "feat: build tx3g subtitle tracks from transcripts

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: `ftyp` and `moov` boxes for mp4, mov and m4a

**Files:**
- Create: `src/utmax/core/media/moov.py`
- Test: `tests/unit/media/test_moov.py`

**Interfaces:**
- Consumes: `mac_language_code` (shared prep); `I32_MAX`, `Reader`, `box`, `find_child`, `full_box`, `i16`, `u8`, `u16`, `u32`, `u64` (Task 1); `Edit` (Task 3); every box function of Task 5; `MuxError`. Tests also use `tx3g.sample_entry` (Task 6) and the factory's `sample_entry`/`ESDS`.
- Produces (in `utmax.core.media.moov`):
  - `Flavor = Literal["mp4", "mov", "m4a"]`, `TrackKind = Literal["video", "audio", "subtitle"]`, `MOVIE_TIMESCALE = 1000`, `UNITY_MATRIX` (36 bytes).
  - `TrackPlan(track_id, kind, timescale, language, tag, name, enabled, matrix, width, height, edits, duration, media_duration, sample_entries, durations, ctos, sync, sizes, chunks)` — everything one `trak` needs except chunk offsets: `language` is an ISO 639-2/T code, `tag` a BCP 47 tag for `elng` (subtitles) or `None`, `name` the track title (subtitles) or `None`, `duration` in movie ticks (`tkhd`), `media_duration` in media ticks (`mdhd`), `chunks` are `(samples in chunk, description)` pairs.
  - `ftyp_box(flavor, codecs: Collection[str]) -> bytes`.
  - `moov_box(flavor, tracks, offsets: Sequence[Sequence[int]], wide: Sequence[bool]) -> bytes` — `offsets` are absolute chunk offsets per track, `wide[i]` selects `co64` for track `i`.
  - `pack_language(code) -> int` (bad codes → `und`), `unpack_language(value) -> str` (QuickTime codes below 0x400 → `und`).
  - `quicktime_sound_entry(entry, *, samples_per_packet) -> bytes` — ISO `mp4a` → SoundDescription version 1 with `wave`; accepts version 0 and 1 inputs; `MuxError` for more than two channels, a rate above 65535 Hz (`srat` box or a zero rate field), a missing `esds` or a version 2 input.
- Flavor rules: MP4/M4A `hdlr` C string, ISO language; MOV Pascal `hdlr`, `dhlr` in `minf`, QuickTime language code when `mac_language_code` has one (else the packed ISO code), and version 1 headers are refused ("too long for a QuickTime .mov file").

- [ ] **Step 1: Write the failing tests**

`tests/unit/media/test_moov.py`:

```python
"""Tests for the ftyp and moov builders and their MP4/MOV/M4A differences."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tests.helpers.fmp4_factory import ESDS, Track, sample_entry
from utmax.core.media.boxes import Reader, box, child_boxes, find_child, full_box, u16, u32
from utmax.core.media.fmp4 import Edit
from utmax.core.media.moov import (
    UNITY_MATRIX,
    Flavor,
    TrackPlan,
    ftyp_box,
    moov_box,
    pack_language,
    quicktime_sound_entry,
    unpack_language,
)
from utmax.core.media.tx3g import sample_entry as tx3g_entry
from utmax.errors import MuxError

VIDEO = TrackPlan(
    track_id=1,
    kind="video",
    timescale=12800,
    language="und",
    tag=None,
    name=None,
    enabled=True,
    matrix=UNITY_MATRIX,
    width=640 << 16,
    height=360 << 16,
    edits=(Edit(2000, 512),),
    duration=2000,
    media_duration=25600,
    sample_entries=(sample_entry(Track()),),
    durations=[512] * 50,
    ctos=[512] * 50,
    sync=bytes([1] + [0] * 49),
    sizes=[100] * 50,
    chunks=((25, 1), (25, 1)),
)
AUDIO = replace(
    VIDEO,
    track_id=2,
    kind="audio",
    timescale=44100,
    language="eng",
    matrix=UNITY_MATRIX,
    width=0,
    height=0,
    edits=(),
    duration=1998,
    media_duration=88064,
    sample_entries=(sample_entry(Track(handler="soun", codec="mp4a")),),
    durations=[1024] * 86,
    ctos=[0] * 86,
    sync=bytes([1] * 86),
    sizes=[300] * 86,
    chunks=((43, 1), (43, 1)),
)
SUBTITLE = replace(
    AUDIO,
    track_id=3,
    kind="subtitle",
    timescale=1000,
    language="tur",
    tag="tr",
    name="Turkish (AI: claude=claude-opus-5)",
    enabled=False,
    duration=1500,
    media_duration=1500,
    sample_entries=(tx3g_entry(),),
    durations=[500, 1000],
    ctos=[0, 0],
    sync=bytes([1, 1]),
    sizes=[2, 9],
    chunks=((2, 1),),
)
TRACKS = (VIDEO, AUDIO, SUBTITLE)


def moov_children(
    flavor: Flavor, tracks: tuple[TrackPlan, ...] = TRACKS
) -> list[tuple[str, bytes]]:
    offsets = [[1000 * (n + 1)] * len(track.chunks) for n, track in enumerate(tracks)]
    moov = moov_box(flavor, tracks, offsets, [False] * len(tracks))
    assert moov[4:8] == b"moov"
    return child_boxes(moov[8:], context="moov")


def trak(flavor: Flavor, number: int) -> bytes:
    traks = [body for kind, body in moov_children(flavor) if kind == "trak"]
    return traks[number]


def path(payload: bytes, *kinds: str) -> bytes:
    for kind in kinds:
        found = find_child(payload, kind, context=kind)
        assert found is not None, kind
        payload = found
    return payload


@pytest.mark.parametrize(
    ("flavor", "codecs", "expected"),
    [
        ("mp4", {"avc1", "mp4a"}, b"isom" + u32(0x200) + b"isomiso2avc1mp41"),
        ("mp4", {"av01", "mp4a"}, b"isom" + u32(0x200) + b"isomiso2av01mp41"),
        ("mp4", {"mp4a"}, b"isom" + u32(0x200) + b"isomiso2mp41"),
        ("mov", {"avc1", "mp4a"}, b"qt  " + u32(0x200) + b"qt  "),
        ("m4a", {"mp4a"}, b"M4A " + u32(0x200) + b"M4A isomiso2mp41"),
    ],
)
def test_ftyp_brands(flavor: Flavor, codecs: set[str], expected: bytes) -> None:
    assert ftyp_box(flavor, codecs) == box("ftyp", expected)


def test_languages_pack_into_15_bits() -> None:
    assert pack_language("und") == 0x55C4
    assert pack_language("eng") == 0x15C7
    assert pack_language("tur") == 0x52B2
    assert pack_language("EN") == 0x55C4
    assert pack_language("t1r") == 0x55C4
    assert unpack_language(0x52B2) == "tur"
    assert unpack_language(17) == "und"  # a QuickTime language code, not ISO


def test_movie_header() -> None:
    mvhd = Reader(dict(moov_children("mp4"))["mvhd"], "mvhd")
    assert (mvhd.u8(), mvhd.u24()) == (0, 0)
    mvhd.skip(8)
    assert (mvhd.u32(), mvhd.u32()) == (1000, 2000)  # timescale, longest track
    mvhd.skip(4 + 2 + 10 + 36 + 24)
    assert mvhd.u32() == 4  # next track ID


def tkhd_fields(payload: bytes) -> tuple[int, int, int, int, int, int]:
    reader = Reader(path(payload, "tkhd"), "tkhd")
    reader.skip(1)
    flags = reader.u24()
    reader.skip(8)
    track_id = reader.u32()
    reader.skip(4)
    duration = reader.u32()
    reader.skip(10)
    group, volume = reader.u16(), reader.u16()
    reader.skip(38)
    return track_id, flags, duration, group, volume, reader.u32()


def test_track_headers_follow_ffmpeg() -> None:
    assert tkhd_fields(trak("mp4", 0)) == (1, 3, 2000, 0, 0, 640 << 16)
    assert tkhd_fields(trak("mp4", 1)) == (2, 3, 1998, 1, 0x100, 0)
    assert tkhd_fields(trak("mp4", 2)) == (3, 2, 1500, 3, 0, 0)  # disabled subtitle


@pytest.mark.parametrize(
    ("number", "handler", "name"),
    [
        (0, b"vide", b"VideoHandler"),
        (1, b"soun", b"SoundHandler"),
        (2, b"sbtl", b"Turkish (AI: claude=claude-opus-5)"),
    ],
)
def test_handler_names_are_c_strings_in_mp4_and_pascal_strings_in_mov(
    number: int, handler: bytes, name: bytes
) -> None:
    mp4 = path(trak("mp4", number), "mdia", "hdlr")
    assert mp4 == bytes(8) + handler + bytes(12) + name + b"\x00"
    mov = path(trak("mov", number), "mdia", "hdlr")
    assert mov == bytes(4) + b"mhlr" + handler + bytes(12) + bytes([len(name)]) + name


def test_mov_media_information_has_a_data_handler() -> None:
    mp4_kinds = [
        kind for kind, _ in child_boxes(path(trak("mp4", 0), "mdia", "minf"), context="minf")
    ]
    mov_minf = path(trak("mov", 0), "mdia", "minf")
    mov_kinds = [kind for kind, _ in child_boxes(mov_minf, context="minf")]
    assert mp4_kinds == ["vmhd", "dinf", "stbl"]
    assert mov_kinds == ["vmhd", "hdlr", "dinf", "stbl"]
    data_handler = path(mov_minf, "hdlr")
    assert data_handler == bytes(4) + b"dhlrurl " + bytes(12) + b"\x0bDataHandler"


@pytest.mark.parametrize(("number", "header"), [(0, "vmhd"), (1, "smhd"), (2, "nmhd")])
def test_media_headers(number: int, header: str) -> None:
    minf = path(trak("mp4", number), "mdia", "minf")
    assert child_boxes(minf, context="minf")[0][0] == header


def mdhd_language(payload: bytes) -> int:
    mdhd = path(payload, "mdia", "mdhd")
    return int.from_bytes(mdhd[20:22], "big")


def test_languages_are_iso_in_mp4_and_quicktime_codes_in_mov_when_mapped() -> None:
    assert mdhd_language(trak("mp4", 2)) == pack_language("tur")
    assert mdhd_language(trak("mov", 2)) == 17  # QuickTime code for Turkish
    assert mdhd_language(trak("mov", 1)) == 0  # "eng" -> English
    assert mdhd_language(trak("mov", 0)) == pack_language("und")
    filipino = replace(SUBTITLE, language="fil", tag="fil")
    traks = [body for kind, body in moov_children("mov", (VIDEO, filipino)) if kind == "trak"]
    assert mdhd_language(traks[1]) == pack_language("fil")


def test_subtitle_tracks_carry_elng_and_a_name() -> None:
    subtitle = trak("mp4", 2)
    assert path(subtitle, "mdia", "elng") == bytes(4) + b"tr\x00"
    assert path(subtitle, "udta", "name") == b"Turkish (AI: claude=claude-opus-5)"
    assert find_child(trak("mp4", 0), "udta", context="trak") is None
    assert find_child(path(trak("mp4", 0), "mdia"), "elng", context="mdia") is None


def test_sample_tables() -> None:
    video = [
        kind
        for kind, _ in child_boxes(path(trak("mp4", 0), "mdia", "minf", "stbl"), context="stbl")
    ]
    audio = [
        kind
        for kind, _ in child_boxes(path(trak("mp4", 1), "mdia", "minf", "stbl"), context="stbl")
    ]
    assert video == ["stsd", "stts", "stss", "ctts", "stsc", "stsz", "stco"]
    assert audio == ["stsd", "stts", "stsc", "stsz", "stco"]
    stsd = path(trak("mp4", 1), "mdia", "minf", "stbl", "stsd")
    assert stsd == bytes(4) + u32(1) + sample_entry(Track(handler="soun", codec="mp4a"))


def test_wide_tracks_use_co64() -> None:
    moov = moov_box("mp4", (VIDEO,), [[2**32, 2**32 + 5000]], [True])
    stbl = path(child_boxes(moov[8:], context="moov")[1][1], "mdia", "minf", "stbl")
    assert find_child(stbl, "stco", context="stbl") is None
    assert path(stbl, "co64")[4:] == u32(2) + (2**32).to_bytes(8, "big") + (2**32 + 5000).to_bytes(
        8, "big"
    )


def test_edit_lists_are_written_only_when_present() -> None:
    assert find_child(trak("mp4", 0), "edts", context="trak") is not None
    assert find_child(trak("mp4", 1), "edts", context="trak") is None


def test_long_tracks_use_version_1_headers_in_mp4_and_fail_in_mov() -> None:
    long = replace(AUDIO, duration=2**31, media_duration=2**33, edits=())
    children = moov_children("mp4", (long,))
    assert dict(children)["mvhd"][0] == 1
    traks = [body for kind, body in children if kind == "trak"]
    assert path(traks[0], "tkhd")[0] == 1
    assert path(traks[0], "mdia", "mdhd")[0] == 1
    with pytest.raises(MuxError, match="too long for a QuickTime"):
        moov_children("mov", (long,))


def test_quicktime_sound_description_version_1_with_a_wave_box() -> None:
    entry = quicktime_sound_entry(
        sample_entry(Track(handler="soun", codec="mp4a")), samples_per_packet=1024
    )
    assert entry[4:8] == b"mp4a"
    # reference, version, revision, vendor, channels, bits, compression ID, packet size, rate...
    reader = Reader(entry, "mp4a")
    reader.skip(8 + 6)
    assert [reader.u16(), reader.u16(), reader.u16(), reader.u32()] == [1, 1, 0, 0]
    assert [reader.u16(), reader.u16(), reader.i16(), reader.u16()] == [2, 16, -2, 0]
    assert reader.u32() == 44100 << 16
    assert [reader.u32() for _ in range(4)] == [1024, 0, 0, 2]
    ((kind, wave),) = child_boxes(reader.rest(), context="mp4a")
    assert kind == "wave"
    assert child_boxes(wave, context="wave") == [
        ("frma", b"mp4a"),
        ("mp4a", bytes(4)),
        ("esds", ESDS),
        ("\x00\x00\x00\x00", b""),
    ]


def test_quicktime_sound_description_accepts_version_1_inputs() -> None:
    entry = box(
        "mp4a",
        bytes(6),
        u16(1),
        u16(1),
        bytes(6),
        u16(1),
        u16(16),
        u32(0),
        u32(48000 << 16),
        bytes(16),
        box("esds", ESDS),
    )
    converted = quicktime_sound_entry(entry, samples_per_packet=1024)
    assert Reader(converted, "mp4a").take(26)[24:26] == u16(1)  # mono kept


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (sample_entry(Track(handler="soun", codec="mp4a", channels=6)), "mono or stereo"),
        (sample_entry(Track(handler="soun", codec="mp4a", sample_rate=0)), "mono or stereo"),
        (
            sample_entry(
                Track(
                    handler="soun", codec="mp4a", extra_audio_box=full_box("srat", 0, 0, u32(96000))
                )
            ),
            "mono or stereo",
        ),
        (
            box("mp4a", bytes(6), u16(1), bytes(8), u16(2), u16(16), u32(0), u32(44100 << 16)),
            "no 'esds'",
        ),
        (box("mp4a", bytes(6), u16(1), u16(2), bytes(18)), "unsupported sample description"),
    ],
)
def test_audio_quicktime_cannot_describe_is_refused(entry: bytes, message: str) -> None:
    with pytest.raises(MuxError, match=message):
        quicktime_sound_entry(entry, samples_per_packet=1024)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/media/test_moov.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'utmax.core.media.moov'`.

- [ ] **Step 3: Implement `moov.py`**

`src/utmax/core/media/moov.py`:

```python
"""The ``ftyp`` and ``moov`` boxes of progressive MP4, MOV and M4A files.

Layouts follow ISO/IEC 14496-12 and Apple's QuickTime File Format; field values follow
FFmpeg's ``libavformat/movenc.c`` (b87602a63a52): tkhd flags "in movie" plus "enabled",
alternate group = media type (video 0, audio 1, subtitle 3), handler names "VideoHandler" and
"SoundHandler", ``mdhd``/``tkhd``/``mvhd`` version 1 only from 2^31 - 1 ticks, zero creation
times. Flavor differences: MOV uses Pascal-string handler names, a ``dhlr`` data handler in
``minf``, Macintosh language codes when one exists, and a SoundDescription version 1 audio
entry with a ``wave`` box; MP4 and M4A keep the source audio entry and C-string names.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal

from utmax.core.languages import mac_language_code
from utmax.core.media.boxes import (
    I32_MAX,
    Reader,
    box,
    find_child,
    full_box,
    i16,
    u8,
    u16,
    u32,
    u64,
)
from utmax.core.media.fmp4 import Edit
from utmax.core.media.tables import (
    chunk_offsets_box,
    ctts_box,
    edts_box,
    stsc_box,
    stss_box,
    stsz_box,
    stts_box,
)
from utmax.errors import MuxError

__all__ = [
    "MOVIE_TIMESCALE",
    "UNITY_MATRIX",
    "Flavor",
    "TrackKind",
    "TrackPlan",
    "ftyp_box",
    "moov_box",
    "pack_language",
    "quicktime_sound_entry",
    "unpack_language",
]

Flavor = Literal["mp4", "mov", "m4a"]
TrackKind = Literal["video", "audio", "subtitle"]

MOVIE_TIMESCALE = 1000
UNITY_MATRIX = b"".join(u32(value) for value in (0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x4000_0000))

_HANDLERS: dict[TrackKind, str] = {"video": "vide", "audio": "soun", "subtitle": "sbtl"}
_HANDLER_NAMES: dict[TrackKind, str] = {"video": "VideoHandler", "audio": "SoundHandler"}
_ALTERNATE_GROUPS: dict[TrackKind, int] = {"video": 0, "audio": 1, "subtitle": 3}
_TKHD_ENABLED = 0x1
_TKHD_IN_MOVIE = 0x2
_DATA_HANDLER = full_box("hdlr", 0, 0, b"dhlr", b"url ", bytes(12), u8(11), b"DataHandler")
_DATA_INFORMATION = box("dinf", full_box("dref", 0, 0, u32(1), full_box("url ", 0, 1)))


@dataclass(frozen=True, slots=True)
class TrackPlan:
    """Everything needed to write one ``trak`` box except its chunk offsets."""

    track_id: int
    kind: TrackKind
    timescale: int
    language: str
    tag: str | None
    name: str | None
    enabled: bool
    matrix: bytes
    width: int
    height: int
    edits: tuple[Edit, ...]
    duration: int
    media_duration: int
    sample_entries: tuple[bytes, ...]
    durations: Sequence[int]
    ctos: Sequence[int]
    sync: bytes | bytearray
    sizes: Sequence[int]
    chunks: tuple[tuple[int, int], ...]


def ftyp_box(flavor: Flavor, codecs: Collection[str]) -> bytes:
    """``isom`` (+ ``iso2``, ``avc1``/``av01``, ``mp41``), ``qt  `` or ``M4A `` brands."""
    if flavor == "mov":
        return box("ftyp", b"qt  ", u32(0x200), b"qt  ")
    if flavor == "m4a":
        return box("ftyp", b"M4A ", u32(0x200), b"M4A ", b"isom", b"iso2", b"mp41")
    brands = [b"isom", b"iso2"]
    brands += [codec.encode("ascii") for codec in ("avc1", "av01") if codec in codecs]
    return box("ftyp", b"isom", u32(0x200), *brands, b"mp41")


def moov_box(
    flavor: Flavor,
    tracks: Sequence[TrackPlan],
    offsets: Sequence[Sequence[int]],
    wide: Sequence[bool],
) -> bytes:
    """The ``moov`` box: ``mvhd`` and one ``trak`` per track, with the given chunk offsets."""
    duration = max(track.duration for track in tracks)
    version = _version(flavor, duration)
    mvhd = full_box(
        "mvhd",
        version,
        0,
        bytes(16 if version else 8),  # creation and modification time
        u32(MOVIE_TIMESCALE),
        u64(duration) if version else u32(duration),
        u32(0x0001_0000),  # preferred rate 1.0
        u16(0x0100),  # preferred volume 1.0
        bytes(10),
        UNITY_MATRIX,
        bytes(24),  # QuickTime preview, poster, selection and current times
        u32(len(tracks) + 1),  # next track ID
    )
    traks = [
        _trak(flavor, track, track_offsets, track_wide)
        for track, track_offsets, track_wide in zip(tracks, offsets, wide, strict=True)
    ]
    return box("moov", mvhd, *traks)


def pack_language(code: str) -> int:
    """An ISO 639-2/T code as the 15-bit ``mdhd`` field (three 5-bit letters); bad -> ``und``."""
    if len(code) != 3 or not (code.isascii() and code.isalpha() and code.islower()):
        code = "und"
    value = 0
    for letter in code:
        value = value << 5 | (ord(letter) - 0x60)
    return value


def unpack_language(value: int) -> str:
    """The ISO 639-2/T code in an ``mdhd`` language field (``und`` for QuickTime codes)."""
    if value < 0x400:
        return "und"
    return "".join(chr(((value >> shift) & 0x1F) + 0x60) for shift in (10, 5, 0))


def quicktime_sound_entry(entry: bytes, *, samples_per_packet: int) -> bytes:
    """An ISO ``mp4a`` sample entry as a QuickTime SoundDescription version 1.

    The AAC configuration moves into a ``wave`` box (``frma``, ``mp4a``, ``esds``, terminator),
    as FFmpeg writes it for ``.mov`` files.

    Raises:
        MuxError: more than two channels or a rate above 65535 Hz (not representable in a
            version 1 SoundDescription).
    """
    reader = Reader(entry, "mp4a")
    reader.skip(8 + 6)  # box header, reserved
    reference = reader.u16()
    version = reader.u16()
    reader.skip(6)  # revision level, vendor
    channels = reader.u16()
    reader.skip(6)  # sample size, compression ID, packet size
    rate = reader.u32()
    if version == 1:
        reader.skip(16)
    elif version != 0:
        raise MuxError(f"The AAC stream uses an unsupported sample description (v{version}).")
    extensions = reader.rest()
    esds = find_child(extensions, "esds", context="mp4a")
    if esds is None:
        raise MuxError("The AAC stream has no 'esds' decoder configuration.")
    too_fast = rate >> 16 == 0 or find_child(extensions, "srat", context="mp4a") is not None
    if not 1 <= channels <= 2 or too_fast:
        raise MuxError(
            "QuickTime .mov files made by utmax hold mono or stereo audio up to 65535 Hz; "
            "this stream needs .mp4 or .m4a.",
            suggestion="Download this video as .mp4 instead of .mov.",
        )
    wave = box("wave", box("frma", b"mp4a"), box("mp4a", u32(0)), box("esds", esds), u32(8), u32(0))
    return box(
        "mp4a",
        bytes(6),
        u16(reference),
        u16(1),  # SoundDescription version 1
        u16(0),  # revision level
        u32(0),  # vendor
        u16(channels),
        u16(16),  # sample size
        i16(-2),  # compression ID: variable bit rate
        u16(0),  # packet size
        u32(rate),
        u32(samples_per_packet),
        u32(0),  # bytes per packet
        u32(0),  # bytes per frame
        u32(2),  # bytes per sample
        wave,
    )


def _trak(flavor: Flavor, track: TrackPlan, offsets: Sequence[int], wide: bool) -> bytes:
    version = _version(flavor, track.duration)
    tkhd = full_box(
        "tkhd",
        version,
        _TKHD_IN_MOVIE | (_TKHD_ENABLED if track.enabled else 0),
        bytes(16 if version else 8),  # creation and modification time
        u32(track.track_id),
        u32(0),
        u64(track.duration) if version else u32(track.duration),
        bytes(8),
        u16(0),  # layer
        u16(_ALTERNATE_GROUPS[track.kind]),
        u16(0x0100 if track.kind == "audio" else 0),  # volume
        u16(0),
        track.matrix,
        u32(track.width),
        u32(track.height),
    )
    parts = [tkhd]
    if track.edits:
        parts.append(edts_box(track.edits))
    parts.append(_mdia(flavor, track, offsets, wide))
    if track.name:
        parts.append(box("udta", box("name", track.name.encode("utf-8"))))
    return box("trak", *parts)


def _mdia(flavor: Flavor, track: TrackPlan, offsets: Sequence[int], wide: bool) -> bytes:
    version = _version(flavor, track.media_duration)
    mdhd = full_box(
        "mdhd",
        version,
        0,
        bytes(16 if version else 8),  # creation and modification time
        u32(track.timescale),
        u64(track.media_duration) if version else u32(track.media_duration),
        u16(_language_field(flavor, track)),
        u16(0),  # quality
    )
    name = track.name or _HANDLER_NAMES.get(track.kind, "")
    parts = [mdhd, _hdlr(flavor, _HANDLERS[track.kind], name)]
    if track.tag:
        parts.append(full_box("elng", 0, 0, track.tag.encode("ascii") + b"\x00"))
    media_header = {
        "video": full_box("vmhd", 0, 1, bytes(8)),
        "audio": full_box("smhd", 0, 0, bytes(4)),
        "subtitle": full_box("nmhd", 0, 0),
    }[track.kind]
    minf = [media_header]
    if flavor == "mov":
        minf.append(_DATA_HANDLER)
    minf += [_DATA_INFORMATION, _stbl(track, offsets, wide)]
    parts.append(box("minf", *minf))
    return box("mdia", *parts)


def _stbl(track: TrackPlan, offsets: Sequence[int], wide: bool) -> bytes:
    entries = full_box("stsd", 0, 0, u32(len(track.sample_entries)), *track.sample_entries)
    parts = [entries, stts_box(track.durations)]
    parts.extend(extra for extra in (stss_box(track.sync), ctts_box(track.ctos)) if extra)
    parts += [stsc_box(track.chunks), stsz_box(track.sizes), chunk_offsets_box(offsets, wide=wide)]
    return box("stbl", *parts)


def _hdlr(flavor: Flavor, handler: str, name: str) -> bytes:
    text = name.replace("\x00", "").encode("utf-8")
    if flavor == "mov":
        text = text[:255].decode("utf-8", errors="ignore").encode("utf-8")
        return full_box(
            "hdlr", 0, 0, b"mhlr", handler.encode("ascii"), bytes(12), u8(len(text)), text
        )
    return full_box("hdlr", 0, 0, bytes(4), handler.encode("ascii"), bytes(12), text, b"\x00")


def _language_field(flavor: Flavor, track: TrackPlan) -> int:
    if flavor == "mov":
        mac = mac_language_code(track.tag or track.language)
        if mac is not None:
            return mac
    return pack_language(track.language)


def _version(flavor: Flavor, duration: int) -> int:
    if duration < I32_MAX:
        return 0
    if flavor == "mov":
        raise MuxError(
            "The video is too long for a QuickTime .mov file with its time scale.",
            suggestion="Download this video as .mp4 instead of .mov.",
        )
    return 1
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/media/test_moov.py -q`
Expected: `28 passed`.

- [ ] **Step 5: Gates and full suite**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected: clean gates (33 source files), `560 passed, 6 deselected`.

- [ ] **Step 6: Commit**

```bash
git add src/utmax/core/media/moov.py tests/unit/media/test_moov.py
git commit -m "feat: write moov and ftyp boxes for mp4, mov and m4a

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Progressive file reader

**Files:**
- Create: `src/utmax/core/media/progressive.py`
- Test: `tests/unit/media/test_progressive.py`

**Interfaces:**
- Consumes: `BoxHeader`, `ByteSource`, `Reader`, `child_boxes`, `find_child`, `iter_boxes`, `read_exact`, `require_child` (Task 1); `Edit`, `parse_elst`, `parse_stsd` (Task 3); tests build files with `ftyp_box`/`moov_box` (Task 7).
- Produces (in `utmax.core.media.progressive`):
  - `Sample(offset, size, dts, duration, cto, sync, description)`, `Chunk(offset, first_sample, count, description)`.
  - `Track(track_id, flags, alternate_group, volume, width, height, duration, edits, handler, handler_name, timescale, media_duration, language, extended_language, name, media_header, data_handler, sample_entries, chunk_box, ctts_version, chunks, samples)` — `language` is the raw `mdhd` field, `media_header` the `minf` media header type (`vmhd`/`smhd`/`nmhd`), `data_handler` whether `minf` holds an `hdlr`, `chunk_box` `"stco"` or `"co64"`, `ctts_version` `None` without `ctts`.
  - `ProgressiveFile(major_brand, minor_version, compatible_brands, boxes, timescale, duration, next_track_id, tracks)` — `boxes` are the top-level `BoxHeader`s.
  - `parse_progressive(source: ByteSource) -> ProgressiveFile` — handler names are Pascal strings in `qt  ` files when the length byte matches (FFmpeg's rule), else C strings; `MuxError` for a missing `ftyp`/`moov`, tables that disagree on the sample count, and chunk maps that list too many or too few samples.

- [ ] **Step 1: Write the failing tests**

`tests/unit/media/test_progressive.py`:

```python
"""Tests for reading progressive MP4/MOV files back."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest

from tests.helpers.fmp4_factory import Track, payload, sample_entry
from utmax.core.media.boxes import BytesSource, box, u32, u64
from utmax.core.media.fmp4 import Edit
from utmax.core.media.moov import UNITY_MATRIX, Flavor, TrackPlan, ftyp_box, moov_box
from utmax.core.media.progressive import Chunk, Sample, parse_progressive
from utmax.core.media.tx3g import sample_entry as tx3g_entry
from utmax.errors import MuxError

VIDEO = TrackPlan(
    track_id=1,
    kind="video",
    timescale=12800,
    language="und",
    tag=None,
    name=None,
    enabled=True,
    matrix=UNITY_MATRIX,
    width=640 << 16,
    height=360 << 16,
    edits=(Edit(250, 512),),
    duration=250,
    media_duration=3072,
    sample_entries=(sample_entry(Track()), sample_entry(Track(width=320))),
    durations=[512] * 6,
    ctos=[1024, -512, 0, 512, 0, 0],
    sync=bytes([1, 0, 0, 1, 0, 0]),
    sizes=[40, 11, 12, 30, 13, 14],
    chunks=((3, 1), (2, 1), (1, 2)),
)
SUBTITLE = replace(
    VIDEO,
    track_id=2,
    kind="subtitle",
    timescale=1000,
    language="tur",
    tag="tr",
    name="Turkish",
    enabled=False,
    width=0,
    height=0,
    edits=(),
    duration=1500,
    media_duration=1500,
    sample_entries=(tx3g_entry(),),
    durations=[500, 1000],
    ctos=[0, 0],
    sync=bytes([1, 1]),
    sizes=[2, 9],
    chunks=((2, 1),),
)


def build(
    flavor: Flavor,
    tracks: Sequence[TrackPlan],
    *,
    wide: bool = False,
    large_mdat: bool = False,
    extra_offsets: int = 0,
) -> bytes:
    chunks: list[list[bytes]] = []
    for track in tracks:
        first, per_chunk = 0, []
        for count, _ in track.chunks:
            samples = range(first, first + count)
            per_chunk.append(b"".join(payload(track.track_id, i, track.sizes[i]) for i in samples))
            first += count
        chunks.append(per_chunk)
    body = b"".join(b"".join(track_chunks) for track_chunks in chunks)
    header = u32(1) + b"mdat" + u64(16 + len(body)) if large_mdat else u32(8 + len(body)) + b"mdat"
    ftyp = ftyp_box(flavor, {"avc1"})
    counts = [[0] * (len(track_chunks) + extra_offsets) for track_chunks in chunks]
    position = len(ftyp) + len(moov_box(flavor, tracks, counts, [wide] * len(tracks))) + len(header)
    offsets: list[list[int]] = []
    for track_chunks in chunks:
        offsets.append([])
        for chunk in track_chunks:
            offsets[-1].append(position)
            position += len(chunk)
        offsets[-1] += [position] * extra_offsets
    return ftyp + moov_box(flavor, tracks, offsets, [wide] * len(tracks)) + header + body


def test_movie_and_file_layout() -> None:
    parsed = parse_progressive(BytesSource(build("mp4", (VIDEO, SUBTITLE))))
    assert (parsed.major_brand, parsed.minor_version) == ("isom", 0x200)
    assert parsed.compatible_brands == ("isom", "iso2", "avc1", "mp41")
    assert [header.kind for header in parsed.boxes] == ["ftyp", "moov", "mdat"]
    assert (parsed.timescale, parsed.duration, parsed.next_track_id) == (1000, 1500, 3)


def test_video_track_samples_and_chunks() -> None:
    data = build("mp4", (VIDEO, SUBTITLE))
    video = parse_progressive(BytesSource(data)).tracks[0]
    assert (video.track_id, video.flags, video.alternate_group, video.volume) == (1, 3, 0, 0)
    assert (video.width, video.height, video.duration) == (640 << 16, 360 << 16, 250)
    assert video.edits == (Edit(250, 512),)
    assert (video.handler, video.handler_name, video.timescale) == ("vide", "VideoHandler", 12800)
    assert (video.media_duration, video.language, video.media_header) == (3072, 0x55C4, "vmhd")
    assert (video.extended_language, video.name, video.data_handler) == (None, None, False)
    assert len(video.sample_entries) == 2
    assert (video.chunk_box, video.ctts_version) == ("stco", 1)
    assert [chunk.count for chunk in video.chunks] == [3, 2, 1]
    assert [chunk.description for chunk in video.chunks] == [1, 1, 2]
    assert video.chunks[1] == Chunk(video.chunks[0].offset + 63, 3, 2, 1)
    assert [sample.dts for sample in video.samples] == [0, 512, 1024, 1536, 2048, 2560]
    assert [sample.cto for sample in video.samples] == [1024, -512, 0, 512, 0, 0]
    assert [sample.sync for sample in video.samples] == [True, False, False, True, False, False]
    assert video.samples[5] == Sample(video.chunks[2].offset, 14, 2560, 512, 0, False, 2)
    for index, sample in enumerate(video.samples):
        assert data[sample.offset : sample.offset + sample.size] == payload(1, index, sample.size)


def test_subtitle_track_details() -> None:
    subtitle = parse_progressive(BytesSource(build("mp4", (VIDEO, SUBTITLE)))).tracks[1]
    assert (subtitle.flags, subtitle.alternate_group, subtitle.media_header) == (2, 3, "nmhd")
    assert (subtitle.handler, subtitle.handler_name) == ("sbtl", "Turkish")
    assert (subtitle.extended_language, subtitle.name) == ("tr", "Turkish")
    assert subtitle.ctts_version is None
    assert all(sample.sync for sample in subtitle.samples)


def test_quicktime_files_have_pascal_handler_names_and_a_data_handler() -> None:
    parsed = parse_progressive(BytesSource(build("mov", (VIDEO, SUBTITLE))))
    assert parsed.major_brand == "qt  "
    assert [track.handler_name for track in parsed.tracks] == ["VideoHandler", "Turkish"]
    assert all(track.data_handler for track in parsed.tracks)
    assert parsed.tracks[1].language == 17


def test_co64_and_64_bit_mdat_headers() -> None:
    parsed = parse_progressive(BytesSource(build("mp4", (VIDEO,), wide=True, large_mdat=True)))
    mdat = parsed.boxes[2]
    assert (mdat.kind, mdat.header_size) == ("mdat", 16)
    assert parsed.tracks[0].chunk_box == "co64"
    assert parsed.tracks[0].samples[0].offset == mdat.payload_offset


def test_version_1_movie_headers() -> None:
    long = replace(SUBTITLE, duration=2**31, media_duration=2**31)
    parsed = parse_progressive(BytesSource(build("mp4", (long,))))
    assert parsed.duration == 2**31
    assert (parsed.tracks[0].duration, parsed.tracks[0].media_duration) == (2**31, 2**31)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (box("ftyp", b"isom", u32(0)), "no top-level 'moov'"),
        (box("moov"), "no top-level 'ftyp'"),
    ],
)
def test_missing_boxes(data: bytes, message: str) -> None:
    with pytest.raises(MuxError, match=message):
        parse_progressive(BytesSource(data))


def test_sample_tables_that_disagree_are_errors() -> None:
    uneven = replace(VIDEO, durations=[512] * 7)
    with pytest.raises(MuxError, match="disagree about the number of samples"):
        parse_progressive(BytesSource(build("mp4", (uneven,))))


def test_chunks_listing_too_many_or_too_few_samples_are_errors() -> None:
    with pytest.raises(MuxError, match="more samples than the sample tables"):
        parse_progressive(BytesSource(build("mp4", (VIDEO,), extra_offsets=1)))
    short = replace(VIDEO, chunks=((3, 1), (2, 1)))
    with pytest.raises(MuxError, match="fewer samples than the sample tables"):
        parse_progressive(BytesSource(build("mp4", (short,))))


def test_a_sample_to_chunk_table_that_skips_chunks_is_an_error() -> None:
    data = build("mp4", (VIDEO,))
    stsc = data.index(b"stsc")
    patched = data[: stsc + 24] + u32(9) + data[stsc + 28 :]  # second entry starts at chunk 9
    with pytest.raises(MuxError, match="does not match the number of chunks"):
        parse_progressive(BytesSource(patched))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/media/test_progressive.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'utmax.core.media.progressive'`.

- [ ] **Step 3: Implement `progressive.py`**

`src/utmax/core/media/progressive.py`:

```python
"""Read progressive (non-fragmented) MP4/MOV files: layout, track headers and every sample.

The muxer's tests re-parse its output with this module, so it understands everything the
muxer writes: ``co64``, 64-bit ``mdat`` sizes, ``ctts`` version 1, ``elng``, ``udta/name`` and
QuickTime's Pascal-string handler names.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import accumulate

from utmax.core.media.boxes import (
    BoxHeader,
    ByteSource,
    Reader,
    child_boxes,
    find_child,
    iter_boxes,
    read_exact,
    require_child,
)
from utmax.core.media.fmp4 import Edit, parse_elst, parse_stsd
from utmax.errors import MuxError

__all__ = ["Chunk", "ProgressiveFile", "Sample", "Track", "parse_progressive"]


@dataclass(frozen=True, slots=True)
class Sample:
    """One sample: where its bytes are and when it is decoded and shown."""

    offset: int
    size: int
    dts: int
    duration: int
    cto: int
    sync: bool
    description: int


@dataclass(frozen=True, slots=True)
class Chunk:
    """A run of samples stored back to back."""

    offset: int
    first_sample: int
    count: int
    description: int


@dataclass(frozen=True, slots=True)
class Track:
    """One ``trak`` box, decoded."""

    track_id: int
    flags: int
    alternate_group: int
    volume: int
    width: int
    height: int
    duration: int
    edits: tuple[Edit, ...]
    handler: str
    handler_name: str
    timescale: int
    media_duration: int
    language: int
    extended_language: str | None
    name: str | None
    media_header: str
    data_handler: bool
    sample_entries: tuple[bytes, ...]
    chunk_box: str
    ctts_version: int | None
    chunks: tuple[Chunk, ...]
    samples: tuple[Sample, ...]


@dataclass(frozen=True, slots=True)
class ProgressiveFile:
    """A whole file: brands, top-level boxes, movie header and tracks."""

    major_brand: str
    minor_version: int
    compatible_brands: tuple[str, ...]
    boxes: tuple[BoxHeader, ...]
    timescale: int
    duration: int
    next_track_id: int
    tracks: tuple[Track, ...]


def parse_progressive(source: ByteSource) -> ProgressiveFile:
    """Decode a progressive MP4/MOV file.

    Raises:
        MuxError: a required box is missing or the sample tables disagree.
    """
    boxes = tuple(iter_boxes(source))
    ftyp = _payload(source, boxes, "ftyp")
    moov = _payload(source, boxes, "moov")
    brands = Reader(ftyp, "ftyp")
    major, minor = brands.fourcc(), brands.u32()
    compatible = tuple(
        ftyp[offset : offset + 4].decode("latin-1") for offset in range(8, len(ftyp), 4)
    )
    mvhd = Reader(require_child(moov, "mvhd", context="moov"), "mvhd")
    version = mvhd.u8()
    mvhd.skip(3 + (16 if version == 1 else 8))
    timescale = mvhd.u32()
    duration = mvhd.u64() if version == 1 else mvhd.u32()
    mvhd.skip(4 + 2 + 10 + 36 + 24)
    next_track_id = mvhd.u32()
    tracks = tuple(
        _track(body, quicktime=major == "qt  ")
        for kind, body in child_boxes(moov, context="moov")
        if kind == "trak"
    )
    return ProgressiveFile(
        major, minor, compatible, boxes, timescale, duration, next_track_id, tracks
    )


def _payload(source: ByteSource, boxes: Sequence[BoxHeader], kind: str) -> bytes:
    header = next((header for header in boxes if header.kind == kind), None)
    if header is None:
        raise MuxError(f"The file has no top-level {kind!r} box.")
    return read_exact(source, header.payload_offset, header.payload_size)


def _track(payload: bytes, *, quicktime: bool) -> Track:
    tkhd = Reader(require_child(payload, "tkhd", context="trak"), "tkhd")
    version = tkhd.u8()
    flags = tkhd.u24()
    tkhd.skip(16 if version == 1 else 8)
    track_id = tkhd.u32()
    tkhd.skip(4)
    duration = tkhd.u64() if version == 1 else tkhd.u32()
    tkhd.skip(8 + 2)
    alternate_group, volume = tkhd.u16(), tkhd.u16()
    tkhd.skip(2 + 36)
    width, height = tkhd.u32(), tkhd.u32()
    edts = find_child(payload, "edts", context="trak")
    elst = find_child(edts, "elst", context="edts") if edts is not None else None
    mdia = require_child(payload, "mdia", context="trak")
    mdhd = Reader(require_child(mdia, "mdhd", context="mdia"), "mdhd")
    version = mdhd.u8()
    mdhd.skip(3 + (16 if version == 1 else 8))
    timescale = mdhd.u32()
    media_duration = mdhd.u64() if version == 1 else mdhd.u32()
    language = mdhd.u16()
    hdlr = require_child(mdia, "hdlr", context="mdia")
    elng = find_child(mdia, "elng", context="mdia")
    minf = require_child(mdia, "minf", context="mdia")
    minf_kinds = [kind for kind, _ in child_boxes(minf, context="minf")]
    udta = find_child(payload, "udta", context="trak")
    name = find_child(udta, "name", context="udta") if udta is not None else None
    stbl = require_child(minf, "stbl", context="minf")
    chunk_box = "co64" if find_child(stbl, "co64", context="stbl") is not None else "stco"
    ctts = find_child(stbl, "ctts", context="stbl")
    chunks, samples = _samples(stbl, chunk_box)
    return Track(
        track_id=track_id,
        flags=flags,
        alternate_group=alternate_group,
        volume=volume,
        width=width,
        height=height,
        duration=duration,
        edits=parse_elst(elst) if elst is not None else (),
        handler=hdlr[8:12].decode("latin-1"),
        handler_name=_handler_name(hdlr[24:], quicktime=quicktime),
        timescale=timescale,
        media_duration=media_duration,
        language=language,
        extended_language=elng[4:].split(b"\x00")[0].decode("ascii") if elng else None,
        name=name.decode("utf-8") if name is not None else None,
        media_header=next(kind for kind in minf_kinds if kind.endswith("hd")),
        data_handler="hdlr" in minf_kinds,
        sample_entries=parse_stsd(require_child(stbl, "stsd", context="stbl")),
        chunk_box=chunk_box,
        ctts_version=ctts[0] if ctts is not None else None,
        chunks=chunks,
        samples=samples,
    )


def _handler_name(raw: bytes, *, quicktime: bool) -> str:
    if quicktime and raw and raw[0] == len(raw) - 1:
        return raw[1:].decode("utf-8")
    return raw.split(b"\x00")[0].decode("utf-8")


def _samples(stbl: bytes, chunk_box: str) -> tuple[tuple[Chunk, ...], tuple[Sample, ...]]:
    durations = [
        duration for count, duration in _pairs(stbl, "stts", signed=False) for _ in range(count)
    ]
    count = len(durations)
    ctts = find_child(stbl, "ctts", context="stbl")
    ctos = (
        [offset for n, offset in _pairs(stbl, "ctts", signed=ctts[0] == 1) for _ in range(n)]
        if ctts is not None
        else [0] * count
    )
    stss = find_child(stbl, "stss", context="stbl")
    sync_numbers = set(_numbers(stss, "stss")) if stss is not None else None
    stsz = Reader(require_child(stbl, "stsz", context="stbl"), "stsz")
    stsz.skip(4)
    uniform, listed = stsz.u32(), stsz.u32()
    sizes = [uniform] * listed if uniform else [stsz.u32() for _ in range(listed)]
    offsets = _numbers(require_child(stbl, chunk_box, context="stbl"), chunk_box)
    if not (len(ctos) == len(sizes) == count):
        raise MuxError("The sample tables disagree about the number of samples.")
    per_chunk = _expand_stsc(require_child(stbl, "stsc", context="stbl"), len(offsets))
    chunks: list[Chunk] = []
    samples: list[Sample] = []
    decode_times = list(accumulate(durations, initial=0))
    for chunk_offset, (samples_in_chunk, description) in zip(offsets, per_chunk, strict=True):
        chunks.append(Chunk(chunk_offset, len(samples), samples_in_chunk, description))
        position = chunk_offset
        for _ in range(samples_in_chunk):
            index = len(samples)
            if index >= count:
                raise MuxError("The chunk tables list more samples than the sample tables.")
            samples.append(
                Sample(
                    offset=position,
                    size=sizes[index],
                    dts=decode_times[index],
                    duration=durations[index],
                    cto=ctos[index],
                    sync=sync_numbers is None or index + 1 in sync_numbers,
                    description=description,
                )
            )
            position += sizes[index]
    if len(samples) != count:
        raise MuxError("The chunk tables list fewer samples than the sample tables.")
    return tuple(chunks), tuple(samples)


def _pairs(stbl: bytes, kind: str, *, signed: bool) -> list[tuple[int, int]]:
    reader = Reader(require_child(stbl, kind, context="stbl"), kind)
    reader.skip(4)
    return [(reader.u32(), reader.i32() if signed else reader.u32()) for _ in range(reader.u32())]


def _numbers(payload: bytes, kind: str) -> list[int]:
    reader = Reader(payload, kind)
    reader.skip(4)
    count = reader.u32()
    return [reader.u64() if kind == "co64" else reader.u32() for _ in range(count)]


def _expand_stsc(payload: bytes, chunk_count: int) -> list[tuple[int, int]]:
    reader = Reader(payload, "stsc")
    reader.skip(4)
    entries = [(reader.u32(), reader.u32(), reader.u32()) for _ in range(reader.u32())]
    expanded: list[tuple[int, int]] = []
    for index, (first, samples, description) in enumerate(entries):
        last = entries[index + 1][0] - 1 if index + 1 < len(entries) else chunk_count
        expanded.extend((samples, description) for _ in range(first, last + 1))
    if len(expanded) != chunk_count:
        raise MuxError("The 'stsc' box does not match the number of chunks.")
    return expanded
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/media/test_progressive.py -q`
Expected: `11 passed`.

- [ ] **Step 5: Gates and full suite**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected: clean gates (34 source files), `571 passed, 6 deselected`.

- [ ] **Step 6: Commit**

```bash
git add src/utmax/core/media/progressive.py tests/unit/media/test_progressive.py
git commit -m "feat: read progressive MP4 and MOV files back for verification

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Mux planner for media tracks

**Files:**
- Create: `src/utmax/core/media/mux.py` (media tracks only; outputs below 4 GiB — Task 10 lifts the limit, Task 11 adds subtitles)
- Create: `tests/unit/media/invariants.py` (shared checks, not a test module)
- Test: `tests/unit/media/test_mux.py`

**Interfaces:**
- Consumes: `U32_MAX`, `ByteSource`, `read_exact`, `u32` (Task 1); `Edit`, `IndexedTrack`, `index_fragments` (Task 3); `chunk_ranges` (Task 5); `MOVIE_TIMESCALE`, `Flavor`, `TrackKind`, `TrackPlan`, `ftyp_box`, `moov_box`, `quicktime_sound_entry`, `unpack_language` (Task 7); `parse_progressive` (Task 8) and `HollowSource` (Task 4) in tests.
- Produces (in `utmax.core.media.mux`):
  - `FLAVORS = ("mp4", "mov", "m4a")`; `Flavor` re-exported (M4 imports it from here).
  - `CopyOp(source: int, offset: int, size: int)` — copy bytes of input number `source`; `Blob(data: bytes)`; `MuxPlan(ops: tuple[CopyOp | Blob, ...])` with `.size`.
  - `PlanSource(plan, sources)` — a `ByteSource` over the planned file (used to verify output, and by M4 if it ever needs to), with `.size` and `.read(offset, n)`.
  - `convert_edits(edits, *, movie_timescale, timescale, first_dts, presentation_end, lead: Fraction) -> tuple[Edit, ...]` — see Decision 6.
  - `plan_mux(sources: Sequence[ByteSource], *, flavor: Flavor) -> MuxPlan` — every track of every source, in order.
  - `tests.unit.media.invariants.check_file(plan, sources, *, hash_payloads=True) -> ProgressiveFile` — re-parses the plan's output through `PlanSource` and asserts: `ftyp`/`moov`/`mdat` layout, 64-bit `mdat` header exactly when needed, `co64` exactly when needed, per-sample sizes, durations, composition offsets, sync flags and descriptions equal to the input, per-sample SHA-256 payload hashes, chunk bounds (media < 1 s, subtitles < 10 s, inside `mdat`), chunks stored in time order, `mvhd` duration = longest track, next track ID.
- Planning rules: tracks keep their timescale; each input is rebased to decode from 0; `presentation_end = max(dts + cto + duration)`; `tkhd` duration = sum of edit durations, else `presentation_end` in ms (rounded up); `mdhd` duration = decode end; chunk span 1 s; chunks interleaved by (start seconds incl. lead, track order); contiguous samples of one input merge into one `CopyOp`; MOV audio entries go through `quicktime_sound_entry` with the most common sample duration as samples per packet; tracks whose sample descriptions mix codecs, or use codecs other than `avc1`/`av01` video and `mp4a` audio, are refused.

- [ ] **Step 1: Write the invariant helper and the failing tests**

`tests/unit/media/invariants.py`:

```python
"""Invariants every muxed file must satisfy, checked by re-parsing it with ``progressive``."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from fractions import Fraction
from itertools import pairwise

from utmax.core.media.boxes import U32_MAX, BoxHeader, ByteSource
from utmax.core.media.fmp4 import IndexedTrack, index_fragments
from utmax.core.media.mux import MuxPlan, PlanSource
from utmax.core.media.progressive import ProgressiveFile, Track, parse_progressive


def check_file(
    plan: MuxPlan, sources: Sequence[ByteSource], *, hash_payloads: bool = True
) -> ProgressiveFile:
    """Re-parse the planned file and compare every media track with its input track.

    Checks the ``ftyp``/``moov``/``mdat`` layout, a 64-bit ``mdat`` header exactly when the box
    needs it, ``co64`` exactly when a track's offsets need it, per-sample sizes, durations,
    composition offsets, sync flags and sample descriptions, per-sample payload hashes, chunk
    bounds (1 s of media, 10 s of subtitles) and that chunks are stored in time order.
    """
    output = PlanSource(plan, sources)
    parsed = parse_progressive(output)
    assert [header.kind for header in parsed.boxes] == ["ftyp", "moov", "mdat"]
    mdat = parsed.boxes[2]
    assert mdat.header_size == (16 if mdat.size > U32_MAX else 8)
    assert mdat.end == output.size == plan.size
    inputs = [
        (number, track)
        for number, source in enumerate(sources)
        for track in index_fragments(source)
    ]
    for (number, expected), track in zip(inputs, parsed.tracks, strict=False):
        _check_track(track, expected, output, sources[number], hash_payloads=hash_payloads)
    for track in parsed.tracks:
        _check_chunks(track, mdat)
    _check_time_order(parsed)
    assert parsed.duration == max(track.duration for track in parsed.tracks)
    assert parsed.next_track_id == len(parsed.tracks) + 1
    return parsed


def _check_track(
    track: Track,
    expected: IndexedTrack,
    output: ByteSource,
    source: ByteSource,
    *,
    hash_payloads: bool,
) -> None:
    samples, table = track.samples, expected.samples
    assert track.timescale == expected.header.timescale
    assert len(samples) == len(table)
    assert [sample.size for sample in samples] == list(table.sizes)
    assert [sample.duration for sample in samples] == list(table.durations)
    assert [sample.cto for sample in samples] == list(table.ctos)
    assert [sample.sync for sample in samples] == [bool(flag) for flag in table.sync]
    assert [sample.description for sample in samples] == list(table.descriptions)
    if hash_payloads:
        for sample, offset in zip(samples, table.offsets, strict=True):
            assert _digest(output, sample.offset, sample.size) == _digest(
                source, offset, sample.size
            )


def _check_chunks(track: Track, mdat: BoxHeader) -> None:
    span = track.timescale * (10 if track.handler == "sbtl" else 1)
    offsets = [chunk.offset for chunk in track.chunks]
    assert track.chunk_box == ("co64" if offsets and max(offsets) > U32_MAX else "stco")
    for chunk in track.chunks:
        first = track.samples[chunk.first_sample]
        last = track.samples[chunk.first_sample + chunk.count - 1]
        assert last.dts - first.dts < span
        assert mdat.payload_offset <= first.offset
        assert last.offset + last.size <= mdat.end


def _check_time_order(parsed: ProgressiveFile) -> None:
    starts: list[tuple[int, Fraction]] = []
    for track in parsed.tracks:
        lead = Fraction(0)
        if track.edits and track.edits[0].media_time == -1:
            lead = Fraction(track.edits[0].duration, 1000)
        for chunk in track.chunks:
            dts = track.samples[chunk.first_sample].dts
            starts.append((chunk.offset, lead + Fraction(dts, track.timescale)))
    times = [time for _, time in sorted(starts)]
    tolerance = Fraction(1, 1000)
    assert all(later >= earlier - tolerance for earlier, later in pairwise(times))


def _digest(source: ByteSource, offset: int, size: int) -> bytes:
    return hashlib.sha256(source.read(offset, size)).digest()
```

`tests/unit/media/test_mux.py`:

```python
"""Tests for planning progressive files from fragmented media streams."""

from __future__ import annotations

from fractions import Fraction

import pytest

from tests.helpers.fmp4_factory import Run, Sample, Track, Traf, fragmented_file, simple_file
from tests.helpers.hollow_source import HollowSource
from tests.unit.media.invariants import check_file
from utmax.core.media.boxes import BytesSource, Reader, child_boxes
from utmax.core.media.fmp4 import Edit, index_fragments
from utmax.core.media.mux import Blob, CopyOp, MuxPlan, PlanSource, convert_edits, plan_mux
from utmax.errors import MuxError

VIDEO = Track(edits=((0, 1024),))
AUDIO = Track(handler="soun", codec="mp4a", timescale=44100)
B_FRAME_OFFSETS = (1024, 2048, 512, 512)


def video_samples(seconds: int = 3) -> list[Sample]:
    return [
        Sample(512, 900 + (i * 37) % 400, sync=i % 25 == 0, cto=B_FRAME_OFFSETS[i % 4])
        for i in range(25 * seconds)
    ]


def audio_samples(seconds: int = 3) -> list[Sample]:
    return [Sample(1024, 200 + (i * 13) % 90) for i in range(43 * seconds)]


def video_file(seconds: int = 3, track: Track = VIDEO) -> BytesSource:
    return BytesSource(simple_file(video_samples(seconds), track=track, per_fragment=25))


def audio_file(seconds: int = 3, track: Track = AUDIO) -> BytesSource:
    return BytesSource(simple_file(audio_samples(seconds), track=track, per_fragment=43))


def test_mp4_keeps_every_sample_and_its_bytes() -> None:
    sources = [video_file(), audio_file()]
    parsed = check_file(plan_mux(sources, flavor="mp4"), sources)
    assert parsed.major_brand == "isom"
    assert parsed.compatible_brands == ("isom", "iso2", "avc1", "mp41")
    video, audio = parsed.tracks
    assert (video.track_id, video.handler, video.flags, video.alternate_group) == (1, "vide", 3, 0)
    assert (audio.track_id, audio.handler, audio.flags, audio.alternate_group) == (2, "soun", 3, 1)
    assert video.ctts_version == 0
    assert (len(video.chunks), len(audio.chunks)) == (3, 3)


def test_negative_composition_offsets_are_kept_with_ctts_version_1() -> None:
    samples = [Sample(512, 100, sync=i == 0, cto=(0, 1024, -512, -512)[i % 4]) for i in range(8)]
    sources = [BytesSource(simple_file(samples, run_version=1))]
    video = check_file(plan_mux(sources, flavor="mp4"), sources).tracks[0]
    assert video.ctts_version == 1


def test_source_edit_lists_are_kept_in_milliseconds() -> None:
    sources = [video_file(), audio_file()]
    video, audio = check_file(plan_mux(sources, flavor="mp4"), sources).tracks
    samples = video_samples()
    presentation_end = max(
        512 * i + sample.cto + sample.duration for i, sample in enumerate(samples)
    )
    assert presentation_end == 39936
    assert video.edits == (Edit(3040, 1024),)  # (39936 - 1024) ticks at 12800 Hz, in ms
    assert video.duration == 3040
    assert audio.edits == ()
    assert audio.duration == 2996  # 129 * 1024 ticks at 44100 Hz, rounded up


def test_edit_durations_are_cut_to_the_media_that_exists() -> None:
    long_edit = Track(edits=((2_727_936, 512),))  # YouTube states the full length (213 s)
    sources = [video_file(track=long_edit)]
    (video,) = check_file(plan_mux(sources, flavor="mp4"), sources).tracks
    assert video.edits == (Edit(3080, 512),)  # (39936 - 512) ticks at 12800 Hz, in ms


def test_a_later_start_becomes_a_leading_empty_edit() -> None:
    late_audio = BytesSource(
        fragmented_file([AUDIO], [[Traf(1, (Run(tuple(audio_samples(1))),), tfdt=22050)]])
    )
    sources = [video_file(1), late_audio]
    video, audio = check_file(plan_mux(sources, flavor="mp4"), sources).tracks
    assert video.edits[0].media_time == 1024
    assert audio.edits == (Edit(500, -1), Edit(999, 0))
    assert audio.samples[0].dts == 0


def test_streams_are_rebased_to_start_at_zero() -> None:
    start = 2**33
    fragment = [Traf(1, (Run(tuple(video_samples(1))),), tfdt=start, tfdt_version=1)]
    sources = [BytesSource(fragmented_file([Track()], [fragment]))]
    (video,) = check_file(plan_mux(sources, flavor="mp4"), sources).tracks
    assert video.samples[0].dts == 0
    assert video.edits == ()


def test_m4a_holds_audio_only() -> None:
    sources = [audio_file()]
    parsed = check_file(plan_mux(sources, flavor="m4a"), sources)
    assert (parsed.major_brand, parsed.compatible_brands) == (
        "M4A ",
        ("M4A ", "isom", "iso2", "mp41"),
    )
    assert [track.handler for track in parsed.tracks] == ["soun"]
    with pytest.raises(MuxError, match="holds only audio"):
        plan_mux([video_file(), audio_file()], flavor="m4a")


def test_contiguous_samples_are_copied_with_one_operation_per_fragment() -> None:
    plan = plan_mux([audio_file()], flavor="m4a")
    assert isinstance(plan.ops[0], Blob)
    assert [type(op) for op in plan.ops[1:]] == [CopyOp, CopyOp, CopyOp]


def test_mov_rewrites_the_audio_description_and_names_handlers_in_pascal() -> None:
    sources = [video_file(), audio_file()]
    parsed = check_file(plan_mux(sources, flavor="mov"), sources)
    assert (parsed.major_brand, parsed.compatible_brands) == ("qt  ", ("qt  ",))
    video, audio = parsed.tracks
    assert (video.handler_name, audio.handler_name) == ("VideoHandler", "SoundHandler")
    assert video.data_handler
    assert audio.data_handler
    entry = Reader(audio.sample_entries[0], "mp4a")
    entry.skip(16)
    assert entry.u16() == 1  # SoundDescription version 1
    assert [kind for kind, _ in child_boxes(audio.sample_entries[0][52:], context="mp4a")] == [
        "wave"
    ]
    assert video.sample_entries == index_fragments(sources[0])[0].header.sample_entries


def test_mov_refuses_av1() -> None:
    with pytest.raises(MuxError, match="cannot hold AV1") as caught:
        plan_mux([video_file(track=Track(codec="av01"))], flavor="mov")
    assert ".mp4" in caught.value.suggestion


@pytest.mark.parametrize(
    "track",
    [
        Track(codec="hvc1"),
        Track(codec="encv"),  # encrypted (DRM) video
        Track(handler="soun", codec="Opus"),
        Track(handler="text", codec="tx3g"),
    ],
)
def test_unsupported_tracks_are_refused(track: Track) -> None:
    with pytest.raises(MuxError, match="audio can be muxed"):
        plan_mux([BytesSource(simple_file([Sample(512, 10)], track=track))], flavor="mp4")


def test_unknown_flavors_and_missing_inputs_are_refused() -> None:
    with pytest.raises(MuxError, match="Unknown container flavor"):
        plan_mux([audio_file()], flavor="webm")  # type: ignore[arg-type]
    with pytest.raises(MuxError, match="no input streams"):
        plan_mux([], flavor="mp4")


def test_the_same_inputs_always_give_the_same_bytes() -> None:
    sources = [video_file(), audio_file()]
    first, second = plan_mux(sources, flavor="mp4"), plan_mux(sources, flavor="mp4")
    assert first == second
    assert PlanSource(first, sources).read(0, first.size) == PlanSource(second, sources).read(
        0, second.size
    )


def test_description_changes_start_new_chunks() -> None:
    track = Track(entries=2)
    fragments = [
        [Traf(1, (Run(tuple(video_samples(1)[:10])),), flags=0x020002, description=1)],
        [Traf(1, (Run(tuple(video_samples(1)[10:])),), flags=0x020002, description=2, tfdt=5120)],
    ]
    sources = [BytesSource(fragmented_file([track], fragments))]
    (video,) = check_file(plan_mux(sources, flavor="mp4"), sources).tracks
    assert [chunk.description for chunk in video.chunks] == [1, 2]
    assert len(video.sample_entries) == 2


def test_plan_sources_read_across_operations() -> None:
    plan = MuxPlan((Blob(b"ab"), CopyOp(0, 2, 3), Blob(b"z")))
    source = PlanSource(plan, [BytesSource(b"0123456")])
    assert (plan.size, source.size) == (6, 6)
    assert source.read(0, 6) == b"ab234z"
    assert source.read(1, 3) == b"b23"
    assert source.read(5, 10) == b"z"
    assert source.read(6, 1) == b""


@pytest.mark.parametrize(
    ("itags", "flavor", "brands"),
    [
        ((137, 140), "mp4", ("isom", "iso2", "avc1", "mp41")),
        ((399, 140), "mp4", ("isom", "iso2", "av01", "mp41")),
        ((137, 140), "mov", ("qt  ",)),
        ((140,), "m4a", ("M4A ", "isom", "iso2", "mp41")),
    ],
)
def test_youtube_streams_mux_cleanly(
    itags: tuple[int, ...], flavor: str, brands: tuple[str, ...]
) -> None:
    sources = [HollowSource.load(itag) for itag in itags]
    parsed = check_file(plan_mux(sources, flavor=flavor), sources)  # type: ignore[arg-type]
    assert parsed.compatible_brands == brands
    if itags[0] == 137:
        (edit,) = parsed.tracks[0].edits
        assert edit.media_time == 512


@pytest.mark.parametrize(
    ("edits", "kwargs", "expected"),
    [
        ((), {}, ()),
        (((0, 1024),), {}, (Edit(3000, 1024),)),
        (((1_000_000, 1024),), {}, (Edit(3000, 1024),)),
        (((1500, 1024),), {}, (Edit(1500, 1024),)),
        (((250, -1), (0, 0)), {}, (Edit(250, -1), Edit(3080, 0))),
        (((0, 5000),), {"first_dts": 4000}, (Edit(3002, 1000),)),
        (((0, 100),), {"first_dts": 4000}, (Edit(3080, 0),)),
        (((0, 50_000),), {}, ()),
        ((), {"lead": Fraction(1, 2)}, (Edit(500, -1), Edit(3080, 0))),
        (((0, 1024),), {"lead": Fraction(2, 3)}, (Edit(666, -1), Edit(3000, 1024))),
    ],
)
def test_convert_edits(
    edits: tuple[tuple[int, int], ...], kwargs: dict[str, object], expected: tuple[Edit, ...]
) -> None:
    arguments: dict[str, object] = {
        "movie_timescale": 1000,
        "timescale": 12800,
        "first_dts": 0,
        "presentation_end": 39424,  # 3.08 s
        "lead": Fraction(0),
    }
    arguments.update(kwargs)
    source = tuple(Edit(duration, media_time) for duration, media_time in edits)
    assert convert_edits(source, **arguments) == expected  # type: ignore[arg-type]


def test_empty_samples_are_listed_but_copy_nothing() -> None:
    samples = [Sample(512, 100), Sample(512, 0, sync=False), Sample(512, 100, sync=False)]
    sources = [BytesSource(simple_file(samples))]
    plan = plan_mux(sources, flavor="mp4")
    (video,) = check_file(plan, sources).tracks
    assert [sample.size for sample in video.samples] == [100, 0, 100]
    assert sum(isinstance(op, CopyOp) for op in plan.ops) == 1


def test_a_track_that_switches_to_an_unsupported_codec_is_refused() -> None:
    data = simple_file([Sample(512, 10)], track=Track(entries=2))
    second = data.index(b"avc1", data.index(b"avc1") + 4)
    mixed = data[:second] + b"hvc1" + data[second + 4 :]
    with pytest.raises(MuxError, match=r"'avc1\+hvc1'"):
        plan_mux([BytesSource(mixed)], flavor="mp4")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/media/test_mux.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'utmax.core.media.mux'`.

- [ ] **Step 3: Implement `mux.py` (media tracks, below 4 GiB)**

`src/utmax/core/media/mux.py`:

```python
"""Plan a progressive MP4, MOV or M4A file from fragmented streams.

:func:`plan_mux` never reads sample data. It indexes the inputs and lays out ``ftyp``, a
"faststart" ``moov`` and one ``mdat`` as a :class:`MuxPlan`: literal bytes (:class:`Blob`) and
byte ranges to copy from the inputs (:class:`CopyOp`), which
``utmax.adapters.files.write_mux_plan`` streams to disk. Chunks hold at most one second of
media and are interleaved by time; tracks keep their source timescales and edit lists
(converted to the 1000 Hz movie timescale); equal inputs give equal bytes. Outputs must stay
below 4 GiB for now.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import accumulate

from utmax.core.media.boxes import U32_MAX, ByteSource, read_exact, u32
from utmax.core.media.fmp4 import Edit, IndexedTrack, index_fragments
from utmax.core.media.moov import (
    MOVIE_TIMESCALE,
    Flavor,
    TrackKind,
    TrackPlan,
    ftyp_box,
    moov_box,
    quicktime_sound_entry,
    unpack_language,
)
from utmax.core.media.tables import chunk_ranges
from utmax.errors import MuxError

__all__ = [
    "FLAVORS",
    "Blob",
    "CopyOp",
    "Flavor",
    "MuxPlan",
    "PlanSource",
    "convert_edits",
    "plan_mux",
]

FLAVORS: tuple[Flavor, ...] = ("mp4", "mov", "m4a")
_MEDIA_CHUNK_SECONDS = 1
_KINDS: dict[tuple[str, str], TrackKind] = {
    ("vide", "avc1"): "video",
    ("vide", "av01"): "video",
    ("soun", "mp4a"): "audio",
}


@dataclass(frozen=True, slots=True)
class CopyOp:
    """Copy ``size`` bytes starting at ``offset`` of input number ``source``."""

    source: int
    offset: int
    size: int


@dataclass(frozen=True, slots=True)
class Blob:
    """Bytes the muxer produced itself (headers, subtitle samples)."""

    data: bytes


@dataclass(frozen=True, slots=True)
class MuxPlan:
    """The output file as an ordered list of operations."""

    ops: tuple[CopyOp | Blob, ...]

    @property
    def size(self) -> int:
        """The size of the output file in bytes."""
        return sum(_op_size(op) for op in self.ops)


class PlanSource:
    """The bytes a :class:`MuxPlan` describes, readable without writing the file."""

    def __init__(self, plan: MuxPlan, sources: Sequence[ByteSource]) -> None:
        self._ops = plan.ops
        self._sources = sources
        self._starts = list(accumulate((_op_size(op) for op in plan.ops), initial=0))
        self.size = self._starts[-1]

    def read(self, offset: int, n: int) -> bytes:
        end = min(offset + n, self.size)
        parts: list[bytes] = []
        index = bisect_right(self._starts, offset) - 1
        while offset < end:
            op, start = self._ops[index], self._starts[index]
            take = min(end, self._starts[index + 1]) - offset
            if isinstance(op, Blob):
                parts.append(op.data[offset - start : offset - start + take])
            else:
                parts.append(read_exact(self._sources[op.source], op.offset + offset - start, take))
            offset += take
            index += 1
        return b"".join(parts)


@dataclass(frozen=True, slots=True)
class _Layout:
    """Where one track's chunks come from: byte ranges of one input."""

    chunks: list[tuple[int, int]]  # (first sample, sample count)
    times: list[Fraction]  # when each chunk starts, in seconds on the movie timeline
    source: int  # input number (media tracks)
    offsets: Sequence[int]  # sample offsets in that input
    sizes: Sequence[int]


def plan_mux(sources: Sequence[ByteSource], *, flavor: Flavor) -> MuxPlan:
    """Plan one progressive file from fragmented MP4 ``sources``.

    Every track of every source is kept in order (YouTube serves one track per stream).

    Raises:
        MuxError: an input is not fragmented MP4, is truncated, uses a codec other than H.264
            (avc1), AV1 (av01) or AAC (mp4a), or does not fit the flavor: video in m4a; AV1,
            multichannel audio or 64-bit durations in mov.
    """
    if flavor not in FLAVORS:
        raise MuxError(f"Unknown container flavor {flavor!r}; use mp4, mov or m4a.")
    if not sources:
        raise MuxError("There is nothing to mux: no input streams were given.")
    inputs = [
        (number, track)
        for number, source in enumerate(sources)
        for track in index_fragments(source)
    ]
    starts = [Fraction(track.samples.dts[0], track.header.timescale) for _, track in inputs]
    origin = min(starts)
    plans: list[TrackPlan] = []
    layouts: list[_Layout] = []
    seen: set[TrackKind] = set()
    for (number, track), start in zip(inputs, starts, strict=True):
        kind = _track_kind(flavor, track)
        plan, layout = _media_track(
            flavor,
            number,
            track,
            track_id=len(plans) + 1,
            kind=kind,
            lead=start - origin,
            enabled=kind not in seen,
        )
        seen.add(kind)
        plans.append(plan)
        layouts.append(layout)
    return _layout(flavor, plans, layouts)


def convert_edits(
    edits: Sequence[Edit],
    *,
    movie_timescale: int,
    timescale: int,
    first_dts: int,
    presentation_end: int,
    lead: Fraction,
) -> tuple[Edit, ...]:
    """A track's edit list on the output timeline (movie timescale 1000).

    Durations become milliseconds, rounded up and cut to the media that exists; media times
    move with the track's first decode time (the output track starts at 0); a positive
    ``lead`` (seconds after the earliest track starts) becomes a leading empty edit, rounded
    down like FFmpeg's.
    """
    converted: list[Edit] = []
    if lead > 0:
        converted.append(Edit(math.floor(lead * MOVIE_TIMESCALE), -1))
    for edit in edits:
        if edit.media_time < 0:
            converted.append(Edit(_to_movie(edit.duration, movie_timescale), -1, edit.rate))
            continue
        media_time = max(edit.media_time - first_dts, 0)
        available = presentation_end - media_time
        if available <= 0:
            continue
        duration = _to_movie(available, timescale)
        if edit.duration:
            duration = min(duration, _to_movie(edit.duration, movie_timescale))
        converted.append(Edit(duration, media_time, edit.rate))
    if lead > 0 and not edits:
        converted.append(Edit(_to_movie(presentation_end, timescale), 0))
    return tuple(converted)


def _track_kind(flavor: Flavor, track: IndexedTrack) -> TrackKind:
    header = track.header
    codecs = {entry[4:8].decode("latin-1") for entry in header.sample_entries}
    kinds = {_KINDS.get((header.handler, codec)) for codec in codecs}
    kind = kinds.pop() if len(kinds) == 1 else None
    if kind is None:
        raise MuxError(
            f"Track {header.track_id} holds {header.handler!r}/{'+'.join(sorted(codecs))!r} "
            "data; only H.264 (avc1) or AV1 (av01) video and AAC (mp4a) audio can be muxed."
        )
    if flavor == "m4a" and kind == "video":
        raise MuxError("An M4A file holds only audio, but an input contains video.")
    if flavor == "mov" and "av01" in codecs:
        raise MuxError(
            "QuickTime .mov files cannot hold AV1 video.",
            suggestion="Download this video as .mp4, or with quality='compat' (H.264).",
        )
    return kind


def _media_track(
    flavor: Flavor,
    number: int,
    track: IndexedTrack,
    *,
    track_id: int,
    kind: TrackKind,
    lead: Fraction,
    enabled: bool,
) -> tuple[TrackPlan, _Layout]:
    header, samples = track.header, track.samples
    first_dts = samples.dts[0]
    dts = [value - first_dts for value in samples.dts]
    media_duration = dts[-1] + samples.durations[-1]
    presentation_end = max(
        decode + offset + duration
        for decode, offset, duration in zip(dts, samples.ctos, samples.durations, strict=True)
    )
    edits = convert_edits(
        header.edits,
        movie_timescale=header.movie_timescale,
        timescale=header.timescale,
        first_dts=first_dts,
        presentation_end=presentation_end,
        lead=lead,
    )
    entries = header.sample_entries
    if flavor == "mov" and kind == "audio":
        frame = Counter(samples.durations).most_common(1)[0][0]  # 1024 for AAC-LC
        entries = tuple(quicktime_sound_entry(entry, samples_per_packet=frame) for entry in entries)
    chunks = chunk_ranges(dts, samples.descriptions, span=_MEDIA_CHUNK_SECONDS * header.timescale)
    visual = kind == "video"
    plan = TrackPlan(
        track_id=track_id,
        kind=kind,
        timescale=header.timescale,
        language=unpack_language(header.language),
        tag=None,
        name=None,
        enabled=enabled,
        matrix=header.matrix,
        width=header.width if visual else 0,
        height=header.height if visual else 0,
        edits=edits,
        duration=(
            sum(edit.duration for edit in edits)
            if edits
            else _to_movie(presentation_end, header.timescale)
        ),
        media_duration=media_duration,
        sample_entries=entries,
        durations=samples.durations,
        ctos=samples.ctos,
        sync=samples.sync,
        sizes=samples.sizes,
        chunks=tuple((count, samples.descriptions[first]) for first, count in chunks),
    )
    times = [lead + Fraction(dts[first], header.timescale) for first, _ in chunks]
    return plan, _Layout(chunks, times, number, samples.offsets, samples.sizes)


def _interleave(layouts: list[_Layout]) -> tuple[list[CopyOp | Blob], list[list[int]]]:
    """The mdat payload in time order, and every chunk's offset from the payload's start."""
    order = sorted(
        (time, track, chunk)
        for track, layout in enumerate(layouts)
        for chunk, time in enumerate(layout.times)
    )
    ops: list[CopyOp | Blob] = []
    offsets = [[0] * len(layout.chunks) for layout in layouts]
    position = 0
    for _, track, chunk in order:
        layout = layouts[track]
        first, count = layout.chunks[chunk]
        offsets[track][chunk] = position
        for sample in range(first, first + count):
            position += _add_copy(
                ops, CopyOp(layout.source, layout.offsets[sample], layout.sizes[sample])
            )
    return ops, offsets


def _layout(flavor: Flavor, plans: list[TrackPlan], layouts: list[_Layout]) -> MuxPlan:
    ops, offsets = _interleave(layouts)
    size = sum(_op_size(op) for op in ops)
    ftyp = ftyp_box(flavor, {plan.sample_entries[0][4:8].decode("latin-1") for plan in plans})
    narrow = [False] * len(plans)
    zeros = [[0] * len(track_offsets) for track_offsets in offsets]
    base = len(ftyp) + len(moov_box(flavor, plans, zeros, narrow)) + 8
    if base + size > U32_MAX:
        raise MuxError("Files larger than 4 GiB are not supported yet.")
    shifted = [[offset + base for offset in track_offsets] for track_offsets in offsets]
    header = ftyp + moov_box(flavor, plans, shifted, narrow) + u32(size + 8) + b"mdat"
    return MuxPlan((Blob(header), *ops))


def _add_copy(ops: list[CopyOp | Blob], op: CopyOp) -> int:
    if op.size == 0:
        return 0
    last = ops[-1] if ops else None
    if (
        isinstance(last, CopyOp)
        and last.source == op.source
        and last.offset + last.size == op.offset
    ):
        ops[-1] = CopyOp(last.source, last.offset, last.size + op.size)
    else:
        ops.append(op)
    return op.size


def _op_size(op: CopyOp | Blob) -> int:
    return op.size if isinstance(op, CopyOp) else len(op.data)


def _to_movie(ticks: int, timescale: int) -> int:
    return -(-ticks * MOVIE_TIMESCALE // timescale)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/media/test_mux.py -q`
Expected: `34 passed`.

- [ ] **Step 5: Gates and full suite**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected: clean gates (35 source files), `605 passed, 6 deselected`.

- [ ] **Step 6: Commit**

```bash
git add src/utmax/core/media/mux.py tests/unit/media/invariants.py tests/unit/media/test_mux.py
git commit -m "feat: plan progressive files from fragmented media streams

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Outputs above 4 GiB

**Files:**
- Modify: `src/utmax/core/media/mux.py` (module docstring, one import line, `_layout`)
- Test: `tests/unit/media/test_mux_large.py`

**Interfaces:**
- Consumes: `plan_mux`, `PlanSource` (Task 9); `virtual_file`, `VirtualSource` (Task 2); `check_file` (Task 9); `u64` (Task 1).
- Produces: no new names. `plan_mux` now writes a 64-bit `mdat` size exactly when `8 + payload > 2^32 − 1`, and gives a track `co64` exactly when its last chunk offset exceeds 2^32 − 1. Because `co64` enlarges the `moov` and moves every chunk, the layout repeats until no further track needs it (at most one round per track).

- [ ] **Step 1: Write the failing tests**

`tests/unit/media/test_mux_large.py`:

```python
"""Files above 4 GiB: co64 and a 64-bit mdat size exactly when needed, checked without writing."""

from __future__ import annotations

from tests.helpers.fmp4_factory import Run, Sample, Track, Traf, VirtualSource, virtual_file
from tests.unit.media.invariants import check_file
from utmax.core.media.boxes import U32_MAX
from utmax.core.media.fmp4 import index_fragments
from utmax.core.media.mux import PlanSource, plan_mux

VIDEO = Track(timescale=1000)
AUDIO = Track(handler="soun", codec="mp4a", timescale=1000)
FRAME = 90_000_000  # one 90 MB "sample" per second: 60 s = 5.4 GB


def stream(track: Track, samples: list[Sample], per_fragment: int = 10) -> VirtualSource:
    fragments = [
        [Traf(1, (Run(tuple(samples[i : i + per_fragment])),), tfdt=i * 1000)]
        for i in range(0, len(samples), per_fragment)
    ]
    return virtual_file([track], fragments)


def big_video(seconds: int = 60) -> VirtualSource:
    return stream(VIDEO, [Sample(1000, FRAME) for _ in range(seconds)])


def small_audio(seconds: int) -> VirtualSource:
    return stream(AUDIO, [Sample(1000, 1000) for _ in range(seconds)])


def test_every_track_that_reaches_past_4_gib_uses_co64() -> None:
    sources = [big_video(), small_audio(60)]
    plan = plan_mux(sources, flavor="mp4")
    assert plan.size > 5_000_000_000
    parsed = check_file(plan, sources, hash_payloads=False)
    assert parsed.boxes[2].header_size == 16
    assert [track.chunk_box for track in parsed.tracks] == ["co64", "co64"]


def test_a_track_that_ends_early_keeps_32_bit_offsets() -> None:
    sources = [big_video(), small_audio(10)]
    parsed = check_file(plan_mux(sources, flavor="mp4"), sources, hash_payloads=False)
    assert [track.chunk_box for track in parsed.tracks] == ["co64", "stco"]
    assert max(chunk.offset for chunk in parsed.tracks[1].chunks) < U32_MAX


def test_a_huge_first_chunk_needs_only_the_64_bit_mdat_size() -> None:
    samples = [Sample(400, 3_900_000_000), Sample(400, 400_000_000)]
    sources = [stream(VIDEO, samples)]
    parsed = check_file(plan_mux(sources, flavor="mp4"), sources, hash_payloads=False)
    assert parsed.boxes[2].header_size == 16
    assert parsed.boxes[2].size > U32_MAX
    assert parsed.tracks[0].chunk_box == "stco"


def test_samples_beyond_4_gib_are_copied_from_the_right_place() -> None:
    sources = [big_video(), small_audio(60)]
    plan = plan_mux(sources, flavor="mp4")
    output = PlanSource(plan, sources)
    parsed = check_file(plan, sources, hash_payloads=False)
    for number, (track, expected) in enumerate(
        zip(parsed.tracks, [index_fragments(source)[0] for source in sources], strict=True)
    ):
        for index in (0, len(track.samples) - 1):
            sample, offset = track.samples[index], expected.samples.offsets[index]
            assert output.read(sample.offset, 64) == sources[number].read(offset, 64)
            end = sample.offset + sample.size
            assert output.read(end - 64, 64) == sources[number].read(offset + sample.size - 64, 64)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/media/test_mux_large.py -q`
Expected: `4 failed`, each with `utmax.errors.MuxError: Files larger than 4 GiB are not supported yet.` The tests take about a second: the 5.4 GB inputs are virtual and nothing is written.

- [ ] **Step 3: Lift the limit**

In `src/utmax/core/media/mux.py`, replace the module docstring with:

```python
"""Plan a progressive MP4, MOV or M4A file from fragmented streams.

:func:`plan_mux` never reads sample data. It indexes the inputs and lays out ``ftyp``, a
"faststart" ``moov`` and one ``mdat`` as a :class:`MuxPlan`: literal bytes (:class:`Blob`) and
byte ranges to copy from the inputs (:class:`CopyOp`), which
``utmax.adapters.files.write_mux_plan`` streams to disk. Chunks hold at most one second of
media and are interleaved by time; tracks keep their source timescales and edit lists
(converted to the 1000 Hz movie timescale); ``co64`` and a 64-bit ``mdat`` size appear
exactly when an offset or size needs them; equal inputs give equal bytes.
"""
```

replace the `utmax.core.media.boxes` import line with:

```python
from utmax.core.media.boxes import U32_MAX, ByteSource, read_exact, u32, u64
```

and replace the whole `_layout` function with:

```python
def _layout(flavor: Flavor, plans: list[TrackPlan], layouts: list[_Layout]) -> MuxPlan:
    ops, offsets = _interleave(layouts)
    size = sum(_op_size(op) for op in ops)
    if size + 8 <= U32_MAX:
        mdat_header = u32(size + 8) + b"mdat"
    else:
        mdat_header = u32(1) + b"mdat" + u64(size + 16)
    ftyp = ftyp_box(flavor, {plan.sample_entries[0][4:8].decode("latin-1") for plan in plans})
    wide = [False] * len(plans)
    while True:  # co64 enlarges the moov and moves every chunk, so repeat until stable
        zeros = [[0] * len(track_offsets) for track_offsets in offsets]
        base = len(ftyp) + len(moov_box(flavor, plans, zeros, wide)) + len(mdat_header)
        needed = [
            flag or (bool(track_offsets) and track_offsets[-1] + base > U32_MAX)
            for flag, track_offsets in zip(wide, offsets, strict=True)
        ]
        if needed == wide:
            break
        wide = needed
    shifted = [[offset + base for offset in track_offsets] for track_offsets in offsets]
    header = ftyp + moov_box(flavor, plans, shifted, wide) + mdat_header
    return MuxPlan((Blob(header), *ops))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/media/test_mux_large.py tests/unit/media/test_mux.py -q`
Expected: `38 passed`.

- [ ] **Step 5: Gates and full suite**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected: clean gates (35 source files), `609 passed, 6 deselected`.

- [ ] **Step 6: Commit**

```bash
git add src/utmax/core/media/mux.py tests/unit/media/test_mux_large.py
git commit -m "feat: use co64 and 64-bit mdat sizes exactly when files pass 4 GiB

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Embedded subtitle tracks

**Files:**
- Modify: `src/utmax/core/media/mux.py` (complete new content below: docstring, imports, `_SUBTITLE_CHUNK_SECONDS`, `_Layout.payloads`, `plan_mux`, new `_subtitle_track`, `_interleave`)
- Test: `tests/unit/media/test_mux_subtitles.py`

**Interfaces:**
- Consumes: `TIMESCALE`, `default_subtitle_index`, `sample_entry`, `subtitle_track` (Task 6); `UNITY_MATRIX` (Task 7); `Transcript`; `InvalidOption`.
- Produces: `plan_mux(sources: Sequence[ByteSource], *, flavor: Flavor, subtitles: Sequence[Transcript] = (), default_subtitle: str | None = None) -> MuxPlan`. Checks run in this order, all before any input is read: flavor, at least one source, no subtitles in `m4a` (`MuxError` "M4A files cannot hold subtitle tracks; write sidecar files instead."), `default_subtitle` (`InvalidOption`). Subtitle tracks follow the media tracks: tx3g, timescale 1000, alternate group 3, `nmhd`, cues clipped to the longest media track (`tkhd` ms), chunks ≤ 10 s interleaved with the media, `hdlr` name and `udta/name` = `track_name`, `elng` = the BCP 47 tag, `mdhd` = ISO code (MOV: QuickTime code when one exists), exactly one enabled.

- [ ] **Step 1: Write the failing tests**

`tests/unit/media/test_mux_subtitles.py`:

```python
"""Tests for embedding transcripts as tx3g subtitle tracks."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tests.helpers.builders import make_transcript
from tests.helpers.fmp4_factory import Sample, Track, simple_file
from tests.helpers.hollow_source import HollowSource
from tests.unit.media.invariants import check_file
from utmax.core.media.boxes import BytesSource
from utmax.core.media.moov import pack_language
from utmax.core.media.mux import PlanSource, plan_mux
from utmax.core.media.progressive import Track as ParsedTrack
from utmax.core.media.tx3g import Cue, decode_sample, normalize_cues, sample_entry
from utmax.errors import InvalidOption, MuxError
from utmax.models import Segment, Transcript

ENGLISH = make_transcript(Segment(0.5, 1.0, "Hello"), Segment(2.0, 0.8, "World\nline two"))
TURKISH = replace(
    make_transcript(
        Segment(0.5, 1.0, "Merhaba"),
        Segment(2.0, 0.8, "D\xfcnya"),
        language_code="tr",
        language="Turkish",
        is_generated=True,
    ),
    translated_from="en",
    translator="claude=claude-opus-5",
)
BILINGUAL = make_transcript(
    Segment(0.5, 1.0, "Hello\nMerhaba"), language_code="en+tr", language="English + Turkish"
)


def media(seconds: int = 3) -> list[BytesSource]:
    video = [Sample(512, 500, sync=i % 25 == 0, cto=1024) for i in range(25 * seconds)]
    audio = [Sample(1024, 200) for _ in range(43 * seconds)]
    audio_track = Track(handler="soun", codec="mp4a", timescale=44100)
    return [
        BytesSource(simple_file(video, per_fragment=25)),
        BytesSource(simple_file(audio, track=audio_track, per_fragment=43)),
    ]


def cues_of(track: ParsedTrack, output: PlanSource) -> list[Cue]:
    cues = []
    for sample in track.samples:
        text = decode_sample(output.read(sample.offset, sample.size))
        if text:
            cues.append(Cue(sample.dts, sample.dts + sample.duration, text))
    return cues


def mux(transcripts: list[Transcript], **options: str) -> tuple[list[ParsedTrack], PlanSource]:
    sources = media()
    plan = plan_mux(sources, flavor=options.pop("flavor", "mp4"), subtitles=transcripts, **options)  # type: ignore[arg-type]
    parsed = check_file(plan, sources)
    return list(parsed.tracks[2:]), PlanSource(plan, sources)


def test_subtitles_follow_the_media_as_tx3g_tracks() -> None:
    tracks, _ = mux([ENGLISH, TURKISH, BILINGUAL])
    assert [track.track_id for track in tracks] == [3, 4, 5]
    assert {(t.handler, t.media_header, t.alternate_group, t.timescale) for t in tracks} == {
        ("sbtl", "nmhd", 3, 1000)
    }
    assert all(track.sample_entries == (sample_entry(),) for track in tracks)
    assert [track.handler_name for track in tracks] == [
        "English",
        "Turkish (AI: claude=claude-opus-5)",
        "English + Turkish",
    ]
    assert [track.name for track in tracks] == [track.handler_name for track in tracks]
    assert [track.extended_language for track in tracks] == ["en", "tr", "mul"]
    assert [track.language for track in tracks] == [
        pack_language("eng"),
        pack_language("tur"),
        pack_language("mul"),
    ]


def test_exactly_one_subtitle_track_is_enabled() -> None:
    assert [t.flags for t in mux([ENGLISH, TURKISH, BILINGUAL])[0]] == [3, 2, 2]
    assert [t.flags for t in mux([ENGLISH, TURKISH], default_subtitle="tr")[0]] == [2, 3]
    both = mux([ENGLISH, TURKISH, BILINGUAL], default_subtitle="EN+TR")[0]
    assert [t.flags for t in both] == [2, 2, 3]


def test_an_unknown_default_subtitle_fails_before_the_inputs_are_read() -> None:
    with pytest.raises(InvalidOption, match="default_subtitle='de'"):
        plan_mux(
            [BytesSource(b"not an mp4")], flavor="mp4", subtitles=[ENGLISH], default_subtitle="de"
        )


def test_m4a_cannot_carry_subtitles() -> None:
    with pytest.raises(MuxError, match="cannot hold subtitle tracks"):
        plan_mux(media()[1:], flavor="m4a", subtitles=[ENGLISH])


def test_subtitle_text_and_timing_round_trip() -> None:
    tracks, output = mux([ENGLISH, TURKISH])
    assert cues_of(tracks[0], output) == list(normalize_cues(ENGLISH.segments))
    assert cues_of(tracks[1], output) == list(normalize_cues(TURKISH.segments))
    assert [sample.duration for sample in tracks[0].samples] == [500, 1000, 500, 800]


def test_subtitles_end_with_the_media() -> None:
    late = make_transcript(
        Segment(2.5, 3.0, "runs past the end"), Segment(10.0, 1.0, "after the end")
    )
    (track,), output = mux([late])
    assert cues_of(track, output) == [Cue(2500, 3080, "runs past the end")]
    assert track.duration == 3080


def test_a_transcript_without_cues_still_gets_a_track() -> None:
    (track,), output = mux([make_transcript()])
    assert [
        (sample.duration, decode_sample(output.read(sample.offset, sample.size)))
        for sample in track.samples
    ] == [(3080, "")]


def test_subtitle_chunks_hold_up_to_ten_seconds() -> None:
    every_second = make_transcript(*(Segment(float(s), 0.5, f"cue {s}") for s in range(25)))
    sources = media(25)
    parsed = check_file(plan_mux(sources, flavor="mp4", subtitles=[every_second]), sources)
    assert len(parsed.tracks[2].chunks) == 3


def test_mov_subtitles_use_quicktime_language_codes() -> None:
    traditional = make_transcript(Segment(0, 1, "x"), language_code="zh-Hant", language="Chinese")
    filipino = make_transcript(Segment(0, 1, "x"), language_code="fil", language="Filipino")
    tracks, _ = mux([TURKISH, traditional, filipino], flavor="mov")
    assert [track.language for track in tracks] == [17, 19, pack_language("fil")]
    assert [track.handler_name for track in tracks][1:] == ["Chinese", "Filipino"]
    assert all(track.data_handler for track in tracks)


def test_youtube_streams_with_subtitles() -> None:
    sources = [HollowSource.load(137), HollowSource.load(140)]
    plan = plan_mux(sources, flavor="mp4", subtitles=[ENGLISH, TURKISH], default_subtitle="tr")
    parsed = check_file(plan, sources)
    assert [track.handler for track in parsed.tracks] == ["vide", "soun", "sbtl", "sbtl"]
    assert [track.flags for track in parsed.tracks] == [3, 3, 2, 3]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/media/test_mux_subtitles.py -q`
Expected: `10 failed`, with `TypeError: plan_mux() got an unexpected keyword argument 'subtitles'`.

- [ ] **Step 3: Add subtitle tracks to the planner**

Replace `src/utmax/core/media/mux.py` with:

```python
"""Plan a progressive MP4, MOV or M4A file from fragmented streams and subtitles.

:func:`plan_mux` never reads sample data. It indexes the inputs and lays out ``ftyp``, a
"faststart" ``moov`` and one ``mdat`` as a :class:`MuxPlan`: literal bytes (:class:`Blob`) and
byte ranges to copy from the inputs (:class:`CopyOp`), which
``utmax.adapters.files.write_mux_plan`` streams to disk. Chunks hold at most one second of
media (ten seconds of subtitles) and are interleaved by time; tracks keep their source
timescales and edit lists (converted to the 1000 Hz movie timescale); ``co64`` and a 64-bit
``mdat`` size appear exactly when an offset or size needs them; equal inputs give equal bytes.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import accumulate

from utmax.core.media.boxes import U32_MAX, ByteSource, read_exact, u32, u64
from utmax.core.media.fmp4 import Edit, IndexedTrack, index_fragments
from utmax.core.media.moov import (
    MOVIE_TIMESCALE,
    UNITY_MATRIX,
    Flavor,
    TrackKind,
    TrackPlan,
    ftyp_box,
    moov_box,
    quicktime_sound_entry,
    unpack_language,
)
from utmax.core.media.tables import chunk_ranges
from utmax.core.media.tx3g import TIMESCALE, default_subtitle_index, sample_entry, subtitle_track
from utmax.errors import MuxError
from utmax.models import Transcript

__all__ = [
    "FLAVORS",
    "Blob",
    "CopyOp",
    "Flavor",
    "MuxPlan",
    "PlanSource",
    "convert_edits",
    "plan_mux",
]

FLAVORS: tuple[Flavor, ...] = ("mp4", "mov", "m4a")
_MEDIA_CHUNK_SECONDS = 1
_SUBTITLE_CHUNK_SECONDS = 10
_KINDS: dict[tuple[str, str], TrackKind] = {
    ("vide", "avc1"): "video",
    ("vide", "av01"): "video",
    ("soun", "mp4a"): "audio",
}


@dataclass(frozen=True, slots=True)
class CopyOp:
    """Copy ``size`` bytes starting at ``offset`` of input number ``source``."""

    source: int
    offset: int
    size: int


@dataclass(frozen=True, slots=True)
class Blob:
    """Bytes the muxer produced itself (headers, subtitle samples)."""

    data: bytes


@dataclass(frozen=True, slots=True)
class MuxPlan:
    """The output file as an ordered list of operations."""

    ops: tuple[CopyOp | Blob, ...]

    @property
    def size(self) -> int:
        """The size of the output file in bytes."""
        return sum(_op_size(op) for op in self.ops)


class PlanSource:
    """The bytes a :class:`MuxPlan` describes, readable without writing the file."""

    def __init__(self, plan: MuxPlan, sources: Sequence[ByteSource]) -> None:
        self._ops = plan.ops
        self._sources = sources
        self._starts = list(accumulate((_op_size(op) for op in plan.ops), initial=0))
        self.size = self._starts[-1]

    def read(self, offset: int, n: int) -> bytes:
        end = min(offset + n, self.size)
        parts: list[bytes] = []
        index = bisect_right(self._starts, offset) - 1
        while offset < end:
            op, start = self._ops[index], self._starts[index]
            take = min(end, self._starts[index + 1]) - offset
            if isinstance(op, Blob):
                parts.append(op.data[offset - start : offset - start + take])
            else:
                parts.append(read_exact(self._sources[op.source], op.offset + offset - start, take))
            offset += take
            index += 1
        return b"".join(parts)


@dataclass(frozen=True, slots=True)
class _Layout:
    """Where one track's chunks come from: an input's byte ranges, or generated payloads."""

    chunks: list[tuple[int, int]]  # (first sample, sample count)
    times: list[Fraction]  # when each chunk starts, in seconds on the movie timeline
    source: int  # input number (media tracks)
    offsets: Sequence[int]  # sample offsets in that input
    sizes: Sequence[int]
    payloads: tuple[bytes, ...] | None = None  # sample bytes of a subtitle track


def plan_mux(
    sources: Sequence[ByteSource],
    *,
    flavor: Flavor,
    subtitles: Sequence[Transcript] = (),
    default_subtitle: str | None = None,
) -> MuxPlan:
    """Plan one progressive file from fragmented MP4 ``sources`` and ``subtitles``.

    Every track of every source is kept in order (YouTube serves one track per stream),
    followed by one tx3g track per transcript; ``default_subtitle`` (a language code) picks the
    subtitle track that is enabled, else the first one is.

    Raises:
        MuxError: an input is not fragmented MP4, is truncated, uses a codec other than H.264
            (avc1), AV1 (av01) or AAC (mp4a), or does not fit the flavor: video or subtitles in
            m4a; AV1, multichannel audio or 64-bit durations in mov.
        InvalidOption: ``default_subtitle`` names none of ``subtitles``.
    """
    if flavor not in FLAVORS:
        raise MuxError(f"Unknown container flavor {flavor!r}; use mp4, mov or m4a.")
    if not sources:
        raise MuxError("There is nothing to mux: no input streams were given.")
    if flavor == "m4a" and subtitles:
        raise MuxError("M4A files cannot hold subtitle tracks; write sidecar files instead.")
    enabled_subtitle = default_subtitle_index(
        [t.language_code for t in subtitles], default_subtitle
    )
    inputs = [
        (number, track)
        for number, source in enumerate(sources)
        for track in index_fragments(source)
    ]
    starts = [Fraction(track.samples.dts[0], track.header.timescale) for _, track in inputs]
    origin = min(starts)
    plans: list[TrackPlan] = []
    layouts: list[_Layout] = []
    seen: set[TrackKind] = set()
    for (number, track), start in zip(inputs, starts, strict=True):
        kind = _track_kind(flavor, track)
        plan, layout = _media_track(
            flavor,
            number,
            track,
            track_id=len(plans) + 1,
            kind=kind,
            lead=start - origin,
            enabled=kind not in seen,
        )
        seen.add(kind)
        plans.append(plan)
        layouts.append(layout)
    limit = max(plan.duration for plan in plans)
    for index, transcript in enumerate(subtitles):
        plan, layout = _subtitle_track(
            transcript, track_id=len(plans) + 1, limit=limit, enabled=index == enabled_subtitle
        )
        plans.append(plan)
        layouts.append(layout)
    return _layout(flavor, plans, layouts)


def convert_edits(
    edits: Sequence[Edit],
    *,
    movie_timescale: int,
    timescale: int,
    first_dts: int,
    presentation_end: int,
    lead: Fraction,
) -> tuple[Edit, ...]:
    """A track's edit list on the output timeline (movie timescale 1000).

    Durations become milliseconds, rounded up and cut to the media that exists; media times
    move with the track's first decode time (the output track starts at 0); a positive
    ``lead`` (seconds after the earliest track starts) becomes a leading empty edit, rounded
    down like FFmpeg's.
    """
    converted: list[Edit] = []
    if lead > 0:
        converted.append(Edit(math.floor(lead * MOVIE_TIMESCALE), -1))
    for edit in edits:
        if edit.media_time < 0:
            converted.append(Edit(_to_movie(edit.duration, movie_timescale), -1, edit.rate))
            continue
        media_time = max(edit.media_time - first_dts, 0)
        available = presentation_end - media_time
        if available <= 0:
            continue
        duration = _to_movie(available, timescale)
        if edit.duration:
            duration = min(duration, _to_movie(edit.duration, movie_timescale))
        converted.append(Edit(duration, media_time, edit.rate))
    if lead > 0 and not edits:
        converted.append(Edit(_to_movie(presentation_end, timescale), 0))
    return tuple(converted)


def _track_kind(flavor: Flavor, track: IndexedTrack) -> TrackKind:
    header = track.header
    codecs = {entry[4:8].decode("latin-1") for entry in header.sample_entries}
    kinds = {_KINDS.get((header.handler, codec)) for codec in codecs}
    kind = kinds.pop() if len(kinds) == 1 else None
    if kind is None:
        raise MuxError(
            f"Track {header.track_id} holds {header.handler!r}/{'+'.join(sorted(codecs))!r} "
            "data; only H.264 (avc1) or AV1 (av01) video and AAC (mp4a) audio can be muxed."
        )
    if flavor == "m4a" and kind == "video":
        raise MuxError("An M4A file holds only audio, but an input contains video.")
    if flavor == "mov" and "av01" in codecs:
        raise MuxError(
            "QuickTime .mov files cannot hold AV1 video.",
            suggestion="Download this video as .mp4, or with quality='compat' (H.264).",
        )
    return kind


def _media_track(
    flavor: Flavor,
    number: int,
    track: IndexedTrack,
    *,
    track_id: int,
    kind: TrackKind,
    lead: Fraction,
    enabled: bool,
) -> tuple[TrackPlan, _Layout]:
    header, samples = track.header, track.samples
    first_dts = samples.dts[0]
    dts = [value - first_dts for value in samples.dts]
    media_duration = dts[-1] + samples.durations[-1]
    presentation_end = max(
        decode + offset + duration
        for decode, offset, duration in zip(dts, samples.ctos, samples.durations, strict=True)
    )
    edits = convert_edits(
        header.edits,
        movie_timescale=header.movie_timescale,
        timescale=header.timescale,
        first_dts=first_dts,
        presentation_end=presentation_end,
        lead=lead,
    )
    entries = header.sample_entries
    if flavor == "mov" and kind == "audio":
        frame = Counter(samples.durations).most_common(1)[0][0]  # 1024 for AAC-LC
        entries = tuple(quicktime_sound_entry(entry, samples_per_packet=frame) for entry in entries)
    chunks = chunk_ranges(dts, samples.descriptions, span=_MEDIA_CHUNK_SECONDS * header.timescale)
    visual = kind == "video"
    plan = TrackPlan(
        track_id=track_id,
        kind=kind,
        timescale=header.timescale,
        language=unpack_language(header.language),
        tag=None,
        name=None,
        enabled=enabled,
        matrix=header.matrix,
        width=header.width if visual else 0,
        height=header.height if visual else 0,
        edits=edits,
        duration=(
            sum(edit.duration for edit in edits)
            if edits
            else _to_movie(presentation_end, header.timescale)
        ),
        media_duration=media_duration,
        sample_entries=entries,
        durations=samples.durations,
        ctos=samples.ctos,
        sync=samples.sync,
        sizes=samples.sizes,
        chunks=tuple((count, samples.descriptions[first]) for first, count in chunks),
    )
    times = [lead + Fraction(dts[first], header.timescale) for first, _ in chunks]
    return plan, _Layout(chunks, times, number, samples.offsets, samples.sizes)


def _subtitle_track(
    transcript: Transcript, *, track_id: int, limit: int, enabled: bool
) -> tuple[TrackPlan, _Layout]:
    track = subtitle_track(transcript, limit=limit)
    durations = [duration for duration, _ in track.samples]
    payloads = tuple(payload for _, payload in track.samples)
    dts = list(accumulate(durations, initial=0))
    chunks = chunk_ranges(dts[:-1], [1] * len(durations), span=_SUBTITLE_CHUNK_SECONDS * TIMESCALE)
    plan = TrackPlan(
        track_id=track_id,
        kind="subtitle",
        timescale=TIMESCALE,
        language=track.language,
        tag=track.tag,
        name=track.name,
        enabled=enabled,
        matrix=UNITY_MATRIX,
        width=0,
        height=0,
        edits=(),
        duration=dts[-1],
        media_duration=dts[-1],
        sample_entries=(sample_entry(),),
        durations=durations,
        ctos=[0] * len(durations),
        sync=bytes([1]) * len(durations),
        sizes=[len(payload) for payload in payloads],
        chunks=tuple((count, 1) for _, count in chunks),
    )
    times = [Fraction(dts[first], TIMESCALE) for first, _ in chunks]
    return plan, _Layout(chunks, times, -1, (), (), payloads)


def _interleave(layouts: list[_Layout]) -> tuple[list[CopyOp | Blob], list[list[int]]]:
    """The mdat payload in time order, and every chunk's offset from the payload's start."""
    order = sorted(
        (time, track, chunk)
        for track, layout in enumerate(layouts)
        for chunk, time in enumerate(layout.times)
    )
    ops: list[CopyOp | Blob] = []
    offsets = [[0] * len(layout.chunks) for layout in layouts]
    position = 0
    for _, track, chunk in order:
        layout = layouts[track]
        first, count = layout.chunks[chunk]
        offsets[track][chunk] = position
        if layout.payloads is not None:
            data = b"".join(layout.payloads[first : first + count])
            ops.append(Blob(data))
            position += len(data)
            continue
        for sample in range(first, first + count):
            position += _add_copy(
                ops, CopyOp(layout.source, layout.offsets[sample], layout.sizes[sample])
            )
    return ops, offsets


def _layout(flavor: Flavor, plans: list[TrackPlan], layouts: list[_Layout]) -> MuxPlan:
    ops, offsets = _interleave(layouts)
    size = sum(_op_size(op) for op in ops)
    if size + 8 <= U32_MAX:
        mdat_header = u32(size + 8) + b"mdat"
    else:
        mdat_header = u32(1) + b"mdat" + u64(size + 16)
    ftyp = ftyp_box(flavor, {plan.sample_entries[0][4:8].decode("latin-1") for plan in plans})
    wide = [False] * len(plans)
    while True:  # co64 enlarges the moov and moves every chunk, so repeat until stable
        zeros = [[0] * len(track_offsets) for track_offsets in offsets]
        base = len(ftyp) + len(moov_box(flavor, plans, zeros, wide)) + len(mdat_header)
        needed = [
            flag or (bool(track_offsets) and track_offsets[-1] + base > U32_MAX)
            for flag, track_offsets in zip(wide, offsets, strict=True)
        ]
        if needed == wide:
            break
        wide = needed
    shifted = [[offset + base for offset in track_offsets] for track_offsets in offsets]
    header = ftyp + moov_box(flavor, plans, shifted, wide) + mdat_header
    return MuxPlan((Blob(header), *ops))


def _add_copy(ops: list[CopyOp | Blob], op: CopyOp) -> int:
    if op.size == 0:
        return 0
    last = ops[-1] if ops else None
    if (
        isinstance(last, CopyOp)
        and last.source == op.source
        and last.offset + last.size == op.offset
    ):
        ops[-1] = CopyOp(last.source, last.offset, last.size + op.size)
    else:
        ops.append(op)
    return op.size


def _op_size(op: CopyOp | Blob) -> int:
    return op.size if isinstance(op, CopyOp) else len(op.data)


def _to_movie(ticks: int, timescale: int) -> int:
    return -(-ticks * MOVIE_TIMESCALE // timescale)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/media/test_mux_subtitles.py tests/unit/media/test_mux.py tests/unit/media/test_mux_large.py -q`
Expected: `48 passed`.

- [ ] **Step 5: Gates, coverage and full suite**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest tests/unit/media --cov=utmax.core.media --cov-branch -q`
Expected: clean gates, `209 passed`, `Total coverage: 100.00%` (every media module is listed as fully covered). Then `uv run pytest -q` → `619 passed, 6 deselected`.

- [ ] **Step 6: Commit**

```bash
git add src/utmax/core/media/mux.py tests/unit/media/test_mux_subtitles.py
git commit -m "feat: embed transcripts as toggleable tx3g subtitle tracks

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Writing plans to disk

**Files:**
- Modify: `src/utmax/adapters/files.py` (complete new content below; `write_text_atomic`, `replace_with_retry` and `REPLACE_RETRY_DELAYS` are unchanged)
- Test: `tests/unit/adapters/test_mux_executor.py` (new; `tests/unit/adapters/test_files.py` stays as it is)

**Interfaces:**
- Consumes: `ByteSource`, `read_exact` (Task 1); `Blob`, `CopyOp`, `MuxPlan`, `PlanSource`, `plan_mux` (Tasks 9–11); M1's `replace_with_retry`.
- Produces (in `utmax.adapters.files`):
  - `COPY_BLOCK_SIZE = 1 << 20`.
  - `FileByteSource(path)` — a `ByteSource` over a file (`.path`, `.size`, `.read(offset, n)`, `.close()`, context manager); one open handle, not thread-safe.
  - `write_mux_plan(plan, sources, path, *, progress: Callable[[int, int], None] | None = None) -> Path` — creates the parent folder, streams `CopyOp`s in 1 MiB `read_exact` blocks and `Blob`s whole into `.<name>.<8 hex>.tmp` next to the target, flushes and fsyncs, then `replace_with_retry(temporary, target)`; `progress(written, total)` after every block; on any exception the temporary file is removed (an existing target stays untouched) and the exception propagates (`MuxError` for a short input).
- M4 will call: `with FileByteSource(video) as v, FileByteSource(audio) as a: write_mux_plan(plan_mux([v, a], flavor=..., subtitles=..., default_subtitle=...), [v, a], target, progress=...)`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/adapters/test_mux_executor.py`:

```python
"""Tests for writing mux plans to disk and reading inputs from files."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.fmp4_factory import Sample, Track, simple_file
from utmax.adapters import files
from utmax.adapters.files import COPY_BLOCK_SIZE, FileByteSource, write_mux_plan
from utmax.core.media.boxes import ByteSource, BytesSource
from utmax.core.media.mux import Blob, CopyOp, MuxPlan, PlanSource, plan_mux
from utmax.errors import MuxError


class RecordingSource:
    def __init__(self, data: bytes) -> None:
        self._inner = BytesSource(data)
        self.size = len(data)
        self.reads: list[tuple[int, int]] = []

    def read(self, offset: int, n: int) -> bytes:
        self.reads.append((offset, n))
        return self._inner.read(offset, n)


def test_file_byte_source_reads_ranges(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4.part"
    path.write_bytes(b"0123456789")
    with FileByteSource(path) as source:
        assert source.size == 10
        assert source.read(3, 4) == b"3456"
        assert source.read(8, 10) == b"89"
        assert source.path == path


def test_writes_exactly_the_planned_bytes(tmp_path: Path) -> None:
    video = simple_file([Sample(512, 700 + i, sync=i == 0) for i in range(30)])
    audio = simple_file(
        [Sample(1024, 90 + i) for i in range(40)],
        track=Track(handler="soun", codec="mp4a", timescale=44100),
    )
    (tmp_path / "v.part").write_bytes(video)
    (tmp_path / "a.part").write_bytes(audio)
    with FileByteSource(tmp_path / "v.part") as v, FileByteSource(tmp_path / "a.part") as a:
        plan = plan_mux([v, a], flavor="mp4")
        target = write_mux_plan(plan, [v, a], tmp_path / "out" / "video.mp4")
        expected = PlanSource(plan, [v, a]).read(0, plan.size)
    assert target == tmp_path / "out" / "video.mp4"
    assert target.read_bytes() == expected
    assert sorted(child.name for child in target.parent.iterdir()) == ["video.mp4"]


def test_copies_stream_in_blocks_and_report_progress(tmp_path: Path) -> None:
    source = RecordingSource(bytes(range(256)) * 10_000)  # 2.56 MB
    plan = MuxPlan((Blob(b"head"), CopyOp(0, 100, 2_500_000), Blob(b"tail")))
    calls: list[tuple[int, int]] = []
    write_mux_plan(plan, [source], tmp_path / "out.bin", progress=lambda d, t: calls.append((d, t)))
    assert all(n <= COPY_BLOCK_SIZE for _, n in source.reads)
    assert source.reads == [(100, 1 << 20), (100 + (1 << 20), 1 << 20), (100 + (2 << 20), 402_848)]
    assert [done for done, _ in calls] == [4, 4 + (1 << 20), 4 + (2 << 20), 2_500_004, 2_500_008]
    assert {total for _, total in calls} == {2_500_008}
    assert (tmp_path / "out.bin").read_bytes() == b"head" + source.read(100, 2_500_000) + b"tail"


def test_existing_files_are_replaced_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "out.m4a"
    target.write_bytes(b"old")
    replaced: list[tuple[Path, Path]] = []
    original = files.replace_with_retry

    def recording(source: Path, destination: Path) -> None:
        replaced.append((source, destination))
        original(source, destination)

    monkeypatch.setattr(files, "replace_with_retry", recording)
    write_mux_plan(MuxPlan((Blob(b"new"),)), [], target)
    assert target.read_bytes() == b"new"
    assert replaced[0][1] == target
    assert replaced[0][0].name.startswith(".out.m4a.")


def test_a_truncated_input_fails_and_leaves_nothing_behind(tmp_path: Path) -> None:
    target = tmp_path / "out.mp4"
    target.write_bytes(b"keep me")
    short: list[ByteSource] = [BytesSource(b"only ten b")]
    with pytest.raises(MuxError, match="ends early"):
        write_mux_plan(MuxPlan((Blob(b"x"), CopyOp(0, 0, 50))), short, target)
    assert target.read_bytes() == b"keep me"
    assert [child.name for child in tmp_path.iterdir()] == ["out.mp4"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/adapters/test_mux_executor.py -q`
Expected: collection error `ImportError: cannot import name 'COPY_BLOCK_SIZE' from 'utmax.adapters.files'`.

- [ ] **Step 3: Implement the executor**

Replace `src/utmax/adapters/files.py` with:

```python
"""Filesystem helpers: atomic writes that tolerate Windows file locks, and muxer output."""

from __future__ import annotations

import io
import os
import secrets
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Self

from utmax.core.media.boxes import ByteSource, read_exact
from utmax.core.media.mux import Blob, CopyOp, MuxPlan

__all__ = [
    "COPY_BLOCK_SIZE",
    "REPLACE_RETRY_DELAYS",
    "FileByteSource",
    "replace_with_retry",
    "write_mux_plan",
    "write_text_atomic",
]

REPLACE_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.6, 3.2)
COPY_BLOCK_SIZE = 1 << 20


def write_text_atomic(path: str | os.PathLike[str], text: str) -> Path:
    """Write ``text`` as UTF-8 with ``\n`` newlines; readers never see a half-written file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def replace_with_retry(
    source: Path,
    target: Path,
    *,
    replace: Callable[[Path, Path], None] = os.replace,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """``os.replace`` that retries while antivirus or indexers briefly hold the file (Windows)."""
    for delay in REPLACE_RETRY_DELAYS:
        try:
            replace(source, target)
        except PermissionError:
            sleep(delay)
        else:
            return
    replace(source, target)


class FileByteSource:
    """A :class:`~utmax.core.media.boxes.ByteSource` over a file on disk; not thread-safe."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._handle: io.BufferedReader = self.path.open("rb")
        self.size = os.fstat(self._handle.fileno()).st_size

    def read(self, offset: int, n: int) -> bytes:
        self._handle.seek(offset)
        return self._handle.read(n)

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def write_mux_plan(
    plan: MuxPlan,
    sources: Sequence[ByteSource],
    path: str | os.PathLike[str],
    *,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Write the file ``plan`` describes to ``path`` and return ``path``.

    Copies stream in 1 MiB blocks into a temporary file next to ``path``, which is flushed to
    disk and then atomically replaces ``path`` (retrying while Windows holds a lock); on any
    error the temporary file is removed. ``progress(written, total)`` runs after each block.

    Raises:
        MuxError: an input is shorter than the plan expects.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    total = plan.size
    written = 0
    try:
        with temporary.open("xb") as handle:
            for op in plan.ops:
                for block in _blocks(op, sources):
                    handle.write(block)
                    written += len(block)
                    if progress is not None:
                        progress(written, total)
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def _blocks(op: CopyOp | Blob, sources: Sequence[ByteSource]) -> Iterator[bytes]:
    if isinstance(op, Blob):
        yield op.data
        return
    end = op.offset + op.size
    for start in range(op.offset, end, COPY_BLOCK_SIZE):
        yield read_exact(sources[op.source], start, min(COPY_BLOCK_SIZE, end - start))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/adapters/test_mux_executor.py tests/unit/adapters/test_files.py -q`
Expected: `10 passed` (5 new + 5 from M1).

- [ ] **Step 5: Gates and full suite**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected: clean gates (35 source files), `624 passed, 6 deselected`. `tests/test_architecture.py` still passes: `adapters` may import `core`.

- [ ] **Step 6: Commit**

```bash
git add src/utmax/adapters/files.py tests/unit/adapters/test_mux_executor.py
git commit -m "feat: stream mux plans to disk atomically

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: ffmpeg integration tests and CI job

**Files:**
- Modify: `pyproject.toml` (the `markers` line only)
- Modify: `.github/workflows/ci.yml` (append one job at the end)
- Test: `tests/unit/media/test_ffmpeg.py`

**Interfaces:**
- Consumes: `FileByteSource`, `write_mux_plan` (Task 12); `plan_mux` (Task 11); `parse_progressive` (Task 8); `to_srt` (M1, read-only); `Flavor` (Task 7).
- Produces: the `ffmpeg` pytest marker; `UTMAX_REQUIRE_FFMPEG=1` makes missing ffmpeg/ffprobe (or a build without `libx264`) a failure instead of a skip; CI job `ffmpeg` on `ubuntu-latest`.
- What the tests prove, for fragments made by `ffmpeg -f lavfi` (`testsrc`, `sine`; H.264 with B-frames, H.264 with `negative_cts_offsets`, AAC, AV1 via `libaom-av1`): `ffprobe -count_packets -show_streams` lists the expected codecs with packet counts equal to utmax's sample counts and to the inputs'; subtitle dispositions, languages and handler names are right; H.264/AAC packet timestamps are identical to the inputs' (relative ones for negative offsets); `ffmpeg -v error … -map 0:v? -map 0:a? -f null -` decodes with an empty stderr; `ffmpeg -map 0:s:N -f srt -` extracts exactly `to_srt(transcript)` (after removing FFmpeg's `<font>` tags) — for mp4, mov and m4a.

- [ ] **Step 1: Write the tests**

`tests/unit/media/test_ffmpeg.py`:

```python
"""End-to-end checks with the real ffmpeg: fragments made by ffmpeg, muxed by utmax, read by ffprobe.

Run with ``uv run pytest -m ffmpeg``. Without ffmpeg and ffprobe on PATH these tests are skipped,
unless ``UTMAX_REQUIRE_FFMPEG=1`` (set in CI) turns the skip into a failure.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from tests.helpers.builders import make_transcript
from utmax.adapters.files import FileByteSource, write_mux_plan
from utmax.core.formats import to_srt
from utmax.core.media.moov import Flavor
from utmax.core.media.mux import plan_mux
from utmax.core.media.progressive import parse_progressive
from utmax.models import Segment, Transcript

pytestmark = pytest.mark.ffmpeg

FRAGMENTED = ["-movflags", "frag_keyframe+empty_moov+default_base_moof"]
ENGLISH = make_transcript(
    Segment(0.5, 1.0, "Hello"), Segment(2.0, 1.2, "World\nsecond line"), Segment(3.3, 0.5, "End")
)
TURKISH = replace(
    make_transcript(
        Segment(0.5, 1.0, "Merhaba"),
        Segment(2.0, 1.2, "D\xfcnya \U0000011f\U0000015f\U00000131"),
        language_code="tr",
        language="Turkish",
        is_generated=True,
    ),
    translated_from="en",
    translator="claude=claude-opus-5",
)


@dataclass(frozen=True)
class Tools:
    ffmpeg: str
    ffprobe: str
    encoders: str


@pytest.fixture(scope="module")
def tools() -> Tools:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        if os.environ.get("UTMAX_REQUIRE_FFMPEG") == "1":
            pytest.fail("UTMAX_REQUIRE_FFMPEG=1 but ffmpeg or ffprobe is not on PATH")
        pytest.skip("ffmpeg and ffprobe are not installed")
    encoders = run([ffmpeg, "-hide_banner", "-encoders"]).stdout
    if "libx264" not in encoders:
        pytest.fail("this ffmpeg build has no libx264 encoder")
    return Tools(ffmpeg, ffprobe, encoders)


@pytest.fixture(scope="module")
def streams(tools: Tools, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    folder = tmp_path_factory.mktemp("fragments")
    video = ["-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=4", "-pix_fmt", "yuv420p"]
    x264 = ["-c:v", "libx264", "-preset", "ultrafast", "-g", "25", "-bf", "2"]
    audio = ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=4", "-ac", "2"]
    made = {
        "h264": [*video, *x264, *FRAGMENTED],
        "h264-negative-cts": [
            *video,
            *x264,
            "-movflags",
            "frag_keyframe+empty_moov+default_base_moof+negative_cts_offsets",
        ],
        "aac": [*audio, "-c:a", "aac", "-b:a", "64k", *FRAGMENTED, "-frag_duration", "1000000"],
    }
    if "libaom-av1" in tools.encoders:
        made["av1"] = [*video, "-c:v", "libaom-av1", "-cpu-used", "8", "-g", "25", *FRAGMENTED]
    paths: dict[str, Path] = {}
    for name, arguments in made.items():
        paths[name] = folder / f"{name}.mp4"
        run(
            [tools.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *arguments, str(paths[name])]
        )
    return paths


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stderr
    return result


def mux(
    inputs: list[Path],
    target: Path,
    flavor: Flavor,
    subtitles: list[Transcript],
    default: str | None = None,
) -> Path:
    sources = [FileByteSource(path) for path in inputs]
    try:
        plan = plan_mux(sources, flavor=flavor, subtitles=subtitles, default_subtitle=default)
        return write_mux_plan(plan, sources, target)
    finally:
        for source in sources:
            source.close()


def probe(tools: Tools, path: Path) -> list[dict[str, Any]]:
    output = run(
        [tools.ffprobe, "-v", "error", "-count_packets", "-show_streams", "-of", "json", str(path)]
    )
    streams: list[dict[str, Any]] = json.loads(output.stdout)["streams"]
    return streams


def packet_times(tools: Tools, path: Path, stream: str) -> list[tuple[int, int]]:
    output = run(
        [
            tools.ffprobe,
            "-v",
            "error",
            "-select_streams",
            stream,
            "-show_entries",
            "packet=pts,dts",
            "-of",
            "csv=p=0",
            str(path),
        ]
    )
    return [
        (int(pts), int(dts)) for pts, dts, *_ in (line.split(",") for line in output.stdout.split())
    ]


def decodes_cleanly(tools: Tools, path: Path) -> None:
    result = run(
        [
            tools.ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v?",
            "-map",
            "0:a?",
            "-f",
            "null",
            "-",
        ]
    )
    assert result.stderr == ""


def extracted_srt(tools: Tools, path: Path, index: int) -> str:
    output = run(
        [tools.ffmpeg, "-v", "error", "-i", str(path), "-map", f"0:s:{index}", "-f", "srt", "-"]
    )
    return re.sub(r"</?font[^>]*>", "", output.stdout).strip()


def test_mp4_with_two_subtitle_tracks(
    tools: Tools, streams: dict[str, Path], tmp_path: Path
) -> None:
    out = mux(
        [streams["h264"], streams["aac"]], tmp_path / "out.mp4", "mp4", [ENGLISH, TURKISH], "tr"
    )
    info = probe(tools, out)
    assert [s["codec_name"] for s in info] == ["h264", "aac", "mov_text", "mov_text"]
    with FileByteSource(out) as output:
        parsed = parse_progressive(output)
    assert [int(s["nb_read_packets"]) for s in info] == [len(t.samples) for t in parsed.tracks]
    sources = probe(tools, streams["h264"]) + probe(tools, streams["aac"])
    assert [s["nb_read_packets"] for s in info[:2]] == [s["nb_read_packets"] for s in sources]
    assert [s["disposition"]["default"] for s in info[2:]] == [0, 1]
    assert [s["tags"]["language"] for s in info[2:]] == ["eng", "tur"]
    assert info[3]["tags"]["handler_name"] == "Turkish (AI: claude=claude-opus-5)"
    assert packet_times(tools, out, "v:0") == packet_times(tools, streams["h264"], "v:0")
    decodes_cleanly(tools, out)
    assert extracted_srt(tools, out, 0) == to_srt(ENGLISH.segments).strip()
    assert extracted_srt(tools, out, 1) == to_srt(TURKISH.segments).strip()


def test_mov_with_a_subtitle_track(tools: Tools, streams: dict[str, Path], tmp_path: Path) -> None:
    out = mux([streams["h264"], streams["aac"]], tmp_path / "out.mov", "mov", [TURKISH])
    info = probe(tools, out)
    assert [s["codec_name"] for s in info] == ["h264", "aac", "mov_text"]
    assert info[2]["tags"]["language"] == "tur"
    assert info[2]["tags"]["handler_name"] == "Turkish (AI: claude=claude-opus-5)"
    assert packet_times(tools, out, "a:0") == packet_times(tools, streams["aac"], "a:0")
    decodes_cleanly(tools, out)
    assert extracted_srt(tools, out, 0) == to_srt(TURKISH.segments).strip()


def test_m4a(tools: Tools, streams: dict[str, Path], tmp_path: Path) -> None:
    out = mux([streams["aac"]], tmp_path / "out.m4a", "m4a", [])
    (audio,) = probe(tools, out)
    assert audio["codec_name"] == "aac"
    assert audio["nb_read_packets"] == probe(tools, streams["aac"])[0]["nb_read_packets"]
    decodes_cleanly(tools, out)


def test_negative_composition_offsets(
    tools: Tools, streams: dict[str, Path], tmp_path: Path
) -> None:
    source = streams["h264-negative-cts"]
    out = mux([source, streams["aac"]], tmp_path / "negative.mp4", "mp4", [])
    with FileByteSource(out) as output:
        assert parse_progressive(output).tracks[0].ctts_version == 1
    decodes_cleanly(tools, out)
    before, after = packet_times(tools, source, "v:0"), packet_times(tools, out, "v:0")
    assert [pts - before[0][0] for pts, _ in before] == [pts - after[0][0] for pts, _ in after]


def test_av1(tools: Tools, streams: dict[str, Path], tmp_path: Path) -> None:
    if "av1" not in streams:
        pytest.skip("this ffmpeg build has no libaom-av1 encoder")
    out = mux([streams["av1"], streams["aac"]], tmp_path / "av1.mp4", "mp4", [ENGLISH])
    assert [s["codec_name"] for s in probe(tools, out)] == ["av1", "aac", "mov_text"]
    with FileByteSource(out) as output:
        brands = parse_progressive(output).compatible_brands
    assert brands == ("isom", "iso2", "av01", "mp41")
    decodes_cleanly(tools, out)
```

- [ ] **Step 2: Run them to verify the marker is missing**

Run: `uv run pytest -m ffmpeg -q`
Expected: a collection error saying that `'ffmpeg'` is not found in the `markers` configuration option (the suite runs with `--strict-markers`).

- [ ] **Step 3: Register the marker**

In `pyproject.toml`, replace the line

```toml
markers = ["live: talks to the real YouTube API; run with `uv run pytest -m live`"]
```

with

```toml
markers = ["live: talks to the real YouTube API; run with `uv run pytest -m live`", "ffmpeg: needs ffmpeg and ffprobe on PATH; run with `uv run pytest -m ffmpeg`"]
```

(one line, so it cannot conflict with M2's edits elsewhere in the file).

- [ ] **Step 4: Run the ffmpeg tests**

Run: `uv run pytest -m ffmpeg -v`
Expected (ffmpeg 9.0 is installed on the development machine): `5 passed, 630 deselected` — `test_mp4_with_two_subtitle_tracks`, `test_mov_with_a_subtitle_track`, `test_m4a`, `test_negative_composition_offsets`, `test_av1`. Without ffmpeg on PATH they are skipped; `UTMAX_REQUIRE_FFMPEG=1 uv run pytest -m ffmpeg` then errors instead.

- [ ] **Step 5: Add the CI job**

Append to `.github/workflows/ci.yml` (after the `build` job, same indentation as the other jobs):

```yaml

  ffmpeg:
    name: muxer vs ffmpeg
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10.2.0
        with:
          python-version: "3.14"
      - name: Install ffmpeg
        run: sudo apt-get update && sudo apt-get install --yes --no-install-recommends ffmpeg
      - run: uv sync --locked
      - run: uv run pytest -m ffmpeg -v
        env:
          UTMAX_REQUIRE_FFMPEG: "1"
```

The job cannot fail with "no tests collected": the five `ffmpeg`-marked tests exist from this task on, and `-m ffmpeg` on the command line overrides the `-m "not live"` in `addopts` (the last `-m` wins). Ubuntu's ffmpeg package includes `libx264`, the native AAC encoder and `libaom-av1`. Check the YAML: `uv run --no-project --with pyyaml python -c "import yaml; print(list(yaml.safe_load(open('.github/workflows/ci.yml'))['jobs']))"` → `['lint', 'test', 'build', 'ffmpeg']`.

- [ ] **Step 6: Gates and full suite**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
Expected: clean gates, `629 passed, 6 deselected` with ffmpeg installed (`624 passed, 5 skipped, 6 deselected` without).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .github/workflows/ci.yml tests/unit/media/test_ffmpeg.py
git commit -m "test: check muxed files with ffmpeg and ffprobe, locally and in CI

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Player matrix and M3 verification

**Files:**
- Modify: only files that the checks below prove wrong (inside M3's ownership list).
- Not committed: the player-matrix helper and its output live outside the repository.

**Interfaces:**
- Consumes: everything above.
- Produces: evidence that M3 meets spec §9 — all invariants, clean ffprobe decoding, tx3g round trip, the `co64` path, green gates and ffmpeg job, and the manual player matrix recorded in the final report (and in the PR description when the user merges `m3-muxer`; M3 may not add documentation files outside its ownership list).

- [ ] **Step 1: Run every gate**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov --cov-report=term-missing
uv run coverage report --include="*/utmax/core/*" --fail-under=95
uv run coverage report --include="*/utmax/core/media/*,*/utmax/adapters/files.py"
```

Expected: clean lint, format and types (35 source files); `629 passed, 6 deselected`; total coverage above 99 % (the run fails below 90 %); core above 95 %; the media package and `files.py` at 100 %. If a line is uncovered, add a test for the behaviour instead of excluding it.

- [ ] **Step 2: Make the player-matrix files**

Save this helper outside the repository, e.g. as `%TEMP%\utmax-player-matrix\make_matrix.py` (it is a manual tool, not part of the package):

```python
"""Make the M3 player-matrix files. Not part of the repository: run it from the repo root with

    uv run python <this file> <output folder>        (needs ffmpeg on PATH)
    uv run python <this file> <output folder> --youtube   (also a real YouTube clip; network)
"""

from __future__ import annotations

import struct
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from utmax.adapters.files import FileByteSource, write_mux_plan
from utmax.adapters.http import RetryingTransport, UrllibTransport
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.clients import ANDROID_VR
from utmax.core.media.mux import Flavor, plan_mux
from utmax.models import Segment, Transcript, VideoInfo
from utmax.transport import HttpRequest

VIDEO = VideoInfo("dQw4w9WgXcQ", "Player matrix", "utmax", "UC", 10.0, False)
ENGLISH = Transcript(
    VIDEO,
    "en",
    "English",
    False,
    (Segment(0.5, 2.0, "English line one"), Segment(3.0, 2.0, "English line two\nsecond row")),
)
TURKISH = replace(
    ENGLISH,
    language_code="tr",
    language="Turkish",
    is_generated=True,
    segments=(
        Segment(0.5, 2.0, "T\xfcrk\xe7e sat\U00000131r bir"),
        Segment(3.0, 2.0, "\U0000011f\xfc\U0000015f\U00000131\xf6\xe7 \U0000266a"),
    ),
    translated_from="en",
    translator="claude=claude-opus-5",
)
BILINGUAL = replace(
    ENGLISH,
    language_code="en+tr",
    language="English + Turkish",
    segments=(Segment(0.5, 2.0, "English line one\nT\xfcrk\xe7e sat\U00000131r bir"),),
)
FRAGMENTED = ["-movflags", "frag_keyframe+empty_moov+default_base_moof"]


def ffmpeg(*arguments: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *arguments], check=True)


def mux(inputs: list[Path], target: Path, flavor: Flavor, subtitles: list[Transcript]) -> None:
    sources = [FileByteSource(path) for path in inputs]
    try:
        plan = plan_mux(sources, flavor=flavor, subtitles=subtitles, default_subtitle="tr" if subtitles else None)
        write_mux_plan(plan, sources, target)
    finally:
        for source in sources:
            source.close()
    print("wrote", target)


def lavfi(out: Path) -> None:
    video = ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=10", "-pix_fmt", "yuv420p"]
    audio = ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=10", "-ac", "2"]
    ffmpeg(*video, "-c:v", "libx264", "-preset", "veryfast", "-g", "50", "-bf", "2", *FRAGMENTED, str(out / "h264.frag.mp4"))
    ffmpeg(*audio, "-c:a", "aac", "-b:a", "128k", *FRAGMENTED, "-frag_duration", "1000000", str(out / "aac.frag.mp4"))
    ffmpeg(*video, "-c:v", "libaom-av1", "-cpu-used", "8", "-g", "50", *FRAGMENTED, str(out / "av1.frag.mp4"))
    subtitles = [ENGLISH, TURKISH, BILINGUAL]
    mux([out / "h264.frag.mp4", out / "aac.frag.mp4"], out / "matrix.mp4", "mp4", subtitles)
    mux([out / "h264.frag.mp4", out / "aac.frag.mp4"], out / "matrix.mov", "mov", subtitles)
    mux([out / "aac.frag.mp4"], out / "matrix.m4a", "m4a", [])
    mux([out / "av1.frag.mp4", out / "aac.frag.mp4"], out / "matrix-av1.mp4", "mp4", subtitles)


def youtube(out: Path, fragments: int = 2) -> None:
    transport = RetryingTransport(UrllibTransport(timeout=30.0))
    player = InnerTubeClient(transport).player_json(ANDROID_VR, VIDEO.video_id)
    formats = {f.get("itag"): f for f in player["streamingData"]["adaptiveFormats"]}
    for itag in (137, 140):
        fmt = formats[itag]
        index_end = int(fmt["indexRange"]["end"])
        head = get(transport, fmt["url"], 0, index_end + 1)
        sidx = head[int(fmt["indexRange"]["start"]) :]
        version = sidx[8]
        position = 20 + (8 if version == 0 else 16)
        (count,) = struct.unpack_from(">H", sidx, position + 2)
        sizes = [struct.unpack_from(">I", sidx, position + 4 + 12 * i)[0] & 0x7FFF_FFFF for i in range(count)]
        body = get(transport, fmt["url"], index_end + 1, sum(sizes[:fragments]))
        (out / f"{itag}.frag.mp4").write_bytes(head + body)
    inputs = [out / "137.frag.mp4", out / "140.frag.mp4"]
    mux(inputs, out / "youtube.mp4", "mp4", [ENGLISH, TURKISH, BILINGUAL])
    mux(inputs, out / "youtube.mov", "mov", [ENGLISH, TURKISH, BILINGUAL])


def get(transport: RetryingTransport, url: str, start: int, length: int) -> bytes:
    headers = {"Range": f"bytes={start}-{start + length - 1}", "User-Agent": ANDROID_VR.user_agent}
    response = transport.send(HttpRequest("GET", url, headers))
    if response.status not in (200, 206) or len(response.body) < length:
        raise SystemExit(f"stream request failed with HTTP {response.status}")
    return response.body[:length]


if __name__ == "__main__":
    folder = Path(sys.argv[1]).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    lavfi(folder)
    if "--youtube" in sys.argv:
        youtube(folder)
```

Run from the repository root: `uv run python "%TEMP%\utmax-player-matrix\make_matrix.py" "%TEMP%\utmax-player-matrix" --youtube` (Git Bash: `"$TEMP/utmax-player-matrix/..."`).
Expected: six `wrote …` lines: `matrix.mp4` and `matrix.mov` (10 s 720p H.264 with B-frames + AAC + English, Turkish (AI) and English + Turkish tracks, Turkish enabled), `matrix.m4a`, `matrix-av1.mp4`, and `youtube.mp4`/`youtube.mov` made from the first two real fragments of itags 137 and 140 (≈10 s of video, 20 s of audio; drop `--youtube` without network). Check each with `ffprobe -v error -show_entries stream=codec_name:stream_tags=language,handler_name -of compact <file>`.

- [ ] **Step 3: Ask the user to run the player matrix**

The checks need a person at the screen. Send the user the folder path and this table to fill in (one cell per file and player: ✓, ✗ with a note, or n/a):

| File | VLC | mpv | QuickTime (macOS) or IINA | Films & TV (Windows) | Chrome (drag the file in) |
|---|---|---|---|---|---|
| `matrix.mp4` | | | | | |
| `matrix.mov` | | | | | |
| `matrix.m4a` | | | | | |
| `matrix-av1.mp4` | | | | | |
| `youtube.mp4` | | | | | |
| `youtube.mov` | | | | | |

For every video cell check: plays from start to end; audio in sync (the lavfi clips beep continuously while the counter runs); three subtitle tracks listed with their names or languages; Turkish on by default; switching to English, to "English + Turkish" (two lines) and off works; seeking keeps subtitles in step; Turkish characters (ğ ü ş ı ö ç) and ♪ render. Chrome plays MP4 and M4A but shows no tx3g subtitles (write "n/a" there); QuickTime does not open AV1 on older Macs (write what happens). Any ✗ is a bug to fix in M3 (for example a player that ignores unnamed tracks, or a QuickTime language quirk): reproduce it with the matching test, fix, rerun Step 1.

- [ ] **Step 4: Ask before pushing, then watch CI**

Ask the user for approval to push branch `m3-muxer`. Only after an explicit yes:

```bash
git push -u origin m3-muxer
gh run watch --exit-status
```

Expected: `lint`, every `test (…)` job, `build` and the new `muxer vs ffmpeg` job succeed. If a job fails, reproduce it locally, fix it inside M3's ownership list, commit and push again (the push to this branch was approved in this step).

- [ ] **Step 5: Report**

Summarise for the user: test counts, total/core/media coverage, the ffmpeg job result (or that the push awaits approval), the filled player matrix, the FFmpeg revision the byte layouts were checked against (`b87602a63a52`), and the decisions listed above that M4 must know (stereo AAC for `.mov`; call `default_subtitle_index` before downloading; `FileByteSource` is not thread-safe).

---

## Out of scope for M3 (later milestones, per the spec)

- `download()`, stream selection, the parallel downloader, `.part` files, resume, progress aggregation, cancellation during the final write, sidecar `.srt` files and `mp3` via ffmpeg → M4. M4 opens the downloaded streams with `FileByteSource`, validates `default_subtitle` with `utmax.core.media.tx3g.default_subtitle_index` before any download starts, calls `plan_mux` and `write_mux_plan`, maps `MuxError` into the download flow, and should prefer stereo AAC (itag 140) for `.mov` because SoundDescription version 2 is not implemented.
- Metadata and cover art, chapters, hardsub, styled tx3g (`styl` boxes), WebM/VP9 inputs, SoundDescription v2 and the `chan` box → not in 0.1.0 (spec §10 "Deferred").
