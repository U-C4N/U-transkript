"""Bulk calls: one job per video on a thread pool, with skip-existing and a circuit breaker."""

from __future__ import annotations

import fnmatch
import logging
import os
import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, TypeVar

from utmax.adapters.providers.base import Translator
from utmax.core.bilingual import bilingual as combine
from utmax.core.filenames import NameTemplate, glob_literal
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
    "BulkService",
    "bulk_items",
    "check_concurrency",
    "run_bulk",
]

log = logging.getLogger("utmax.bulk")

MAX_CONCURRENCY = 16
TRANSCRIPT_FIELDS = ("video_id", "title", "channel", "index", "language_code", "ext")
DOWNLOAD_FIELDS = ("video_id", "title", "channel", "index", "ext")
DEFAULT_TRANSCRIPT_NAME = "{video_id}.{language_code}.{ext}"
DEFAULT_DOWNLOAD_NAME = "{title} [{video_id}].{ext}"
_POLL_SECONDS = 0.1
_UNFINISHED = (".part", ".part.json", ".tmp")
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

        # The trailing separator keeps the target a folder even if the folder vanishes during
        # the run; the download then creates it again instead of writing "<folder>.<ext>".
        target = os.path.join(folder, "")

        def work(item: BulkItem) -> tuple[DownloadResult, Path | None]:
            def name(video: VideoInfo, ext: str) -> str:
                return files.name(item, video, ext=ext)

            result = self._downloads.download(item.video_id, target, replace(options, name=name))
            return result, result.path

        existing = files.finder(lambda item: [files.pattern(item)]) if skip_existing else None
        return run_bulk(
            items, work, concurrency=concurrency, existing=existing, progress=progress, stop=stop
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
        """Finds the file an earlier run left for an item; ``None`` without a folder. The parts
        and state of an interrupted download, and temporary files, never count."""
        folder = self.folder
        if folder is None:
            return None
        names = sorted(name for name in os.listdir(folder) if not name.endswith(_UNFINISHED))

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
