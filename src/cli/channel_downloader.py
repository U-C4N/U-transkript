from __future__ import annotations

import argparse
import os
import re

from exceptions import TranscriptRetrievalError
from formatters import get_formatter
from utils.console import error, info, success, warning
from youtube_transcript import YouTubeTranscriptApi

from .channel_scraper import get_channel_video_ids
from .helpers import build_formatter_kwargs, fetch_transcript_cached, get_progress_bar
from .output import file_extension_for

_DEFAULT_VIDEO_COUNT = 10

_INVALID_DIR_CHARS = re.compile(r'[<>:"/\\|?*]')


def _ensure_output_dir(target: str, output: str | None) -> str:
    if output:
        os.makedirs(output, exist_ok=True)
        return output

    clean = _INVALID_DIR_CHARS.sub("_", target.replace("@", "")).strip(" .")
    if not clean:
        clean = "channel"
    os.makedirs(clean, exist_ok=True)
    return clean


def _download_one(
    video_id: str, index: int, args: argparse.Namespace, output_dir: str
) -> tuple[bool, str | None]:
    try:
        transcript = fetch_transcript_cached(
            YouTubeTranscriptApi,
            video_id,
            languages=args.languages,
            use_cache=not getattr(args, "no_cache", False),
        )
        formatter = get_formatter(args.format)
        body = formatter.format_transcript(transcript, **build_formatter_kwargs(args.format))

        filepath = os.path.join(
            output_dir, f"{index}_{video_id}.{file_extension_for(args.format)}"
        )
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(body)
        return True, None
    except TranscriptRetrievalError as e:
        warning(f"  No transcript for {video_id}: {e}")
        return False, str(e)
    except Exception as e:
        error(f"  Unexpected error for {video_id}: {e}")
        return False, str(e)


def download_channel_transcripts(target: str, args: argparse.Namespace) -> None:
    info(f"Getting video list for {target}...")

    count = getattr(args, "count", None) or _DEFAULT_VIDEO_COUNT
    try:
        video_ids = get_channel_video_ids(target, count)
    except Exception as e:
        raise RuntimeError(f"Failed to get video list: {e}")

    info(f"Found {len(video_ids)} videos")

    output_dir = _ensure_output_dir(target, args.output)
    successful = 0
    failed: list[tuple[str, str]] = []

    iterator = get_progress_bar(
        enumerate(video_ids, 1), total=len(video_ids), desc="Downloading"
    )
    for index, video_id in iterator:
        ok, err = _download_one(video_id, index, args, output_dir)
        if ok:
            successful += 1
        else:
            failed.append((video_id, err or ""))

    print()
    if failed:
        warning(f"{len(failed)} failed.")
    if failed and successful == 0:
        raise TranscriptRetrievalError(
            None, f"All {len(failed)} transcript downloads failed for {target}"
        )
    success(f"Download completed! {successful} succeeded.")
    info(f"Transcripts saved in directory: {output_dir}")
