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
