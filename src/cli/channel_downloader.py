from __future__ import annotations

import argparse
import os

from exceptions import TranscriptRetrievalError
from formatters import get_formatter
from utils.console import error, info, success, warning
from youtube_transcript import YouTubeTranscriptApi

from .channel_scraper import get_channel_video_ids
from .helpers import build_formatter_kwargs, get_progress_bar
from .output import file_extension_for

_DEFAULT_VIDEO_COUNT = 10


def _ensure_output_dir(target: str, output: str | None) -> str:
    if output:
        os.makedirs(output, exist_ok=True)
        return output

    clean = target.replace("@", "").replace("/", "_").replace("\\", "_").strip()
    if not clean:
        clean = "channel"
    os.makedirs(clean, exist_ok=True)
    return clean


def _download_one(
    video_id: str, index: int, args: argparse.Namespace, output_dir: str
) -> tuple[bool, str | None]:
    try:
        transcript = YouTubeTranscriptApi.get_transcript(
            video_id, languages=args.languages
        )
        formatter = get_formatter(args.format)
        body = formatter.format_transcript(transcript, **build_formatter_kwargs(args.format))

        filepath = os.path.join(
            output_dir, f"{index}.{file_extension_for(args.format)}"
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

    try:
        video_ids = get_channel_video_ids(target, _DEFAULT_VIDEO_COUNT)
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
    success(f"Download completed! {successful} succeeded.")
    if failed:
        warning(f"{len(failed)} failed.")
    info(f"Transcripts saved in directory: {output_dir}")
