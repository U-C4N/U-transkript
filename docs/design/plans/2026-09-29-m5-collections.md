# M5 — Collections Implementation Plan

**Goal:** `utmax.list_videos()` lists the videos of a playlist or a channel (all uploads, long-form videos, Shorts or past live streams), and `utmax.fetch_many()`, `translate_many()` and `download_many()` run the one-video calls over many videos in parallel, skip files that already exist, and stop when YouTube blocks the IP address; the same calls exist on `utmax.Client`.

**Architecture:** Pure core modules decide: `core/ids.py` finds the playlist or channel in a pasted source (`parse_source`) and names a channel's upload lists, `core/browse.py` reads ANDROID_VR and WEB `browse` pages and decides when a listing is complete (`Pager`), and `core/filenames.py` fills in bulk file-name templates and turns them into skip patterns. `adapters/innertube.py` sends the `browse` and `navigation/resolve_url` requests. `services/collections.py` lists a playlist with ANDROID_VR (WEB lists it again when ANDROID_VR fails), and `services/bulk.py` runs one job per video on a thread pool with skip-existing, a circuit breaker and Ctrl-C handling, for transcripts, translations and downloads. `Client` and the `utmax` facade expose the four calls.

**Tech Stack:** Python ≥ 3.11 standard library (`concurrent.futures`, `threading`, `string.Formatter`, `fnmatch`, `json`, `urllib.parse`) · pytest · ruff · mypy (strict) · uv.

**Spec:** `docs/design/2026-09-27-u-transcript-max-design.md` — read §2 (verified browse facts), §4.1 (`list_videos`, `fetch_many`, `translate_many`, `download_many`), §4.3 (`VideoEntry`, `VideoList`, `BulkResult`, `BulkReport`), §5 ("Identifiers" `parse_source`, "InnerTube" browse/resolve fallback, "Collections"), §6 (errors), §7 (logging), §8 items 2, 5 and 10, and §9 row M5 before starting. Prerequisites: M1–M4 are merged into `v4`; M2's translation engine and M4's `DownloadService`, `Target` and `safe_name` are reused with the small extensions below.

## Global Constraints

- `requires-python = ">=3.11"`; zero runtime dependencies; `src/utmax` imports only the standard library; M5 adds no runtime or dev dependency and does not touch `pyproject.toml` or `uv.lock` (the `live` marker already exists).
- `utmax.core` stays pure: no network, subprocess, threads, clock or filesystem; `tests/test_architecture.py` bans `asyncio concurrent http.* socket ssl subprocess threading time shutil tempfile urllib.request urllib.error` and the outer layers (so `core/filenames.py` escapes globs with a regular expression instead of importing `glob`). Adapters may import core and other adapters, never `utmax.services` or `utmax.client`; services may import adapters and core.
- M5 works on branch `m5-collections` in the worktree `.worktrees/m5-collections`, cut from `v4` after this plan was committed. It creates or edits only: `src/utmax/models.py`, `src/utmax/errors.py`, `src/utmax/__init__.py`, `src/utmax/client.py`, `src/utmax/core/ids.py`, `src/utmax/core/browse.py`, `src/utmax/core/filenames.py`, `src/utmax/adapters/innertube.py`, `src/utmax/services/collections.py`, `src/utmax/services/bulk.py`, `src/utmax/services/translation.py`, `src/utmax/services/download.py`, `scripts/record_fixtures.py`, `tests/fixtures/youtube/README.md`, the seven new `tests/fixtures/youtube/browse_*.json` and `resolve_*.json` files, `tests/helpers/browse.py`, `tests/helpers/bulk.py`, `tests/helpers/files.py`, the three folder checks of `tests/unit/services/test_download_audio.py` (Task 10), and new test files under `tests/unit/**` and `tests/live/`. It does not edit `.github/workflows/**`, other source files or other existing test files.
- Errors: every failure raises a `utmax.errors` class with an English message. Bad arguments raise `InvalidSource`, `InvalidOption`, `UnsupportedFormat` or `InvalidModelSpec` (and `.mp3` without ffmpeg `FFmpegNotFound`) before any network request. A bulk call reports one video's failure in that video's `BulkResult` instead of raising it.
- Log through `logging.getLogger("utmax.youtube")` (listings) and `logging.getLogger("utmax.bulk")` (bulk runs). The library never prints.
- Files: transcripts are written with `Transcript.save` (atomic, UTF-8, `\n` line endings); downloads keep M4's rules (`.part` files, atomic replace).
- Non-ASCII characters appear in Python source only as escapes. This plan writes them as `\xXX` or `\U0000XXXX` (eight hex digits) on purpose: editing tools silently turn four-digit backslash-u escapes into raw characters (it happened again while this plan was prepared). Copy the escapes exactly. The JSON fixtures hold raw UTF-8 (emoji in Shorts titles): write them as UTF-8 exactly as shown.
- Lint lessons from M1–M4, applied below: `pytest.raises` with a specific exception and a `match=` pattern that is raw or free of regex metacharacters (for example `match=r"uses \{language_code\}"`), no unused `noqa`, at most five positional parameters (the rest keyword-only), `filterwarnings = error`, `docs/` excluded from ruff. After writing a file run `uv run ruff format <file>`: the code below is already formatted, so a formatter change points at a transcription slip.
- Edits: "Replace … with …" steps quote the old text exactly; each old block occurs exactly once in the file at that point, and the blocks of one step are applied in the order given.
- Gates after every task: `uv run ruff check .` · `uv run ruff format --check .` · `uv run mypy` · `uv run pytest` (branch coverage ≥ 90 %). At the end: `uv run pytest --cov` then `uv run coverage report --include="*/utmax/core/*" --fail-under=95`. Each task gives the exact number of its new tests and the suite total afterwards (the baseline on `v4` is 1110 passed, 15 deselected with all extras installed). If a count differs, find out why before moving on.
- Windows only: security software on some machines shows a file that was just deleted, for a fraction of a second, under its name in capitals plus `.tmp` (for example `RICK.M4A.140.PART.JSON.tmp`; utmax never creates such a name). A test that compares a whole folder listing right after a download then fails now and then: M4's `test_download_audio.py` did three times in about twenty-five full runs while this plan was verified. Task 10 adds `tests/helpers/files.py::folder_names`, which leaves out exactly these names, and uses it in those three checks and in M5's own. If another folder check fails this way, rerun it before investigating.
- Commits use a conventional prefix (`feat:`, `test:`), stage explicit paths only (never `git add -A` or `.`) and end with the trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Never push, merge or publish without the user's explicit approval.

## Review Focus

1. **Links people paste** — channel tabs (`/@RickAstleyYT/shorts`, `/channel/UC…/videos`, `/c/name/featured`), `m.`/`music.` hosts, links without a scheme or starting with `//`, `youtu.be/…?list=…`, a watch link inside a playlist, Mix links (`list=RD…`), percent-encoded handles, a plain video link → the right playlist or channel, or a clear `InvalidSource`/`CollectionUnavailable`, always before any request. Pinned in Task 2 (`test_playlists`, `test_channels`, `test_mixes_are_refused_before_any_request`, `test_anything_else_is_invalid`, `test_single_videos_point_to_fetch_and_download`).
2. **Listings that break or change shape** — ANDROID_VR answering an unreadable page, a server error, or failing on page two; WEB's older continuation shape; a continuation token that repeats or never ends; private videos and repeated videos → one complete, numbered listing from a single client, never half a list glued from two. Pinned in Task 4 (`test_unplayable_and_foreign_items_are_counted_but_skipped`, `test_older_web_pages_continue_through_a_continuation_item_renderer`), Task 5 (all Pager tests) and Task 6 (`test_web_takes_over_when_android_vr_fails`, `test_web_restarts_the_listing_when_android_vr_fails_midway`, `test_an_unreadable_first_page_falls_back_to_web`, `test_the_page_cap_stops_endless_listings`).
3. **Playlists and channels that cannot be listed** — an unknown handle, a mistyped channel ID, a channel without Shorts or live streams, a channel without uploads, a private or deleted playlist, a rate limit → `CollectionNotFound`, `CollectionUnavailable` with YouTube's reason, an empty list, or `IpBlocked` at once. Pinned in Task 6 (`test_missing_playlists_are_not_found`, `test_youtube_alerts_explain_unviewable_playlists`, `test_channels_without_shorts_list_nothing`, `test_channels_without_uploads_are_not_found`, `test_unknown_handles_are_not_found_without_browsing`, `test_rate_limits_stop_the_listing_at_once`).
4. **Running a bulk job again into the same folder** — files from an earlier run (possibly in another language or for another target language), titles containing `[` or `*`, `{index}` templates, a video listed twice, a half-finished download → a video is skipped without any request only when its file really exists; everything else runs, and interrupted downloads resume. Pinned in Task 7 (`test_patterns_escape_what_is_known_and_match_the_rest`, `test_glob_literals_match_only_themselves`), Task 9 (`test_existing_files_are_skipped_without_a_request`, `test_the_requested_languages_decide_which_files_count`, `test_translate_many_skips_what_it_would_write`) and Task 10 (`test_existing_downloads_are_skipped_without_a_request`).
5. **Long bulk runs that go wrong** — YouTube blocks the IP address half-way, an API key is rejected, one video is private, the user presses Ctrl-C, a progress callback raises → the other videos still finish (or are reported as not attempted after a block), nothing hangs, Ctrl-C propagates once the running videos stopped, and the report keeps the input order. Pinned in Task 8 (`test_a_block_stops_the_run`, `test_ctrl_c_or_a_progress_error_stops_the_run`, `test_ctrl_c_while_the_videos_are_queued_stops_the_run`, `test_items_that_need_no_work_are_decided_first`), Task 9 (`test_a_block_stops_fetch_many`, `test_a_rejected_api_key_stops_translate_many`) and Task 10 (`test_ctrl_c_stops_the_downloads`, `test_failures_are_reported_and_blocks_stop_the_run`).

## Verified facts this plan relies on

**YouTube** (read-only probes on 2026-09-28 and 2026-09-29):

- `POST /youtubei/v1/browse?prettyPrint=false` with `browseId` = `"VL"` + a playlist ID needs no API key. ANDROID_VR answers `contents.singleColumnBrowseResultsRenderer` → `playlistVideoListRenderer` with 20 `playlistVideoRenderer` items a page (`videoId`, `title.runs`, `index`, `shortBylineText.runs[].navigationEndpoint.browseEndpoint.browseId`, `lengthSeconds` as a string, `isPlayable`), the next token in `continuations[].nextContinuationData.continuation`, and the following pages under `continuationContents.playlistVideoListContinuation`.
- WEB answers `contents.twoColumnBrowseResultsRenderer` with 100 `lockupViewModel` items a page (`contentId`; the duration only as a thumbnail badge such as `"3:51"`; the title in `metadata.lockupMetadataViewModel.title.content`; the channel in a metadata part whose `commandRuns[].onTap.innertubeCommand.browseEndpoint.browseId` is the channel ID), a `continuationItemViewModel` (`continuationCommand.innertubeCommand.continuationCommand.token`) as the last item, and the following pages under `onResponseReceivedActions[].appendContinuationItemsAction.continuationItems`. Older WEB pages used `continuationItemRenderer.continuationEndpoint.continuationCommand.token`.
- Headers: ANDROID_VR uses `header.playlistHeaderRenderer` for every list (`title.runs`, `numVideosText` such as `"139 videos"` or `"1 video"`, `ownerText.runs`). WEB uses the same renderer (with `title.simpleText`) for a channel's upload lists but `header.pageHeaderRenderer` for regular playlists (`pageTitle`, and the count as a metadata text `"10 videos"`); WEB also sends `metadata.playlistMetadataRenderer.title`.
- WEB lists a channel's Shorts (`UUSH…`) as `richGridRenderer` → `richItemRenderer.content.shortsLockupViewModel` (`onTap.innertubeCommand.reelWatchEndpoint.videoId`, `overlayMetadata.primaryText.content`), without duration or channel; ANDROID_VR lists them as ordinary `playlistVideoRenderer` items with `lengthSeconds`.
- A channel's upload lists are `UU` (all), `UULF` (long-form videos), `UUSH` (Shorts) and `UULV` (past live streams) followed by the channel ID without its `UC`. Complete ANDROID_VR listings of `@RickAstleyYT` on 2026-09-29 matched the header counts exactly: all 438 (5.8 s), videos 139, Shorts 297, live 2; the playlist `PL2MI040U_GXobmpXtTwBF7oHBGT5BETSD` 10 of 10.
- Failures: a nonexistent playlist answers HTTP 400 (`INVALID_ARGUMENT`) on both clients. A Mix (`RD…`) answers 400 on ANDROID_VR and 200 on WEB with nothing but `alerts[].alertRenderer.text` "This playlist type is unviewable.". The Shorts or live list of a channel that has none (`@jawed`) answers 404 (`NOT_FOUND`) on ANDROID_VR and 200 on WEB with only the alert "The playlist does not exist."; the channel's `UU` list works ("1 video"). 429 means rate limiting.
- `POST /youtubei/v1/navigation/resolve_url?prettyPrint=false` with `url`: a known handle answers `endpoint.browseEndpoint.browseId` (`https://www.youtube.com/@RickAstleyYT` → `UCuAXFkgsw1L7xaCfnd5JJOw`) on both clients; an unknown handle answers 200 with only `endpoint.urlEndpoint` on ANDROID_VR and 404 on WEB.

**Python** (3.11–3.14 standard library):

- `string.Formatter().parse(text)` yields `(literal, field, spec, conversion)` tuples (the last one has `field=None` when the text ends with literal text) and raises `ValueError` for unbalanced braces; `convert_field` and `format_field` format one value the way `str.format` does.
- `fnmatch.filter` compares through `os.path.normcase`, so it ignores case on Windows only. In a glob `[` starts a character class; a literal `[` is written `[[]` (what `glob.escape` does).
- A frozen, slotted dataclass may subclass `collections.abc.Sequence[BulkResult[T]]` and `Generic[T]`: `BulkReport[Transcript]` works at run time, the class pickles, and mypy strict accepts it (checked on 3.11 and 3.14).
- `concurrent.futures.wait(..., timeout=0.1)` in a loop lets Ctrl-C reach the main thread on Windows, where an untimed wait on a lock cannot be interrupted.

## Decisions (where the spec is silent or ambiguous)

