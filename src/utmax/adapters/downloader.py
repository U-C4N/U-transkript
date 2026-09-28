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
            total = (
                content_range_total(body.header("Content-Range")) if body.status == 206 else None
            )
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
                        position, copy_error = self._copy(body, handle, position, chunk.end)
                        if position > start:
                            failures = 0
                        elif not self._should_stop():
                            failures = self._retry(
                                failures, copy_error or self._short(target), target
                            )
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