1. **Sources**: bare values are recognized first (a channel ID `UC` + 22 characters, an `@handle`, a Mix `RD…`, a playlist ID `PL|UU|FL|OLAK5uy_` + at least 10 characters), then URLs of `youtube.com` (also `www.`, `m.`, `music.`, `youtube-nocookie.com`) and `youtu.be`, with or without a scheme: `list=` wins (a watch link inside a playlist means the playlist), then `/@handle`, `/channel/UC…`, `/c/name` and `/user/name`. Channel tabs (`/videos`, `/shorts`, `/featured`) are ignored, because `kind` chooses the list. A video link raises `InvalidSource` that points to `fetch()` and `download()`. Mixes are refused before any request (spec §5).
2. **`kind`** applies to channels; a playlist with a `kind` other than `"all"` is `InvalidOption`.
3. **Client fallback**: ANDROID_VR lists the whole playlist; when any of its pages fails (not found, an alert, an HTTP error, an unreadable answer), WEB lists it again from the first page, because continuation tokens belong to one client. When both fail, YouTube's own reason (`CollectionUnavailable`) wins over "not found", which wins over the first failure. HTTP 429 raises `IpBlocked` at once and `NetworkError` propagates, as for player requests. Resolving a handle asks ANDROID_VR, then WEB.
4. **First pages without items**: alerts become `alert_error` (a message with "does not exist" → `CollectionNotFound`, anything else → `CollectionUnavailable` with the message as `reason`); a header that says 0 videos is an empty playlist; anything else is unreadable and goes to the next client.
5. **Missing Shorts or live lists**: when a channel's `UULF`, `UUSH` or `UULV` list is not found, its `UU` list is checked (one page): if that exists the result is an empty `VideoList` with `video_count=0`, otherwise `CollectionNotFound`.
6. **Stop rules** (`Pager`): `limit` videos; a page without a continuation; a page without items; a continuation token seen before; 1000 pages (a warning, and `truncated` is set). A video seen before is dropped.
7. **Entries**: `VideoEntry.index` is the 1-based position in the returned list (YouTube's own playlist index exists only on ANDROID_VR); `duration` is `None` when YouTube shows none (WEB Shorts, upcoming streams); an item that names no channel gets the playlist owner's (`BrowsePage.owner_name` and `owner_id` from the first page's header, applied to every page by `Pager`, because continuation pages have no header). `VideoList.video_count` holds YouTube's header number — the "count" of the spec's MCP tool — because a `Sequence` already has a `count()` method.
8. **Bulk results**: exactly one `BulkResult` per input, in input order. An input without a video ID fails (`InvalidVideoId`) and a repeated video is `"skipped"` with `path=None`, both without work. `progress` receives every result once, in the order the results become known (those decided without work first), always from the calling thread. `concurrency` is 1 to 16.
9. **Circuit breaker**: `RequestBlocked` (and so `IpBlocked`) stops every bulk call; `translate_many` also stops on `ProviderAuthError`. Running videos finish; videos not started yet become `"not_attempted"`.
10. **Ctrl-C**, or an exception raised by `progress`: the run's stop event is set (running downloads use it as their `cancel` event, so their `.part` files stay), videos not started are dropped, the running ones are awaited, and the exception propagates; there is no report.
11. **One video's failure** is any `Exception`, not only a `UTMaxError`, so a disk error on one file does not end a long run; `BaseException` (Ctrl-C) propagates.
12. **File-name templates** use `str.format` fields; `{video_id}` is required (names must differ per video, and skip detection relies on it); the fields are `video_id title channel index language_code ext` (`download_many` has no `language_code`); path separators, the characters Windows does not allow in a file name (`<>:"|?*` and control characters, also as the fill of a format spec) and a name that ends with a dot or a space are refused, so a template that no file system accepts raises `InvalidOption` before any request; `title`, `channel` and `language_code` go through `safe_name`; an empty title becomes the video ID; a name longer than 220 UTF-8 bytes gets a shorter title (room, within Linux's 255-byte limit, for the longest names a download derives: the temporary file of its `.401.part.json` state file is 28 bytes longer than the name, and that of a `.srt` sidecar is 15 bytes plus the language code longer, up to 20 characters). `{index}` is a `VideoEntry`'s listing position, otherwise the position in `videos`.
13. **`skip_existing`** matches the file names that were in `out_dir` when the call started against a glob built from the template: known values are escaped, `title` and `channel` are always `*`. `language_code` is `*` without `languages`; with `languages`, it is each requested base language alone or with a region (`de`, `de-*`), as track selection matches; `translate_many` uses the target code, or `"<source glob>+<target>"` when bilingual. So a run for other languages, or for another target, does not skip because of a file in a different language.
14. **Folders**: `out_dir=None` keeps transcripts in memory (`fetch_many`, `translate_many`); a missing folder is created, but only after every argument was checked; a path to a file is `InvalidOption`.
15. **`translate_many`** also takes `instructions` and `resegment`, as `translate()` does (`**options` go to the translator, which would refuse them). It creates one translator before any request, through `resolve_translator`, which `translate()` now shares; `check_language_code` (the former `_language_code`) checks `to` up front.
16. **`download_many`** takes subtitle language codes only (a `Transcript` belongs to one video). It always replaces a file it downloads again (`skip_existing=False` means "download again"). Its options are checked once up front with the new `DownloadService.check` (including ffmpeg for `.mp3`), and file names come from the template through the new `DownloadOptions.name`.
17. **Layout**: the spec's collections service is split into `services/collections.py` (listings) and `services/bulk.py` (bulk calls). `Source`, `BrowsePage`, `Pager`, `NameTemplate`, `BulkItem` and `run_bulk` are internal; the public surface is the four calls, the four models and the three errors.

## File map

| File | Responsibility | Task |
|---|---|---|
| `src/utmax/models.py` | `CollectionKind`, `BulkStatus`, `VideoEntry`, `VideoList`, `BulkResult`, `BulkReport` | 1 |
| `src/utmax/errors.py` | `InvalidSource`, `CollectionNotFound`, `CollectionUnavailable` | 1 |
| `src/utmax/core/ids.py` | `COLLECTION_KINDS`, `Source`, `parse_source`, `uploads_playlist_id` | 2 |
| `src/utmax/adapters/innertube.py` | `InnerTubeClient.browse`, `InnerTubeClient.resolve_url` | 3 |
| `scripts/record_fixtures.py`, `tests/fixtures/youtube/*` | Record and keep trimmed browse and resolve answers | 4 |
| `src/utmax/core/browse.py` | `BrowsePage`, `parse_browse_page`, `resolved_channel_id`, `alert_error` (Task 4); `MAX_PAGES`, `Pager` (Task 5) | 4, 5 |
| `tests/helpers/browse.py` | Fixture loader and small synthetic browse answers | 4 |
| `src/utmax/services/collections.py` | `CollectionService.list_videos` | 6 |
| `src/utmax/core/filenames.py` | `NameTemplate`, `glob_literal`, `MAX_BULK_NAME_BYTES`, `Target.path_for(..., name=)` | 7 |
| `src/utmax/services/bulk.py` | `BulkItem`, `bulk_items`, `check_concurrency`, `run_bulk` (Task 8); `BulkService.fetch_many`, `translate_many` (Task 9); `download_many` (Task 10) | 8–10 |
| `src/utmax/services/translation.py` | `resolve_translator`, `check_language_code` | 9 |
| `tests/helpers/bulk.py` | A fake YouTube with several videos | 9 |
| `src/utmax/services/download.py` | `DownloadOptions.name`, `DownloadService.check` | 10 |
| `tests/helpers/files.py` | `folder_names`: folder listings without Windows' transient ghost names | 10 |
| `src/utmax/client.py`, `src/utmax/__init__.py` | `list_videos`, `fetch_many`, `translate_many`, `download_many` (exports of the types in Task 1) | 11 |
| `tests/live/test_collections_live.py` | Live listings and a live bulk fetch; M5 verification | 12 |

---

### Task 1: Collection and bulk models and errors

**Files:**
- Modify: `src/utmax/models.py`, `src/utmax/errors.py`, `src/utmax/__init__.py`
- Test: `tests/unit/test_collection_types.py` (create)

**Interfaces:**
- Consumes: `utmax.errors.UTMaxError`, `YouTubeError` and the pickling support of `UTMaxError` (M1); the `Sequence` pattern of `TrackList` in `utmax.models`.
- Produces (in `utmax.models`):
  - `CollectionKind = Literal["all", "videos", "shorts", "live"]`, `BulkStatus = Literal["ok", "skipped", "failed", "not_attempted"]`.
  - `VideoEntry(video_id: str, title: str, duration: float | None, channel: str, channel_id: str, index: int)` with `.url`.
  - `VideoList(title: str, source_id: str, kind: CollectionKind, video_count: int | None, entries: tuple[VideoEntry, ...])`, a `Sequence[VideoEntry]`.
  - `BulkResult[T](video_id: str, status: BulkStatus, value: T | None = None, path: Path | None = None, error: Exception | None = None)`.
  - `BulkReport[T](results: tuple[BulkResult[T], ...])`, a `Sequence[BulkResult[T]]` with `.ok`, `.skipped`, `.failed`, `.not_attempted` (tuples of results) and `.raise_for_errors()`.
- Produces (in `utmax.errors`): `InvalidSource(UTMaxError, ValueError)`; `CollectionNotFound(YouTubeError)` built as `CollectionNotFound(message, *, source, video_id=None, suggestion=None)` with `.source`; `CollectionUnavailable(YouTubeError)` built as `CollectionUnavailable(message, *, source, reason="", video_id=None, suggestion=None)` with `.source` and `.reason`. All three, plus `BulkReport`, `BulkResult`, `CollectionKind`, `VideoEntry` and `VideoList`, are exported from `utmax`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_collection_types.py`:

```python
"""Tests for the collection and bulk models and errors."""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

import utmax
from utmax import errors
from utmax.models import BulkReport, BulkResult, Transcript, VideoEntry, VideoList

FIRST = VideoEntry("PXC_PYeB6F8", "Angels On My Side", 231.0, "Rick Astley", "UC" + "x" * 22, 1)
SECOND = VideoEntry("LaOUkDBDjW8", "Dance", None, "Rick Astley", "UC" + "x" * 22, 2)


def test_video_entries_know_their_url() -> None:
    assert FIRST.url == "https://www.youtube.com/watch?v=PXC_PYeB6F8"


def test_video_lists_are_sequences_of_entries() -> None:
    videos = VideoList("Videos", "UULF" + "x" * 22, "videos", 139, (FIRST, SECOND))
    assert len(videos) == 2
    assert videos[0] is FIRST
    assert videos[-1:] == (SECOND,)
    assert [entry.video_id for entry in videos] == ["PXC_PYeB6F8", "LaOUkDBDjW8"]
    assert (videos.title, videos.kind, videos.video_count) == ("Videos", "videos", 139)


def test_bulk_reports_group_results_by_status() -> None:
    missing = errors.VideoUnavailable("gone", video_id="b")
    report: BulkReport[Transcript] = BulkReport(
        (
            BulkResult("a", "ok", path=Path("a.en.srt")),
            BulkResult("b", "failed", error=missing),
            BulkResult("c", "skipped", path=Path("c.en.srt")),
            BulkResult("d", "not_attempted"),
            BulkResult("e", "ok"),
        )
    )
    assert len(report) == 5
    assert report[1].error is missing
    assert [result.video_id for result in report.ok] == ["a", "e"]
    assert [result.video_id for result in report.failed] == ["b"]
    assert [result.video_id for result in report.skipped] == ["c"]
    assert [result.video_id for result in report.not_attempted] == ["d"]
    assert [result.video_id for result in report[3:]] == ["d", "e"]


def test_raise_for_errors_raises_the_first_failure() -> None:
    first = errors.IpBlocked("429", video_id="b")
    report: BulkReport[Transcript] = BulkReport(
        (
            BulkResult("a", "ok"),
            BulkResult("b", "failed", error=first),
            BulkResult("c", "failed", error=errors.VideoUnavailable("gone")),
        )
    )
    with pytest.raises(errors.IpBlocked) as caught:
        report.raise_for_errors()
    assert caught.value is first
    BulkReport((BulkResult("a", "ok"), BulkResult("b", "skipped"))).raise_for_errors()


@pytest.mark.parametrize(
    ("child", "parent"),
    [
        (errors.InvalidSource, errors.UTMaxError),
        (errors.InvalidSource, ValueError),
        (errors.CollectionNotFound, errors.YouTubeError),
        (errors.CollectionUnavailable, errors.YouTubeError),
    ],
)
def test_collection_error_hierarchy(child: type[Exception], parent: type[Exception]) -> None:
    assert issubclass(child, parent)


def test_collection_error_fields() -> None:
    missing = errors.CollectionNotFound("no such playlist", source="PLx")
    assert (missing.source, missing.video_id) == ("PLx", None)
    mix = errors.CollectionUnavailable("mix", source="RDx", reason="Mixes cannot be listed.")
    assert (mix.source, mix.reason) == ("RDx", "Mixes cannot be listed.")
    assert errors.CollectionUnavailable("mix", source="RDx").reason == ""
    assert "RD" in errors.CollectionUnavailable.suggestion
    assert "@handle" in errors.InvalidSource.suggestion


@pytest.mark.parametrize(
    "error",
    [
        errors.InvalidSource("not a playlist"),
        errors.CollectionNotFound("missing", source="@nobody"),
        errors.CollectionUnavailable("mix", source="RDx", reason="unviewable"),
    ],
)
def test_collection_errors_survive_pickling(error: errors.UTMaxError) -> None:
    clone = pickle.loads(pickle.dumps(error))
    assert type(clone) is type(error)
    assert str(clone) == str(error)
    assert clone.__dict__ == error.__dict__


def test_collection_names_are_exported() -> None:
    for name in ("CollectionNotFound", "CollectionUnavailable", "InvalidSource"):
        assert name in errors.__all__
        assert name in utmax.__all__
        assert getattr(utmax, name) is getattr(errors, name)
    for name in ("BulkReport", "BulkResult", "CollectionKind", "VideoEntry", "VideoList"):
        assert name in utmax.__all__
        assert hasattr(utmax, name)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_collection_types.py -q`
Expected: collection error — `ImportError: cannot import name 'BulkReport' from 'utmax.models'`.

- [ ] **Step 3: Add the errors**

In `src/utmax/errors.py`:

1. Replace:

```python

__all__ = [
    "AgeRestricted",
    "DownloadCancelled",
    "DownloadError",
    "DownloadIncomplete",
```

   with:

```python

__all__ = [
    "AgeRestricted",
    "CollectionNotFound",
    "CollectionUnavailable",
    "DownloadCancelled",
    "DownloadError",
    "DownloadIncomplete",
```

2. Replace:

```python
    "FormatNotAvailable",
    "InvalidModelSpec",
    "InvalidOption",
    "InvalidVideoId",
    "IpBlocked",
    "MissingExtra",
```

   with:

```python
    "FormatNotAvailable",
    "InvalidModelSpec",
    "InvalidOption",
    "InvalidSource",
    "InvalidVideoId",
    "IpBlocked",
    "MissingExtra",
```

3. Replace:

```python
    """The input does not contain a YouTube video ID."""

    suggestion = "Pass a YouTube URL or an 11-character video ID."


class InvalidModelSpec(UTMaxError, ValueError):
```

   with:

```python
    """The input does not contain a YouTube video ID."""

    suggestion = "Pass a YouTube URL or an 11-character video ID."


class InvalidSource(UTMaxError, ValueError):
    """The input is not a playlist or a channel."""

    suggestion = (
        "Pass a playlist URL or ID, a channel URL, an @handle or a channel ID "
        "(UC followed by 22 characters)."
    )


class InvalidModelSpec(UTMaxError, ValueError):
```

4. Replace:

```python
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.available = tuple(available)


class DownloadError(UTMaxError):
```

   with:

```python
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.available = tuple(available)


class CollectionNotFound(YouTubeError):
    """The playlist or channel does not exist, is private, or has no public videos."""

    suggestion = (
        "Check the link; private playlists and channels without public videos cannot be listed."
    )

    def __init__(
        self,
        message: str,
        *,
        source: str,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.source = source


class CollectionUnavailable(YouTubeError):
    """YouTube will not list this playlist, such as a Mix."""

    suggestion = (
        "Mixes (playlists starting with RD) and other generated playlists cannot be listed; "
        "list a regular playlist or the channel instead."
    )

    def __init__(
        self,
        message: str,
        *,
        source: str,
        reason: str = "",
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.source = source
        self.reason = reason


class DownloadError(UTMaxError):
```

- [ ] **Step 4: Add the models**

In `src/utmax/models.py`:

1. Replace:

```python
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, Protocol, overload

from utmax.errors import NotTranslatable, TranslationLanguageNotAvailable

__all__ = [
    "Codec",
    "Container",
    "DownloadResult",
    "Format",
```

   with:

```python
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Generic, Literal, Protocol, TypeVar, overload

from utmax.errors import NotTranslatable, TranslationLanguageNotAvailable

__all__ = [
    "BulkReport",
    "BulkResult",
    "BulkStatus",
    "Codec",
    "CollectionKind",
    "Container",
    "DownloadResult",
    "Format",
```

2. Replace:

```python
    "TrackFetcher",
    "TrackList",
    "Transcript",
    "VideoInfo",
    "Word",
]

```

   with:

```python
    "TrackFetcher",
    "TrackList",
    "Transcript",
    "VideoEntry",
    "VideoInfo",
    "VideoList",
    "Word",
]

```

3. Replace:

```python
SubtitleMode = Literal["embed", "sidecar", "both"]
ProgressPhase = Literal["downloading", "muxing", "converting", "finished"]
Codec = Literal["h264", "av1", "vp9", "aac", "he-aac", "opus", "other"]


@dataclass(frozen=True, slots=True)
```

   with:

```python
SubtitleMode = Literal["embed", "sidecar", "both"]
ProgressPhase = Literal["downloading", "muxing", "converting", "finished"]
Codec = Literal["h264", "av1", "vp9", "aac", "he-aac", "opus", "other"]
CollectionKind = Literal["all", "videos", "shorts", "live"]
BulkStatus = Literal["ok", "skipped", "failed", "not_attempted"]

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
```

4. Replace:

```python
    sidecars: tuple[Path, ...] = ()
    size_bytes: int = 0
    resumed: bool = False
```

   with:

```python
    sidecars: tuple[Path, ...] = ()
    size_bytes: int = 0
    resumed: bool = False


@dataclass(frozen=True, slots=True)
class VideoEntry:
    """One video of a playlist or channel, as :func:`utmax.list_videos` lists it."""

    video_id: str
    title: str
    duration: float | None
    channel: str
    channel_id: str
    index: int

    @property
    def url(self) -> str:
        """The canonical watch URL."""
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass(frozen=True, slots=True)
class VideoList(Sequence[VideoEntry]):
    """The videos of a playlist or channel, in YouTube's order.

    ``source_id`` is the playlist that was listed: the playlist's own ID, or for a channel
    the list YouTube keeps of its uploads (``UU...``, ``UULF...``, ``UUSH...``, ``UULV...``).
    ``video_count`` is the number of videos YouTube says the playlist has (it can include
    private videos, which are not listed); ``None`` when YouTube does not say.
    """

    title: str
    source_id: str
    kind: CollectionKind
    video_count: int | None
    entries: tuple[VideoEntry, ...]

    @overload
    def __getitem__(self, index: int) -> VideoEntry: ...
    @overload
    def __getitem__(self, index: slice) -> tuple[VideoEntry, ...]: ...
    def __getitem__(self, index: int | slice) -> VideoEntry | tuple[VideoEntry, ...]:
        return self.entries[index]

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[VideoEntry]:
        return iter(self.entries)


@dataclass(frozen=True, slots=True)
class BulkResult(Generic[T]):
    """What happened to one video of ``fetch_many``, ``translate_many`` or ``download_many``.

    ``status`` is ``"ok"`` (``value`` holds the result, ``path`` the file written, if any),
    ``"skipped"`` (``path`` is the file that already existed; ``None`` for a video listed
    twice), ``"failed"`` (``error`` says why) or ``"not_attempted"`` (the run stopped first).
    """

    video_id: str
    status: BulkStatus
    value: T | None = None
    path: Path | None = None
    error: Exception | None = None


@dataclass(frozen=True, slots=True)
class BulkReport(Sequence[BulkResult[T]], Generic[T]):
    """Every result of a bulk call, in the order the videos were given."""

    results: tuple[BulkResult[T], ...]

    @overload
    def __getitem__(self, index: int) -> BulkResult[T]: ...
    @overload
    def __getitem__(self, index: slice) -> tuple[BulkResult[T], ...]: ...
    def __getitem__(self, index: int | slice) -> BulkResult[T] | tuple[BulkResult[T], ...]:
        return self.results[index]

    def __len__(self) -> int:
        return len(self.results)

    def __iter__(self) -> Iterator[BulkResult[T]]:
        return iter(self.results)

    @property
    def ok(self) -> tuple[BulkResult[T], ...]:
        """The videos that succeeded."""
        return self._with("ok")

    @property
    def skipped(self) -> tuple[BulkResult[T], ...]:
        """The videos whose file already existed (or that were listed twice)."""
        return self._with("skipped")

    @property
    def failed(self) -> tuple[BulkResult[T], ...]:
        """The videos that failed; each result's ``error`` says why."""
        return self._with("failed")

    @property
    def not_attempted(self) -> tuple[BulkResult[T], ...]:
        """The videos never tried because the run stopped (YouTube blocked it, for example)."""
        return self._with("not_attempted")

    def raise_for_errors(self) -> None:
        """Raise the error of the first failed video; do nothing when none failed."""
        for result in self.results:
            if result.error is not None:
                raise result.error

    def _with(self, status: BulkStatus) -> tuple[BulkResult[T], ...]:
        return tuple(result for result in self.results if result.status == status)
```

- [ ] **Step 5: Export them from `utmax`**

In `src/utmax/__init__.py`:

1. Replace:

```python
from utmax.core.downloads import DEFAULT_CHUNK_SIZE
from utmax.errors import (
    AgeRestricted,
    DownloadCancelled,
    DownloadError,
    DownloadIncomplete,
```

   with:

```python
from utmax.core.downloads import DEFAULT_CHUNK_SIZE
from utmax.errors import (
    AgeRestricted,
    CollectionNotFound,
    CollectionUnavailable,
    DownloadCancelled,
    DownloadError,
    DownloadIncomplete,
```

2. Replace:

```python
    FormatNotAvailable,
    InvalidModelSpec,
    InvalidOption,
    InvalidVideoId,
    IpBlocked,
    MissingExtra,
```

   with:

```python
    FormatNotAvailable,
    InvalidModelSpec,
    InvalidOption,
    InvalidSource,
    InvalidVideoId,
    IpBlocked,
    MissingExtra,
```

3. Replace:

```python
    YouTubeRequestFailed,
)
from utmax.models import (
    Container,
    DownloadResult,
    Format,
```

   with:

```python
    YouTubeRequestFailed,
)
from utmax.models import (
    BulkReport,
    BulkResult,
    CollectionKind,
    Container,
    DownloadResult,
    Format,
```

4. Replace:

```python
    Track,
    TrackList,
    Transcript,
    VideoInfo,
    Word,
)
from utmax.providers import Translator

__all__ = [
    "AgeRestricted",
    "Client",
    "Container",
    "DownloadCancelled",
    "DownloadError",
```

   with:

```python
    Track,
    TrackList,
    Transcript,
    VideoEntry,
    VideoInfo,
    VideoList,
    Word,
)
from utmax.providers import Translator

__all__ = [
    "AgeRestricted",
    "BulkReport",
    "BulkResult",
    "Client",
    "CollectionKind",
    "CollectionNotFound",
    "CollectionUnavailable",
    "Container",
    "DownloadCancelled",
    "DownloadError",
```

5. Replace:

```python
    "FormatNotAvailable",
    "InvalidModelSpec",
    "InvalidOption",
    "InvalidVideoId",
    "IpBlocked",
    "Language",
```

   with:

```python
    "FormatNotAvailable",
    "InvalidModelSpec",
    "InvalidOption",
    "InvalidSource",
    "InvalidVideoId",
    "IpBlocked",
    "Language",
```

6. Replace:

```python
    "Translator",
    "UTMaxError",
    "UnsupportedFormat",
    "VideoInfo",
    "VideoUnavailable",
    "VideoUnplayable",
    "Word",
```

   with:

```python
    "Translator",
    "UTMaxError",
    "UnsupportedFormat",
    "VideoEntry",
    "VideoInfo",
    "VideoList",
    "VideoUnavailable",
    "VideoUnplayable",
    "Word",
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_collection_types.py tests/unit/test_errors.py tests/unit/test_facade.py -q`
Expected: the new file reports 13 passed; the existing error and facade tests (which walk every public error and name) pass with the new ones.

- [ ] **Step 7: Gates and commit**

Run the four gates (the suite grows by 13 to 1123 passed, 15 deselected).

```bash
git add src/utmax/models.py src/utmax/errors.py src/utmax/__init__.py tests/unit/test_collection_types.py
git commit -m "feat: add the collection and bulk models and errors" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Find the playlist or channel in a pasted source

**Files:**
- Modify: `src/utmax/core/ids.py`
- Test: `tests/unit/core/test_sources.py` (create)

**Interfaces:**
- Consumes: `CollectionUnavailable`, `InvalidSource`, `CollectionKind` (Task 1); `parse_video_id` and its URL rules (M1).
- Produces (in `utmax.core.ids`):
  - `COLLECTION_KINDS: tuple[CollectionKind, ...] = ("all", "videos", "shorts", "live")`.
  - `Source(kind: Literal["playlist", "channel"], id: str = "", url: str = "")` — `id` is the playlist ID, or the channel ID when one was given; `url` is a channel URL (`https://www.youtube.com/@handle`, `/c/name`, `/user/name`) still to be resolved.
  - `parse_source(value: str) -> Source` (raises `CollectionUnavailable` for Mixes and `InvalidSource` for anything else it cannot use; never makes a request).
  - `uploads_playlist_id(channel_id: str, kind: CollectionKind) -> str` (`UU`, `UULF`, `UUSH`, `UULV` + `channel_id[2:]`).

- [ ] **Step 1: Write the failing tests**

`tests/unit/core/test_sources.py`:

```python
"""Tests for finding the playlist or channel in what a user pastes."""

from __future__ import annotations

import pytest

from utmax.core.ids import COLLECTION_KINDS, Source, parse_source, uploads_playlist_id
from utmax.errors import CollectionUnavailable, InvalidSource
from utmax.models import CollectionKind

PLAYLIST = "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"
ALBUM = "OLAK5uy_nMr9h2VlS-2PULNz3M3XVXQj_P3C2bqaY"
CHANNEL = "UCuAXFkgsw1L7xaCfnd5JJOw"
HANDLE_URL = "https://www.youtube.com/@RickAstleyYT"


@pytest.mark.parametrize(
    ("value", "playlist_id"),
    [
        (PLAYLIST, PLAYLIST),
        (f"  {PLAYLIST}\n", PLAYLIST),
        (f"https://www.youtube.com/playlist?list={PLAYLIST}", PLAYLIST),
        (f"youtube.com/playlist?list={PLAYLIST}&si=abc", PLAYLIST),
        (f"https://www.youtube.com/watch?v=dQw4w9WgXcQ&list={PLAYLIST}&index=3", PLAYLIST),
        (f"https://youtu.be/dQw4w9WgXcQ?list={PLAYLIST}", PLAYLIST),
        (f"https://m.youtube.com/playlist?list={PLAYLIST}", PLAYLIST),
        (f"https://music.youtube.com/playlist?list={ALBUM}", ALBUM),
        (ALBUM, ALBUM),
        ("UUuAXFkgsw1L7xaCfnd5JJOw", "UUuAXFkgsw1L7xaCfnd5JJOw"),
        ("UULFuAXFkgsw1L7xaCfnd5JJOw", "UULFuAXFkgsw1L7xaCfnd5JJOw"),
        ("FLuAXFkgsw1L7xaCfnd5JJOw", "FLuAXFkgsw1L7xaCfnd5JJOw"),
        ("https://www.youtube.com/playlist?list=WL", "WL"),
    ],
)
def test_playlists(value: str, playlist_id: str) -> None:
    assert parse_source(value) == Source("playlist", id=playlist_id)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (CHANNEL, Source("channel", id=CHANNEL)),
        (f"https://www.youtube.com/channel/{CHANNEL}", Source("channel", id=CHANNEL)),
        (f"www.youtube.com/channel/{CHANNEL}/videos", Source("channel", id=CHANNEL)),
        (f"https://music.youtube.com/channel/{CHANNEL}", Source("channel", id=CHANNEL)),
        ("@RickAstleyYT", Source("channel", url=HANDLE_URL)),
        (HANDLE_URL, Source("channel", url=HANDLE_URL)),
        (f"{HANDLE_URL}/shorts", Source("channel", url=HANDLE_URL)),
        ("m.youtube.com/@RickAstleyYT/videos?view=0", Source("channel", url=HANDLE_URL)),
        ("//www.youtube.com/@RickAstleyYT", Source("channel", url=HANDLE_URL)),
        (
            "https://www.youtube.com/c/RickAstleyYT/featured",
            Source("channel", url="https://www.youtube.com/c/RickAstleyYT"),
        ),
        (
            "https://www.youtube.com/user/RickAstleyVEVO",
            Source("channel", url="https://www.youtube.com/user/RickAstleyVEVO"),
        ),
        (
            "https://www.youtube.com/@%D0%9A%D0%B0%D0%BD%D0%B0%D0%BB",
            Source("channel", url="https://www.youtube.com/@%D0%9A%D0%B0%D0%BD%D0%B0%D0%BB"),
        ),
    ],
)
def test_channels(value: str, expected: Source) -> None:
    assert parse_source(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "RDdQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ&start_radio=1",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RDAMVMdQw4w9WgXcQ",
    ],
)
def test_mixes_are_refused_before_any_request(value: str) -> None:
    with pytest.raises(CollectionUnavailable, match="is a Mix") as caught:
        parse_source(value)
    assert caught.value.source == value
    assert caught.value.reason == "YouTube does not list Mixes."


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "@",
        "PLshort",
        "RickAstleyYT",
        "https://example.com/playlist?list=" + PLAYLIST,
        "https://www.youtube.com/playlist?list=PL%20bad",
        "https://www.youtube.com/channel/UCshort",
        "https://www.youtube.com/channel/",
        "https://www.youtube.com/c/",
        "https://www.youtube.com/feed/subscriptions",
        "https://www.youtube.com/RickAstleyYT",
        "https://youtu.be/",
        "http://[::1",
    ],
)
def test_anything_else_is_invalid(value: str) -> None:
    with pytest.raises(InvalidSource, match="Could not find a playlist or channel"):
        parse_source(value)


@pytest.mark.parametrize(
    "value", ["dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ", "youtube.com/shorts/dQw4w9WgXcQ"]
)
def test_single_videos_point_to_fetch_and_download(value: str) -> None:
    with pytest.raises(InvalidSource, match="single video") as caught:
        parse_source(value)
    assert "utmax.fetch()" in caught.value.suggestion


@pytest.mark.parametrize(
    ("kind", "playlist_id"),
    [
        ("all", "UUuAXFkgsw1L7xaCfnd5JJOw"),
        ("videos", "UULFuAXFkgsw1L7xaCfnd5JJOw"),
        ("shorts", "UUSHuAXFkgsw1L7xaCfnd5JJOw"),
        ("live", "UULVuAXFkgsw1L7xaCfnd5JJOw"),
    ],
)
def test_uploads_playlists_by_kind(kind: CollectionKind, playlist_id: str) -> None:
    assert kind in COLLECTION_KINDS
    assert uploads_playlist_id(CHANNEL, kind) == playlist_id
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_sources.py -q`
Expected: collection error — `ImportError: cannot import name 'COLLECTION_KINDS' from 'utmax.core.ids'`.

- [ ] **Step 3: Add `parse_source`**

`_id_from_url` and the new `_source_from_url` share the URL splitting in `_split_url`.

In `src/utmax/core/ids.py`:

1. Replace:

```python
"""Extract the 11-character video ID from anything a user might paste."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from utmax.errors import InvalidVideoId

__all__ = ["parse_video_id"]

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
```

   with:

```python
"""Find the video, playlist or channel in anything a user might paste."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import SplitResult, parse_qs, urlsplit

from utmax.errors import CollectionUnavailable, InvalidSource, InvalidVideoId
from utmax.models import CollectionKind

__all__ = [
    "COLLECTION_KINDS",
    "Source",
    "parse_source",
    "parse_video_id",
    "uploads_playlist_id",
]

COLLECTION_KINDS: tuple[CollectionKind, ...] = ("all", "videos", "shorts", "live")

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
```

2. Replace:

```python
_SHORT_HOSTS = frozenset({"youtu.be", "www.youtu.be"})
_ID_PATH_PREFIXES = frozenset({"shorts", "live", "embed", "v", "e"})
_RESERVED_WORDS = frozenset({"videoseries", "live_stream"})


def parse_video_id(value: str) -> str:
```

   with:

```python
_SHORT_HOSTS = frozenset({"youtu.be", "www.youtu.be"})
_ID_PATH_PREFIXES = frozenset({"shorts", "live", "embed", "v", "e"})
_RESERVED_WORDS = frozenset({"videoseries", "live_stream"})
_PLAYLIST_ID = re.compile(r"(?:PL|UU|FL|OLAK5uy_)[A-Za-z0-9_-]{10,}")
_LIST_ID = re.compile(r"[A-Za-z0-9_-]+")
_MIX_ID = re.compile(r"RD[A-Za-z0-9_-]*")
_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
_HANDLE = re.compile(r"@[^\s/?#]+")
_UPLOADS_PREFIXES: dict[CollectionKind, str] = {
    "all": "UU",
    "videos": "UULF",
    "shorts": "UUSH",
    "live": "UULV",
}


def parse_video_id(value: str) -> str:
```

3. Replace:

```python


def _id_from_url(text: str) -> str | None:
    if not text:
        return None
    if text.startswith("//"):
        text = f"https:{text}"
    elif not _SCHEME.match(text):
        text = f"https://{text}"
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    segments = [segment for segment in parts.path.split("/") if segment]
```

   with:

```python


def _id_from_url(text: str) -> str | None:
    parts = _split_url(text)
    if parts is None:
        return None
    host = (parts.hostname or "").lower()
    segments = [segment for segment in parts.path.split("/") if segment]
```

4. Replace:

```python
    return (
        candidate if _VIDEO_ID.fullmatch(candidate) and candidate not in _RESERVED_WORDS else None
    )
```

   with:

```python
    return (
        candidate if _VIDEO_ID.fullmatch(candidate) and candidate not in _RESERVED_WORDS else None
    )


@dataclass(frozen=True, slots=True)
class Source:
    """What :func:`parse_source` found: a playlist, or a channel.

    ``id`` is the playlist ID, or the channel ID when it was given; for channels given by
    handle or custom URL it is empty and ``url`` must be resolved to the channel ID first.
    """

    kind: Literal["playlist", "channel"]
    id: str = ""
    url: str = ""


def parse_source(value: str) -> Source:
    """The playlist or channel in ``value``.

    Playlists: any YouTube URL with ``list=``, or a bare playlist ID (``PL``, ``UU``, ``FL`` or
    ``OLAK5uy_`` followed by at least 10 characters). Channels: ``/@handle``,
    ``/channel/UC...``, ``/c/name`` and ``/user/name`` URLs (tabs such as ``/videos`` are
    ignored), a bare ``@handle``, or a bare channel ID (``UC`` followed by 22 characters).

    Raises:
        CollectionUnavailable: ``value`` is a Mix (``RD...``), which YouTube never lists.
        InvalidSource: ``value`` names no playlist or channel. No request is ever made.
    """
    text = value.strip()
    if _CHANNEL_ID.fullmatch(text):
        return Source("channel", id=text)
    if _HANDLE.fullmatch(text):
        return Source("channel", url=f"https://www.youtube.com/{text}")
    if _MIX_ID.fullmatch(text):
        raise _mix(value)
    if _PLAYLIST_ID.fullmatch(text):
        return Source("playlist", id=text)
    source = _source_from_url(text, value)
    if source is not None:
        return source
    try:
        parse_video_id(text)
    except InvalidVideoId:
        raise InvalidSource(f"Could not find a playlist or channel in {value!r}.") from None
    raise InvalidSource(
        f"{value!r} is a single video, not a playlist or a channel.",
        suggestion=(
            "Use utmax.fetch() or utmax.download() for one video, or pass the link of its "
            "playlist or channel."
        ),
    )


def uploads_playlist_id(channel_id: str, kind: CollectionKind) -> str:
    """The playlist YouTube keeps of a channel's uploads: all of them, long videos, Shorts or
    live streams (``UU``, ``UULF``, ``UUSH`` or ``UULV`` plus the channel ID without ``UC``)."""
    return f"{_UPLOADS_PREFIXES[kind]}{channel_id[2:]}"


def _source_from_url(text: str, value: str) -> Source | None:
    parts = _split_url(text)
    if parts is None:
        return None
    host = (parts.hostname or "").lower()
    if host not in _WATCH_HOSTS and host not in _SHORT_HOSTS:
        return None
    playlist = parse_qs(parts.query).get("list", [""])[0].strip()
    if playlist:
        if playlist.startswith("RD"):
            raise _mix(value)
        return Source("playlist", id=playlist) if _LIST_ID.fullmatch(playlist) else None
    segments = [segment for segment in parts.path.split("/") if segment]
    if host in _SHORT_HOSTS or not segments:
        return None
    first = segments[0]
    if _HANDLE.fullmatch(first):
        return Source("channel", url=f"https://www.youtube.com/{first}")
    if len(segments) < 2:
        return None
    if first.lower() == "channel" and _CHANNEL_ID.fullmatch(segments[1]):
        return Source("channel", id=segments[1])
    if first.lower() in ("c", "user"):
        return Source("channel", url=f"https://www.youtube.com/{first.lower()}/{segments[1]}")
    return None


def _split_url(text: str) -> SplitResult | None:
    if not text:
        return None
    if text.startswith("//"):
        text = f"https:{text}"
    elif not _SCHEME.match(text):
        text = f"https://{text}"
    try:
        return urlsplit(text)
    except ValueError:
        return None


def _mix(value: str) -> CollectionUnavailable:
    return CollectionUnavailable(
        f"{value!r} is a Mix, a playlist YouTube makes for each viewer; Mixes cannot be listed.",
        source=value,
        reason="YouTube does not list Mixes.",
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_sources.py tests/unit/core/test_ids.py -q`
Expected: the new file reports 49 passed; the existing video ID tests still pass.

- [ ] **Step 5: Gates and commit**

Run the four gates (the suite grows by 49 to 1172 passed).

```bash
git add src/utmax/core/ids.py tests/unit/core/test_sources.py
git commit -m "feat: find the playlist or channel in a pasted source" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: InnerTube `browse` and `resolve_url` requests

**Files:**
- Modify: `src/utmax/adapters/innertube.py`
- Test: `tests/unit/adapters/test_innertube_browse.py` (create)

**Interfaces:**
- Consumes: `ClientProfile`, `ANDROID_VR`, `WEB` (`utmax.core.clients`); the module's `_json_object` and `InnerTubeClient._with_block_retries`.
- Produces (on `utmax.adapters.innertube.InnerTubeClient`):
  - `browse(profile: ClientProfile, *, browse_id: str | None = None, continuation: str | None = None) -> dict[str, Any]` — `POST {API_BASE}/browse?prettyPrint=false` with the profile's headers and `{"context": ..., "browseId": ...}` or `{"context": ..., "continuation": ...}`.
  - `resolve_url(profile: ClientProfile, url: str) -> dict[str, Any]` — `POST {API_BASE}/navigation/resolve_url?prettyPrint=false` with `{"context": ..., "url": url}`.
  - Both return the raw JSON object. HTTP 429 raises `IpBlocked` (retried `block_retries` times, as for the player), any other non-200 status `YouTubeRequestFailed(status_code=...)`, a body that is not a JSON object `YouTubeDataUnparsable`; none of them carries a video ID (`_json_object`'s `video_id` becomes optional).

- [ ] **Step 1: Write the failing tests**

`tests/unit/adapters/test_innertube_browse.py`:

```python
"""Tests for the InnerTube browse and resolve_url requests."""

from __future__ import annotations

import json

import pytest

from tests.helpers.fake_transport import FakeTransport, json_response, text_response
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.clients import ANDROID_VR, WEB
from utmax.errors import IpBlocked, YouTubeDataUnparsable, YouTubeRequestFailed

API = "https://www.youtube.com/youtubei/v1"
PAGE = {"contents": {"singleColumnBrowseResultsRenderer": {}}}


def test_browse_asks_for_the_first_page_of_a_playlist() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/browse", json_response(PAGE))
    answer = InnerTubeClient(transport).browse(ANDROID_VR, browse_id="VLPLtest")
    assert answer == PAGE
    (request,) = transport.requests
    assert request.url == f"{API}/browse?prettyPrint=false"
    assert request.headers["X-YouTube-Client-Name"] == "28"
    body = json.loads(request.body or b"{}")
    assert body == {"context": ANDROID_VR.context_payload(), "browseId": "VLPLtest"}


def test_browse_follows_a_continuation_token() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/browse", json_response(PAGE))
    InnerTubeClient(transport).browse(WEB, continuation="token-2")
    (request,) = transport.requests
    assert request.headers["X-YouTube-Client-Name"] == "1"
    body = json.loads(request.body or b"{}")
    assert body == {"context": WEB.context_payload(), "continuation": "token-2"}


def test_resolve_url_asks_about_one_url() -> None:
    answer = {"endpoint": {"browseEndpoint": {"browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"}}}
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/navigation/resolve_url", json_response(answer))
    url = "https://www.youtube.com/@RickAstleyYT"
    assert InnerTubeClient(transport).resolve_url(ANDROID_VR, url) == answer
    (request,) = transport.requests
    assert request.url == f"{API}/navigation/resolve_url?prettyPrint=false"
    body = json.loads(request.body or b"{}")
    assert body == {"context": ANDROID_VR.context_payload(), "url": url}


def test_rate_limits_are_retried_only_with_block_retries() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/browse", json_response({}, status=429))
    with pytest.raises(IpBlocked, match="HTTP 429") as caught:
        InnerTubeClient(transport).browse(ANDROID_VR, browse_id="VLPLtest")
    assert caught.value.video_id is None
    retried = FakeTransport()
    retried.add(
        "POST",
        "/youtubei/v1/navigation/resolve_url",
        json_response({}, status=429),
        json_response({"endpoint": {}}),
    )
    client = InnerTubeClient(retried, block_retries=1)
    assert client.resolve_url(WEB, "https://www.youtube.com/@x") == {"endpoint": {}}
    assert len(retried.requests) == 2


def test_http_errors_and_unreadable_answers() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        "/youtubei/v1/browse",
        json_response({"error": {"code": 404}}, status=404),
        text_response("<html>not json</html>"),
        json_response(["not", "an", "object"]),
    )
    client = InnerTubeClient(transport)
    with pytest.raises(YouTubeRequestFailed, match="HTTP 404") as caught:
        client.browse(ANDROID_VR, browse_id="VLUULVx")
    assert caught.value.status_code == 404
    with pytest.raises(YouTubeDataUnparsable, match="not JSON"):
        client.browse(ANDROID_VR, continuation="t")
    with pytest.raises(YouTubeDataUnparsable, match="unexpected JSON value"):
        client.browse(WEB, continuation="t")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/adapters/test_innertube_browse.py -q`
Expected: 5 failed — `AttributeError: 'InnerTubeClient' object has no attribute 'browse'` (and `'resolve_url'`).

- [ ] **Step 3: Add the requests**

In `src/utmax/adapters/innertube.py`:

1. Replace:

```python
"""InnerTube (YouTube's internal API): player requests with client fallback, and captions."""

from __future__ import annotations

```

   with:

```python
"""InnerTube (YouTube's internal API): player requests with client fallback, captions, and
the ``browse`` and ``navigation/resolve_url`` requests behind playlists and channels."""

from __future__ import annotations

```

2. Replace:

```python
        response = self._transport.send(HttpRequest("POST", url, profile.request_headers(), body))
        return _json_object(response, video_id=video_id)

    def fetch_captions(self, base_url: str, *, video_id: str) -> HttpResponse:
        """Download a caption track as json3."""
        check_caption_url(base_url, video_id=video_id)
        url = caption_url(base_url, fmt="json3")
        return self._with_block_retries(partial(self._caption_response, url, video_id))

    def _playable(
        self, profile: ClientProfile, video_id: str, api_key: str | None, *, purpose: Purpose
```

   with:

```python
        response = self._transport.send(HttpRequest("POST", url, profile.request_headers(), body))
        return _json_object(response, video_id=video_id)

    def browse(
        self,
        profile: ClientProfile,
        *,
        browse_id: str | None = None,
        continuation: str | None = None,
    ) -> dict[str, Any]:
        """One raw ``browse`` answer of ``profile``: the first page of ``browse_id`` (``"VL"``
        plus a playlist ID), or the page behind a ``continuation`` token."""
        payload: dict[str, Any] = {"context": profile.context_payload()}
        if browse_id is not None:
            payload["browseId"] = browse_id
        if continuation is not None:
            payload["continuation"] = continuation
        return self._with_block_retries(partial(self._post, profile, "browse", payload))

    def resolve_url(self, profile: ClientProfile, url: str) -> dict[str, Any]:
        """The raw ``navigation/resolve_url`` answer of ``profile`` for a YouTube ``url``, such as
        a channel's ``https://www.youtube.com/@handle``."""
        payload = {"context": profile.context_payload(), "url": url}
        return self._with_block_retries(
            partial(self._post, profile, "navigation/resolve_url", payload)
        )

    def fetch_captions(self, base_url: str, *, video_id: str) -> HttpResponse:
        """Download a caption track as json3."""
        check_caption_url(base_url, video_id=video_id)
        url = caption_url(base_url, fmt="json3")
        return self._with_block_retries(partial(self._caption_response, url, video_id))

    def _post(
        self, profile: ClientProfile, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        url = f"{API_BASE}/{endpoint}?prettyPrint=false"
        body = json.dumps(payload).encode("utf-8")
        response = self._transport.send(HttpRequest("POST", url, profile.request_headers(), body))
        return _json_object(response)

    def _playable(
        self, profile: ClientProfile, video_id: str, api_key: str | None, *, purpose: Purpose
```

3. Replace:

```python
                )


def _json_object(response: HttpResponse, *, video_id: str) -> dict[str, Any]:
    if response.status == 429:
        raise IpBlocked("YouTube rate-limited this IP address (HTTP 429).", video_id=video_id)
    if response.status != 200:
```

   with:

```python
                )


def _json_object(response: HttpResponse, *, video_id: str | None = None) -> dict[str, Any]:
    if response.status == 429:
        raise IpBlocked("YouTube rate-limited this IP address (HTTP 429).", video_id=video_id)
    if response.status != 200:
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/adapters/test_innertube_browse.py tests/unit/adapters/test_innertube.py -q`
Expected: the new file reports 5 passed; the existing player and caption tests still pass.

- [ ] **Step 5: Gates and commit**

Run the four gates (the suite grows by 5 to 1177 passed).

```bash
git add src/utmax/adapters/innertube.py tests/unit/adapters/test_innertube_browse.py
git commit -m "feat: add the InnerTube browse and resolve_url requests" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Recorded browse answers and the page parser

**Files:**
- Create: `tests/fixtures/youtube/browse_android_vr_1.json`, `browse_android_vr_2.json`, `browse_web_1.json`, `browse_web_2.json`, `browse_web_shorts.json`, `resolve_handle.json`, `resolve_unknown.json`, `tests/helpers/browse.py`, `src/utmax/core/browse.py`
- Modify: `scripts/record_fixtures.py`, `tests/fixtures/youtube/README.md`
- Test: `tests/unit/core/test_browse.py` (create)

**Interfaces:**
- Consumes: `VideoEntry`, `CollectionNotFound`, `CollectionUnavailable` (Task 1); `utmax.core.ytdata.items`, `mapping`, `text_of`; `InnerTubeClient.browse` and `resolve_url` (Task 3, used by the recorder only).
- Produces (in `utmax.core.browse`):
  - `BrowsePage(videos: tuple[VideoEntry, ...] = (), items: int = 0, continuation: str | None = None, title: str = "", video_count: int | None = None, alerts: tuple[str, ...] = (), owner_name: str = "", owner_id: str = "")` — `videos` holds the playable videos numbered 0; `items` counts every list item, skipped ones included; `owner_name` and `owner_id` name the playlist's channel when the page has a header (a first page): continuation pages have none, so `Pager` (Task 5) fills the first page's owner into the videos of later pages.
  - `parse_browse_page(data: Mapping[str, Any]) -> BrowsePage` for first and continuation pages of both clients.
  - `resolved_channel_id(data: Mapping[str, Any]) -> str | None`.
  - `alert_error(page: BrowsePage, *, source: str) -> CollectionNotFound | CollectionUnavailable`.
- Produces (in `tests.helpers.browse`, for Tasks 5, 6 and 11): `CHANNEL_ID`, `VIDEOS_LIST`, `VR_PAGE_1`, `VR_PAGE_2`, `WEB_LAST_PAGE`, `browse_fixture(name)`, `alert_page(text)`, `error_body(code)`, `lockup(video_id, *, badge="3:51", title="A video", channel_id="")`, `web_page(*items, header=None)`, `vr_page(*video_ids, token=None, count="")`.

- [ ] **Step 1: Add the recorded answers**

These are trimmed ANDROID_VR and WEB answers recorded on 2026-09-28 by the recorder of Step 7 (Rick Astley's long-form uploads `UULFuAXFkgsw1L7xaCfnd5JJOw` and Shorts `UUSHuAXFkgsw1L7xaCfnd5JJOw`, and the `resolve_url` answers for `@RickAstleyYT` and an unknown handle). They hold no secrets. Write each file exactly as shown (UTF-8, `\n` line endings, a final newline).

`tests/fixtures/youtube/browse_android_vr_1.json`:

```json
{
 "header": {
  "playlistHeaderRenderer": {
   "playlistId": "UULFuAXFkgsw1L7xaCfnd5JJOw",
   "title": {
    "runs": [
     {
      "text": "Videos"
     }
    ]
   },
   "numVideosText": {
    "runs": [
     {
      "text": "139"
     },
     {
      "text": " videos"
     }
    ]
   },
   "ownerText": {
    "runs": [
     {
      "text": "Rick Astley",
      "navigationEndpoint": {
       "browseEndpoint": {
        "browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"
       }
      }
     }
    ]
   }
  }
 },
 "contents": {
  "singleColumnBrowseResultsRenderer": {
   "tabs": [
    {
     "tabRenderer": {
      "content": {
       "sectionListRenderer": {
        "contents": [
         {
          "playlistVideoListRenderer": {
           "contents": [
            {
             "playlistVideoRenderer": {
              "videoId": "PXC_PYeB6F8",
              "title": {
               "runs": [
                {
                 "text": "Rick Astley - Angels On My Side (Live at The O2, London, April 2026)"
                }
               ]
              },
              "index": {
               "runs": [
                {
                 "text": "1"
                }
               ]
              },
              "shortBylineText": {
               "runs": [
                {
                 "text": "Rick Astley",
                 "navigationEndpoint": {
                  "browseEndpoint": {
                   "browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"
                  }
                 }
                }
               ]
              },
              "lengthSeconds": "231",
              "isPlayable": true
             }
            },
            {
             "playlistVideoRenderer": {
              "videoId": "LaOUkDBDjW8",
              "title": {
               "runs": [
                {
                 "text": "Rick Astley - Dance (Live at The O2, London, April 2026)"
                }
               ]
              },
              "index": {
               "runs": [
                {
                 "text": "2"
                }
               ]
              },
              "shortBylineText": {
               "runs": [
                {
                 "text": "Rick Astley",
                 "navigationEndpoint": {
                  "browseEndpoint": {
                   "browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"
                  }
                 }
                }
               ]
              },
              "lengthSeconds": "234",
              "isPlayable": true
             }
            },
            {
             "playlistVideoRenderer": {
              "videoId": "wvr7-pDJUOA",
              "title": {
               "runs": [
                {
                 "text": "Rick Astley - Keep Singing (Live at The O2, London, April 2026)"
                }
               ]
              },
              "index": {
               "runs": [
                {
                 "text": "3"
                }
               ]
              },
              "shortBylineText": {
               "runs": [
                {
                 "text": "Rick Astley",
                 "navigationEndpoint": {
                  "browseEndpoint": {
                   "browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"
                  }
                 }
                }
               ]
              },
              "lengthSeconds": "248",
              "isPlayable": true
             }
            }
           ],
           "continuations": [
            {
             "nextContinuationData": {
              "continuation": "4qmFsgJUEhxWTFVVTEZ1QVhGa2dzdzFMN3hhQ2ZuZDVKSk93GjRDQUY2SGxCVU9rTkNVV2xGUkU1RlRYcFNSRTFyU2tOUmVsVjNUMFJKTVZKVVRRJTNEJTNE"
             }
            }
           ]
          }
         }
        ]
       }
      }
     }
    }
   ]
  }
 }
}
```

`tests/fixtures/youtube/browse_android_vr_2.json`:

```json
{
 "continuationContents": {
  "playlistVideoListContinuation": {
   "contents": [
    {
     "playlistVideoRenderer": {
      "videoId": "1hCm58jzquQ",
      "title": {
       "runs": [
        {
         "text": "Rick Astley - Forever And More (Official BTS)"
        }
       ]
      },
      "index": {
       "runs": [
        {
         "text": "21"
        }
       ]
      },
      "shortBylineText": {
       "runs": [
        {
         "text": "Rick Astley",
         "navigationEndpoint": {
          "browseEndpoint": {
           "browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"
          }
         }
        }
       ]
      },
      "lengthSeconds": "436",
      "isPlayable": true
     }
    },
    {
     "playlistVideoRenderer": {
      "videoId": "QJjrf9RkzGo",
      "title": {
       "runs": [
        {
         "text": "Rick Astley - Forever and More (Official Video)"
        }
       ]
      },
      "index": {
       "runs": [
        {
         "text": "22"
        }
       ]
      },
      "shortBylineText": {
       "runs": [
        {
         "text": "Rick Astley",
         "navigationEndpoint": {
          "browseEndpoint": {
           "browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"
          }
         }
        }
       ]
      },
      "lengthSeconds": "227",
      "isPlayable": true
     }
    }
   ],
   "continuations": [
    {
     "nextContinuationData": {
      "continuation": "4qmFsgJUEhxWTFVVTEZ1QVhGa2dzdzFMN3hhQ2ZuZDVKSk93GjRDQUo2SGxCVU9rTkRaMmxGUlUxNVRtcGFRazE2WjNsT1JWcEdUMFZLUkUxRVNRJTNEJTNE"
     }
    }
   ]
  }
 }
}
```

`tests/fixtures/youtube/browse_web_1.json`:

```json
{
 "header": {
  "playlistHeaderRenderer": {
   "playlistId": "UULFuAXFkgsw1L7xaCfnd5JJOw",
   "title": {
    "simpleText": "Videos"
   },
   "numVideosText": {
    "runs": [
     {
      "text": "139"
     },
     {
      "text": " videos"
     }
    ]
   },
   "ownerText": {
    "runs": [
     {
      "text": "Rick Astley",
      "navigationEndpoint": {
       "browseEndpoint": {
        "browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"
       }
      }
     }
    ]
   }
  }
 },
 "contents": {
  "twoColumnBrowseResultsRenderer": {
   "tabs": [
    {
     "tabRenderer": {
      "content": {
       "sectionListRenderer": {
        "contents": [
         {
          "itemSectionRenderer": {
           "contents": [
            {
             "lockupViewModel": {
              "contentId": "PXC_PYeB6F8",
              "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
              "contentImage": {
               "thumbnailViewModel": {
                "overlays": [
                 {
                  "thumbnailBottomOverlayViewModel": {
                   "badges": [
                    {
                     "thumbnailBadgeViewModel": {
                      "text": "3:51"
                     }
                    }
                   ]
                  }
                 },
                 {}
                ]
               }
              },
              "metadata": {
               "lockupMetadataViewModel": {
                "title": {
                 "content": "Rick Astley - Angels On My Side (Live at The O2, London, April 2026)"
                },
                "metadata": {
                 "contentMetadataViewModel": {
                  "metadataRows": [
                   {
                    "metadataParts": [
                     {
                      "text": {
                       "content": "Rick Astley",
                       "commandRuns": [
                        {
                         "onTap": {
                          "innertubeCommand": {
                           "browseEndpoint": {
                            "browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"
                           }
                          }
                         }
                        }
                       ]
                      }
                     }
                    ]
                   },
                   {
                    "metadataParts": [
                     {
                      "text": {
                       "content": "100K views"
                      }
                     },
                     {
                      "text": {
                       "content": "3 months ago"
                      }
                     }
                    ]
                   }
                  ]
                 }
                }
               }
              }
             }
            },
            {
             "lockupViewModel": {
              "contentId": "LaOUkDBDjW8",
              "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
              "contentImage": {
               "thumbnailViewModel": {
                "overlays": [
                 {
                  "thumbnailBottomOverlayViewModel": {
                   "badges": [
                    {
                     "thumbnailBadgeViewModel": {
                      "text": "3:54"
                     }
                    }
                   ]
                  }
                 },
                 {}
                ]
               }
              },
              "metadata": {
               "lockupMetadataViewModel": {
                "title": {
                 "content": "Rick Astley - Dance (Live at The O2, London, April 2026)"
                },
                "metadata": {
                 "contentMetadataViewModel": {
                  "metadataRows": [
                   {
                    "metadataParts": [
                     {
                      "text": {
                       "content": "Rick Astley",
                       "commandRuns": [
                        {
                         "onTap": {
                          "innertubeCommand": {
                           "browseEndpoint": {
                            "browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"
                           }
                          }
                         }
                        }
                       ]
                      }
                     }
                    ]
                   },
                   {
                    "metadataParts": [
                     {
                      "text": {
                       "content": "59K views"
                      }
                     },
                     {
                      "text": {
                       "content": "3 months ago"
                      }
                     }
                    ]
                   }
                  ]
                 }
                }
               }
              }
             }
            },
            {
             "lockupViewModel": {
              "contentId": "wvr7-pDJUOA",
              "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
              "contentImage": {
               "thumbnailViewModel": {
                "overlays": [
                 {
                  "thumbnailBottomOverlayViewModel": {
                   "badges": [
                    {
                     "thumbnailBadgeViewModel": {
                      "text": "4:08"
                     }
                    }
                   ]
                  }
                 },
                 {}
                ]
               }
              },
              "metadata": {
               "lockupMetadataViewModel": {
                "title": {
                 "content": "Rick Astley - Keep Singing (Live at The O2, London, April 2026)"
                },
                "metadata": {
                 "contentMetadataViewModel": {
                  "metadataRows": [
                   {
                    "metadataParts": [
                     {
                      "text": {
                       "content": "Rick Astley",
                       "commandRuns": [
                        {
                         "onTap": {
                          "innertubeCommand": {
                           "browseEndpoint": {
                            "browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"
                           }
                          }
                         }
                        }
                       ]
                      }
                     }
                    ]
                   },
                   {
                    "metadataParts": [
                     {
                      "text": {
                       "content": "88K views"
                      }
                     },
                     {
                      "text": {
                       "content": "3 months ago"
                      }
                     }
                    ]
                   }
                  ]
                 }
                }
               }
              }
             }
            },
            {
             "continuationItemViewModel": {
              "continuationCommand": {
               "innertubeCommand": {
                "continuationCommand": {
                 "token": "4qmFsgJxEhxWTFVVTEZ1QVhGa2dzdzFMN3hhQ2ZuZDVKSk93GjRDQUY2SGxCVU9rTkhVV2xGUlVrMVRrVlZlbEpxWkVKTlJVWkVUbXBCTTA1RVdRJTNEJTNEmgIaVVVMRnVBWEZrZ3N3MUw3eGFDZm5kNUpKT3c%3D"
                }
               }
              }
             }
            }
           ]
          }
         }
        ]
       }
      }
     }
    }
   ]
  }
 }
}
```

`tests/fixtures/youtube/browse_web_2.json`:

```json
{
 "onResponseReceivedActions": [
  {
   "appendContinuationItemsAction": {
    "continuationItems": [
     {
      "lockupViewModel": {
       "contentId": "CdI9nxxXe4U",
       "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
       "contentImage": {
        "thumbnailViewModel": {
         "overlays": [
          {
           "thumbnailBottomOverlayViewModel": {
            "badges": [
             {
              "thumbnailBadgeViewModel": {
               "text": "3:38"
              }
             }
            ]
           }
          },
          {}
         ]
        }
       },
       "metadata": {
        "lockupMetadataViewModel": {
         "title": {
          "content": "Rick Astley - Last Night On Earth (Official Audio)"
         },
         "metadata": {
          "contentMetadataViewModel": {
           "metadataRows": [
            {
             "metadataParts": [
              {
               "text": {
                "content": "Rick Astley",
                "commandRuns": [
                 {
                  "onTap": {
                   "innertubeCommand": {
                    "browseEndpoint": {
                     "browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"
                    }
                   }
                  }
                 }
                ]
               }
              }
             ]
            },
            {
             "metadataParts": [
              {
               "text": {
                "content": "151K views"
               }
              },
              {
               "text": {
                "content": "8 years ago"
               }
              }
             ]
            }
           ]
          }
         }
        }
       }
      }
     },
     {
      "lockupViewModel": {
       "contentId": "nDoU231XCqs",
       "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
       "contentImage": {
        "thumbnailViewModel": {
         "overlays": [
          {
           "thumbnailBottomOverlayViewModel": {
            "badges": [
             {
              "thumbnailBadgeViewModel": {
               "text": "3:39"
              }
             }
            ]
           }
          },
          {}
         ]
        }
       },
       "metadata": {
        "lockupMetadataViewModel": {
         "title": {
          "content": "Rick Astley - Shivers (Official Audio)"
         },
         "metadata": {
          "contentMetadataViewModel": {
           "metadataRows": [
            {
             "metadataParts": [
              {
               "text": {
                "content": "Rick Astley",
                "commandRuns": [
                 {
                  "onTap": {
                   "innertubeCommand": {
                    "browseEndpoint": {
                     "browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"
                    }
                   }
                  }
                 }
                ]
               }
              }
             ]
            },
            {
             "metadataParts": [
              {
               "text": {
                "content": "178K views"
               }
              },
              {
               "text": {
                "content": "8 years ago"
               }
              }
             ]
            }
           ]
          }
         }
        }
       }
      }
     },
     {
      "lockupViewModel": {
       "contentId": "dQw4w9WgXcQ",
       "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
       "contentImage": {
        "thumbnailViewModel": {
         "overlays": [
          {
           "thumbnailBottomOverlayViewModel": {
            "badges": [
             {
              "thumbnailBadgeViewModel": {
               "text": "3:34"
              }
             }
            ]
           }
          },
          {}
         ]
        }
       },
       "metadata": {
        "lockupMetadataViewModel": {
         "title": {
          "content": "Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)"
         },
         "metadata": {
          "contentMetadataViewModel": {
           "metadataRows": [
            {
             "metadataParts": [
              {
               "text": {
                "content": "Rick Astley",
                "commandRuns": [
                 {
                  "onTap": {
                   "innertubeCommand": {
                    "browseEndpoint": {
                     "browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"
                    }
                   }
                  }
                 }
                ]
               }
              }
             ]
            },
            {
             "metadataParts": [
              {
               "text": {
                "content": "1.8B views"
               }
              },
              {
               "text": {
                "content": "16 years ago"
               }
              }
             ]
            }
           ]
          }
         }
        }
       }
      }
     }
    ]
   }
  }
 ]
}
```

`tests/fixtures/youtube/browse_web_shorts.json`:

```json
{
 "header": {
  "playlistHeaderRenderer": {
   "playlistId": "UUSHuAXFkgsw1L7xaCfnd5JJOw",
   "title": {
    "simpleText": "Short videos"
   },
   "numVideosText": {
    "runs": [
     {
      "text": "297"
     },
     {
      "text": " videos"
     }
    ]
   },
   "ownerText": {
    "runs": [
     {
      "text": "Rick Astley",
      "navigationEndpoint": {
       "browseEndpoint": {
        "browseId": "UCuAXFkgsw1L7xaCfnd5JJOw"
       }
      }
     }
    ]
   }
  }
 },
 "contents": {
  "twoColumnBrowseResultsRenderer": {
   "tabs": [
    {
     "tabRenderer": {
      "content": {
       "sectionListRenderer": {
        "contents": [
         {
          "itemSectionRenderer": {
           "contents": [
            {
             "richGridRenderer": {
              "contents": [
               {
                "richItemRenderer": {
                 "content": {
                  "shortsLockupViewModel": {
                   "onTap": {
                    "innertubeCommand": {
                     "reelWatchEndpoint": {
                      "videoId": "E_MGy41IYVw"
                     }
                    }
                   },
                   "overlayMetadata": {
                    "primaryText": {
                     "content": "38 years on, and the music video still hits 🕺 # #rickastley #80smusic"
                    }
                   }
                  }
                 }
                }
               },
               {
                "richItemRenderer": {
                 "content": {
                  "shortsLockupViewModel": {
                   "onTap": {
                    "innertubeCommand": {
                     "reelWatchEndpoint": {
                      "videoId": "ihRdK3x3cUY"
                     }
                    }
                   },
                   "overlayMetadata": {
                    "primaryText": {
                     "content": "A message from Rick ♥️ #rickastley"
                    }
                   }
                  }
                 }
                }
               }
              ]
             }
            }
           ]
          }
         }
        ]
       }
      }
     }
    }
   ]
  }
 }
}
```

`tests/fixtures/youtube/resolve_handle.json`:

```json
{
 "endpoint": {
  "browseEndpoint": {
   "browseId": "UCuAXFkgsw1L7xaCfnd5JJOw",
   "params": "EgC4AQCSAwDyBgQKAjIA"
  }
 }
}
```

`tests/fixtures/youtube/resolve_unknown.json`:

```json
{
 "endpoint": {
  "urlEndpoint": {
   "url": "https://www.youtube.com/@thishandledoesnotexist20260928x"
  }
 }
}
```

- [ ] **Step 2: Add the test helpers**

`tests/helpers/browse.py`:

```python
"""Browse answers for collection tests: the recorded fixtures and small synthetic pages.

The synthetic shapes copy what InnerTube answered on 2026-09-28 (see the M5 plan's verified
facts); only the fields utmax reads are filled in.
"""

from __future__ import annotations

import json
from typing import Any

from tests.helpers.youtube import FIXTURES

CHANNEL_ID = "UCuAXFkgsw1L7xaCfnd5JJOw"
VIDEOS_LIST = "UULFuAXFkgsw1L7xaCfnd5JJOw"
VR_PAGE_1 = ["PXC_PYeB6F8", "LaOUkDBDjW8", "wvr7-pDJUOA"]
VR_PAGE_2 = ["1hCm58jzquQ", "QJjrf9RkzGo"]
WEB_LAST_PAGE = ["CdI9nxxXe4U", "nDoU231XCqs", "dQw4w9WgXcQ"]


def browse_fixture(name: str) -> dict[str, Any]:
    """A recorded answer from tests/fixtures/youtube, such as ``"browse_web_1"``."""
    return dict(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))


def alert_page(text: str) -> dict[str, Any]:
    """A WEB answer that holds only an alert."""
    return {"alerts": [{"alertRenderer": {"type": "ERROR", "text": {"runs": [{"text": text}]}}}]}


def error_body(code: int) -> dict[str, Any]:
    """InnerTube's JSON body for HTTP 400 and 404 answers."""
    status = {400: "INVALID_ARGUMENT", 404: "NOT_FOUND"}[code]
    return {"error": {"code": code, "message": "Request failed.", "status": status}}


def lockup(
    video_id: str, *, badge: str = "3:51", title: str = "A video", channel_id: str = ""
) -> dict[str, Any]:
    """A WEB ``lockupViewModel`` item; with ``channel_id`` its metadata links to a channel."""
    parts = []
    if channel_id:
        command = {"onTap": {"innertubeCommand": {"browseEndpoint": {"browseId": channel_id}}}}
        parts.append({"text": {"content": "Some Channel", "commandRuns": [command]}})
    badges = [{"thumbnailBadgeViewModel": {"text": badge}}]
    return {
        "lockupViewModel": {
            "contentId": video_id,
            "contentImage": {
                "thumbnailViewModel": {
                    "overlays": [{"thumbnailBottomOverlayViewModel": {"badges": badges}}]
                }
            },
            "metadata": {
                "lockupMetadataViewModel": {
                    "title": {"content": title},
                    "metadata": {
                        "contentMetadataViewModel": {"metadataRows": [{"metadataParts": parts}]}
                    },
                }
            },
        }
    }


def web_page(*items: dict[str, Any], header: dict[str, Any] | None = None) -> dict[str, Any]:
    """A WEB first page listing ``items`` under ``header`` (a whole ``header`` object)."""
    section = {"itemSectionRenderer": {"contents": list(items)}}
    tab = {"tabRenderer": {"content": {"sectionListRenderer": {"contents": [section]}}}}
    page: dict[str, Any] = {"contents": {"twoColumnBrowseResultsRenderer": {"tabs": [tab]}}}
    if header is not None:
        page["header"] = header
    return page


def vr_page(*video_ids: str, token: str | None = None, count: str = "") -> dict[str, Any]:
    """An ANDROID_VR page of playable videos, with a playlist header when ``count`` is set."""
    videos = [
        {"playlistVideoRenderer": {"videoId": video_id, "title": {"runs": [{"text": video_id}]}}}
        for video_id in video_ids
    ]
    renderer: dict[str, Any] = {"contents": videos}
    if token is not None:
        renderer["continuations"] = [{"nextContinuationData": {"continuation": token}}]
    page: dict[str, Any] = {"continuationContents": {"playlistVideoListContinuation": renderer}}
    if count:
        title = {"runs": [{"text": "A playlist"}]}
        numbers = {"runs": [{"text": count}]}
        page["header"] = {"playlistHeaderRenderer": {"title": title, "numVideosText": numbers}}
    return page
```

- [ ] **Step 3: Write the failing tests**

`tests/unit/core/test_browse.py`:

```python
"""Tests for reading browse and resolve_url answers (recorded and synthetic)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.helpers.browse import (
    CHANNEL_ID,
    VR_PAGE_1,
    VR_PAGE_2,
    WEB_LAST_PAGE,
    alert_page,
    browse_fixture,
    lockup,
    vr_page,
    web_page,
)
from utmax.core.browse import BrowsePage, alert_error, parse_browse_page, resolved_channel_id
from utmax.errors import CollectionNotFound, CollectionUnavailable
from utmax.models import VideoEntry


def test_android_vr_first_page() -> None:
    page = parse_browse_page(browse_fixture("browse_android_vr_1"))
    assert (page.title, page.video_count, page.items, page.alerts) == ("Videos", 139, 3, ())
    assert [video.video_id for video in page.videos] == VR_PAGE_1
    assert page.videos[0] == VideoEntry(
        video_id="PXC_PYeB6F8",
        title="Rick Astley - Angels On My Side (Live at The O2, London, April 2026)",
        duration=231.0,
        channel="Rick Astley",
        channel_id=CHANNEL_ID,
        index=0,
    )
    assert [video.duration for video in page.videos] == [231.0, 234.0, 248.0]
    assert page.continuation is not None
    assert page.continuation.startswith("4qmFsgJUEhxW")


def test_android_vr_continuation_page() -> None:
    first = parse_browse_page(browse_fixture("browse_android_vr_1"))
    page = parse_browse_page(browse_fixture("browse_android_vr_2"))
    assert (page.title, page.video_count, page.items) == ("", None, 2)
    assert [video.video_id for video in page.videos] == VR_PAGE_2
    assert [video.duration for video in page.videos] == [436.0, 227.0]
    assert page.continuation not in (None, first.continuation)


def test_web_first_page() -> None:
    page = parse_browse_page(browse_fixture("browse_web_1"))
    assert (page.title, page.video_count, page.items) == ("Videos", 139, 3)
    assert [video.video_id for video in page.videos] == VR_PAGE_1
    assert [video.duration for video in page.videos] == [231.0, 234.0, 248.0]
    assert {(video.channel, video.channel_id) for video in page.videos} == {
        ("Rick Astley", CHANNEL_ID)
    }
    assert page.videos[1].title == "Rick Astley - Dance (Live at The O2, London, April 2026)"
    assert page.continuation is not None
    assert page.continuation.startswith("4qmFsgJxEhxW")


def test_web_last_page_has_no_continuation() -> None:
    page = parse_browse_page(browse_fixture("browse_web_2"))
    assert [video.video_id for video in page.videos] == WEB_LAST_PAGE
    assert [video.duration for video in page.videos] == [218.0, 219.0, 214.0]
    assert page.continuation is None


def test_web_shorts_take_their_channel_from_the_header() -> None:
    page = parse_browse_page(browse_fixture("browse_web_shorts"))
    assert (page.title, page.video_count, page.items) == ("Short videos", 297, 2)
    assert [video.video_id for video in page.videos] == ["E_MGy41IYVw", "ihRdK3x3cUY"]
    assert page.videos[0].title.startswith("38 years on, and the music video still hits")
    assert page.videos[1].title.startswith("A message from Rick")
    assert {(v.duration, v.channel, v.channel_id) for v in page.videos} == {
        (None, "Rick Astley", CHANNEL_ID)
    }


def test_only_a_first_page_names_the_playlist_owner() -> None:
    whole = browse_fixture("browse_web_shorts")
    first = parse_browse_page(whole)
    assert (first.owner_name, first.owner_id) == ("Rick Astley", CHANNEL_ID)
    # Shorts never name a channel and continuation pages have no header: a listing fills in.
    later = parse_browse_page({key: value for key, value in whole.items() if key != "header"})
    assert (later.owner_name, later.owner_id) == ("", "")
    assert {(video.channel, video.channel_id) for video in later.videos} == {("", "")}


def test_unplayable_and_foreign_items_are_counted_but_skipped() -> None:
    hidden = {"playlistVideoRenderer": {"videoId": "aaaaaaaaaaa", "isPlayable": False}}
    broken = {"playlistVideoRenderer": {"videoId": "too-short"}}
    playlist = {"lockupViewModel": {"contentId": "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"}}
    short = {"shortsLockupViewModel": {"onTap": {}}}
    page = parse_browse_page(
        web_page(hidden, broken, playlist, short, lockup("bbbbbbbbbbb", title="Kept"))
    )
    assert page.items == 5
    assert [(video.video_id, video.title) for video in page.videos] == [("bbbbbbbbbbb", "Kept")]


def test_items_name_their_own_channel_before_the_header_owner() -> None:
    owner = {"runs": [{"text": "Owner", "navigationEndpoint": {}}]}
    header = {"playlistHeaderRenderer": {"title": {"simpleText": "Mixed"}, "ownerText": owner}}
    other = "UC" + "o" * 22
    page = parse_browse_page(web_page(lockup("aaaaaaaaaaa", channel_id=other), header=header))
    (video,) = page.videos
    assert (video.channel, video.channel_id) == ("Some Channel", other)
    page = parse_browse_page(web_page(lockup("aaaaaaaaaaa"), header=header))
    assert (page.videos[0].channel, page.videos[0].channel_id) == ("Owner", "")


def test_older_web_pages_continue_through_a_continuation_item_renderer() -> None:
    renderer = {
        "continuationItemRenderer": {
            "continuationEndpoint": {"continuationCommand": {"token": "old-token"}}
        }
    }
    action = {"appendContinuationItemsAction": {"continuationItems": [lockup("aaaaaaaaaaa")]}}
    page = parse_browse_page({"onResponseReceivedActions": [action, renderer]})
    assert (page.items, page.continuation) == (1, "old-token")


def test_the_first_continuation_token_wins() -> None:
    def renderer(token: str) -> dict[str, Any]:
        command = {"continuationCommand": {"token": token}}
        return {"continuationItemRenderer": {"continuationEndpoint": command}}

    empty = {"nextContinuationData": {"continuation": ""}}
    page = parse_browse_page({"contents": [empty, renderer("first"), renderer("second")]})
    assert page.continuation == "first"


def test_the_first_link_to_a_channel_names_a_lockups_channel() -> None:
    channel_id = "UC" + "c" * 22
    item = lockup("aaaaaaaaaaa", channel_id=channel_id)
    meta = item["lockupViewModel"]["metadata"]["lockupMetadataViewModel"]["metadata"]
    parts = meta["contentMetadataViewModel"]["metadataRows"][0]["metadataParts"]
    to_playlist = {"onTap": {"innertubeCommand": {"browseEndpoint": {"browseId": "VLPLx"}}}}
    parts.insert(0, {"text": {"content": "A playlist", "commandRuns": [to_playlist, {}]}})
    (video,) = parse_browse_page(web_page(item)).videos
    assert (video.channel, video.channel_id) == ("Some Channel", channel_id)


def test_web_playlist_pages_use_the_page_header() -> None:
    rows = [
        {"metadataParts": [{"avatarStack": {}}]},
        {
            "metadataParts": [
                {"text": {"content": "Playlist"}},
                {"text": {"content": "10 videos"}},
                {"text": {"content": "248,980 views"}},
            ]
        },
    ]
    view = {"metadata": {"contentMetadataViewModel": {"metadataRows": rows}}}
    header = {
        "pageHeaderRenderer": {
            "pageTitle": "RickAstley - Greatest Hits",
            "content": {"pageHeaderViewModel": view},
        }
    }
    page = parse_browse_page(web_page(lockup("aaaaaaaaaaa"), header=header))
    assert (page.title, page.video_count) == ("RickAstley - Greatest Hits", 10)


def test_the_title_falls_back_to_the_playlist_metadata() -> None:
    data = web_page(lockup("aaaaaaaaaaa"))
    data["metadata"] = {"playlistMetadataRenderer": {"title": "Uploads from jawed"}}
    assert parse_browse_page(data).title == "Uploads from jawed"


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("139 videos", 139),
        ("1 video", 1),
        ("1,234 videos", 1234),
        ("No videos", 0),
        ("", None),
        ("many videos", None),
        (", videos", None),
        pytest.param("9" * 5000 + " videos", None, id="5000 digits"),
    ],
)
def test_video_counts(text: str, count: int | None) -> None:
    assert parse_browse_page(vr_page(count=text or " ")).video_count == count


@pytest.mark.parametrize(
    ("badge", "seconds"),
    [("3:51", 231.0), ("0:05", 5.0), ("1:02:03", 3723.0), ("LIVE", None), ("SHORTS", None)],
)
def test_durations_come_from_the_thumbnail_badge(badge: str, seconds: float | None) -> None:
    (video,) = parse_browse_page(web_page(lockup("aaaaaaaaaaa", badge=badge))).videos
    assert video.duration == seconds


@pytest.mark.parametrize(
    ("length", "seconds"), [("231", 231.0), (231, 231.0), ("\xb2", None), ("2.5", None)]
)
def test_android_vr_lengths_are_whole_seconds(length: object, seconds: float | None) -> None:
    item = {"playlistVideoRenderer": {"videoId": "aaaaaaaaaaa", "lengthSeconds": length}}
    (video,) = parse_browse_page({"contents": [item]}).videos
    assert video.duration == seconds


def test_alert_only_answers_become_errors() -> None:
    mix = parse_browse_page(alert_page("This playlist type is unviewable."))
    assert (mix.items, mix.alerts) == (0, ("This playlist type is unviewable.",))
    unavailable = alert_error(mix, source="PLx")
    assert isinstance(unavailable, CollectionUnavailable)
    assert (unavailable.source, unavailable.reason) == ("PLx", "This playlist type is unviewable.")
    missing = alert_error(
        parse_browse_page(alert_page("The playlist does not exist.")), source="@x"
    )
    assert isinstance(missing, CollectionNotFound)
    assert missing.source == "@x"
    assert "The playlist does not exist." in str(missing)


def test_alerts_with_buttons_are_read_too() -> None:
    data = {"alerts": [{"alertWithButtonRenderer": {"text": {"simpleText": "Hidden videos."}}}]}
    assert parse_browse_page(data).alerts == ("Hidden videos.",)


def test_resolved_channel_ids() -> None:
    assert resolved_channel_id(browse_fixture("resolve_handle")) == CHANNEL_ID
    assert resolved_channel_id(browse_fixture("resolve_unknown")) is None
    elsewhere = {"endpoint": {"browseEndpoint": {"browseId": "VLPLFgquLnL59alCl_2TQvOiD5Vgm1"}}}
    assert resolved_channel_id(elsewhere) is None
    assert resolved_channel_id({}) is None


@pytest.mark.parametrize(
    "data",
    [{}, {"contents": "text"}, {"contents": [1, None, [{}]]}, {"header": [], "alerts": "x"}],
)
def test_unexpected_shapes_are_ignored(data: dict[str, Any]) -> None:
    assert parse_browse_page(data) == BrowsePage()
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_browse.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'utmax.core.browse'`.

- [ ] **Step 5: Write the parser**

The walk looks for item renderers and continuation tokens only below `contents`, `continuationContents` and `onResponseReceivedActions`, so headers, sidebars and tracking data never add videos; it does not descend into an item it has read.

`src/utmax/core/browse.py`:

```python
"""Read InnerTube ``browse`` and ``navigation/resolve_url`` answers about playlists and channels.

ANDROID_VR pages list ``playlistVideoRenderer`` items (20 a page) and continue through
``nextContinuationData``. WEB pages list ``lockupViewModel`` items (100 a page), or Shorts as
``richItemRenderer``/``shortsLockupViewModel``, and continue through a
``continuationItemViewModel`` (older pages: ``continuationItemRenderer``). WEB shows regular
playlists under a ``pageHeaderRenderer`` and channel upload lists under a
``playlistHeaderRenderer``, as ANDROID_VR does for both.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from utmax.core.ytdata import items, mapping, text_of
from utmax.errors import CollectionNotFound, CollectionUnavailable
from utmax.models import VideoEntry

__all__ = ["BrowsePage", "alert_error", "parse_browse_page", "resolved_channel_id"]

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
_VIDEO_COUNT = re.compile(r"(\d[\d,]{0,14}) videos?")  # int() refuses absurdly long numbers
_CLOCK = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})")
_LISTING_ROOTS = ("contents", "continuationContents", "onResponseReceivedActions")
_TOKEN_PATHS: dict[str, tuple[str, ...]] = {
    "nextContinuationData": ("continuation",),
    "continuationItemViewModel": (
        "continuationCommand",
        "innertubeCommand",
        "continuationCommand",
        "token",
    ),
    "continuationItemRenderer": ("continuationEndpoint", "continuationCommand", "token"),
}


@dataclass(frozen=True, slots=True)
class BrowsePage:
    """One ``browse`` answer.

    ``videos`` are the playable videos on the page, numbered 0 (a listing numbers them);
    ``items`` counts every list item, skipped ones included; ``continuation`` is the token of
    the next page. ``title``, ``video_count`` and the playlist's owner (``owner_name`` and
    ``owner_id``, the channel that owns it) come from the playlist header of a first page;
    continuation pages have no header, so a listing takes the owner from its first page.
    ``alerts`` are YouTube's messages, such as "The playlist does not exist.".
    """

    videos: tuple[VideoEntry, ...] = ()
    items: int = 0
    continuation: str | None = None
    title: str = ""
    video_count: int | None = None
    alerts: tuple[str, ...] = ()
    owner_name: str = ""
    owner_id: str = ""


def parse_browse_page(data: Mapping[str, Any]) -> BrowsePage:
    """Read a first or continuation page of either client; unknown parts are ignored."""
    title, video_count, owner = _header(data)
    listing = _Listing(owner)
    for root in _LISTING_ROOTS:
        listing.walk(data.get(root))
    return BrowsePage(
        videos=tuple(listing.videos),
        items=listing.items,
        continuation=listing.continuation,
        title=title,
        video_count=video_count,
        alerts=_alerts(data),
        owner_name=owner.name,
        owner_id=owner.channel_id,
    )


def resolved_channel_id(data: Mapping[str, Any]) -> str | None:
    """The channel a ``navigation/resolve_url`` answer points to; ``None`` when it points
    nowhere (ANDROID_VR answers an unknown handle with a plain ``urlEndpoint``)."""
    browse_id = _dig(data, "endpoint", "browseEndpoint", "browseId")
    return browse_id if isinstance(browse_id, str) and _CHANNEL_ID.fullmatch(browse_id) else None


def alert_error(page: BrowsePage, *, source: str) -> CollectionNotFound | CollectionUnavailable:
    """The error for a page that holds only alerts, such as WEB's answers for a missing
    playlist ("The playlist does not exist.") or a Mix ("This playlist type is unviewable.")."""
    reason = " ".join(page.alerts)
    if "does not exist" in reason.lower():
        return CollectionNotFound(f"YouTube cannot find {source!r}: {reason}", source=source)
    return CollectionUnavailable(
        f"YouTube will not list {source!r}: {reason}", source=source, reason=reason
    )


@dataclass(frozen=True, slots=True)
class _Owner:
    """The playlist's channel: the fallback for items that do not name theirs."""

    name: str = ""
    channel_id: str = ""


class _Listing:
    """Collects the videos and the first continuation token under a listing root."""

    def __init__(self, owner: _Owner) -> None:
        self.owner = owner
        self.videos: list[VideoEntry] = []
        self.items = 0
        self.continuation: str | None = None

    def walk(self, node: object) -> None:
        if isinstance(node, list):
            for child in node:
                self.walk(child)
            return
        if not isinstance(node, Mapping):
            return
        for key, value in node.items():
            reader = _ITEM_READERS.get(key)
            if reader is not None:
                self.items += 1
                entry = reader(mapping(value), self.owner)
                if entry is not None:
                    self.videos.append(entry)
            elif key in _TOKEN_PATHS:
                token = _dig(value, *_TOKEN_PATHS[key])
                if isinstance(token, str) and token and self.continuation is None:
                    self.continuation = token
            else:
                self.walk(value)


def _android_vr_video(raw: Mapping[str, Any], owner: _Owner) -> VideoEntry | None:
    video_id = _video_id(raw.get("videoId"))
    if video_id is None or raw.get("isPlayable") is False:
        return None
    byline = mapping(raw.get("shortBylineText"))
    return VideoEntry(
        video_id=video_id,
        title=text_of(raw.get("title")),
        duration=_seconds(raw.get("lengthSeconds")),
        channel=text_of(byline) or owner.name,
        channel_id=_run_channel_id(byline) or owner.channel_id,
        index=0,
    )


def _lockup_video(raw: Mapping[str, Any], owner: _Owner) -> VideoEntry | None:
    video_id = _video_id(raw.get("contentId"))
    if video_id is None:
        return None
    meta = mapping(_dig(raw, "metadata", "lockupMetadataViewModel"))
    name, channel_id = _lockup_channel(meta)
    return VideoEntry(
        video_id=video_id,
        title=str(_dig(meta, "title", "content") or ""),
        duration=_badge_seconds(raw),
        channel=name or owner.name,
        channel_id=channel_id or owner.channel_id,
        index=0,
    )


def _short_video(raw: Mapping[str, Any], owner: _Owner) -> VideoEntry | None:
    video_id = _video_id(_dig(raw, "onTap", "innertubeCommand", "reelWatchEndpoint", "videoId"))
    if video_id is None:
        return None
    return VideoEntry(
        video_id=video_id,
        title=str(_dig(raw, "overlayMetadata", "primaryText", "content") or ""),
        duration=None,
        channel=owner.name,
        channel_id=owner.channel_id,
        index=0,
    )


_ITEM_READERS: dict[str, Callable[[Mapping[str, Any], _Owner], VideoEntry | None]] = {
    "playlistVideoRenderer": _android_vr_video,
    "lockupViewModel": _lockup_video,
    "shortsLockupViewModel": _short_video,
}


def _header(data: Mapping[str, Any]) -> tuple[str, int | None, _Owner]:
    header = mapping(data.get("header"))
    classic = mapping(header.get("playlistHeaderRenderer"))
    if classic:
        owner_text = mapping(classic.get("ownerText"))
        title = text_of(classic.get("title"))
        video_count = _video_count(text_of(classic.get("numVideosText")))
        owner = _Owner(text_of(owner_text), _run_channel_id(owner_text))
    else:
        page = mapping(header.get("pageHeaderRenderer"))
        title = str(page.get("pageTitle") or "")
        counts = (_video_count(text) for text in _page_header_texts(page))
        video_count = next((count for count in counts if count is not None), None)
        owner = _Owner()
    title = title or str(_dig(data, "metadata", "playlistMetadataRenderer", "title") or "")
    return title, video_count, owner


def _page_header_texts(page: Mapping[str, Any]) -> list[str]:
    rows = items(
        _dig(
            page,
            "content",
            "pageHeaderViewModel",
            "metadata",
            "contentMetadataViewModel",
            "metadataRows",
        )
    )
    return [
        str(_dig(part, "text", "content") or "")
        for row in map(mapping, rows)
        for part in map(mapping, items(row.get("metadataParts")))
    ]


def _alerts(data: Mapping[str, Any]) -> tuple[str, ...]:
    texts: list[str] = []
    for alert in map(mapping, items(data.get("alerts"))):
        for renderer in ("alertRenderer", "alertWithButtonRenderer"):
            text = text_of(_dig(alert, renderer, "text")).strip()
            if text:
                texts.append(text)
    return tuple(texts)


def _lockup_channel(meta: Mapping[str, Any]) -> tuple[str, str]:
    """The first metadata text that links to a channel: that text and the channel ID."""
    rows = items(_dig(meta, "metadata", "contentMetadataViewModel", "metadataRows"))
    for row in map(mapping, rows):
        for part in map(mapping, items(row.get("metadataParts"))):
            text = mapping(part.get("text"))
            for command in map(mapping, items(text.get("commandRuns"))):
                browse_id = _dig(command, "onTap", "innertubeCommand", "browseEndpoint", "browseId")
                if isinstance(browse_id, str) and _CHANNEL_ID.fullmatch(browse_id):
                    return str(text.get("content") or ""), browse_id
    return "", ""


def _run_channel_id(text: Mapping[str, Any]) -> str:
    """The channel the runs of a text object link to, or ``""``."""
    for run in map(mapping, items(text.get("runs"))):
        browse_id = _dig(run, "navigationEndpoint", "browseEndpoint", "browseId")
        if isinstance(browse_id, str) and _CHANNEL_ID.fullmatch(browse_id):
            return browse_id
    return ""


def _badge_seconds(raw: Mapping[str, Any]) -> float | None:
    """The duration shown on a lockup's thumbnail ("3:51"); ``None`` for "LIVE" and the like."""
    for overlay in map(mapping, items(_dig(raw, "contentImage", "thumbnailViewModel", "overlays"))):
        for badge in map(
            mapping, items(_dig(overlay, "thumbnailBottomOverlayViewModel", "badges"))
        ):
            seconds = _clock_seconds(_dig(badge, "thumbnailBadgeViewModel", "text"))
            if seconds is not None:
                return seconds
    return None


def _clock_seconds(text: object) -> float | None:
    """``"3:51"`` is 231 seconds and ``"1:02:03"`` 3723; other text is ``None``."""
    match = _CLOCK.fullmatch(text.strip()) if isinstance(text, str) else None
    if match is None:
        return None
    hours, minutes, seconds = (int(group or 0) for group in match.groups())
    return float(hours * 3600 + minutes * 60 + seconds)


def _video_count(text: str) -> int | None:
    """``"139 videos"`` is 139, ``"1 video"`` 1 and ``"No videos"`` 0; other text is ``None``."""
    text = text.strip()
    if text.lower() == "no videos":
        return 0
    match = _VIDEO_COUNT.fullmatch(text)
    return int(match.group(1).replace(",", "")) if match else None


def _seconds(value: object) -> float | None:
    text = str(value) if isinstance(value, (str, int)) else ""
    # isdecimal, not isdigit: float() rejects the superscript digits that isdigit accepts.
    return float(text) if text.isdecimal() else None


def _video_id(value: object) -> str | None:
    return value if isinstance(value, str) and _VIDEO_ID.fullmatch(value) else None


def _dig(value: object, *keys: str) -> Any:
    """The value at ``keys`` inside nested JSON objects, or ``None``."""
    for key in keys:
        value = mapping(value).get(key)
    return value
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_browse.py -q`
Expected: 37 passed.

- [ ] **Step 7: Teach the recorder to keep the browse answers**

Do not run the recorder: it needs network access and re-records every fixture. The files of Step 1 are its output, and the README text below is what it writes.

In `scripts/record_fixtures.py`:

1. Replace:

```python
from utmax.adapters.http import RetryingTransport, UrllibTransport
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.captions import caption_url
from utmax.core.clients import ANDROID, ANDROID_VR, IOS
from utmax.transport import HttpRequest

VIDEO_ID = "dQw4w9WgXcQ"
```

   with:

```python
from utmax.adapters.http import RetryingTransport, UrllibTransport
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.captions import caption_url
from utmax.core.clients import ANDROID, ANDROID_VR, IOS, WEB
from utmax.transport import HttpRequest

VIDEO_ID = "dQw4w9WgXcQ"
```

2. Replace:

```python
    "drmFamilies",
    "targetDurationSec",
)


def redact_url(url: str) -> str:
```

   with:

```python
    "drmFamilies",
    "targetDurationSec",
)
CHANNEL_ID = "UCuAXFkgsw1L7xaCfnd5JJOw"  # Rick Astley
VIDEOS_LIST = f"UULF{CHANNEL_ID[2:]}"  # his long-form uploads
SHORTS_LIST = f"UUSH{CHANNEL_ID[2:]}"  # his Shorts
HANDLE_URL = "https://www.youtube.com/@RickAstleyYT"
UNKNOWN_HANDLE_URL = "https://www.youtube.com/@thishandledoesnotexist20260928x"
# What the browse fixtures keep of each renderer (True keeps a whole value).
OWNER_KEEP = {"runs": {"text": True, "navigationEndpoint": {"browseEndpoint": {"browseId": True}}}}
HEADER_KEEP = {"playlistId": True, "title": True, "numVideosText": True, "ownerText": OWNER_KEEP}
PLAYLIST_VIDEO_KEEP = {
    "videoId": True,
    "title": True,
    "index": True,
    "shortBylineText": OWNER_KEEP,
    "lengthSeconds": True,
    "isPlayable": True,
}
CHANNEL_RUN_KEEP = {
    "content": True,
    "commandRuns": {"onTap": {"innertubeCommand": {"browseEndpoint": {"browseId": True}}}},
}
BADGE_KEEP = {
    "thumbnailBottomOverlayViewModel": {"badges": {"thumbnailBadgeViewModel": {"text": True}}}
}
LOCKUP_KEEP = {
    "contentId": True,
    "contentType": True,
    "contentImage": {"thumbnailViewModel": {"overlays": BADGE_KEEP}},
    "metadata": {
        "lockupMetadataViewModel": {
            "title": True,
            "metadata": {
                "contentMetadataViewModel": {
                    "metadataRows": {"metadataParts": {"text": CHANNEL_RUN_KEEP}}
                }
            },
        }
    },
}
SHORTS_KEEP = {
    "onTap": {"innertubeCommand": {"reelWatchEndpoint": {"videoId": True}}},
    "overlayMetadata": {"primaryText": True},
}
CONTINUATION_KEEP = {
    "continuationCommand": {"innertubeCommand": {"continuationCommand": {"token": True}}}
}


def redact_url(url: str) -> str:
```

3. Replace:

```python
    return "\n".join(lines) + "\n"


def first_elements(xml: str, tag: str, count: int, *, head_end: str, tail: str) -> str:
    head = xml[: xml.index(head_end) + len(head_end)]
    elements = re.findall(rf"<{tag}\b.*?</{tag}>", xml, flags=re.DOTALL)[:count]
```

   with:

```python
    return "\n".join(lines) + "\n"


def prune(node: Any, keep: Any) -> Any:
    """Only the keys named in ``keep`` (``True`` keeps a whole value); lists are pruned per item."""
    if keep is True:
        return node
    if isinstance(node, list):
        return [prune(item, keep) for item in node]
    if isinstance(node, dict):
        return {key: prune(node[key], sub) for key, sub in keep.items() if key in node}
    return node


def playlist_page(renderer: dict[str, Any], count: int, token: str) -> dict[str, Any]:
    """An ANDROID_VR video list with its first ``count`` videos and a continuation token."""
    return {
        "contents": [
            {"playlistVideoRenderer": prune(item["playlistVideoRenderer"], PLAYLIST_VIDEO_KEEP)}
            for item in renderer["contents"][:count]
        ],
        "continuations": [{"nextContinuationData": {"continuation": token}}],
    }


def android_vr_pages(innertube: InnerTubeClient) -> tuple[dict[str, Any], dict[str, Any]]:
    """The first two ANDROID_VR pages of VIDEOS_LIST: three and two videos."""
    first = innertube.browse(ANDROID_VR, browse_id=f"VL{VIDEOS_LIST}")
    tab = first["contents"]["singleColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]
    renderer = next(
        item["playlistVideoListRenderer"]
        for item in tab["content"]["sectionListRenderer"]["contents"]
        if "playlistVideoListRenderer" in item
    )
    token = renderer["continuations"][0]["nextContinuationData"]["continuation"]
    second = innertube.browse(ANDROID_VR, continuation=token)
    following = second["continuationContents"]["playlistVideoListContinuation"]
    next_token = following["continuations"][0]["nextContinuationData"]["continuation"]
    section = {"playlistVideoListRenderer": playlist_page(renderer, 3, token)}
    header = prune(first["header"]["playlistHeaderRenderer"], HEADER_KEEP)
    first_page = {
        "header": {"playlistHeaderRenderer": header},
        "contents": {
            "singleColumnBrowseResultsRenderer": {
                "tabs": [
                    {"tabRenderer": {"content": {"sectionListRenderer": {"contents": [section]}}}}
                ]
            }
        },
    }
    continuation = playlist_page(following, 2, next_token)
    second_page = {"continuationContents": {"playlistVideoListContinuation": continuation}}
    return first_page, second_page


def web_items(items: list[Any]) -> list[Any]:
    """WEB list items with only the fields utmax reads."""
    kept: list[Any] = []
    for item in items:
        if "lockupViewModel" in item:
            kept.append({"lockupViewModel": prune(item["lockupViewModel"], LOCKUP_KEEP)})
        elif "continuationItemViewModel" in item:
            view = prune(item["continuationItemViewModel"], CONTINUATION_KEEP)
            kept.append({"continuationItemViewModel": view})
        elif "richItemRenderer" in item:
            short = prune(item["richItemRenderer"]["content"]["shortsLockupViewModel"], SHORTS_KEEP)
            kept.append({"richItemRenderer": {"content": {"shortsLockupViewModel": short}}})
    return kept


def web_page(items: list[Any], header: dict[str, Any]) -> dict[str, Any]:
    """A WEB first page holding ``items`` under a playlist header."""
    section = {"itemSectionRenderer": {"contents": items}}
    return {
        "header": {"playlistHeaderRenderer": prune(header, HEADER_KEEP)},
        "contents": {
            "twoColumnBrowseResultsRenderer": {
                "tabs": [
                    {"tabRenderer": {"content": {"sectionListRenderer": {"contents": [section]}}}}
                ]
            }
        },
    }


def web_pages(innertube: InnerTubeClient) -> tuple[dict[str, Any], ...]:
    """WEB pages: the first page of VIDEOS_LIST (three videos) and its last page (the first
    two and the last video), and the first page of SHORTS_LIST (two Shorts)."""
    first = innertube.browse(WEB, browse_id=f"VL{VIDEOS_LIST}")
    tab = first["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]
    items = tab["content"]["sectionListRenderer"]["contents"][0]["itemSectionRenderer"]["contents"]
    command = items[-1]["continuationItemViewModel"]["continuationCommand"]
    second = innertube.browse(
        WEB, continuation=command["innertubeCommand"]["continuationCommand"]["token"]
    )
    action = second["onResponseReceivedActions"][0]["appendContinuationItemsAction"]
    appended = action["continuationItems"]
    shorts = innertube.browse(WEB, browse_id=f"VL{SHORTS_LIST}")
    shorts_tab = shorts["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]
    shorts_section = shorts_tab["content"]["sectionListRenderer"]["contents"][0]
    grid = shorts_section["itemSectionRenderer"]["contents"][0]["richGridRenderer"]
    header = first["header"]["playlistHeaderRenderer"]
    first_page = web_page(web_items([*items[:3], items[-1]]), header)
    last_items = web_items([*appended[:2], appended[-1]])
    second_page = {
        "onResponseReceivedActions": [
            {"appendContinuationItemsAction": {"continuationItems": last_items}}
        ]
    }
    shorts_page = web_page(
        [{"richGridRenderer": {"contents": web_items(grid["contents"][:2])}}],
        shorts["header"]["playlistHeaderRenderer"],
    )
    return first_page, second_page, shorts_page


def resolved(innertube: InnerTubeClient, url: str) -> dict[str, Any]:
    """The ``endpoint`` of the ANDROID_VR ``navigation/resolve_url`` answer for ``url``."""
    endpoint = innertube.resolve_url(ANDROID_VR, url)["endpoint"]
    kept = {key: endpoint[key] for key in ("browseEndpoint", "urlEndpoint") if key in endpoint}
    return {"endpoint": kept}


def first_elements(xml: str, tag: str, count: int, *, head_end: str, tail: str) -> str:
    head = xml[: xml.index(head_end) + len(head_end)]
    elements = re.findall(rf"<{tag}\b.*?</{tag}>", xml, flags=re.DOTALL)[:count]
```

4. Replace:

```python
        "srv3_en_asr.xml",
        first_elements(srv3, "p", 16, head_end="<body>", tail="\n</body></timedtext>\n"),
    )
    write(
        "README.md",
        f"# YouTube fixtures\n\nRecorded {date.today().isoformat()} from video `{VIDEO_ID}` with\n"
        "`uv run python scripts/record_fixtures.py`. URL parameters "
        f"{', '.join(sorted(SECRET_PARAMS))} are replaced with `REDACTED`.\n"
        "`streams_android_vr.json` keeps only the stream fields utmax reads; its URLs are\n"
        "placeholders that keep the itag and the client name.\n",
    )


```

   with:

```python
        "srv3_en_asr.xml",
        first_elements(srv3, "p", 16, head_end="<body>", tail="\n</body></timedtext>\n"),
    )
    vr_first, vr_second = android_vr_pages(innertube)
    web_first, web_second, web_shorts = web_pages(innertube)
    browse_fixtures = {
        "browse_android_vr_1.json": vr_first,
        "browse_android_vr_2.json": vr_second,
        "browse_web_1.json": web_first,
        "browse_web_2.json": web_second,
        "browse_web_shorts.json": web_shorts,
        "resolve_handle.json": resolved(innertube, HANDLE_URL),
        "resolve_unknown.json": resolved(innertube, UNKNOWN_HANDLE_URL),
    }
    for name, data in browse_fixtures.items():
        write(name, json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    write(
        "README.md",
        f"# YouTube fixtures\n\nRecorded {date.today().isoformat()} from video `{VIDEO_ID}` with\n"
        "`uv run python scripts/record_fixtures.py`. URL parameters "
        f"{', '.join(sorted(SECRET_PARAMS))} are replaced with `REDACTED`.\n"
        "`streams_android_vr.json` keeps only the stream fields utmax reads; its URLs are\n"
        "placeholders that keep the itag and the client name.\n"
        "`browse_*.json` hold the first videos of Rick Astley's long-form uploads\n"
        f"(`{VIDEOS_LIST}`: ANDROID_VR pages 1 and 2, the WEB first and last pages) and\n"
        f"of his Shorts (`{SHORTS_LIST}`, WEB), trimmed to the fields utmax reads;\n"
        "`resolve_*.json` hold the ANDROID_VR `navigation/resolve_url` answers for\n"
        "`@RickAstleyYT` and for a handle that does not exist.\n",
    )


```

In `tests/fixtures/youtube/README.md`:

1. Replace:

```markdown
# YouTube fixtures

Recorded 2026-09-27 from video `dQw4w9WgXcQ` with
`uv run python scripts/record_fixtures.py`. URL parameters ei, expire, ip, key, lsig, sig, signature are replaced with `REDACTED`.
`streams_android_vr.json` keeps only the stream fields utmax reads; its URLs are
placeholders that keep the itag and the client name.
```

   with:

```markdown
# YouTube fixtures

Recorded 2026-09-28 from video `dQw4w9WgXcQ` with
`uv run python scripts/record_fixtures.py`. URL parameters ei, expire, ip, key, lsig, sig, signature are replaced with `REDACTED`.
`streams_android_vr.json` keeps only the stream fields utmax reads; its URLs are
placeholders that keep the itag and the client name.
`browse_*.json` hold the first videos of Rick Astley's long-form uploads
(`UULFuAXFkgsw1L7xaCfnd5JJOw`: ANDROID_VR pages 1 and 2, the WEB first and last pages) and
of his Shorts (`UUSHuAXFkgsw1L7xaCfnd5JJOw`, WEB), trimmed to the fields utmax reads;
`resolve_*.json` hold the ANDROID_VR `navigation/resolve_url` answers for
`@RickAstleyYT` and for a handle that does not exist.
```

- [ ] **Step 8: Gates and commit**

Run the four gates (the suite grows by 37 to 1214 passed). `mypy` checks `src` only; the recorder was checked with `uv run mypy --strict scripts/record_fixtures.py` while this plan was written, and `ruff` covers it.

```bash
git add tests/fixtures/youtube/browse_android_vr_1.json tests/fixtures/youtube/browse_android_vr_2.json tests/fixtures/youtube/browse_web_1.json tests/fixtures/youtube/browse_web_2.json tests/fixtures/youtube/browse_web_shorts.json tests/fixtures/youtube/resolve_handle.json tests/fixtures/youtube/resolve_unknown.json tests/fixtures/youtube/README.md tests/helpers/browse.py tests/unit/core/test_browse.py src/utmax/core/browse.py scripts/record_fixtures.py
git commit -m "feat: read browse pages of both clients over recorded answers" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Decide when a listing is complete

**Files:**
- Modify: `src/utmax/core/browse.py`
- Test: `tests/unit/core/test_pager.py` (create)

**Interfaces:**
- Consumes: `BrowsePage` and `parse_browse_page` (Task 4), and in the tests `CHANNEL_ID` and `browse_fixture` of `tests.helpers.browse` (Task 4); `VideoEntry` (Task 1).
- Produces (in `utmax.core.browse`):
  - `MAX_PAGES = 1000`.
  - `Pager(*, limit: int | None = None, max_pages: int = MAX_PAGES)` with `add(page: BrowsePage) -> str | None` (the continuation token to fetch next, or `None` when the listing is complete), `entries -> tuple[VideoEntry, ...]` (numbered 1, 2, 3 …, repeats dropped; a video that names no channel gets the playlist owner of the first page, `owner_name` and `owner_id`, because only a first page has a header) and `truncated: bool` (set when `max_pages` stopped the listing).

- [ ] **Step 1: Write the failing tests**

`tests/unit/core/test_pager.py`:

```python
"""Tests for the Pager, which decides when a listing is complete."""

from __future__ import annotations

import json

from tests.helpers.browse import CHANNEL_ID, browse_fixture
from utmax.core.browse import MAX_PAGES, BrowsePage, Pager, parse_browse_page
from utmax.models import VideoEntry


def page(*video_ids: str, token: str | None = None, items: int | None = None) -> BrowsePage:
    videos = tuple(
        VideoEntry(v, f"Video {v}", 60.0, "Channel", "UC" + "x" * 22, 0) for v in video_ids
    )
    return BrowsePage(videos, len(videos) if items is None else items, token)


def ids(pager: Pager) -> list[tuple[str, int]]:
    return [(entry.video_id, entry.index) for entry in pager.entries]


def test_videos_are_numbered_across_pages_and_repeats_dropped() -> None:
    pager = Pager()
    assert pager.add(page("a", "b", token="t1")) == "t1"
    assert pager.add(page("b", "c", token="t2")) == "t2"
    assert pager.add(page("d")) is None
    assert ids(pager) == [("a", 1), ("b", 2), ("c", 3), ("d", 4)]
    assert pager.entries[2].title == "Video c"
    assert not pager.truncated


def test_the_limit_stops_in_the_middle_of_a_page() -> None:
    pager = Pager(limit=3)
    assert pager.add(page("a", "b", token="t1")) == "t1"
    assert pager.add(page("c", "d", "e", token="t2")) is None
    assert ids(pager) == [("a", 1), ("b", 2), ("c", 3)]


def test_a_full_first_page_needs_no_second_request() -> None:
    pager = Pager(limit=2)
    assert pager.add(page("a", "b", token="t1")) is None
    assert ids(pager) == [("a", 1), ("b", 2)]


def test_a_repeated_token_ends_the_listing() -> None:
    pager = Pager()
    assert pager.add(page("a", token="t1")) == "t1"
    assert pager.add(page("b", token="t1")) is None
    assert ids(pager) == [("a", 1), ("b", 2)]


def test_a_page_without_items_ends_the_listing() -> None:
    pager = Pager()
    assert pager.add(page("a", token="t1")) == "t1"
    assert pager.add(page(token="t2")) is None
    assert ids(pager) == [("a", 1)]


def test_pages_of_skipped_items_do_not_end_the_listing() -> None:
    pager = Pager()
    assert pager.add(page(token="t1", items=20)) == "t1"
    assert pager.add(page("a")) is None
    assert ids(pager) == [("a", 1)]


def test_the_page_cap_truncates_endless_listings() -> None:
    pager = Pager(max_pages=3)
    assert pager.add(page("a", token="t1")) == "t1"
    assert pager.add(page("b", token="t2")) == "t2"
    assert pager.add(page("c", token="t3")) is None
    assert pager.truncated
    assert ids(pager) == [("a", 1), ("b", 2), ("c", 3)]
    assert MAX_PAGES == 1000


def test_videos_that_name_no_channel_get_the_owner_of_the_first_page() -> None:
    whole = browse_fixture("browse_web_shorts")
    # The next page of Shorts: no header (as on every continuation page), other videos.
    text = json.dumps({key: value for key, value in whole.items() if key != "header"})
    text = text.replace("E_MGy41IYVw", "aaaaaaaaaaa").replace("ihRdK3x3cUY", "bbbbbbbbbbb")
    pager = Pager()
    pager.add(parse_browse_page(whole))
    pager.add(parse_browse_page(json.loads(text)))
    assert ids(pager) == [
        ("E_MGy41IYVw", 1),
        ("ihRdK3x3cUY", 2),
        ("aaaaaaaaaaa", 3),
        ("bbbbbbbbbbb", 4),
    ]
    assert {(entry.channel, entry.channel_id) for entry in pager.entries} == {
        ("Rick Astley", CHANNEL_ID)
    }


def test_videos_keep_the_channel_they_name() -> None:
    other, owner = "UC" + "x" * 22, "UC" + "o" * 22
    named = VideoEntry("a", "A", 60.0, "Other", other, 0)
    unnamed = VideoEntry("b", "B", None, "", "", 0)
    pager = Pager()
    pager.add(BrowsePage((named,), 1, "t1", owner_name="Owner", owner_id=owner))
    pager.add(BrowsePage((unnamed,), 1))
    assert [(entry.channel, entry.channel_id) for entry in pager.entries] == [
        ("Other", other),
        ("Owner", owner),
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_pager.py -q`
Expected: collection error — `ImportError: cannot import name 'MAX_PAGES' from 'utmax.core.browse'`.

- [ ] **Step 3: Add the Pager**

In `src/utmax/core/browse.py`:

1. Replace:

```python
``richItemRenderer``/``shortsLockupViewModel``, and continue through a
``continuationItemViewModel`` (older pages: ``continuationItemRenderer``). WEB shows regular
playlists under a ``pageHeaderRenderer`` and channel upload lists under a
``playlistHeaderRenderer``, as ANDROID_VR does for both.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from utmax.core.ytdata import items, mapping, text_of
from utmax.errors import CollectionNotFound, CollectionUnavailable
from utmax.models import VideoEntry

__all__ = ["BrowsePage", "alert_error", "parse_browse_page", "resolved_channel_id"]

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
```

   with:

```python
``richItemRenderer``/``shortsLockupViewModel``, and continue through a
``continuationItemViewModel`` (older pages: ``continuationItemRenderer``). WEB shows regular
playlists under a ``pageHeaderRenderer`` and channel upload lists under a
``playlistHeaderRenderer``, as ANDROID_VR does for both. :class:`Pager` decides which page
comes next; the caller fetches it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from utmax.core.ytdata import items, mapping, text_of
from utmax.errors import CollectionNotFound, CollectionUnavailable
from utmax.models import VideoEntry

__all__ = [
    "MAX_PAGES",
    "BrowsePage",
    "Pager",
    "alert_error",
    "parse_browse_page",
    "resolved_channel_id",
]

MAX_PAGES = 1000

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
```

2. Replace:

```python
    return CollectionUnavailable(
        f"YouTube will not list {source!r}: {reason}", source=source, reason=reason
    )


@dataclass(frozen=True, slots=True)
```

   with:

```python
    return CollectionUnavailable(
        f"YouTube will not list {source!r}: {reason}", source=source, reason=reason
    )


class Pager:
    """Collects the pages of one listing and says which page to fetch next (no I/O).

    Videos are numbered 1, 2, 3 ... in listing order and a video seen before is dropped. Only
    the first page has a header, so its owner is the channel of every video that names none.
    The listing ends at ``limit`` videos, at a page without a continuation or without items, at
    a continuation seen before, or after ``max_pages`` pages (``truncated`` is then true).
    """

    def __init__(self, *, limit: int | None = None, max_pages: int = MAX_PAGES) -> None:
        self._limit = limit
        self._max_pages = max_pages
        self._pages = 0
        self._tokens: set[str] = set()
        self._seen: set[str] = set()
        self._entries: list[VideoEntry] = []
        self._owner = ("", "")
        self.truncated = False

    @property
    def entries(self) -> tuple[VideoEntry, ...]:
        """The videos collected so far, numbered."""
        return tuple(self._entries)

    def add(self, page: BrowsePage) -> str | None:
        """Take the next page; return the continuation token to fetch, or ``None`` when done."""
        self._pages += 1
        if self._pages == 1:
            self._owner = (page.owner_name, page.owner_id)
        for video in page.videos:
            if self._full():
                break
            if video.video_id not in self._seen:
                self._seen.add(video.video_id)
                self._entries.append(self._numbered(video))
        token = page.continuation
        if token is None or not page.items or self._full() or token in self._tokens:
            return None
        if self._pages >= self._max_pages:
            self.truncated = True
            return None
        self._tokens.add(token)
        return token

    def _numbered(self, video: VideoEntry) -> VideoEntry:
        """``video`` at the next position; a channel it does not name is the owner's."""
        name, channel_id = self._owner
        return replace(
            video,
            channel=video.channel or name,
            channel_id=video.channel_id or channel_id,
            index=len(self._entries) + 1,
        )

    def _full(self) -> bool:
        return self._limit is not None and len(self._entries) >= self._limit


@dataclass(frozen=True, slots=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_pager.py tests/unit/core/test_browse.py -q`
Expected: 46 passed (9 new).

- [ ] **Step 5: Gates and commit**

Run the four gates (the suite grows by 9 to 1223 passed).

```bash
git add src/utmax/core/browse.py tests/unit/core/test_pager.py
git commit -m "feat: decide when a listing is complete" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: List the videos of playlists and channels

**Files:**
- Create: `src/utmax/services/collections.py`
- Test: `tests/unit/services/test_collections.py` (create)

**Interfaces:**
- Consumes: `COLLECTION_KINDS`, `parse_source`, `uploads_playlist_id` (Task 2); `InnerTubeClient.browse` and `resolve_url` (Task 3); `parse_browse_page`, `alert_error`, `resolved_channel_id` (Task 4); `Pager`, `MAX_PAGES` (Task 5); `ORDER["browse"]` and `ORDER["resolve"]` (both `(ANDROID_VR, WEB)`, M1); `CollectionKind`, `VideoList` and the errors of Task 1.
- Produces: `utmax.services.collections.CollectionService(innertube: InnerTubeClient, *, max_pages: int = MAX_PAGES)` with `list_videos(source: str, *, kind: CollectionKind = "all", limit: int | None = None) -> VideoList` (Decisions 2–7).

- [ ] **Step 1: Write the failing tests**

The tests script `FakeTransport` routes: replies of one route are served in order, and ANDROID_VR and WEB use the same URL, so the order of the replies is the order of the requests (the tests also check which client sent each one).

`tests/unit/services/test_collections.py`:

```python
"""Tests for listing playlists and channels over recorded and synthetic browse answers."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from tests.helpers.browse import (
    CHANNEL_ID,
    VIDEOS_LIST,
    VR_PAGE_1,
    VR_PAGE_2,
    WEB_LAST_PAGE,
    alert_page,
    browse_fixture,
    error_body,
    vr_page,
)
from tests.helpers.fake_transport import FakeTransport, json_response, text_response
from utmax.adapters.innertube import InnerTubeClient
from utmax.errors import (
    CollectionNotFound,
    CollectionUnavailable,
    InvalidOption,
    InvalidSource,
    IpBlocked,
    UTMaxError,
    YouTubeRequestFailed,
)
from utmax.models import CollectionKind
from utmax.services.collections import CollectionService

PLAYLIST = "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"
HANDLE = "@RickAstleyYT"
BROWSE = "/youtubei/v1/browse"
RESOLVE = "/youtubei/v1/navigation/resolve_url"
VR_1 = browse_fixture("browse_android_vr_1")
VR_2 = browse_fixture("browse_android_vr_2")
WEB_1 = browse_fixture("browse_web_1")
WEB_2 = browse_fixture("browse_web_2")


def service(transport: FakeTransport, **options: Any) -> CollectionService:
    return CollectionService(InnerTubeClient(transport), **options)


def sent(transport: FakeTransport) -> list[tuple[str, dict[str, Any]]]:
    """The client name and the body (without its context) of every request."""
    calls = []
    for request in transport.requests:
        body = json.loads(request.body or b"{}")
        calls.append((body.pop("context")["client"]["clientName"], body))
    return calls


def token(page: dict[str, Any]) -> str:
    renderer = page["continuationContents"]["playlistVideoListContinuation"]
    return str(renderer["continuations"][0]["nextContinuationData"]["continuation"])


def first_token() -> str:
    tab = VR_1["contents"]["singleColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]
    renderer = tab["content"]["sectionListRenderer"]["contents"][0]["playlistVideoListRenderer"]
    return str(renderer["continuations"][0]["nextContinuationData"]["continuation"])


def test_a_playlist_is_listed_page_by_page() -> None:
    transport = FakeTransport()
    transport.add("POST", BROWSE, json_response(VR_1), json_response(VR_2), json_response(VR_2))
    videos = service(transport).list_videos(VIDEOS_LIST)
    assert [entry.video_id for entry in videos] == VR_PAGE_1 + VR_PAGE_2
    assert [entry.index for entry in videos] == [1, 2, 3, 4, 5]
    assert [entry.duration for entry in videos] == [231.0, 234.0, 248.0, 436.0, 227.0]
    assert (videos.title, videos.source_id, videos.kind, videos.video_count) == (
        "Videos",
        VIDEOS_LIST,
        "all",
        139,
    )
    assert sent(transport) == [
        ("ANDROID_VR", {"browseId": f"VL{VIDEOS_LIST}"}),
        ("ANDROID_VR", {"continuation": first_token()}),
        ("ANDROID_VR", {"continuation": token(VR_2)}),
    ]


def test_limit_stops_the_listing_early() -> None:
    transport = FakeTransport()
    transport.add("POST", BROWSE, json_response(VR_1))
    url = f"https://www.youtube.com/playlist?list={VIDEOS_LIST}"
    videos = service(transport).list_videos(url, limit=2)
    assert [entry.video_id for entry in videos] == VR_PAGE_1[:2]
    assert len(transport.requests) == 1


def test_handles_are_resolved_then_listed_by_kind() -> None:
    transport = FakeTransport()
    transport.add("POST", RESOLVE, json_response(browse_fixture("resolve_handle")))
    transport.add("POST", BROWSE, json_response(VR_1), json_response(VR_2), json_response(VR_2))
    videos = service(transport).list_videos(HANDLE, kind="videos")
    assert (videos.source_id, videos.kind, len(videos)) == (VIDEOS_LIST, "videos", 5)
    assert sent(transport)[:2] == [
        ("ANDROID_VR", {"url": f"https://www.youtube.com/{HANDLE}"}),
        ("ANDROID_VR", {"browseId": f"VL{VIDEOS_LIST}"}),
    ]


def test_web_resolves_what_android_vr_does_not_know() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        RESOLVE,
        json_response(browse_fixture("resolve_unknown")),
        json_response(browse_fixture("resolve_handle")),
    )
    transport.add("POST", BROWSE, json_response(vr_page("aaaaaaaaaaa", count="1 video")))
    videos = service(transport).list_videos("https://www.youtube.com/c/RickAstleyYT")
    assert videos.source_id == f"UU{CHANNEL_ID[2:]}"
    assert [client for client, _ in sent(transport)] == ["ANDROID_VR", "WEB", "ANDROID_VR"]


@pytest.mark.parametrize(
    "source", [CHANNEL_ID, f"https://www.youtube.com/channel/{CHANNEL_ID}/videos"]
)
def test_channel_ids_need_no_resolving(source: str) -> None:
    transport = FakeTransport()
    transport.add("POST", BROWSE, json_response(vr_page("aaaaaaaaaaa", count="1 video")))
    videos = service(transport).list_videos(source)
    assert (videos.source_id, videos.kind) == (f"UU{CHANNEL_ID[2:]}", "all")
    assert transport.urls() == ["https://www.youtube.com/youtubei/v1/browse?prettyPrint=false"]


def test_web_takes_over_when_android_vr_fails() -> None:
    transport = FakeTransport()
    failed = json_response(error_body(400), status=500)
    transport.add("POST", BROWSE, failed, json_response(WEB_1), json_response(WEB_2))
    videos = service(transport).list_videos(VIDEOS_LIST)
    assert [entry.video_id for entry in videos] == VR_PAGE_1 + WEB_LAST_PAGE
    assert [entry.duration for entry in videos] == [231.0, 234.0, 248.0, 218.0, 219.0, 214.0]
    assert [client for client, _ in sent(transport)] == ["ANDROID_VR", "WEB", "WEB"]


def test_web_restarts_the_listing_when_android_vr_fails_midway() -> None:
    transport = FakeTransport()
    broken = text_response("<html>busy</html>")
    transport.add(
        "POST", BROWSE, json_response(VR_1), broken, json_response(WEB_1), json_response(WEB_2)
    )
    videos = service(transport).list_videos(VIDEOS_LIST)
    assert [entry.video_id for entry in videos] == VR_PAGE_1 + WEB_LAST_PAGE
    assert [entry.index for entry in videos] == [1, 2, 3, 4, 5, 6]
    assert [(client, list(body)) for client, body in sent(transport)] == [
        ("ANDROID_VR", ["browseId"]),
        ("ANDROID_VR", ["continuation"]),
        ("WEB", ["browseId"]),
        ("WEB", ["continuation"]),
    ]


def test_an_unreadable_first_page_falls_back_to_web() -> None:
    transport = FakeTransport()
    unreadable = json_response({"responseContext": {}})
    transport.add("POST", BROWSE, unreadable, json_response(WEB_1), json_response(WEB_2))
    assert len(service(transport).list_videos(VIDEOS_LIST)) == 6


def test_web_lists_shorts_from_the_rich_grid() -> None:
    transport = FakeTransport()
    transport.add("POST", RESOLVE, json_response(browse_fixture("resolve_handle")))
    shorts = json_response(browse_fixture("browse_web_shorts"))
    transport.add("POST", BROWSE, json_response(error_body(400), status=503), shorts)
    videos = service(transport).list_videos(HANDLE, kind="shorts")
    assert (videos.title, videos.video_count, videos.source_id) == (
        "Short videos",
        297,
        f"UUSH{CHANNEL_ID[2:]}",
    )
    assert [(entry.video_id, entry.duration) for entry in videos] == [
        ("E_MGy41IYVw", None),
        ("ihRdK3x3cUY", None),
    ]


def test_empty_playlists_list_nothing() -> None:
    transport = FakeTransport()
    transport.add("POST", BROWSE, json_response(vr_page(count="No videos")))
    videos = service(transport).list_videos(PLAYLIST)
    assert (len(videos), videos.video_count, videos.title) == (0, 0, "A playlist")
    assert len(transport.requests) == 1


def test_missing_playlists_are_not_found() -> None:
    transport = FakeTransport()
    missing = json_response(error_body(400), status=400)
    transport.add("POST", BROWSE, missing, missing)
    with pytest.raises(CollectionNotFound, match="HTTP 400") as caught:
        service(transport).list_videos(PLAYLIST)
    assert caught.value.source == PLAYLIST
    assert [client for client, _ in sent(transport)] == ["ANDROID_VR", "WEB"]


def test_youtube_alerts_explain_unviewable_playlists() -> None:
    transport = FakeTransport()
    alert = json_response(alert_page("This playlist type is unviewable."))
    transport.add("POST", BROWSE, json_response(error_body(400), status=400), alert)
    with pytest.raises(CollectionUnavailable, match="will not list") as caught:
        service(transport).list_videos(PLAYLIST)
    assert (caught.value.source, caught.value.reason) == (
        PLAYLIST,
        "This playlist type is unviewable.",
    )


def test_channels_without_shorts_list_nothing() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        BROWSE,
        json_response(error_body(404), status=404),
        json_response(alert_page("The playlist does not exist.")),
        json_response(vr_page("aaaaaaaaaaa", count="1 video")),
    )
    videos = service(transport).list_videos(CHANNEL_ID, kind="shorts")
    assert (len(videos), videos.video_count, videos.title) == (0, 0, "")
    assert (videos.source_id, videos.kind) == (f"UUSH{CHANNEL_ID[2:]}", "shorts")
    assert [body["browseId"] for _, body in sent(transport)] == [
        f"VLUUSH{CHANNEL_ID[2:]}",
        f"VLUUSH{CHANNEL_ID[2:]}",
        f"VLUU{CHANNEL_ID[2:]}",
    ]


@pytest.mark.parametrize(("kind", "requests"), [("all", 2), ("live", 4)])
def test_channels_without_uploads_are_not_found(kind: CollectionKind, requests: int) -> None:
    transport = FakeTransport()
    missing = json_response(error_body(404), status=404)
    alert = json_response(alert_page("The playlist does not exist."))
    transport.add("POST", BROWSE, missing, alert, missing, alert)
    with pytest.raises(CollectionNotFound, match="could not find") as caught:
        service(transport).list_videos(CHANNEL_ID, kind=kind)
    assert caught.value.source == CHANNEL_ID
    assert len(transport.requests) == requests


def test_unknown_handles_are_not_found_without_browsing() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        RESOLVE,
        json_response(browse_fixture("resolve_unknown")),
        json_response(error_body(404), status=404),
    )
    with pytest.raises(CollectionNotFound, match="knows no channel") as caught:
        service(transport).list_videos("@thishandledoesnotexist20260928x")
    assert caught.value.source == "@thishandledoesnotexist20260928x"
    assert all(RESOLVE in url for url in transport.urls())


def test_resolving_reports_server_errors() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        RESOLVE,
        json_response(error_body(400), status=500),
        text_response("<html>busy</html>"),
    )
    with pytest.raises(YouTubeRequestFailed) as caught:
        service(transport).list_videos(HANDLE)
    assert caught.value.status_code == 500


def test_rate_limits_stop_the_listing_at_once() -> None:
    transport = FakeTransport()
    transport.add("POST", BROWSE, json_response({}, status=429))
    with pytest.raises(IpBlocked):
        service(transport).list_videos(PLAYLIST)
    assert len(transport.requests) == 1


def test_the_page_cap_stops_endless_listings(caplog: pytest.LogCaptureFixture) -> None:
    transport = FakeTransport()
    pages = [vr_page(f"{letter * 11}", token=f"t{n}") for n, letter in enumerate("abc", 1)]
    transport.add("POST", BROWSE, *(json_response(page) for page in pages))
    with caplog.at_level(logging.WARNING, logger="utmax.youtube"):
        videos = service(transport, max_pages=2).list_videos(PLAYLIST)
    assert [entry.video_id for entry in videos] == ["a" * 11, "b" * 11]
    assert "stopped listing" in caplog.text


@pytest.mark.parametrize(
    ("source", "options", "error"),
    [
        (PLAYLIST, {"kind": "music"}, InvalidOption),
        (PLAYLIST, {"limit": 0}, InvalidOption),
        (PLAYLIST, {"limit": True}, InvalidOption),
        (PLAYLIST, {"limit": 2.5}, InvalidOption),
        (PLAYLIST, {"kind": "videos"}, InvalidOption),
        ("https://youtu.be/dQw4w9WgXcQ", {}, InvalidSource),
        ("RDdQw4w9WgXcQ", {}, CollectionUnavailable),
    ],
)
def test_bad_arguments_fail_before_any_request(
    source: str, options: dict[str, Any], error: type[UTMaxError]
) -> None:
    transport = FakeTransport()
    with pytest.raises(error):
        service(transport).list_videos(source, **options)
    assert transport.requests == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/services/test_collections.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'utmax.services.collections'`.

- [ ] **Step 3: Write the service**

`src/utmax/services/collections.py`:

```python
"""List the videos of a playlist or a channel."""

from __future__ import annotations

import logging
from typing import Any

from utmax.adapters.innertube import InnerTubeClient
from utmax.core.browse import MAX_PAGES, Pager, alert_error, parse_browse_page, resolved_channel_id
from utmax.core.clients import ORDER, ClientProfile
from utmax.core.ids import COLLECTION_KINDS, parse_source, uploads_playlist_id
from utmax.errors import (
    CollectionNotFound,
    CollectionUnavailable,
    InvalidOption,
    YouTubeDataUnparsable,
    YouTubeError,
    YouTubeRequestFailed,
)
from utmax.models import CollectionKind, VideoList

__all__ = ["CollectionService"]

log = logging.getLogger("utmax.youtube")

_NOT_FOUND = (400, 404)
_NEXT_CLIENT = (
    CollectionNotFound,
    CollectionUnavailable,
    YouTubeRequestFailed,
    YouTubeDataUnparsable,
)


class CollectionService:
    """Lists playlists and channels with InnerTube ``browse``: ANDROID_VR first, then WEB."""

    def __init__(self, innertube: InnerTubeClient, *, max_pages: int = MAX_PAGES) -> None:
        self._innertube = innertube
        self._max_pages = max_pages

    def list_videos(
        self, source: str, *, kind: CollectionKind = "all", limit: int | None = None
    ) -> VideoList:
        """The videos of a playlist or channel; :func:`utmax.list_videos` documents the rules."""
        if kind not in COLLECTION_KINDS:
            raise InvalidOption(f'kind={kind!r} is not "all", "videos", "shorts" or "live".')
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
        ):
            raise InvalidOption(f"limit must be a positive whole number or None, not {limit!r}.")
        parsed = parse_source(source)
        if parsed.kind == "playlist":
            if kind != "all":
                raise InvalidOption(
                    f"kind={kind!r} only applies to channels; a playlist is listed as it is.",
                    suggestion="Leave kind out for playlists.",
                )
            return self._listing(parsed.id, "all", limit, source=source)
        channel_id = parsed.id or self._resolve(parsed.url, source=source)
        playlist_id = uploads_playlist_id(channel_id, kind)
        try:
            return self._listing(playlist_id, kind, limit, source=source)
        except CollectionNotFound:
            if kind == "all":
                raise
        # YouTube keeps no Shorts or live list for a channel without them, so a missing list
        # means "none" as long as the channel itself has uploads.
        self._listing(uploads_playlist_id(channel_id, "all"), "all", 1, source=source)
        log.info("channel %s has no %s", channel_id, kind)
        return VideoList(title="", source_id=playlist_id, kind=kind, video_count=0, entries=())

    def _listing(
        self, playlist_id: str, kind: CollectionKind, limit: int | None, *, source: str
    ) -> VideoList:
        """Every page of one playlist, from the first client that lists all of it."""
        failures: list[YouTubeError] = []
        for profile in ORDER["browse"]:
            try:
                return self._listing_with(profile, playlist_id, kind, limit, source=source)
            except _NEXT_CLIENT as error:
                log.info(
                    "InnerTube client %s could not list %s: %s", profile.name, playlist_id, error
                )
                failures.append(error)
        raise _most_telling(failures)

    def _listing_with(
        self,
        profile: ClientProfile,
        playlist_id: str,
        kind: CollectionKind,
        limit: int | None,
        *,
        source: str,
    ) -> VideoList:
        first = parse_browse_page(self._first_page(profile, playlist_id, source=source))
        if not first.items:
            if first.alerts:
                raise alert_error(first, source=source)
            if first.video_count != 0:
                raise YouTubeDataUnparsable(
                    f"The {profile.name} client's answer for {playlist_id} holds no videos "
                    "utmax can read."
                )
        pager = Pager(limit=limit, max_pages=self._max_pages)
        token = pager.add(first)
        while token is not None:
            token = pager.add(
                parse_browse_page(self._innertube.browse(profile, continuation=token))
            )
        if pager.truncated:
            log.warning(
                "stopped listing %s after %d pages; the list is incomplete",
                playlist_id,
                self._max_pages,
            )
        return VideoList(
            title=first.title,
            source_id=playlist_id,
            kind=kind,
            video_count=first.video_count,
            entries=pager.entries,
        )

    def _first_page(
        self, profile: ClientProfile, playlist_id: str, *, source: str
    ) -> dict[str, Any]:
        try:
            return self._innertube.browse(profile, browse_id=f"VL{playlist_id}")
        except YouTubeRequestFailed as error:
            if error.status_code not in _NOT_FOUND:
                raise
            raise CollectionNotFound(
                f"YouTube could not find {source!r} (HTTP {error.status_code}).", source=source
            ) from None

    def _resolve(self, url: str, *, source: str) -> str:
        """The channel ID behind a handle or custom URL: ANDROID_VR's answer, then WEB's."""
        failures: list[YouTubeError] = []
        for profile in ORDER["resolve"]:
            try:
                channel_id = resolved_channel_id(self._innertube.resolve_url(profile, url))
            except YouTubeRequestFailed as error:
                if error.status_code not in _NOT_FOUND:
                    failures.append(error)
                    continue
                channel_id = None
            except YouTubeDataUnparsable as error:
                failures.append(error)
                continue
            if channel_id is not None:
                return channel_id
            failures.append(
                CollectionNotFound(f"YouTube knows no channel at {source!r}.", source=source)
            )
        raise _most_telling(failures)


def _most_telling(failures: list[YouTubeError]) -> YouTubeError:
    """YouTube's own reason first, then "not found", then the first failure."""
    for wanted in (CollectionUnavailable, CollectionNotFound):
        for failure in failures:
            if isinstance(failure, wanted):
                return failure
    return failures[0]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/services/test_collections.py -q`
Expected: 27 passed.

- [ ] **Step 5: Gates and commit**

Run the four gates (the suite grows by 27 to 1250 passed).

```bash
git add src/utmax/services/collections.py tests/unit/services/test_collections.py
git commit -m "feat: list the videos of playlists and channels" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: File-name templates and skip patterns

**Files:**
- Modify: `src/utmax/core/filenames.py`
- Test: `tests/unit/core/test_name_templates.py` (create)

**Interfaces:**
- Consumes: `safe_name`, `MAX_NAME_CHARS`, `MAX_NAME_BYTES`, `default_filename`, `Target`, `resolve_target` (M4); `InvalidOption`.
- Produces (in `utmax.core.filenames`):
  - `MAX_BULK_NAME_BYTES = 220` (Linux allows 255 bytes per name; the temporary file of a download's `<name>.401.part.json` state file is 28 bytes longer than the name, and that of a `.srt` sidecar 15 bytes plus the language code longer).
  - `NameTemplate(text: str, fields: tuple[str, ...])` with `NameTemplate.parse(text: str, *, allowed: Collection[str]) -> NameTemplate` (Decision 12; raises `InvalidOption`), `render(values: Mapping[str, str | int]) -> str` and `pattern(values: Mapping[str, str | int], globs: Mapping[str, str] | None = None) -> str` (Decision 13).
  - `glob_literal(text: str) -> str`.
  - `Target.path_for(video: VideoInfo, *, name: Callable[[VideoInfo, str], str] | None = None) -> PurePath` — for a folder target, `name(video, extension)` replaces the default file name; a file target ignores it.

- [ ] **Step 1: Write the failing tests**

`tests/unit/core/test_name_templates.py`:

```python
"""Tests for the file-name templates of bulk calls."""

from __future__ import annotations

from dataclasses import replace
from fnmatch import fnmatchcase
from pathlib import Path, PurePath

import pytest

from tests.helpers.builders import VIDEO
from tests.helpers.fake_media import media_stream
from utmax.adapters import files
from utmax.adapters.downloader import Job
from utmax.adapters.files import write_text_atomic
from utmax.core.filenames import (
    MAX_BULK_NAME_BYTES,
    NameTemplate,
    glob_literal,
    part_name,
    resolve_target,
    sidecar_name,
)
from utmax.errors import InvalidOption
from utmax.models import VideoInfo

NAME_MAX = 255  # bytes in a file name on Linux and macOS
FIELDS = ("video_id", "title", "channel", "index", "language_code", "ext")
TRANSCRIPT = NameTemplate.parse("{video_id}.{language_code}.{ext}", allowed=FIELDS)
VIDEO_NAME = NameTemplate.parse("{title} [{video_id}].{ext}", allowed=FIELDS)


def test_templates_remember_their_fields() -> None:
    assert TRANSCRIPT.fields == ("video_id", "language_code", "ext")
    numbered = NameTemplate.parse("{index:03d} - {title} [{video_id}].{ext}", allowed=FIELDS)
    assert numbered.fields == ("index", "title", "video_id", "ext")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{title}.{ext}", "does not contain {video_id}"),
        ("{video_id}.{language}.{ext}", "uses {language}"),
        ("{video_id}.{title.upper}", "uses {title.upper}"),
        ("{video_id}{}", "uses {}"),
        ("{video_id", "is not a valid template"),
        ("{video_id}}", "is not a valid template"),
        ("subs/{video_id}.{ext}", "makes a path"),
        ("{video_id}\\{ext}", "makes a path"),
        ("{title:/>9} {video_id}", "makes a path"),
        ("{title}: {video_id}.{ext}", "contains ':'"),
        ("{title}|{video_id}.{ext}", "contains '|'"),
        ("{video_id}*.{ext}", "contains '*'"),
        ("{video_id}?.{ext}", "contains '?'"),
        ('{video_id}".{ext}', "contains '\"'"),
        ("{video_id}\x00.{ext}", "contains '\\x00'"),
        ("{title:*>9} {video_id}", "contains '*'"),
        ("{video_id}.{ext}.", "ends with '.'"),
        ("{video_id}{index:<3}", "ends with ' '"),
        ("{video_id}{title:{index}}", "inside a format spec"),
        ("{video_id}.{title:03d}", "cannot be filled in"),
    ],
)
def test_bad_templates_are_refused(text: str, message: str) -> None:
    with pytest.raises(InvalidOption, match="filename=") as caught:
        NameTemplate.parse(text, allowed=FIELDS)
    assert message in str(caught.value)


def test_download_templates_have_no_language_field() -> None:
    with pytest.raises(InvalidOption, match=r"uses \{language_code\}") as caught:
        NameTemplate.parse("{video_id}.{language_code}.{ext}", allowed=("video_id", "ext"))
    assert "{ext}, {video_id}" in caught.value.suggestion


def test_render_makes_titles_channels_and_language_codes_safe() -> None:
    template = NameTemplate.parse(
        "{index:02d} {channel} - {title} [{video_id}].{language_code}.{ext}", allowed=FIELDS
    )
    name = template.render(
        {
            "video_id": "dQw4w9WgXcQ",
            "title": 'Who: "Rick"?',
            "channel": "AC/DC",
            "index": 7,
            "language_code": "en/../x",
            "ext": "srt",
        }
    )
    assert name == "07 AC_DC - Who_ _Rick__ [dQw4w9WgXcQ].en_.._x.srt"


def test_an_empty_title_becomes_the_video_id() -> None:
    values = {"video_id": "dQw4w9WgXcQ", "title": " ... ", "ext": "mp4"}
    assert VIDEO_NAME.render(values) == "dQw4w9WgXcQ [dQw4w9WgXcQ].mp4"


def test_long_names_shorten_the_title_and_keep_the_rest() -> None:
    template = NameTemplate.parse("{channel} - {title} [{video_id}].{ext}", allowed=FIELDS)
    wide = "\U00004e2d" * 100  # 300 UTF-8 bytes, cut to 60 characters (180 bytes) by safe_name
    name = template.render(
        {"video_id": "dQw4w9WgXcQ", "title": wide, "channel": wide, "ext": "mp4"}
    )
    assert len(name.encode("utf-8")) <= MAX_BULK_NAME_BYTES
    assert name.endswith(" [dQw4w9WgXcQ].mp4")
    assert name.startswith("\U00004e2d" * 60 + " - \U00004e2d")


def atomic_write_affix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    """How many bytes ``write_text_atomic`` adds to a name for the temporary file it writes."""
    temporary: list[str] = []
    replace_file = files.replace_with_retry

    def spy(source: Path, target: Path) -> None:
        temporary.append(source.name)
        replace_file(source, target)

    monkeypatch.setattr(files, "replace_with_retry", spy)
    write_text_atomic(tmp_path / "a", "")
    return len(temporary[0]) - len("a")


def test_the_longest_name_leaves_room_for_the_files_a_download_derives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template = NameTemplate.parse("{channel} - {title} [{video_id}].{ext}", allowed=FIELDS)
    name = template.render(
        {"video_id": "dQw4w9WgXcQ", "title": "t" * 150, "channel": "c" * 150, "ext": "mp4"}
    )
    assert len(name) == MAX_BULK_NAME_BYTES  # ASCII: the title gave way until the name fit
    final = PurePath(name)
    job = Job(media_stream(401, "https://media.test/401", 1), Path(part_name(final, 401)))
    sidecar = sidecar_name(final, "c" * 20)
    affix = atomic_write_affix(tmp_path, monkeypatch)
    for written in (final, job.state_path, sidecar):
        assert len(written.name.encode("utf-8")) + affix <= NAME_MAX


def test_patterns_escape_what_is_known_and_match_the_rest() -> None:
    pattern = VIDEO_NAME.pattern({"video_id": "dQw4w9WgXcQ", "ext": "mp4", "title": "ignored"})
    assert pattern == "* [[]dQw4w9WgXcQ].mp4"
    assert fnmatchcase("Never Gonna [Live] [dQw4w9WgXcQ].mp4", pattern)
    assert not fnmatchcase("Never Gonna [dQw4w9WgXcQ].mp4.137.part", pattern)
    assert not fnmatchcase("Other [jNQXAC9IVRw].mp4", pattern)
    assert TRANSCRIPT.pattern({"video_id": "dQw4w9WgXcQ", "ext": "srt"}) == "dQw4w9WgXcQ.*.srt"


def test_patterns_take_extra_globs_as_they_are() -> None:
    values = {"video_id": "dQw4w9WgXcQ", "ext": "srt", "language_code": "de"}
    assert TRANSCRIPT.pattern(values) == "dQw4w9WgXcQ.de.srt"
    assert TRANSCRIPT.pattern(values, {"language_code": "de-*"}) == "dQw4w9WgXcQ.de-*.srt"
    numbered = NameTemplate.parse("{index:03d} {video_id}.{ext}", allowed=FIELDS)
    assert numbered.pattern({"video_id": "a", "index": 7, "ext": "srt"}) == "007 a.srt"
    fixed = NameTemplate.parse("[{video_id}] subtitles.txt", allowed=FIELDS)
    assert fixed.pattern({"video_id": "a"}) == "[[]a] subtitles.txt"


def test_glob_literals_match_only_themselves() -> None:
    assert glob_literal("a*b?c[d]") == "a[*]b[?]c[[]d]"
    assert fnmatchcase("a*b?c[d]", glob_literal("a*b?c[d]"))
    assert not fnmatchcase("axbycd]", glob_literal("a*b?c[d]"))


def test_folder_targets_name_files_with_a_callback() -> None:
    folder = resolve_target("videos/", format="m4a", is_dir=False)

    def name(video: VideoInfo, ext: str) -> str:
        return f"{video.video_id}.{ext}"

    assert folder.path_for(VIDEO, name=name) == PurePath("videos", "dQw4w9WgXcQ.m4a")
    assert folder.path_for(replace(VIDEO, title="")) == PurePath("videos", "dQw4w9WgXcQ.m4a")
    file = resolve_target("rick.mp4", format=None, is_dir=False)
    assert file.path_for(VIDEO, name=name) == PurePath("rick.mp4")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_name_templates.py -q`
Expected: collection error — `ImportError: cannot import name 'MAX_BULK_NAME_BYTES' from 'utmax.core.filenames'`.

- [ ] **Step 3: Add the templates**

In `src/utmax/core/filenames.py`:

1. Replace:

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
```

   with:

```python
"""Safe file names, where ``download(video, path)`` writes its files, and the name templates
of bulk calls."""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import PurePath
from string import Formatter

from utmax.errors import InvalidOption, UnsupportedFormat
from utmax.models import Container, VideoInfo

__all__ = [
    "MAX_BULK_NAME_BYTES",
    "MAX_NAME_BYTES",
    "MAX_NAME_CHARS",
    "NameTemplate",
    "Target",
    "default_filename",
    "glob_literal",
    "part_name",
    "resolve_target",
    "safe_name",
```

2. Replace:

```python

MAX_NAME_CHARS = 150
MAX_NAME_BYTES = 180
_SUFFIXES: dict[str, Container] = {".mp4": "mp4", ".mov": "mov", ".m4a": "m4a", ".mp3": "mp3"}
_WHITESPACE = re.compile(r"\s+")
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"{name}{n}" for name in ("COM", "LPT") for n in range(1, 10)}
)
```

   with:

```python

MAX_NAME_CHARS = 150
MAX_NAME_BYTES = 180
# The most a bulk name may take, in UTF-8 bytes. Linux and macOS allow 255 per file name, and a
# download derives longer names: the temporary file of its state, "<name>.401.part.json" written
# through write_text_atomic (".<...>.<8 hex digits>.tmp"), is 28 bytes longer than the name, and
# that of a subtitle sidecar is 15 bytes plus the language code longer (255 for 20 characters).
MAX_BULK_NAME_BYTES = 220
_SUFFIXES: dict[str, Container] = {".mp4": "mp4", ".mov": "mov", ".m4a": "m4a", ".mp3": "mp3"}
_WHITESPACE = re.compile(r"\s+")
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_GLOB_MAGIC = re.compile(r"([*?[])")
_SAMPLE_FIELDS: dict[str, str | int] = {
    "video_id": "dQw4w9WgXcQ",
    "title": "Title",
    "channel": "Channel",
    "index": 1,
    "language_code": "en",
    "ext": "srt",
}
_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"{name}{n}" for name in ("COM", "LPT") for n in range(1, 10)}
)
```

3. Replace:

```python
    file: PurePath | None = None
    folder: PurePath | None = None

    def path_for(self, video: VideoInfo) -> PurePath:
        """The output file for ``video``."""
        if self.file is not None:
            return self.file
        return (self.folder or PurePath(".")) / default_filename(video, self.container)


def resolve_target(
```

   with:

```python
    file: PurePath | None = None
    folder: PurePath | None = None

    def path_for(
        self, video: VideoInfo, *, name: Callable[[VideoInfo, str], str] | None = None
    ) -> PurePath:
        """The output file for ``video``; in a folder, ``name(video, extension)`` replaces the
        default ``"{title} [{video_id}].{ext}"``."""
        if self.file is not None:
            return self.file
        if name is None:
            return (self.folder or PurePath(".")) / default_filename(video, self.container)
        return (self.folder or PurePath(".")) / name(video, self.container)


def resolve_target(
```

4. Replace:

```python
    return media.with_name(f"{media.stem}.{code}.srt")


def part_name(target: PurePath, itag: int) -> PurePath:
    """Where stream ``itag`` of ``target`` is downloaded: ``rick.mp4`` gives ``rick.mp4.137.part``."""
    return target.with_name(f"{target.name}.{itag}.part")


def _shorten(text: str, max_chars: int, max_bytes: int) -> str:
```

   with:

```python
    return media.with_name(f"{media.stem}.{code}.srt")


@dataclass(frozen=True, slots=True)
class NameTemplate:
    """The file-name template of a bulk call, such as ``"{title} [{video_id}].{ext}"``.

    Fields are written like :meth:`str.format` fields and may carry a format spec
    (``{index:03d}``). ``title``, ``channel`` and ``language_code`` values are made safe with
    :func:`safe_name`; an empty title becomes the video ID.
    """

    text: str
    fields: tuple[str, ...]

    @classmethod
    def parse(cls, text: str, *, allowed: Collection[str]) -> NameTemplate:
        """Check ``text``: it must contain ``{video_id}`` (every video needs its own name), use
        only ``allowed`` fields, and give a plain file name that Windows accepts too: no path
        separator, none of ``<>:"|?*`` or a control character (the fill of a format spec
        counts), and no trailing dot or space.

        Raises:
            InvalidOption: ``text`` breaks one of these rules or is not a valid template.
        """
        names = ", ".join(f"{{{field}}}" for field in sorted(allowed))
        try:
            parsed = list(Formatter().parse(text))
        except ValueError as error:
            raise InvalidOption(
                f"filename={text!r} is not a valid template: {error}.",
                suggestion=f"Write fields in braces; available fields: {names}.",
            ) from None
        fields = tuple(field for _, field, _, _ in parsed if field is not None)
        unknown = [field for field in fields if field not in allowed]
        if unknown:
            raise InvalidOption(
                f"filename={text!r} uses {{{unknown[0]}}}, which is not a template field.",
                suggestion=f"Use only these fields: {names}.",
            )
        if "video_id" not in fields:
            raise InvalidOption(
                f"filename={text!r} does not contain {{video_id}}, so names could repeat.",
                suggestion='Add {video_id}, as in "{title} [{video_id}].{ext}".',
            )
        if any("{" in (spec or "") for _, field, spec, _ in parsed if field is not None):
            raise InvalidOption(f"filename={text!r} puts a field inside a format spec.")
        template = cls(text, fields)
        try:
            sample = template.render(_SAMPLE_FIELDS)
        except (ValueError, TypeError) as error:
            raise InvalidOption(f"filename={text!r} cannot be filled in: {error}.") from None
        if "/" in sample or "\\" in sample:
            raise InvalidOption(
                f"filename={text!r} makes a path; it must be a plain file name.",
                suggestion="Remove / and \\ from the template and choose the folder with out_dir.",
            )
        forbidden = _FORBIDDEN.search(sample)
        if forbidden is not None:
            raise InvalidOption(
                f"filename={text!r} contains {forbidden.group()!r}, which Windows does not allow "
                "in a file name.",
                suggestion=(
                    'Leave <>:"|?* and control characters out of the template; titles and '
                    "channels are made safe for you."
                ),
            )
        if sample.endswith((".", " ")):
            raise InvalidOption(
                f"filename={text!r} makes a name that ends with {sample[-1]!r}, which Windows "
                "does not allow.",
                suggestion='End the template with a field or a letter, as in "{video_id}.{ext}".',
            )
        return template

    def render(self, values: Mapping[str, str | int]) -> str:
        """The file name for ``values``; the title is shortened when the name would pass
        ``MAX_BULK_NAME_BYTES`` UTF-8 bytes."""
        safe = dict(values)
        for field, (chars, size) in _SAFE_FIELDS.items():
            if field in safe:
                safe[field] = safe_name(str(safe[field]), max_chars=chars, max_bytes=size)
        if "title" in safe and not safe["title"]:
            safe["title"] = str(values.get("video_id", ""))
        name = self.text.format(**safe)
        excess = len(name.encode("utf-8")) - MAX_BULK_NAME_BYTES
        title = str(safe.get("title", ""))
        if excess > 0 and title:
            budget = max(0, len(title.encode("utf-8")) - excess)
            safe["title"] = safe_name(title, max_bytes=budget)
            name = self.text.format(**safe)
        return name

    def pattern(
        self, values: Mapping[str, str | int], globs: Mapping[str, str] | None = None
    ) -> str:
        """A glob pattern that matches every name :meth:`render` can give when only ``values``
        are known: literal text and known values are escaped, a field in ``globs`` becomes that
        glob as it is, and any other field (``title`` and ``channel`` always) becomes ``*``."""
        formatter = Formatter()
        parts: list[str] = []
        for literal, field, spec, conversion in formatter.parse(self.text):
            parts.append(glob_literal(literal))
            if field is None:
                continue
            if globs is not None and field in globs:
                parts.append(globs[field])
            elif field in values and field not in ("title", "channel"):
                value = formatter.convert_field(values[field], conversion)
                parts.append(glob_literal(formatter.format_field(value, spec or "")))
            else:
                parts.append("*")
        return "".join(parts)


def glob_literal(text: str) -> str:
    """``text`` as a glob pattern that matches only itself (``[`` becomes ``[[]``)."""
    return _GLOB_MAGIC.sub(r"[\1]", text)


def part_name(target: PurePath, itag: int) -> PurePath:
    """Where stream ``itag`` of ``target`` is downloaded: ``rick.mp4`` gives ``rick.mp4.137.part``."""
    return target.with_name(f"{target.name}.{itag}.part")


_SAFE_FIELDS: dict[str, tuple[int, int]] = {
    "title": (MAX_NAME_CHARS, MAX_NAME_BYTES),
    "channel": (MAX_NAME_CHARS, MAX_NAME_BYTES),
    "language_code": (35, 35),
}


def _shorten(text: str, max_chars: int, max_bytes: int) -> str:
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_name_templates.py tests/unit/core/test_filenames.py -q`
Expected: the new file reports 30 passed; the existing file-name tests still pass.

- [ ] **Step 5: Gates and commit**

Run the four gates (the suite grows by 30 to 1280 passed).

```bash
git add src/utmax/core/filenames.py tests/unit/core/test_name_templates.py
git commit -m "feat: add file-name templates and skip patterns for bulk calls" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: The bulk runner

**Files:**
- Create: `src/utmax/services/bulk.py`
- Test: `tests/unit/services/test_bulk_runner.py` (create)

**Interfaces:**
- Consumes: `parse_video_id` (M1); `BulkReport`, `BulkResult`, `VideoEntry` (Task 1); `InvalidOption`, `InvalidVideoId`, `RequestBlocked`.
- Produces (in `utmax.services.bulk`):
  - `MAX_CONCURRENCY = 16`; `check_concurrency(concurrency: int) -> None` (raises `InvalidOption` outside 1–16; `bool` and `float` are refused too).
  - `BulkItem(position: int, video_id: str, video: str | VideoEntry, error: InvalidVideoId | None = None)` with `index` (Decision 12).
  - `bulk_items(videos: Iterable[str | VideoEntry]) -> list[BulkItem]` (raises `InvalidOption` for a single string or `VideoEntry`).
  - `run_bulk(items: Sequence[BulkItem], work: Callable[[BulkItem], tuple[T, Path | None]], *, concurrency: int, existing: Callable[[BulkItem], Path | None] | None = None, progress: Callable[[BulkResult[T]], None] | None = None, breaker: tuple[type[Exception], ...] = (RequestBlocked,), stop: threading.Event | None = None) -> BulkReport[T]` (Decisions 8–11).

- [ ] **Step 1: Write the failing tests**

The order and Ctrl-C tests synchronize through events and the progress callback, not through timing; only the concurrency test sleeps (20 ms per video). The file passed eight runs in a row while this plan was verified.

`tests/unit/services/test_bulk_runner.py`:

```python
"""Tests for the bulk runner: order, concurrency, skips, the circuit breaker and Ctrl-C."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from utmax.errors import (
    InvalidOption,
    InvalidVideoId,
    IpBlocked,
    ProviderAuthError,
    VideoUnavailable,
)
from utmax.models import BulkResult, VideoEntry
from utmax.services.bulk import BulkItem, bulk_items, check_concurrency, run_bulk

IDS = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"]


def upper(item: BulkItem) -> tuple[str, Path | None]:
    return item.video_id.upper(), None


def test_results_keep_the_input_order_and_progress_the_finishing_order() -> None:
    second_reported = threading.Event()
    seen: list[BulkResult[str]] = []

    def work(item: BulkItem) -> tuple[str, Path | None]:
        if item.video_id == IDS[0]:
            assert second_reported.wait(5)
        return upper(item)

    def progress(result: BulkResult[str]) -> None:
        seen.append(result)
        if result.video_id == IDS[1]:
            second_reported.set()

    report = run_bulk(bulk_items(IDS[:2]), work, concurrency=2, progress=progress)
    assert [(result.video_id, result.status) for result in report] == [
        (IDS[0], "ok"),
        (IDS[1], "ok"),
    ]
    assert [result.value for result in report] == [IDS[0].upper(), IDS[1].upper()]
    assert [result.video_id for result in seen] == [IDS[1], IDS[0]]


def test_items_that_need_no_work_are_decided_first() -> None:
    calls: list[str] = []

    def work(item: BulkItem) -> tuple[str, Path | None]:
        calls.append(item.video_id)
        if item.video_id == IDS[2]:
            raise VideoUnavailable("gone", video_id=item.video_id)
        return "value", Path(f"{item.video_id}.srt")

    def existing(item: BulkItem) -> Path | None:
        return Path("old.srt") if item.video_id == IDS[1] else None

    seen: list[BulkResult[str]] = []
    videos = [IDS[0], "not a video", IDS[1], f"https://youtu.be/{IDS[0]}", IDS[2]]
    report = run_bulk(
        bulk_items(videos), work, concurrency=1, existing=existing, progress=seen.append
    )
    assert [(result.video_id, result.status) for result in report] == [
        (IDS[0], "ok"),
        ("not a video", "failed"),
        (IDS[1], "skipped"),
        (IDS[0], "skipped"),
        (IDS[2], "failed"),
    ]
    assert (report[0].value, report[0].path) == ("value", Path(f"{IDS[0]}.srt"))
    assert isinstance(report[1].error, InvalidVideoId)
    assert (report[2].path, report[3].path) == (Path("old.srt"), None)
    assert isinstance(report[4].error, VideoUnavailable)
    assert sorted(calls) == [IDS[0], IDS[2]]
    assert [result.video_id for result in seen[:3]] == ["not a video", IDS[1], IDS[0]]
    assert len(seen) == 5


def test_no_more_than_concurrency_videos_run_at_once() -> None:
    lock = threading.Lock()
    active = peak = 0

    def work(item: BulkItem) -> tuple[None, Path | None]:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return None, None

    report = run_bulk(bulk_items([letter * 11 for letter in "abcdefgh"]), work, concurrency=3)
    assert len(report.ok) == 8
    assert 1 <= peak <= 3


def test_a_block_stops_the_run(caplog: pytest.LogCaptureFixture) -> None:
    def work(item: BulkItem) -> tuple[str, Path | None]:
        if item.video_id == IDS[1]:
            raise IpBlocked("HTTP 429", video_id=item.video_id)
        return upper(item)

    seen: list[BulkResult[str]] = []
    with caplog.at_level(logging.WARNING, logger="utmax.bulk"):
        report = run_bulk(bulk_items(IDS), work, concurrency=1, progress=seen.append)
    statuses = [result.status for result in report]
    assert statuses == ["ok", "failed", "not_attempted", "not_attempted"]
    assert len(seen) == 4
    assert "not attempted" in caplog.text
    with pytest.raises(IpBlocked):
        report.raise_for_errors()


def test_callers_choose_what_stops_the_run() -> None:
    def work(item: BulkItem) -> tuple[str, Path | None]:
        raise ProviderAuthError("The API key was rejected.", provider="fake")

    stopped = run_bulk(bulk_items(IDS[:3]), work, concurrency=1, breaker=(ProviderAuthError,))
    assert [result.status for result in stopped] == ["failed", "not_attempted", "not_attempted"]
    carried_on = run_bulk(bulk_items(IDS[:3]), work, concurrency=1)
    assert [result.status for result in carried_on] == ["failed", "failed", "failed"]


@pytest.mark.parametrize("error", [KeyboardInterrupt, ValueError])
def test_ctrl_c_or_a_progress_error_stops_the_run(error: type[BaseException]) -> None:
    stop = threading.Event()
    calls: list[str] = []

    def work(item: BulkItem) -> tuple[str, Path | None]:
        calls.append(item.video_id)
        return upper(item)

    def progress(result: BulkResult[str]) -> None:
        raise error

    with pytest.raises(error):
        run_bulk(bulk_items(IDS), work, concurrency=1, progress=progress, stop=stop)
    assert stop.is_set()
    assert 1 <= len(calls) <= 2


def test_ctrl_c_while_the_videos_are_queued_stops_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = threading.Event()
    calls: list[str] = []
    videos = [letter * 11 for letter in "abcdefgh"]
    submitted = 0
    real_submit = ThreadPoolExecutor.submit

    def submit(
        pool: ThreadPoolExecutor, fn: Callable[..., Any], /, *args: Any, **kwargs: Any
    ) -> Future[Any]:
        nonlocal submitted
        submitted += 1
        if submitted == 5:
            raise KeyboardInterrupt
        return real_submit(pool, fn, *args, **kwargs)

    def work(item: BulkItem) -> tuple[str, Path | None]:
        calls.append(item.video_id)
        assert stop.wait(5)
        return upper(item)

    monkeypatch.setattr(ThreadPoolExecutor, "submit", submit)
    with pytest.raises(KeyboardInterrupt):
        run_bulk(bulk_items(videos), work, concurrency=2, stop=stop)
    assert stop.is_set()
    assert set(calls) <= set(videos[:2])


def test_nothing_to_do() -> None:
    assert len(run_bulk([], upper, concurrency=4)) == 0
    report = run_bulk(bulk_items(["nope"]), upper, concurrency=4)
    assert [result.status for result in report] == ["failed"]


def test_bulk_items_read_ids_urls_and_listing_entries() -> None:
    entry = VideoEntry("eeeeeeeeeee", "E", 60.0, "Channel", "UC" + "x" * 22, 7)
    items = bulk_items(iter([f"https://youtu.be/{IDS[1]}", entry, " bad "]))
    assert [(item.position, item.video_id, item.index) for item in items] == [
        (1, IDS[1], 1),
        (2, "eeeeeeeeeee", 7),
        (3, "bad", 3),
    ]
    assert items[1].video is entry
    assert (items[0].error, type(items[2].error)) == (None, InvalidVideoId)


@pytest.mark.parametrize("videos", ["dQw4w9WgXcQ", VideoEntry("eeeeeeeeeee", "E", None, "", "", 1)])
def test_one_video_is_not_a_list(videos: Any) -> None:
    with pytest.raises(InvalidOption, match="must be a list"):
        bulk_items(videos)


@pytest.mark.parametrize("value", [0, 17, -1, True, 2.0])
def test_concurrency_is_between_1_and_16(value: Any) -> None:
    with pytest.raises(InvalidOption, match="concurrency must be between 1 and 16"):
        check_concurrency(value)
    check_concurrency(1)
    check_concurrency(16)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/services/test_bulk_runner.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'utmax.services.bulk'`.

- [ ] **Step 3: Write the runner**

Results are collected on the calling thread, which waits in 0.1-second steps so that Ctrl-C reaches it on Windows too. Workers check the stop and breaker events before starting a video, so after a block the remaining videos return `"not_attempted"` at once. The jobs are submitted inside the `try` as well: Ctrl-C while a long list is still being queued sets `stop` and drops the queue, instead of letting the pool work off every video already submitted.

`src/utmax/services/bulk.py`:

```python
"""Bulk calls: one job per video on a thread pool, with skip-existing and a circuit breaker."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from utmax.core.ids import parse_video_id
from utmax.errors import InvalidOption, InvalidVideoId, RequestBlocked
from utmax.models import BulkReport, BulkResult, VideoEntry

__all__ = ["MAX_CONCURRENCY", "BulkItem", "bulk_items", "check_concurrency", "run_bulk"]

log = logging.getLogger("utmax.bulk")

MAX_CONCURRENCY = 16
_POLL_SECONDS = 0.1
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class BulkItem:
    """One input of a bulk call: its position (from 1), its video ID and what was passed.

    ``error`` is set when the input holds no video ID; ``video_id`` is then the input itself.
    """

    position: int
    video_id: str
    video: str | VideoEntry
    error: InvalidVideoId | None = None

    @property
    def index(self) -> int:
        """The ``{index}`` of file-name templates: a VideoEntry's position in its listing,
        otherwise the position in the input."""
        return self.video.index if isinstance(self.video, VideoEntry) else self.position


def check_concurrency(concurrency: int) -> None:
    """Refuse a ``concurrency`` outside 1 to ``MAX_CONCURRENCY``."""
    if (
        isinstance(concurrency, bool)
        or not isinstance(concurrency, int)
        or not 1 <= concurrency <= MAX_CONCURRENCY
    ):
        raise InvalidOption(
            f"concurrency must be between 1 and {MAX_CONCURRENCY}, not {concurrency!r}."
        )


def bulk_items(videos: Iterable[str | VideoEntry]) -> list[BulkItem]:
    """The inputs of a bulk call; one without a video ID becomes an item that fails.

    Raises:
        InvalidOption: ``videos`` is one video instead of a list of them.
    """
    if isinstance(videos, (str, VideoEntry)):
        raise InvalidOption(
            f"videos must be a list, such as [{videos!r}], or a VideoList from list_videos()."
        )
    items: list[BulkItem] = []
    for position, video in enumerate(videos, start=1):
        if isinstance(video, VideoEntry):
            items.append(BulkItem(position, video.video_id, video))
            continue
        try:
            items.append(BulkItem(position, parse_video_id(video), video))
        except InvalidVideoId as error:
            items.append(BulkItem(position, video.strip(), video, error))
    return items


def run_bulk(
    items: Sequence[BulkItem],
    work: Callable[[BulkItem], tuple[T, Path | None]],
    *,
    concurrency: int,
    existing: Callable[[BulkItem], Path | None] | None = None,
    progress: Callable[[BulkResult[T]], None] | None = None,
    breaker: tuple[type[Exception], ...] = (RequestBlocked,),
    stop: threading.Event | None = None,
) -> BulkReport[T]:
    """Run ``work`` (which returns a value and the file it wrote) for every item.

    An item without a video ID fails, a video given again is skipped, and a video for which
    ``existing`` finds a file is skipped, all without running ``work``. The rest run on up to
    ``concurrency`` threads. An exception from ``work`` fails its item only, but one of the
    ``breaker`` types (YouTube blocking this IP address, by default) stops the run: items not
    started yet become ``not_attempted``. ``progress`` receives every result once, in the
    order the results become known, never in parallel. Ctrl-C, or an exception from
    ``progress``, sets ``stop`` (running downloads watch it), drops the items not started yet,
    waits for the running ones and propagates.
    """
    stop = stop if stop is not None else threading.Event()
    tripped = threading.Event()
    results: dict[int, BulkResult[T]] = {}
    queued: list[int] = []
    seen: set[str] = set()
    for number, item in enumerate(items):
        if item.error is not None:
            results[number] = BulkResult(item.video_id, "failed", error=item.error)
        elif item.video_id in seen:
            results[number] = BulkResult(item.video_id, "skipped")
        else:
            seen.add(item.video_id)
            found = existing(item) if existing is not None else None
            if found is None:
                queued.append(number)
            else:
                results[number] = BulkResult(item.video_id, "skipped", path=found)
    if progress is not None:
        for number in sorted(results):
            progress(results[number])

    def attempt(item: BulkItem) -> BulkResult[T]:
        if tripped.is_set() or stop.is_set():
            return BulkResult(item.video_id, "not_attempted")
        try:
            value, path = work(item)
        except Exception as error:  # one video's failure is reported, not raised
            if isinstance(error, breaker):
                tripped.set()
            return BulkResult(item.video_id, "failed", error=error)
        return BulkResult(item.video_id, "ok", value=value, path=path)

    if queued:
        workers = min(concurrency, len(queued))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="utmax-bulk") as pool:
            futures: dict[Future[BulkResult[T]], int] = {}
            pending: set[Future[BulkResult[T]]] = set()
            warned = False
            try:
                for number in queued:
                    future = pool.submit(attempt, items[number])
                    futures[future] = number
                    pending.add(future)
                while pending:
                    done, pending = wait(
                        pending, timeout=_POLL_SECONDS, return_when=FIRST_COMPLETED
                    )
                    for future in done:
                        result = future.result()
                        results[futures[future]] = result
                        if not warned and isinstance(result.error, breaker):
                            warned = True
                            log.warning(
                                "stopping after %s failed: %s; videos not started yet are "
                                "not attempted",
                                result.video_id,
                                result.error,
                            )
                        if progress is not None:
                            progress(result)
            except BaseException:
                stop.set()
                for future in pending:
                    future.cancel()
                raise
    return BulkReport(tuple(results[number] for number in range(len(items))))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/services/test_bulk_runner.py -q`
Expected: 17 passed.

- [ ] **Step 5: Gates and commit**

Run the four gates (the suite grows by 17 to 1297 passed).

```bash
git add src/utmax/services/bulk.py tests/unit/services/test_bulk_runner.py
git commit -m "feat: add the bulk runner with a circuit breaker" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: `fetch_many` and `translate_many`

**Files:**
- Modify: `src/utmax/services/translation.py`, `src/utmax/services/bulk.py`
- Create: `tests/helpers/bulk.py`
- Test: `tests/unit/services/test_bulk_transcripts.py` (create)

**Interfaces:**
- Consumes: `BulkItem`, `bulk_items`, `check_concurrency`, `run_bulk` (Task 8); `NameTemplate`, `glob_literal` (Task 7); `TranscriptService.fetch` (M1); `translate_transcript` and `create_translator` (M2); `utmax.core.bilingual.bilingual` (M2); `format_for_path` (M1); `DownloadService` (M4; stored for Task 10); `FakeTranslator` (M2 test helper) and `streaming_data_for` (M4 test helper).
- Produces:
  - In `utmax.services.translation`: `resolve_translator(model: str | Translator, options: Mapping[str, Any], *, video_id: str | None = None) -> Translator` and `check_language_code(to: str, *, video_id: str | None = None) -> str` (the former private `_language_code`). `translate()` uses both and behaves as before.
  - In `utmax.services.bulk`: `TRANSCRIPT_FIELDS = ("video_id", "title", "channel", "index", "language_code", "ext")`, `DEFAULT_TRANSCRIPT_NAME = "{video_id}.{language_code}.{ext}"`, and `BulkService(transcripts: TranscriptService, downloads: DownloadService)` with
    - `fetch_many(videos, *, out_dir=None, format="srt", languages=None, include_manual=True, include_generated=True, concurrency=4, skip_existing=True, filename=DEFAULT_TRANSCRIPT_NAME, progress=None) -> BulkReport[Transcript]`;
    - `translate_many(videos, to, *, model, out_dir=None, format="srt", languages=None, bilingual=False, instructions=None, resegment=None, concurrency=2, skip_existing=True, filename=DEFAULT_TRANSCRIPT_NAME, progress=None, **options) -> BulkReport[Transcript]`.
  - Internal helpers used by Task 10: `_Files(folder, template, ext)` with `name(item, video, **fields)`, `save(transcript, item, format)`, `pattern(item, language_glob=None)` and `finder(patterns)`; `_folder(out_dir) -> Path` (creates the folder; `InvalidOption` for a file).
  - In `tests.helpers.bulk`: `TITLES` (three video IDs and titles), `IDS`, and `ManyVideos(titles=TITLES, *, blocked=(), missing=())` — a transport whose player answers depend on the requested video (`blocked` → HTTP 429, `missing` → unavailable), serving the default caption tracks and M4's synthetic streams; `players` lists the video ID of every player request; `bulk(**download_options) -> BulkService`.

- [ ] **Step 1: Add the fake YouTube with several videos**

`tests/helpers/bulk.py`:

```python
"""A fake YouTube with several videos for bulk tests: the player answer depends on the video.

Every video has the default caption tracks: manual English (``MANUAL_JSON3``), auto English
and German (``de-DE``). Its streams are the synthetic ones of ``tests.helpers.downloads``.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Collection, Mapping
from typing import Any

from tests.helpers.downloads import streaming_data_for
from tests.helpers.fake_media import FakeBody, FakeMedia
from tests.helpers.fake_transport import json_response
from tests.helpers.youtube import MANUAL_JSON3, json3_payload, player_payload
from utmax.adapters.innertube import InnerTubeClient
from utmax.services.bulk import BulkService
from utmax.services.download import DownloadService
from utmax.services.transcripts import TranscriptService
from utmax.transport import HttpRequest, HttpResponse

TITLES = {
    "dQw4w9WgXcQ": "Never Gonna Give You Up",
    "jNQXAC9IVRw": "Me at the zoo",
    "9bZkp7q19f0": "Gangnam Style",
}
IDS = list(TITLES)


class ManyVideos:
    """InnerTube, captions and googlevideo for every video in ``titles``.

    Videos in ``blocked`` answer HTTP 429 and videos in ``missing`` are unavailable.
    ``players`` lists the video ID of every player request, in order.
    """

    def __init__(
        self,
        titles: Mapping[str, str] = TITLES,
        *,
        blocked: Collection[str] = (),
        missing: Collection[str] = (),
    ) -> None:
        self.titles = dict(titles)
        self.blocked = set(blocked)
        self.missing = set(missing)
        self.media = FakeMedia()
        self.players: list[str] = []
        self._streaming = streaming_data_for(self.media)
        self._lock = threading.Lock()

    def send(self, request: HttpRequest) -> HttpResponse:
        if "/youtubei/v1/player" in request.url:
            video_id = json.loads(request.body or b"{}")["videoId"]
            with self._lock:
                self.players.append(video_id)
            if video_id in self.blocked:
                return json_response({}, status=429)
            if video_id in self.missing:
                reason = "This video is unavailable"
                return json_response(
                    player_payload(video_id=video_id, status="ERROR", reason=reason)
                )
            title = self.titles[video_id]
            payload = player_payload(video_id=video_id, title=title, streaming_data=self._streaming)
            return json_response(payload)
        if "lang=de-DE" in request.url:
            return json_response(json3_payload((1000, 2000, "Wir sind keine Fremden")))
        if "/api/timedtext" in request.url:
            return json_response(MANUAL_JSON3)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    def stream(self, request: HttpRequest) -> FakeBody:
        return self.media.stream(request)

    def bulk(self, **options: Any) -> BulkService:
        """A BulkService over this fake; ``options`` go to the DownloadService."""
        innertube = InnerTubeClient(self)
        transcripts = TranscriptService(innertube)
        downloads = DownloadService(innertube, transcripts, self.stream, **options)
        return BulkService(transcripts, downloads)
```

- [ ] **Step 2: Write the failing tests**

`tests/unit/services/test_bulk_transcripts.py`:

```python
"""Tests for fetch_many and translate_many over a fake YouTube with several videos."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.helpers.bulk import IDS, TITLES, ManyVideos
from tests.helpers.fake_translator import FakeTranslator
from utmax.errors import (
    InvalidModelSpec,
    InvalidOption,
    InvalidVideoId,
    IpBlocked,
    ProviderAuthError,
    UnsupportedFormat,
    UTMaxError,
    VideoUnavailable,
)
from utmax.models import BulkResult, Transcript
from utmax.services.bulk import BulkService


def value(result: BulkResult[Transcript]) -> Transcript:
    assert result.value is not None
    return result.value


def test_fetch_many_returns_transcripts_in_input_order() -> None:
    report = ManyVideos().bulk().fetch_many(IDS)
    assert [result.status for result in report] == ["ok", "ok", "ok"]
    assert [value(result).video.title for result in report] == [TITLES[i] for i in IDS]
    assert [value(result).language_code for result in report] == ["en", "en", "en"]
    assert [result.path for result in report] == [None, None, None]


def test_fetch_many_saves_files_named_by_the_template(tmp_path: Path) -> None:
    subs = tmp_path / "subs"
    report = ManyVideos().bulk().fetch_many(IDS[:2], out_dir=subs)
    assert [result.path for result in report] == [subs / f"{i}.en.srt" for i in IDS[:2]]
    text = (subs / f"{IDS[0]}.en.srt").read_text(encoding="utf-8")
    assert text.startswith("1\n00:00:01,360 --> 00:00:03,040\n")
    pretty = (
        ManyVideos()
        .bulk()
        .fetch_many(
            IDS[:1],
            out_dir=subs,
            format="pretty",
            filename="{index:02d} {title} [{video_id}].{ext}",
        )
    )
    assert pretty[0].path == subs / f"01 {TITLES[IDS[0]]} [{IDS[0]}].txt"
    assert pretty[0].path.read_text(encoding="utf-8").startswith("[00:01] ")


def test_existing_files_are_skipped_without_a_request(tmp_path: Path) -> None:
    old = tmp_path / f"{IDS[0]}.en.srt"
    old.write_text("old", encoding="utf-8")
    youtube = ManyVideos()
    report = youtube.bulk().fetch_many(IDS[:2], out_dir=tmp_path)
    assert [(result.status, result.path) for result in report] == [
        ("skipped", old),
        ("ok", tmp_path / f"{IDS[1]}.en.srt"),
    ]
    assert youtube.players == [IDS[1]]
    assert old.read_text(encoding="utf-8") == "old"
    again = youtube.bulk().fetch_many(IDS[:2], out_dir=tmp_path, skip_existing=False)
    assert [result.status for result in again] == ["ok", "ok"]
    assert old.read_text(encoding="utf-8") != "old"


@pytest.mark.parametrize(
    ("existing", "languages", "skipped"),
    [
        ("en", None, True),
        ("en", ["de"], False),
        ("en", ["en"], True),
        ("de-DE", ["de"], True),
        ("de-DE", "de", True),
        ("de", ["de-AT"], True),
        ("en", ["de", "en"], True),
    ],
)
def test_the_requested_languages_decide_which_files_count(
    tmp_path: Path, existing: str, languages: list[str] | str | None, skipped: bool
) -> None:
    (tmp_path / f"{IDS[0]}.{existing}.srt").write_text("old", encoding="utf-8")
    report = ManyVideos().bulk().fetch_many(IDS[:1], out_dir=tmp_path, languages=languages)
    assert (report[0].status == "skipped") is skipped


def test_failures_are_reported_per_video() -> None:
    youtube = ManyVideos(missing={IDS[1]})
    report = youtube.bulk().fetch_many([IDS[0], IDS[1], "not a video", IDS[2]])
    assert [result.status for result in report] == ["ok", "failed", "failed", "ok"]
    assert isinstance(report[1].error, VideoUnavailable)
    assert isinstance(report[2].error, InvalidVideoId)
    with pytest.raises(VideoUnavailable):
        report.raise_for_errors()


def test_a_block_stops_fetch_many() -> None:
    youtube = ManyVideos(blocked={IDS[1]})
    report = youtube.bulk().fetch_many(IDS, concurrency=1)
    assert [result.status for result in report] == ["ok", "failed", "not_attempted"]
    assert isinstance(report[1].error, IpBlocked)
    assert youtube.players == IDS[:2]


def test_progress_sees_every_video_once() -> None:
    seen: list[BulkResult[Transcript]] = []
    ManyVideos().bulk().fetch_many([*IDS, "nope"], progress=seen.append)
    assert sorted(result.video_id for result in seen) == sorted([*IDS, "nope"])


def test_translate_many_names_files_by_the_target_language(tmp_path: Path) -> None:
    bulk = ManyVideos().bulk()
    report = bulk.translate_many(IDS[:2], "tr", model=FakeTranslator(), out_dir=tmp_path)
    assert [result.path for result in report] == [tmp_path / f"{i}.tr.srt" for i in IDS[:2]]
    turkish = value(report[0])
    assert (turkish.language_code, turkish.translated_from, turkish.translator) == (
        "tr",
        "en",
        "fake=echo-1",
    )
    assert turkish.source is not None
    assert [cue.text for cue in turkish] == [cue.text.upper() for cue in turkish.source]


def test_translate_many_can_write_bilingual_subtitles(tmp_path: Path) -> None:
    bulk = ManyVideos().bulk()
    report = bulk.translate_many(
        IDS[:1], "tr", model=FakeTranslator(), out_dir=tmp_path, bilingual=True, format="vtt"
    )
    assert report[0].path == tmp_path / f"{IDS[0]}.en+tr.vtt"
    both = value(report[0])
    assert both.language_code == "en+tr"
    first, second = both.segments[1].text.split("\n")
    assert second == first.upper()


def test_translate_many_skips_what_it_would_write(tmp_path: Path) -> None:
    (tmp_path / f"{IDS[0]}.tr.srt").write_text("old", encoding="utf-8")
    (tmp_path / f"{IDS[1]}.en+tr.srt").write_text("old", encoding="utf-8")
    translator = FakeTranslator()
    bulk = ManyVideos().bulk()
    plain = bulk.translate_many(IDS[:2], "tr", model=translator, out_dir=tmp_path)
    assert [result.status for result in plain] == ["skipped", "ok"]
    both = bulk.translate_many(IDS, "tr", model=translator, out_dir=tmp_path, bilingual=True)
    assert [result.status for result in both] == ["ok", "skipped", "ok"]


def test_a_rejected_api_key_stops_translate_many() -> None:
    def reject(request: dict[str, Any]) -> str:
        raise ProviderAuthError("The API key was rejected.", provider="fake")

    bulk = ManyVideos().bulk()
    report = bulk.translate_many(IDS, "tr", model=FakeTranslator(reject), concurrency=1)
    assert [result.status for result in report] == ["failed", "not_attempted", "not_attempted"]
    assert isinstance(report[0].error, ProviderAuthError)


Call = Callable[[BulkService, Path], object]


@pytest.mark.parametrize(
    ("call", "error"),
    [
        (lambda bulk, folder: bulk.fetch_many(IDS, out_dir=folder, concurrency=0), InvalidOption),
        (
            lambda bulk, folder: bulk.fetch_many(IDS, out_dir=folder, format="doc"),
            UnsupportedFormat,
        ),
        (
            lambda bulk, folder: bulk.fetch_many(IDS, out_dir=folder, filename="{title}.{ext}"),
            InvalidOption,
        ),
        (lambda bulk, folder: bulk.fetch_many(IDS[0], out_dir=folder), InvalidOption),
        (
            lambda bulk, folder: bulk.translate_many(IDS, "not a code", model=FakeTranslator()),
            InvalidOption,
        ),
        (
            lambda bulk, folder: bulk.translate_many(IDS, "tr", model=FakeTranslator(), key="x"),
            InvalidOption,
        ),
        (
            lambda bulk, folder: bulk.translate_many(IDS, "tr", model="nope=model-1"),
            InvalidModelSpec,
        ),
    ],
)
def test_bad_arguments_fail_before_any_request(
    tmp_path: Path, call: Call, error: type[UTMaxError]
) -> None:
    youtube = ManyVideos()
    folder = tmp_path / "subs"
    with pytest.raises(error):
        call(youtube.bulk(), folder)
    assert youtube.players == []
    assert not folder.exists()


def test_out_dir_must_be_a_folder(tmp_path: Path) -> None:
    file = tmp_path / "file.txt"
    file.write_text("x", encoding="utf-8")
    with pytest.raises(InvalidOption, match="is a file, not a folder"):
        ManyVideos().bulk().fetch_many(IDS, out_dir=file)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/services/test_bulk_transcripts.py -q`
Expected: collection error — `ImportError: cannot import name 'BulkService' from 'utmax.services.bulk'` (raised while importing `tests/helpers/bulk.py`).

- [ ] **Step 4: Share the translator and language-code checks**

In `src/utmax/services/translation.py`:

1. Replace:

```python

import logging
import re
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from typing import Any
```

   with:

```python

import logging
import re
from collections.abc import Mapping
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from typing import Any
```

2. Replace:

```python
from utmax.errors import InvalidOption, TranslationError, TranslationMismatch
from utmax.models import Language, Segment, Transcript

__all__ = ["translate", "translate_transcript"]

log = logging.getLogger("utmax.translate")

```

   with:

```python
from utmax.errors import InvalidOption, TranslationError, TranslationMismatch
from utmax.models import Language, Segment, Transcript

__all__ = ["check_language_code", "resolve_translator", "translate", "translate_transcript"]

log = logging.getLogger("utmax.translate")

```

3. Replace:

```python
    **options: Any,
) -> Transcript:
    """Pick the translator for ``model``, then translate; see :func:`utmax.translate`."""
    if isinstance(model, Translator):
        if options:
            raise InvalidOption(
                f"Options such as {', '.join(sorted(options))} only apply when model is a "
                '"provider=model-id" string; set them on the Translator instead.',
                video_id=transcript.video.video_id,
            )
        translator = model
    else:
        translator = create_translator(model, **options)
    return translate_transcript(
        transcript, to, translator, instructions=instructions, resegment=resegment
    )


def translate_transcript(
```

   with:

```python
    **options: Any,
) -> Transcript:
    """Pick the translator for ``model``, then translate; see :func:`utmax.translate`."""
    translator = resolve_translator(model, options, video_id=transcript.video.video_id)
    return translate_transcript(
        transcript, to, translator, instructions=instructions, resegment=resegment
    )


def resolve_translator(
    model: str | Translator, options: Mapping[str, Any], *, video_id: str | None = None
) -> Translator:
    """``model`` itself when it is a Translator (``options`` must then be empty), otherwise the
    built-in translator for ``"provider=model-id"`` made with ``options``."""
    if isinstance(model, Translator):
        if options:
            raise InvalidOption(
                f"Options such as {', '.join(sorted(options))} only apply when model is a "
                '"provider=model-id" string; set them on the Translator instead.',
                video_id=video_id,
            )
        return model
    return create_translator(model, **options)


def translate_transcript(
```

4. Replace:

```python
    remembers the source cues in ``source``. Nothing is returned unless every cue translated.
    """
    video_id = transcript.video.video_id
    target = _language_code(to, video_id=video_id)
    if transcript.is_bilingual:
        raise InvalidOption(
            f"The {transcript.language_code} transcript is bilingual; translate the original "
```

   with:

```python
    remembers the source cues in ``source``. Nothing is returned unless every cue translated.
    """
    video_id = transcript.video.video_id
    target = check_language_code(to, video_id=video_id)
    if transcript.is_bilingual:
        raise InvalidOption(
            f"The {transcript.language_code} transcript is bilingual; translate the original "
```

5. Replace:

```python
        return {**self._translate(first, system, schema), **self._translate(second, system, schema)}


def _language_code(to: str, *, video_id: str) -> str:
    code = str(to).strip()
    if not _LANGUAGE_TAG.fullmatch(code):
        raise InvalidOption(
```

   with:

```python
        return {**self._translate(first, system, schema), **self._translate(second, system, schema)}


def check_language_code(to: str, *, video_id: str | None = None) -> str:
    """``to`` without surrounding spaces, when it looks like a language code such as ``"tr"``,
    ``"de"`` or ``"pt-BR"``.

    Raises:
        InvalidOption: ``to`` is not a language code.
    """
    code = str(to).strip()
    if not _LANGUAGE_TAG.fullmatch(code):
        raise InvalidOption(
```

- [ ] **Step 5: Add `fetch_many` and `translate_many`**

In `src/utmax/services/bulk.py`:

1. Replace:

```python

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from utmax.core.ids import parse_video_id
from utmax.errors import InvalidOption, InvalidVideoId, RequestBlocked
from utmax.models import BulkReport, BulkResult, VideoEntry

__all__ = ["MAX_CONCURRENCY", "BulkItem", "bulk_items", "check_concurrency", "run_bulk"]

log = logging.getLogger("utmax.bulk")

MAX_CONCURRENCY = 16
_POLL_SECONDS = 0.1
T = TypeVar("T")

```

   with:

```python

from __future__ import annotations

import fnmatch
import logging
import os
import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from utmax.adapters.providers.base import Translator
from utmax.core.bilingual import bilingual as combine
from utmax.core.filenames import NameTemplate, glob_literal
from utmax.core.formats import format_for_path
from utmax.core.ids import parse_video_id
from utmax.errors import InvalidOption, InvalidVideoId, ProviderAuthError, RequestBlocked
from utmax.models import BulkReport, BulkResult, FormatName, Transcript, VideoEntry, VideoInfo
from utmax.services.download import DownloadService
from utmax.services.transcripts import TranscriptService
from utmax.services.translation import check_language_code, resolve_translator, translate_transcript

__all__ = [
    "DEFAULT_TRANSCRIPT_NAME",
    "MAX_CONCURRENCY",
    "TRANSCRIPT_FIELDS",
    "BulkItem",
    "BulkService",
    "bulk_items",
    "check_concurrency",
    "run_bulk",
]

log = logging.getLogger("utmax.bulk")

MAX_CONCURRENCY = 16
TRANSCRIPT_FIELDS = ("video_id", "title", "channel", "index", "language_code", "ext")
DEFAULT_TRANSCRIPT_NAME = "{video_id}.{language_code}.{ext}"
_POLL_SECONDS = 0.1
T = TypeVar("T")

```

2. Replace:

```python
                    future.cancel()
                raise
    return BulkReport(tuple(results[number] for number in range(len(items))))
```

   with:

```python
                    future.cancel()
                raise
    return BulkReport(tuple(results[number] for number in range(len(items))))


class BulkService:
    """``fetch_many``, ``translate_many`` and ``download_many`` over the one-video services."""

    def __init__(self, transcripts: TranscriptService, downloads: DownloadService) -> None:
        self._transcripts = transcripts
        self._downloads = downloads

    def fetch_many(
        self,
        videos: Iterable[str | VideoEntry],
        *,
        out_dir: str | os.PathLike[str] | None = None,
        format: FormatName = "srt",
        languages: Sequence[str] | str | None = None,
        include_manual: bool = True,
        include_generated: bool = True,
        concurrency: int = 4,
        skip_existing: bool = True,
        filename: str = DEFAULT_TRANSCRIPT_NAME,
        progress: Callable[[BulkResult[Transcript]], None] | None = None,
    ) -> BulkReport[Transcript]:
        """The transcript of every video; see :func:`utmax.fetch_many`."""
        check_concurrency(concurrency)
        ext = _extension(format)
        template = NameTemplate.parse(filename, allowed=TRANSCRIPT_FIELDS)
        items = bulk_items(videos)
        files = _Files(None if out_dir is None else _folder(out_dir), template, ext)

        def work(item: BulkItem) -> tuple[Transcript, Path | None]:
            transcript = self._transcripts.fetch(
                item.video_id,
                languages,
                include_manual=include_manual,
                include_generated=include_generated,
            )
            return transcript, files.save(transcript, item, format)

        def patterns(item: BulkItem) -> list[str]:
            return [files.pattern(item, glob) for glob in _language_globs(languages)]

        existing = files.finder(patterns) if skip_existing else None
        return run_bulk(items, work, concurrency=concurrency, existing=existing, progress=progress)

    def translate_many(
        self,
        videos: Iterable[str | VideoEntry],
        to: str,
        *,
        model: str | Translator,
        out_dir: str | os.PathLike[str] | None = None,
        format: FormatName = "srt",
        languages: Sequence[str] | str | None = None,
        bilingual: bool = False,
        instructions: str | None = None,
        resegment: bool | None = None,
        concurrency: int = 2,
        skip_existing: bool = True,
        filename: str = DEFAULT_TRANSCRIPT_NAME,
        progress: Callable[[BulkResult[Transcript]], None] | None = None,
        **options: Any,
    ) -> BulkReport[Transcript]:
        """Fetch and translate every video with one translator; see :func:`utmax.translate_many`."""
        check_concurrency(concurrency)
        target = check_language_code(to)
        ext = _extension(format)
        template = NameTemplate.parse(filename, allowed=TRANSCRIPT_FIELDS)
        translator = resolve_translator(model, options)
        items = bulk_items(videos)
        files = _Files(None if out_dir is None else _folder(out_dir), template, ext)

        def work(item: BulkItem) -> tuple[Transcript, Path | None]:
            original = self._transcripts.fetch(item.video_id, languages)
            translation = translate_transcript(
                original, target, translator, instructions=instructions, resegment=resegment
            )
            result = combine(original, translation) if bilingual else translation
            return result, files.save(result, item, format)

        def patterns(item: BulkItem) -> list[str]:
            if not bilingual:
                return [files.pattern(item, glob_literal(target))]
            suffix = f"+{glob_literal(target)}"
            return [files.pattern(item, glob + suffix) for glob in _language_globs(languages)]

        existing = files.finder(patterns) if skip_existing else None
        return run_bulk(
            items,
            work,
            concurrency=concurrency,
            existing=existing,
            progress=progress,
            breaker=(RequestBlocked, ProviderAuthError),
        )


@dataclass(frozen=True, slots=True)
class _Files:
    """Where a bulk call writes: a folder (``None`` keeps the results in memory only), the
    name template, and the file extension."""

    folder: Path | None
    template: NameTemplate
    ext: str

    def name(self, item: BulkItem, video: VideoInfo, **fields: str) -> str:
        """The file name of ``item``, whose video is ``video``."""
        values: dict[str, str | int] = {
            "video_id": item.video_id,
            "title": video.title,
            "channel": video.channel,
            "index": item.index,
            "ext": self.ext,
        }
        return self.template.render({**values, **fields})

    def save(self, transcript: Transcript, item: BulkItem, format: FormatName) -> Path | None:
        """Write ``transcript`` into the folder; ``None`` when there is no folder."""
        if self.folder is None:
            return None
        name = self.name(item, transcript.video, language_code=transcript.language_code)
        return transcript.save(self.folder / name, format=format)

    def pattern(self, item: BulkItem, language_glob: str | None = None) -> str:
        """A glob for the names ``item`` can get, before anything about its video is known."""
        values: dict[str, str | int] = {
            "video_id": item.video_id,
            "index": item.index,
            "ext": self.ext,
        }
        globs = None if language_glob is None else {"language_code": language_glob}
        return self.template.pattern(values, globs)

    def finder(
        self, patterns: Callable[[BulkItem], list[str]]
    ) -> Callable[[BulkItem], Path | None] | None:
        """Finds the file an earlier run left for an item; ``None`` without a folder."""
        folder = self.folder
        if folder is None:
            return None
        names = sorted(os.listdir(folder))

        def existing(item: BulkItem) -> Path | None:
            for pattern in patterns(item):
                found = fnmatch.filter(names, pattern)
                if found:
                    return folder / found[0]
            return None

        return existing


def _folder(out_dir: str | os.PathLike[str]) -> Path:
    """``out_dir`` as a folder that exists; it is created when missing."""
    folder = Path(out_dir)
    if folder.exists() and not folder.is_dir():
        raise InvalidOption(f"out_dir={os.fspath(out_dir)!r} is a file, not a folder.")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _extension(format: FormatName) -> str:
    """The file extension of a transcript format (``pretty`` text is ``.txt``).

    Raises:
        UnsupportedFormat: ``format`` is not a transcript format.
    """
    name = format_for_path("", format)
    return "txt" if name == "pretty" else name


def _language_globs(languages: Sequence[str] | str | None) -> list[str]:
    """Globs for the language codes a transcript chosen by ``languages`` can have: any code
    without ``languages``, otherwise every code of a requested base language (``de`` finds
    ``de`` and ``de-DE``, just like track selection)."""
    requested = [languages] if isinstance(languages, str) else list(languages or [])
    bases = dict.fromkeys(code.strip().split("-", maxsplit=1)[0].lower() for code in requested)
    if not bases:
        return ["*"]
    return [glob for base in bases for glob in (glob_literal(base), f"{glob_literal(base)}-*")]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/services/test_bulk_transcripts.py tests/unit/services/test_bulk_runner.py tests/unit/services/test_translation.py tests/unit/test_translation_api.py -q`
Expected: the new file reports 25 passed; the runner and translation tests still pass.

- [ ] **Step 7: Gates and commit**

Run the four gates (the suite grows by 25 to 1322 passed).

```bash
git add src/utmax/services/translation.py src/utmax/services/bulk.py tests/helpers/bulk.py tests/unit/services/test_bulk_transcripts.py
git commit -m "feat: add fetch_many and translate_many" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: `download_many`

**Files:**
- Create: `tests/helpers/files.py`
- Modify: `src/utmax/services/download.py`, `src/utmax/services/bulk.py`, `tests/unit/services/test_download_audio.py` (three folder checks)
- Test: `tests/unit/services/test_bulk_downloads.py` (create)

**Interfaces:**
- Consumes: `BulkService`, `_Files`, `_folder` (Task 9); `NameTemplate` and `Target.path_for(..., name=)` (Task 7); `DownloadService`, `DownloadOptions` (M4); `ManyVideos` (Task 9); `FakeFFmpegRuns`, `read_movie`, `codec_of` (M4 test helpers).
- Produces:
  - `tests.helpers.files.folder_names(folder: Path) -> list[str]` — the sorted names in `folder` without Windows' transient ghost names (see the Global Constraints).
  - `DownloadOptions.name: Callable[[VideoInfo, str], str] | None = None` — names the file inside a folder target.
  - `DownloadService.check(path: str | os.PathLike[str], options: DownloadOptions) -> None` — raises what `download()` would raise before its first request (bad options, a missing ffmpeg for `.mp3`, an existing file). `download()` runs the same checks through the new private `_prepare`, so its behaviour is unchanged.
  - In `utmax.services.bulk`: `DOWNLOAD_FIELDS = ("video_id", "title", "channel", "index", "ext")`, `DEFAULT_DOWNLOAD_NAME = "{title} [{video_id}].{ext}"` and `BulkService.download_many(videos, out_dir, *, format="mp4", quality="compat", subtitles=None, subtitle_mode="embed", concurrency=2, skip_existing=True, filename=DEFAULT_DOWNLOAD_NAME, ffmpeg=None, progress=None) -> BulkReport[DownloadResult]` (Decision 16).

- [ ] **Step 1: Make folder checks ignore Windows' ghost names**

`tests/helpers/files.py`:

```python
"""Folder checks that hold on every platform."""

from __future__ import annotations

from pathlib import Path


def folder_names(folder: Path) -> list[str]:
    """The sorted names in ``folder``, without the ones some Windows security software shows
    for a moment after a file was deleted: the old name in capitals plus ``.tmp`` (such as
    ``RICK.M4A.140.PART.JSON.tmp``). utmax's own temporary files start with a dot, so they
    still show up."""
    return sorted(name for name in (path.name for path in folder.iterdir()) if not _ghost(name))


def _ghost(name: str) -> bool:
    stem = name.removesuffix(".tmp")
    return stem != name and not name.startswith(".") and stem == stem.upper()
```

In `tests/unit/services/test_download_audio.py`:

1. Replace:

```python

from tests.helpers.builders import make_transcript
from tests.helpers.downloads import FakeFFmpegRuns, FakeYouTube, read_movie
from tests.helpers.youtube import VIDEO_ID
from utmax.adapters import ffmpeg as ffmpeg_module
from utmax.errors import (
```

   with:

```python

from tests.helpers.builders import make_transcript
from tests.helpers.downloads import FakeFFmpegRuns, FakeYouTube, read_movie
from tests.helpers.files import folder_names
from tests.helpers.youtube import VIDEO_ID
from utmax.adapters import ffmpeg as ffmpeg_module
from utmax.errors import (
```

2. Replace:

```python
    assert movie.major_brand == "M4A "
    assert [track.handler for track in movie.tracks] == ["soun"]
    assert len(movie.tracks[0].samples) == 172
    assert sorted(path.name for path in tmp_path.iterdir()) == ["rick.m4a"]
    assert youtube.api.urls("GET") == []


```

   with:

```python
    assert movie.major_brand == "M4A "
    assert [track.handler for track in movie.tracks] == ["soun"]
    assert len(movie.tracks[0].samples) == 172
    assert folder_names(tmp_path) == ["rick.m4a"]
    assert youtube.api.urls("GET") == []


```

3. Replace:

```python
    assert result.path.read_bytes().startswith(b"ID3")
    conversion = next(call for call in runs.calls if "-i" in call)
    assert conversion[conversion.index("-i") + 1] == str(tmp_path / "song.mp3.140.part")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["song.mp3"]
    phases = [progress.phase for progress in seen]
    assert "converting" in phases
    assert phases == sorted(phases, key=["downloading", "converting", "finished"].index)
```

   with:

```python
    assert result.path.read_bytes().startswith(b"ID3")
    conversion = next(call for call in runs.calls if "-i" in call)
    assert conversion[conversion.index("-i") + 1] == str(tmp_path / "song.mp3.140.part")
    assert folder_names(tmp_path) == ["song.mp3"]
    phases = [progress.phase for progress in seen]
    assert "converting" in phases
    assert phases == sorted(phases, key=["downloading", "converting", "finished"].index)
```

4. Replace:

```python
    result = youtube.service().download(VIDEO_ID, tmp_path / "rick.m4a", DownloadOptions())
    assert result.resumed is True
    assert len(youtube.media.requests) == media_requests
    assert sorted(path.name for path in tmp_path.iterdir()) == ["rick.m4a"]


def test_failed_downloads_keep_their_parts(tmp_path: Path) -> None:
```

   with:

```python
    result = youtube.service().download(VIDEO_ID, tmp_path / "rick.m4a", DownloadOptions())
    assert result.resumed is True
    assert len(youtube.media.requests) == media_requests
    assert folder_names(tmp_path) == ["rick.m4a"]


def test_failed_downloads_keep_their_parts(tmp_path: Path) -> None:
```

Run: `uv run pytest tests/unit/services/test_download_audio.py -q`
Expected: all pass, as before.

- [ ] **Step 2: Write the failing tests**

`tests/unit/services/test_bulk_downloads.py`:

```python
"""Tests for download_many over a fake YouTube with several videos."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.helpers.builders import make_transcript
from tests.helpers.bulk import IDS, TITLES, ManyVideos
from tests.helpers.downloads import FakeFFmpegRuns, codec_of, read_movie
from tests.helpers.files import folder_names
from utmax.adapters.ffmpeg import FFmpeg
from utmax.errors import FFmpegNotFound, InvalidOption, IpBlocked, VideoUnavailable
from utmax.models import BulkResult, DownloadResult, VideoEntry


def value(result: BulkResult[DownloadResult]) -> DownloadResult:
    assert result.value is not None
    return result.value


def test_videos_are_named_by_title_and_id(tmp_path: Path) -> None:
    folder = tmp_path / "videos"
    names = [f"{TITLES[video_id]} [{video_id}].mp4" for video_id in IDS[:2]]
    report = ManyVideos().bulk().download_many(IDS[:2], folder)
    assert [result.status for result in report] == ["ok", "ok"]
    assert [result.path for result in report] == [folder / name for name in names]
    for result in report:
        assert value(result).path == result.path
        assert value(result).embedded_subtitles == ("en",)
        tracks = read_movie(value(result).path).tracks
        assert [codec_of(track) for track in tracks] == [b"avc1", b"mp4a", b"tx3g"]
    assert folder_names(folder) == sorted(names)


def test_folder_checks_ignore_only_windows_ghost_names(tmp_path: Path) -> None:
    for name in ("RICK.M4A.140.PART.JSON.tmp", ".rick.m4a.1a2b.tmp", "rick.m4a.140.part"):
        (tmp_path / name).write_bytes(b"")
    assert folder_names(tmp_path) == [".rick.m4a.1a2b.tmp", "rick.m4a.140.part"]


def test_existing_downloads_are_skipped_without_a_request(tmp_path: Path) -> None:
    old = tmp_path / f"Old title [{IDS[0]}].mp4"
    old.write_bytes(b"old")
    youtube = ManyVideos()
    report = youtube.bulk().download_many(IDS[:2], tmp_path)
    assert [(result.status, result.path) for result in report] == [
        ("skipped", old),
        ("ok", tmp_path / f"{TITLES[IDS[1]]} [{IDS[1]}].mp4"),
    ]
    assert youtube.players == [IDS[1]]
    again = youtube.bulk().download_many(IDS[:1], tmp_path, skip_existing=False)
    assert again[0].path == tmp_path / f"{TITLES[IDS[0]]} [{IDS[0]}].mp4"
    assert old.read_bytes() == b"old"


def test_templates_number_listing_entries(tmp_path: Path) -> None:
    entries = [
        VideoEntry(video_id, TITLES[video_id], 60.0, "Rick Astley", "UC" + "x" * 22, index)
        for index, video_id in ((7, IDS[0]), (8, IDS[1]))
    ]
    report = (
        ManyVideos()
        .bulk()
        .download_many(
            entries,
            tmp_path,
            format="m4a",
            filename="{index:03d} {channel} - {title} [{video_id}].{ext}",
        )
    )
    assert [result.path.name for result in report if result.path] == [
        f"007 Rick Astley - {TITLES[IDS[0]]} [{IDS[0]}].m4a",
        f"008 Rick Astley - {TITLES[IDS[1]]} [{IDS[1]}].m4a",
    ]
    assert {(value(result).container, value(result).video_format) for result in report} == {
        ("m4a", None)
    }


def test_subtitle_languages_apply_to_every_video(tmp_path: Path) -> None:
    report = (
        ManyVideos().bulk().download_many(IDS[:2], tmp_path, subtitles=["de"], subtitle_mode="both")
    )
    for result, video_id in zip(report, IDS[:2], strict=True):
        assert value(result).embedded_subtitles == ("de-DE",)
        sidecar = tmp_path / f"{TITLES[video_id]} [{video_id}].de-DE.srt"
        assert value(result).sidecars == (sidecar,)


def test_mp3_files_are_converted_with_ffmpeg(tmp_path: Path) -> None:
    runs = FakeFFmpegRuns()
    bulk = ManyVideos().bulk(
        locate=lambda _: "ffmpeg-for-tests",
        make_ffmpeg=lambda executable: FFmpeg(executable, spawn=runs),
    )
    report = bulk.download_many(IDS[:2], tmp_path, format="mp3")
    assert [result.status for result in report] == ["ok", "ok"]
    assert all(value(result).path.read_bytes().startswith(b"ID3") for result in report)


def test_mp3_needs_ffmpeg_before_any_request(tmp_path: Path) -> None:
    def missing(_: object) -> str:
        raise FFmpegNotFound("No ffmpeg was found.")

    youtube = ManyVideos()
    with pytest.raises(FFmpegNotFound):
        youtube.bulk(locate=missing).download_many(IDS, tmp_path / "audio", format="mp3")
    assert youtube.players == []
    assert not (tmp_path / "audio").exists()


@pytest.mark.parametrize(
    "options",
    [
        {"quality": "best"},
        {"format": "mov", "quality": "max"},
        {"format": "avi"},
        {"subtitles": "en"},
        {"subtitles": [make_transcript()]},
        {"subtitle_mode": "burn"},
        {"filename": "{title}.{ext}"},
        {"filename": "{video_id}.{language_code}.{ext}"},
        {"concurrency": 0},
    ],
)
def test_bad_options_fail_before_any_request(tmp_path: Path, options: dict[str, Any]) -> None:
    youtube = ManyVideos()
    with pytest.raises(InvalidOption):
        youtube.bulk().download_many(IDS, tmp_path / "videos", **options)
    assert youtube.players == []
    assert not (tmp_path / "videos").exists()


def test_failures_are_reported_and_blocks_stop_the_run(tmp_path: Path) -> None:
    missing = ManyVideos(missing={IDS[0]}).bulk().download_many(IDS[:2], tmp_path / "a")
    assert [result.status for result in missing] == ["failed", "ok"]
    assert isinstance(missing[0].error, VideoUnavailable)
    blocked = ManyVideos(blocked={IDS[0]}).bulk()
    report = blocked.download_many(IDS, tmp_path / "b", concurrency=1)
    assert [result.status for result in report] == ["failed", "not_attempted", "not_attempted"]
    assert isinstance(report[0].error, IpBlocked)


def test_ctrl_c_stops_the_downloads(tmp_path: Path) -> None:
    def interrupt(result: BulkResult[DownloadResult]) -> None:
        raise KeyboardInterrupt

    youtube = ManyVideos()
    with pytest.raises(KeyboardInterrupt):
        youtube.bulk().download_many(IDS, tmp_path, concurrency=1, progress=interrupt)
    assert IDS[2] not in youtube.players
    assert len(list(tmp_path.glob("*.mp4"))) <= 2
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/services/test_bulk_downloads.py -q`
Expected: 17 failed, 1 passed — `AttributeError: 'BulkService' object has no attribute 'download_many'` (`test_folder_checks_ignore_only_windows_ghost_names` already passes: it checks the helper of Step 1).

- [ ] **Step 4: Let a download take its checks and its file name from outside**

In `src/utmax/services/download.py`:

1. Replace:

```python
)
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.downloads import DEFAULT_CHUNK_SIZE, MIN_CHUNK_SIZE
from utmax.core.filenames import part_name, resolve_target, sidecar_name
from utmax.core.ids import parse_video_id
from utmax.core.media.moov import Flavor
from utmax.core.media.mux import plan_mux
```

   with:

```python
)
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.downloads import DEFAULT_CHUNK_SIZE, MIN_CHUNK_SIZE
from utmax.core.filenames import Target, part_name, resolve_target, sidecar_name
from utmax.core.ids import parse_video_id
from utmax.core.media.moov import Flavor
from utmax.core.media.mux import plan_mux
```

2. Replace:

```python
    SubtitleMode,
    TrackList,
    Transcript,
)
from utmax.services.transcripts import TranscriptService

```

   with:

```python
    SubtitleMode,
    TrackList,
    Transcript,
    VideoInfo,
)
from utmax.services.transcripts import TranscriptService

```

3. Replace:

```python

@dataclass(frozen=True, slots=True)
class DownloadOptions:
    """Everything :func:`utmax.download` accepts besides the video and the path."""

    format: Container | None = None
    quality: Quality = "compat"
```

   with:

```python

@dataclass(frozen=True, slots=True)
class DownloadOptions:
    """Everything :func:`utmax.download` accepts besides the video and the path.

    ``name`` names the file when ``path`` is a folder, from the video and the file extension
    (``download_many`` fills in its file-name template this way).
    """

    format: Container | None = None
    quality: Quality = "compat"
```

4. Replace:

```python
    ffmpeg: str | os.PathLike[str] | None = None
    progress: Callable[[Progress], None] | None = None
    cancel: threading.Event | None = None

    def check(self) -> None:
        """Reject option values that can never work, before anything is requested."""
```

   with:

```python
    ffmpeg: str | os.PathLike[str] | None = None
    progress: Callable[[Progress], None] | None = None
    cancel: threading.Event | None = None
    name: Callable[[VideoInfo, str], str] | None = None

    def check(self) -> None:
        """Reject option values that can never work, before anything is requested."""
```

5. Replace:

```python
                error.video_id = video_id
            raise

    def _download(
        self, video_id: str, path: str | os.PathLike[str], options: DownloadOptions
    ) -> DownloadResult:
        if options.subtitles is not None and not isinstance(options.subtitles, (str, Transcript)):
            options = replace(options, subtitles=tuple(options.subtitles))
        options.check()
        target = resolve_target(path, format=options.format, is_dir=Path(path).is_dir())
        container = target.container
        if container == "mov" and options.quality == "max":
            raise InvalidOption(
                'quality="max" needs .mp4: QuickTime .mov files cannot hold AV1 video.',
                suggestion='Save max quality as .mp4, or use quality="compat" for .mov.',
                video_id=video_id,
            )
        audio_only = container in ("m4a", "mp3")
        if audio_only and options.default_subtitle is not None:
            raise InvalidOption(
                f".{container} files cannot embed subtitles, so default_subtitle has no effect.",
                suggestion="Leave default_subtitle out for audio files.",
                video_id=video_id,
            )
        ffmpeg = self._ffmpeg(options.ffmpeg) if container == "mp3" else None
        if target.file is not None:
            _check_free(Path(target.file), options.overwrite, video_id)
        player = self._innertube.player(video_id, purpose="streams")
        final = Path(target.path_for(player.video))
        if target.file is None:
            _check_free(final, options.overwrite, video_id)
        subtitles = self._subtitles(player, options.subtitles, audio_only=audio_only)
```

   with:

```python
                error.video_id = video_id
            raise

    def check(self, path: str | os.PathLike[str], options: DownloadOptions) -> None:
        """Raise what :meth:`download` would raise for ``path`` and ``options`` before its first
        request: bad options, no usable ffmpeg for ``.mp3``, an existing file."""
        self._prepare(path, _listed(options), video_id=None)

    def _download(
        self, video_id: str, path: str | os.PathLike[str], options: DownloadOptions
    ) -> DownloadResult:
        options = _listed(options)
        target, ffmpeg = self._prepare(path, options, video_id=video_id)
        container = target.container
        audio_only = container in ("m4a", "mp3")
        player = self._innertube.player(video_id, purpose="streams")
        final = Path(target.path_for(player.video, name=options.name))
        if target.file is None:
            _check_free(final, options.overwrite, video_id)
        subtitles = self._subtitles(player, options.subtitles, audio_only=audio_only)
```

6. Replace:

```python
            size_bytes=size,
            resumed=resumed,
        )

    def _ffmpeg(self, explicit: str | os.PathLike[str] | None) -> FFmpeg:
        tool = self._make_ffmpeg(self._locate(explicit))
```

   with:

```python
            size_bytes=size,
            resumed=resumed,
        )

    def _prepare(
        self, path: str | os.PathLike[str], options: DownloadOptions, *, video_id: str | None
    ) -> tuple[Target, FFmpeg | None]:
        """Every check that needs no request; the target and, for ``.mp3``, ffmpeg."""
        options.check()
        target = resolve_target(path, format=options.format, is_dir=Path(path).is_dir())
        container = target.container
        if container == "mov" and options.quality == "max":
            raise InvalidOption(
                'quality="max" needs .mp4: QuickTime .mov files cannot hold AV1 video.',
                suggestion='Save max quality as .mp4, or use quality="compat" for .mov.',
                video_id=video_id,
            )
        if container in ("m4a", "mp3") and options.default_subtitle is not None:
            raise InvalidOption(
                f".{container} files cannot embed subtitles, so default_subtitle has no effect.",
                suggestion="Leave default_subtitle out for audio files.",
                video_id=video_id,
            )
        ffmpeg = self._ffmpeg(options.ffmpeg) if container == "mp3" else None
        if target.file is not None:
            _check_free(Path(target.file), options.overwrite, video_id)
        return target, ffmpeg

    def _ffmpeg(self, explicit: str | os.PathLike[str] | None) -> FFmpeg:
        tool = self._make_ffmpeg(self._locate(explicit))
```

7. Replace:

```python
        log.warning("could not delete %s: %s", leftover.name, error)


def _check_free(path: Path, overwrite: bool, video_id: str) -> None:
    if path.exists() and not overwrite:
        raise OutputExists(f"{path} already exists.", video_id=video_id)

```

   with:

```python
        log.warning("could not delete %s: %s", leftover.name, error)


def _listed(options: DownloadOptions) -> DownloadOptions:
    """``options`` with ``subtitles`` as a tuple (callers may pass any iterable)."""
    if options.subtitles is None or isinstance(options.subtitles, (str, Transcript)):
        return options
    return replace(options, subtitles=tuple(options.subtitles))


def _check_free(path: Path, overwrite: bool, video_id: str | None) -> None:
    if path.exists() and not overwrite:
        raise OutputExists(f"{path} already exists.", video_id=video_id)

```

- [ ] **Step 5: Add `download_many`**

In `src/utmax/services/bulk.py`:

1. Replace:

```python
import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

```

   with:

```python
import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, TypeVar

```

2. Replace:

```python
from utmax.core.formats import format_for_path
from utmax.core.ids import parse_video_id
from utmax.errors import InvalidOption, InvalidVideoId, ProviderAuthError, RequestBlocked
from utmax.models import BulkReport, BulkResult, FormatName, Transcript, VideoEntry, VideoInfo
from utmax.services.download import DownloadService
from utmax.services.transcripts import TranscriptService
from utmax.services.translation import check_language_code, resolve_translator, translate_transcript

__all__ = [
    "DEFAULT_TRANSCRIPT_NAME",
    "MAX_CONCURRENCY",
    "TRANSCRIPT_FIELDS",
    "BulkItem",
```

   with:

```python
from utmax.core.formats import format_for_path
from utmax.core.ids import parse_video_id
from utmax.errors import InvalidOption, InvalidVideoId, ProviderAuthError, RequestBlocked
from utmax.models import (
    BulkReport,
    BulkResult,
    Container,
    DownloadResult,
    FormatName,
    Quality,
    SubtitleMode,
    Transcript,
    VideoEntry,
    VideoInfo,
)
from utmax.services.download import DownloadOptions, DownloadService
from utmax.services.transcripts import TranscriptService
from utmax.services.translation import check_language_code, resolve_translator, translate_transcript

__all__ = [
    "DEFAULT_DOWNLOAD_NAME",
    "DEFAULT_TRANSCRIPT_NAME",
    "DOWNLOAD_FIELDS",
    "MAX_CONCURRENCY",
    "TRANSCRIPT_FIELDS",
    "BulkItem",
```

3. Replace:

```python

MAX_CONCURRENCY = 16
TRANSCRIPT_FIELDS = ("video_id", "title", "channel", "index", "language_code", "ext")
DEFAULT_TRANSCRIPT_NAME = "{video_id}.{language_code}.{ext}"
_POLL_SECONDS = 0.1
T = TypeVar("T")

```

   with:

```python

MAX_CONCURRENCY = 16
TRANSCRIPT_FIELDS = ("video_id", "title", "channel", "index", "language_code", "ext")
DOWNLOAD_FIELDS = ("video_id", "title", "channel", "index", "ext")
DEFAULT_TRANSCRIPT_NAME = "{video_id}.{language_code}.{ext}"
DEFAULT_DOWNLOAD_NAME = "{title} [{video_id}].{ext}"
_POLL_SECONDS = 0.1
T = TypeVar("T")

```

4. Replace:

```python
            breaker=(RequestBlocked, ProviderAuthError),
        )


@dataclass(frozen=True, slots=True)
class _Files:
```

   with:

```python
            breaker=(RequestBlocked, ProviderAuthError),
        )

    def download_many(
        self,
        videos: Iterable[str | VideoEntry],
        out_dir: str | os.PathLike[str],
        *,
        format: Container = "mp4",
        quality: Quality = "compat",
        subtitles: Sequence[str] | None = None,
        subtitle_mode: SubtitleMode = "embed",
        concurrency: int = 2,
        skip_existing: bool = True,
        filename: str = DEFAULT_DOWNLOAD_NAME,
        ffmpeg: str | os.PathLike[str] | None = None,
        progress: Callable[[BulkResult[DownloadResult]], None] | None = None,
    ) -> BulkReport[DownloadResult]:
        """Download every video into ``out_dir``; see :func:`utmax.download_many`."""
        check_concurrency(concurrency)
        if subtitles is not None and not isinstance(subtitles, str):
            subtitles = tuple(subtitles)
            if not all(isinstance(code, str) for code in subtitles):
                raise InvalidOption(
                    "download_many takes subtitle language codes, such as subtitles=['en']; "
                    "a Transcript belongs to a single video."
                )
        stop = threading.Event()
        options = DownloadOptions(
            format=format,
            quality=quality,
            subtitles=subtitles,
            subtitle_mode=subtitle_mode,
            overwrite=True,
            ffmpeg=ffmpeg,
            cancel=stop,
        )
        template = NameTemplate.parse(filename, allowed=DOWNLOAD_FIELDS)
        self._downloads.check(os.path.join(os.fspath(out_dir), ""), options)
        items = bulk_items(videos)
        folder = _folder(out_dir)
        files = _Files(folder, template, format)

        def work(item: BulkItem) -> tuple[DownloadResult, Path | None]:
            def name(video: VideoInfo, ext: str) -> str:
                return files.name(item, video)

            result = self._downloads.download(item.video_id, folder, replace(options, name=name))
            return result, result.path

        existing = files.finder(lambda item: [files.pattern(item)]) if skip_existing else None
        return run_bulk(
            items, work, concurrency=concurrency, existing=existing, progress=progress, stop=stop
        )


@dataclass(frozen=True, slots=True)
class _Files:
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/services/test_bulk_downloads.py tests/unit/services/test_download_video.py tests/unit/services/test_download_audio.py tests/unit/test_download_api.py -q`
Expected: the new file reports 18 passed; the M4 download tests still pass.

- [ ] **Step 7: Gates and commit**

Run the four gates (the suite grows by 18 to 1340 passed).

```bash
git add tests/helpers/files.py tests/unit/services/test_download_audio.py src/utmax/services/download.py src/utmax/services/bulk.py tests/unit/services/test_bulk_downloads.py
git commit -m "feat: add download_many" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: `list_videos` and the bulk calls on `utmax` and `Client`

**Files:**
- Modify: `src/utmax/client.py`, `src/utmax/__init__.py`
- Test: `tests/unit/test_collections_api.py` (create)

**Interfaces:**
- Consumes: `CollectionService` (Task 6); `BulkService`, `DEFAULT_TRANSCRIPT_NAME`, `DEFAULT_DOWNLOAD_NAME` (Tasks 9 and 10); `ManyVideos` (Task 9); `vr_page` (Task 4).
- Produces: `Client.list_videos`, `Client.fetch_many`, `Client.translate_many`, `Client.download_many`, and the module functions `utmax.list_videos`, `utmax.fetch_many`, `utmax.translate_many`, `utmax.download_many` with exactly the parameters of the service methods (the tests compare the signatures). The facade docstrings are the user documentation of the four calls.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_collections_api.py`:

```python
"""Tests for utmax.list_videos, fetch_many, translate_many and download_many."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import utmax
from tests.helpers.browse import vr_page
from tests.helpers.bulk import IDS, TITLES, ManyVideos
from tests.helpers.fake_translator import FakeTranslator
from tests.helpers.fake_transport import FakeTransport, json_response
from utmax import Client
from utmax.models import VideoEntry, VideoList

PARAMETERS = {
    "list_videos": ["source", "kind", "limit"],
    "fetch_many": [
        "videos",
        "out_dir",
        "format",
        "languages",
        "include_manual",
        "include_generated",
        "concurrency",
        "skip_existing",
        "filename",
        "progress",
    ],
    "translate_many": [
        "videos",
        "to",
        "model",
        "out_dir",
        "format",
        "languages",
        "bilingual",
        "instructions",
        "resegment",
        "concurrency",
        "skip_existing",
        "filename",
        "progress",
        "options",
    ],
    "download_many": [
        "videos",
        "out_dir",
        "format",
        "quality",
        "subtitles",
        "subtitle_mode",
        "concurrency",
        "skip_existing",
        "filename",
        "ffmpeg",
        "progress",
    ],
}


@pytest.mark.parametrize("name", sorted(PARAMETERS))
def test_the_facade_and_the_client_take_the_same_arguments(name: str) -> None:
    facade = inspect.signature(getattr(utmax, name))
    method = inspect.signature(getattr(Client, name))
    assert list(facade.parameters) == PARAMETERS[name]
    assert list(method.parameters) == ["self", *PARAMETERS[name]]
    for parameter in facade.parameters.values():
        twin = method.parameters[parameter.name]
        assert (twin.kind, twin.default) == (parameter.kind, parameter.default)
    assert name in utmax.__all__


def test_list_videos_uses_the_default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeTransport()
    transport.add(
        "POST", "/youtubei/v1/browse", json_response(vr_page("aaaaaaaaaaa", count="1 video"))
    )
    monkeypatch.setattr(utmax, "_default_client", Client(transport=transport))
    videos = utmax.list_videos("PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI", limit=5)
    assert [(entry.video_id, entry.index) for entry in videos] == [("aaaaaaaaaaa", 1)]
    assert (videos.title, videos.video_count) == ("A playlist", 1)


def test_bulk_calls_use_the_default_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(utmax, "_default_client", Client(transport=ManyVideos()))
    fetched = utmax.fetch_many(IDS[:2], out_dir=tmp_path, format="vtt")
    assert [result.path for result in fetched] == [tmp_path / f"{i}.en.vtt" for i in IDS[:2]]
    translated = utmax.translate_many(IDS[:1], "tr", model=FakeTranslator(), bilingual=True)
    assert translated[0].value is not None
    assert translated[0].value.language_code == "en+tr"
    downloaded = utmax.download_many(IDS[:1], tmp_path, format="m4a")
    assert downloaded[0].path == tmp_path / f"{TITLES[IDS[0]]} [{IDS[0]}].m4a"


def test_video_lists_feed_the_bulk_calls(tmp_path: Path) -> None:
    entries = tuple(
        VideoEntry(video_id, TITLES[video_id], 60.0, "Rick Astley", "UC" + "x" * 22, index)
        for index, video_id in enumerate(IDS, start=1)
    )
    videos = VideoList("Uploads from Rick Astley", "UU" + "x" * 22, "all", 3, entries)
    client = Client(transport=ManyVideos())
    report = client.fetch_many(videos, out_dir=tmp_path, filename="{index:02d} {video_id}.{ext}")
    assert [result.path for result in report] == [
        tmp_path / f"{index:02d} {video_id}.srt" for index, video_id in enumerate(IDS, start=1)
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_collections_api.py -q`
Expected: 7 failed — `AttributeError: module 'utmax' has no attribute 'download_many'` (and likewise `fetch_many`, `list_videos` and `translate_many`; the last test fails on `Client.fetch_many`).

- [ ] **Step 3: Add the calls to `Client`**

In `src/utmax/client.py`:

1. Replace:

```python

import os
import threading
from collections.abc import Callable, Sequence
from functools import partial
from typing import Any, Self

```

   with:

```python

import os
import threading
from collections.abc import Callable, Iterable, Sequence
from functools import partial
from typing import Any, Self

```

2. Replace:

```python
from utmax.core.downloads import DEFAULT_CHUNK_SIZE
from utmax.errors import InvalidOption
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
from utmax.services.transcripts import TranscriptService
from utmax.services.translation import translate
```

   with:

```python
from utmax.core.downloads import DEFAULT_CHUNK_SIZE
from utmax.errors import InvalidOption
from utmax.models import (
    BulkReport,
    BulkResult,
    CollectionKind,
    Container,
    DownloadResult,
    FormatName,
    Progress,
    Quality,
    SubtitleMode,
    TrackList,
    Transcript,
    VideoEntry,
    VideoInfo,
    VideoList,
)
from utmax.services.bulk import DEFAULT_DOWNLOAD_NAME, DEFAULT_TRANSCRIPT_NAME, BulkService
from utmax.services.collections import CollectionService
from utmax.services.download import DownloadOptions, DownloadService
from utmax.services.transcripts import TranscriptService
from utmax.services.translation import translate
```

3. Replace:

```python
        self._downloads = DownloadService(
            innertube, self._transcripts, partial(open_stream, transport)
        )

    def fetch(
        self,
```

   with:

```python
        self._downloads = DownloadService(
            innertube, self._transcripts, partial(open_stream, transport)
        )
        self._collections = CollectionService(innertube)
        self._bulk = BulkService(self._transcripts, self._downloads)

    def fetch(
        self,
```

4. Replace:

```python
        )
        return self._downloads.download(video, path, options)

    def close(self) -> None:
        """Release resources; utmax keeps no open connections today, so this does nothing yet."""

```

   with:

```python
        )
        return self._downloads.download(video, path, options)

    def list_videos(
        self, source: str, *, kind: CollectionKind = "all", limit: int | None = None
    ) -> VideoList:
        """The videos of a playlist or channel; see :func:`utmax.list_videos`."""
        return self._collections.list_videos(source, kind=kind, limit=limit)

    def fetch_many(
        self,
        videos: Iterable[str | VideoEntry],
        *,
        out_dir: str | os.PathLike[str] | None = None,
        format: FormatName = "srt",
        languages: Sequence[str] | str | None = None,
        include_manual: bool = True,
        include_generated: bool = True,
        concurrency: int = 4,
        skip_existing: bool = True,
        filename: str = DEFAULT_TRANSCRIPT_NAME,
        progress: Callable[[BulkResult[Transcript]], None] | None = None,
    ) -> BulkReport[Transcript]:
        """Fetch the transcripts of many videos; see :func:`utmax.fetch_many`."""
        return self._bulk.fetch_many(
            videos,
            out_dir=out_dir,
            format=format,
            languages=languages,
            include_manual=include_manual,
            include_generated=include_generated,
            concurrency=concurrency,
            skip_existing=skip_existing,
            filename=filename,
            progress=progress,
        )

    def translate_many(
        self,
        videos: Iterable[str | VideoEntry],
        to: str,
        *,
        model: str | Translator,
        out_dir: str | os.PathLike[str] | None = None,
        format: FormatName = "srt",
        languages: Sequence[str] | str | None = None,
        bilingual: bool = False,
        instructions: str | None = None,
        resegment: bool | None = None,
        concurrency: int = 2,
        skip_existing: bool = True,
        filename: str = DEFAULT_TRANSCRIPT_NAME,
        progress: Callable[[BulkResult[Transcript]], None] | None = None,
        **options: Any,
    ) -> BulkReport[Transcript]:
        """Fetch and translate many transcripts; see :func:`utmax.translate_many`."""
        return self._bulk.translate_many(
            videos,
            to,
            model=model,
            out_dir=out_dir,
            format=format,
            languages=languages,
            bilingual=bilingual,
            instructions=instructions,
            resegment=resegment,
            concurrency=concurrency,
            skip_existing=skip_existing,
            filename=filename,
            progress=progress,
            **options,
        )

    def download_many(
        self,
        videos: Iterable[str | VideoEntry],
        out_dir: str | os.PathLike[str],
        *,
        format: Container = "mp4",
        quality: Quality = "compat",
        subtitles: Sequence[str] | None = None,
        subtitle_mode: SubtitleMode = "embed",
        concurrency: int = 2,
        skip_existing: bool = True,
        filename: str = DEFAULT_DOWNLOAD_NAME,
        ffmpeg: str | os.PathLike[str] | None = None,
        progress: Callable[[BulkResult[DownloadResult]], None] | None = None,
    ) -> BulkReport[DownloadResult]:
        """Download many videos into a folder; see :func:`utmax.download_many`."""
        return self._bulk.download_many(
            videos,
            out_dir,
            format=format,
            quality=quality,
            subtitles=subtitles,
            subtitle_mode=subtitle_mode,
            concurrency=concurrency,
            skip_existing=skip_existing,
            filename=filename,
            ffmpeg=ffmpeg,
            progress=progress,
        )

    def close(self) -> None:
        """Release resources; utmax keeps no open connections today, so this does nothing yet."""

```

- [ ] **Step 4: Add the module functions**

In `src/utmax/__init__.py`:

1. Replace:

```python
    utmax.bilingual(transcript, turkish).save("rick.en+tr.srt")

    utmax.download("dQw4w9WgXcQ", "rick.mp4")  # H.264 + AAC + English subtitles
"""

from __future__ import annotations
```

   with:

```python
    utmax.bilingual(transcript, turkish).save("rick.en+tr.srt")

    utmax.download("dQw4w9WgXcQ", "rick.mp4")  # H.264 + AAC + English subtitles

    videos = utmax.list_videos("@RickAstleyYT", kind="videos", limit=20)
    utmax.fetch_many(videos, out_dir="subs")  # one .srt per video
"""

from __future__ import annotations
```

2. Replace:

```python
import logging
import os
import threading
from collections.abc import Callable, Sequence
from typing import Any

from utmax._version import __version__
```

   with:

```python
import logging
import os
import threading
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from utmax._version import __version__
```

3. Replace:

```python
    Word,
)
from utmax.providers import Translator

__all__ = [
    "AgeRestricted",
```

   with:

```python
    Word,
)
from utmax.providers import Translator
from utmax.services.bulk import DEFAULT_DOWNLOAD_NAME, DEFAULT_TRANSCRIPT_NAME

__all__ = [
    "AgeRestricted",
```

4. Replace:

```python
    "__version__",
    "bilingual",
    "download",
    "fetch",
    "list_tracks",
    "translate",
    "translator",
    "video_info",
]
```

   with:

```python
    "__version__",
    "bilingual",
    "download",
    "download_many",
    "fetch",
    "fetch_many",
    "list_tracks",
    "list_videos",
    "translate",
    "translate_many",
    "translator",
    "video_info",
]
```

5. Replace:

```python
        progress=progress,
        cancel=cancel,
    )
```

   with:

```python
        progress=progress,
        cancel=cancel,
    )


def list_videos(
    source: str, *, kind: CollectionKind = "all", limit: int | None = None
) -> VideoList:
    """The videos of a playlist or a channel, in YouTube's order.

    Examples::

        videos = utmax.list_videos("https://www.youtube.com/playlist?list=PL...")
        shorts = utmax.list_videos("@RickAstleyYT", kind="shorts", limit=50)
        report = utmax.fetch_many(videos, out_dir="subs")

    Args:
        source: a playlist URL or ID, a channel URL (``/@handle``, ``/channel/UC...``,
            ``/c/name``, ``/user/name``; tabs such as ``/videos`` are ignored), an ``@handle``
            or a channel ID.
        kind: for channels, ``"all"`` uploads, long-form ``"videos"``, ``"shorts"`` or past
            ``"live"`` streams; playlists are always listed whole.
        limit: stop after this many videos; ``None`` lists everything (at most 1000 pages).

    Each :class:`VideoEntry` has the video ID, title, duration (``None`` when YouTube does not
    show one), channel and its 1-based position. Private and deleted videos are left out and a
    video listed twice appears once. A channel without Shorts or live streams gives an empty
    list for those kinds.

    Raises:
        InvalidSource: ``source`` names no playlist or channel (checked before any request).
        InvalidOption: ``kind`` or ``limit`` is invalid, or ``kind`` was given for a playlist.
        CollectionUnavailable: a Mix (``RD...``) or another playlist YouTube will not list.
        CollectionNotFound: the playlist or channel does not exist or is private.
        RequestBlocked, IpBlocked: YouTube is blocking or rate-limiting this IP address.
        NetworkError: the network failed after retries.
    """
    return _client().list_videos(source, kind=kind, limit=limit)


def fetch_many(
    videos: Iterable[str | VideoEntry],
    *,
    out_dir: str | os.PathLike[str] | None = None,
    format: FormatName = "srt",
    languages: Sequence[str] | str | None = None,
    include_manual: bool = True,
    include_generated: bool = True,
    concurrency: int = 4,
    skip_existing: bool = True,
    filename: str = DEFAULT_TRANSCRIPT_NAME,
    progress: Callable[[BulkResult[Transcript]], None] | None = None,
) -> BulkReport[Transcript]:
    """Fetch the transcripts of many videos, optionally saving each one as a file.

    Example::

        report = utmax.fetch_many(utmax.list_videos("@RickAstleyYT", limit=20), out_dir="subs")
        print(len(report.ok), "saved,", len(report.failed), "failed")

    Args:
        videos: video IDs, URLs and/or entries of a :func:`list_videos` result.
        out_dir: the folder for the files (created when missing); ``None`` keeps the
            transcripts in memory only (``result.value``).
        format: ``"srt"``, ``"vtt"``, ``"json"``, ``"txt"`` or ``"pretty"`` (saved as ``.txt``).
        languages: language codes in order of preference, chosen per video as in
            :func:`fetch`; ``include_manual`` and ``include_generated`` work as there too.
        concurrency: how many videos are fetched at the same time, 1 to 16.
        skip_existing: skip a video, without any request, when ``out_dir`` already holds its
            file: the name the template gives, with ``*`` for what only the request tells (a
            file in another language than ``languages`` asks for does not count).
        filename: the file-name template. Fields: ``{video_id}`` (required), ``{title}``,
            ``{channel}``, ``{index}`` (the position in ``videos``, or in the listing for
            :class:`VideoEntry` items), ``{language_code}`` and ``{ext}``. Format specs such
            as ``{index:03d}`` work.
        progress: called with each video's :class:`BulkResult` as soon as it is known, never
            in parallel.

    The :class:`BulkReport` holds one result per video, in the order given: ``"ok"``,
    ``"skipped"``, ``"failed"`` (with its ``error``) or ``"not_attempted"``. A failure never
    stops the other videos, except that when YouTube blocks the IP address the videos not
    started yet are not attempted. ``report.raise_for_errors()`` raises the first failure.

    Raises:
        InvalidOption, UnsupportedFormat: bad arguments (before any request).
        KeyboardInterrupt: Ctrl-C; videos not started yet are dropped.
    """
    return _client().fetch_many(
        videos,
        out_dir=out_dir,
        format=format,
        languages=languages,
        include_manual=include_manual,
        include_generated=include_generated,
        concurrency=concurrency,
        skip_existing=skip_existing,
        filename=filename,
        progress=progress,
    )


def translate_many(
    videos: Iterable[str | VideoEntry],
    to: str,
    *,
    model: str | Translator,
    out_dir: str | os.PathLike[str] | None = None,
    format: FormatName = "srt",
    languages: Sequence[str] | str | None = None,
    bilingual: bool = False,
    instructions: str | None = None,
    resegment: bool | None = None,
    concurrency: int = 2,
    skip_existing: bool = True,
    filename: str = DEFAULT_TRANSCRIPT_NAME,
    progress: Callable[[BulkResult[Transcript]], None] | None = None,
    **options: Any,
) -> BulkReport[Transcript]:
    """Fetch the transcripts of many videos and translate them with one AI translator.

    Example::

        videos = utmax.list_videos("@RickAstleyYT", limit=20)
        utmax.translate_many(videos, "tr", model="claude=claude-opus-5", out_dir="subs")

    Args:
        videos: video IDs, URLs and/or entries of a :func:`list_videos` result.
        to: the target language code, such as ``"tr"``.
        model: ``"provider=model-id"`` or a :class:`~utmax.providers.Translator`, as in
            :func:`translate`.
        out_dir, format, concurrency, skip_existing, filename, progress: as in
            :func:`fetch_many`; ``{language_code}`` is the target language, or
            ``"<source>+<target>"`` (such as ``"en+tr"``) with ``bilingual``.
        languages: the source track, chosen per video as in :func:`fetch`.
        bilingual: return (and save) bilingual transcripts, the original line on top.
        instructions, resegment: as in :func:`translate`.
        **options: passed to :func:`translator` when ``model`` is a string.

    The same translator serves every video. Besides a block by YouTube, a rejected API key
    stops the run: the videos not started yet are then ``"not_attempted"``.

    Raises:
        InvalidOption, InvalidModelSpec, UnsupportedFormat: bad arguments (before any request).
        ProviderNotInstalled, ProviderAuthError: the translator cannot be created.
        KeyboardInterrupt: Ctrl-C; videos not started yet are dropped.
    """
    return _client().translate_many(
        videos,
        to,
        model=model,
        out_dir=out_dir,
        format=format,
        languages=languages,
        bilingual=bilingual,
        instructions=instructions,
        resegment=resegment,
        concurrency=concurrency,
        skip_existing=skip_existing,
        filename=filename,
        progress=progress,
        **options,
    )


def download_many(
    videos: Iterable[str | VideoEntry],
    out_dir: str | os.PathLike[str],
    *,
    format: Container = "mp4",
    quality: Quality = "compat",
    subtitles: Sequence[str] | None = None,
    subtitle_mode: SubtitleMode = "embed",
    concurrency: int = 2,
    skip_existing: bool = True,
    filename: str = DEFAULT_DOWNLOAD_NAME,
    ffmpeg: str | os.PathLike[str] | None = None,
    progress: Callable[[BulkResult[DownloadResult]], None] | None = None,
) -> BulkReport[DownloadResult]:
    """Download many videos, or their audio, into one folder.

    Example::

        videos = utmax.list_videos("@RickAstleyYT", kind="videos")
        utmax.download_many(videos, "rick", format="m4a")

    Args:
        videos: video IDs, URLs and/or entries of a :func:`list_videos` result.
        out_dir: the folder for the files (created when missing).
        format, quality, subtitles, subtitle_mode, ffmpeg: as in :func:`download`, for every
            video; ``subtitles`` takes language codes only.
        concurrency: how many videos are downloaded at the same time, 1 to 16 (each with four
            connections).
        skip_existing: skip a video, without any request, when ``out_dir`` already holds its
            file; ``False`` downloads it again and replaces the file. Interrupted downloads
            resume either way.
        filename: the file-name template, as in :func:`fetch_many` but without
            ``{language_code}``; the default is ``"{title} [{video_id}].{ext}"``.
        progress: called with each video's :class:`BulkResult` as soon as it is known.

    The :class:`BulkReport` works as for :func:`fetch_many`; each ``value`` is the video's
    :class:`DownloadResult`.

    Raises:
        InvalidOption, UnsupportedFormat: bad arguments (before any request).
        FFmpegNotFound: ``format="mp3"`` without a usable ffmpeg (before any request).
        KeyboardInterrupt: Ctrl-C; running downloads stop and keep their ``.part`` files.
    """
    return _client().download_many(
        videos,
        out_dir,
        format=format,
        quality=quality,
        subtitles=subtitles,
        subtitle_mode=subtitle_mode,
        concurrency=concurrency,
        skip_existing=skip_existing,
        filename=filename,
        ffmpeg=ffmpeg,
        progress=progress,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_collections_api.py tests/unit/test_facade.py tests/unit/test_client.py -q`
Expected: the new file reports 7 passed; the existing facade and client tests still pass.

- [ ] **Step 6: Gates and commit**

Run the four gates (the suite grows by 7 to 1347 passed, 15 deselected).

```bash
git add src/utmax/client.py src/utmax/__init__.py tests/unit/test_collections_api.py
git commit -m "feat: expose list_videos and the bulk calls on utmax and Client" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Live checks and M5 verification

**Files:**
- Test: `tests/live/test_collections_live.py` (create)

**Interfaces:**
- Consumes: everything above, through `utmax`; `InnerTubeClient`, `WEB` and `parse_browse_page` for a direct check of the WEB shape.
- Produces: the live checks of spec §8 item 10 for M5 ("playlist count = header", `@RickAstleyYT` → `UCuAXFkgsw1L7xaCfnd5JJOw`) and the M5 verification report.

- [ ] **Step 1: Write the live tests**

They use Rick Astley's channel and jawed's channel (a single video, "Me at the zoo", and no Shorts or live streams), so the counts do not drift.

`tests/live/test_collections_live.py`:

```python
"""Live listing and bulk checks against YouTube (``uv run pytest -m live``).

They use Rick Astley's channel (hundreds of uploads, Shorts and live streams) and jawed's
channel, which holds a single video ("Me at the zoo") and no Shorts or live streams.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import utmax
from utmax.adapters.http import RetryingTransport, UrllibTransport
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.browse import parse_browse_page
from utmax.core.clients import WEB
from utmax.errors import CollectionNotFound, CollectionUnavailable

pytestmark = pytest.mark.live

RICK = "UCuAXFkgsw1L7xaCfnd5JJOw"
ZOO = "jNQXAC9IVRw"


def test_a_handle_resolves_to_its_channel() -> None:
    videos = utmax.list_videos("@RickAstleyYT", kind="videos", limit=5)
    assert videos.source_id == f"UULF{RICK[2:]}"
    assert len(videos) == 5
    assert {entry.channel_id for entry in videos} == {RICK}
    assert all(entry.duration for entry in videos)


def test_listings_cross_pages_without_repeats() -> None:
    videos = utmax.list_videos(f"https://www.youtube.com/channel/{RICK}", limit=45)
    video_ids = [entry.video_id for entry in videos]
    assert len(video_ids) == len(set(video_ids)) == 45
    assert [entry.index for entry in videos] == list(range(1, 46))


def test_a_whole_listing_matches_the_count_youtube_shows() -> None:
    videos = utmax.list_videos("https://www.youtube.com/@jawed")
    assert videos.video_count == 1
    assert [entry.video_id for entry in videos] == [ZOO]


def test_kinds_a_channel_lacks_are_empty() -> None:
    shorts = utmax.list_videos("@jawed", kind="shorts")
    assert (len(shorts), shorts.video_count, shorts.kind) == (0, 0, "shorts")


def test_shorts_and_live_streams_have_their_own_lists() -> None:
    shorts = utmax.list_videos("@RickAstleyYT", kind="shorts", limit=3)
    live = utmax.list_videos("@RickAstleyYT", kind="live", limit=3)
    assert (len(shorts), shorts.source_id) == (3, f"UUSH{RICK[2:]}")
    assert live.source_id == f"UULV{RICK[2:]}"
    assert len(live) >= 1


def test_the_web_client_still_reads_upload_lists() -> None:
    innertube = InnerTubeClient(RetryingTransport(UrllibTransport()))
    page = parse_browse_page(innertube.browse(WEB, browse_id=f"VLUULF{RICK[2:]}"))
    assert page.items >= 50
    assert page.continuation is not None
    assert all(video.duration for video in page.videos[:10])
    assert page.video_count is not None


def test_missing_playlists_and_mixes_are_reported() -> None:
    with pytest.raises(CollectionNotFound):
        utmax.list_videos("PLnotaplaylist000000000000000000")
    with pytest.raises(CollectionUnavailable):
        utmax.list_videos("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ")


def test_fetch_many_saves_one_file_per_video_and_skips_them_next_time(tmp_path: Path) -> None:
    report = utmax.fetch_many([ZOO, "dQw4w9WgXcQ"], out_dir=tmp_path)
    assert [result.status for result in report] == ["ok", "ok"]
    assert sorted(path.name for path in tmp_path.glob("*.srt")) == [
        "dQw4w9WgXcQ.en.srt",
        f"{ZOO}.en.srt",
    ]
    assert utmax.fetch_many([ZOO], out_dir=tmp_path)[0].status == "skipped"
```

- [ ] **Step 2: Run the live tests**

Run: `uv run pytest -m live tests/live/test_collections_live.py -v`
Expected: 8 passed in a few seconds (about 30 small requests). `RequestBlocked` from YouTube is reported as a skip by `tests/live/conftest.py`, not a failure; report skips as such.

- [ ] **Step 3: Run every gate**

```
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov --cov-report=term-missing
uv run coverage report --include="*/utmax/core/*" --fail-under=95
uv sync --locked            # then, without the AI extras:
uv run pytest -q
uv sync --locked --all-extras
uv build --out-dir <a scratch folder outside the repository>
```

Expected: ruff, format and mypy clean; 1347 passed, 23 deselected (the 8 new live tests are deselected by default) with total coverage ≥ 90 % (99.6 % when this plan was verified) and core coverage ≥ 95 % (99 %); the run without extras passes with the provider tests skipped; the wheel contains only `utmax/` and the dist-info. Record every count in the report.

- [ ] **Step 4: Check the spec's acceptance list for M5**

Write a table in the report mapping each item of spec §9 row M5 to the tests that prove it:

| Acceptance item | Proven by |
|---|---|
| Both continuation styles | Task 4 `test_android_vr_first_page`, `test_android_vr_continuation_page`, `test_web_first_page`, `test_web_last_page_has_no_continuation`, `test_older_web_pages_continue_through_a_continuation_item_renderer`; Task 6 `test_a_playlist_is_listed_page_by_page`, `test_web_takes_over_when_android_vr_fails`; live `test_the_web_client_still_reads_upload_lists` |
| Skip-existing | Task 7 `test_patterns_escape_what_is_known_and_match_the_rest`; Task 9 `test_existing_files_are_skipped_without_a_request`, `test_the_requested_languages_decide_which_files_count`, `test_translate_many_skips_what_it_would_write`; Task 10 `test_existing_downloads_are_skipped_without_a_request`; live `test_fetch_many_saves_one_file_per_video_and_skips_them_next_time` |
| Circuit breaker | Task 8 `test_a_block_stops_the_run`, `test_callers_choose_what_stops_the_run`; Task 9 `test_a_block_stops_fetch_many`, `test_a_rejected_api_key_stops_translate_many`; Task 10 `test_failures_are_reported_and_blocks_stop_the_run` |
| Live playlist + channel kinds | Task 12 `test_a_handle_resolves_to_its_channel`, `test_listings_cross_pages_without_repeats`, `test_a_whole_listing_matches_the_count_youtube_shows`, `test_kinds_a_channel_lacks_are_empty`, `test_shorts_and_live_streams_have_their_own_lists`, `test_missing_playlists_and_mixes_are_reported` |

- [ ] **Step 5: Hand the manual checks to the user**

Do not push. List these as pending user actions in the report (the user runs them; nothing is needed from the agent):

1. `len(utmax.list_videos("@RickAstleyYT"))` equals the count on the channel's page (438 on 2026-09-29), and `utmax.list_videos("@RickAstleyYT", kind="shorts")` lists the Shorts.
2. `utmax.fetch_many(utmax.list_videos("@RickAstleyYT", limit=20), out_dir="subs")` writes 20 `.srt` files; running it again skips all of them at once.
3. `utmax.translate_many(<the same 20 videos>, "tr", model="<provider=model-id>", out_dir="subs")` with the user's own API key.
4. `utmax.download_many(utmax.list_videos("@jawed"), "downloads", format="m4a")`, and a bigger `download_many` interrupted with Ctrl-C and run again: finished files are skipped and the interrupted one resumes.
5. Approval to push `v4` after M5 is merged.

- [ ] **Step 6: Commit**

```bash
git add tests/live/test_collections_live.py
git commit -m "test: add live collection checks" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
