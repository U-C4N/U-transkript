from __future__ import annotations

import argparse
import os

from youtube_transcript import YouTubeTranscriptApi
from formatters import get_formatter
from exceptions import TranscriptRetrievalError
from utils.console import error, info, success, warning

from .channel_scraper import get_channel_video_ids
from .helpers import build_formatter_kwargs, build_proxies, get_progress_bar
from .output import file_extension_for


def _ensure_output_dir(username: str, verbose: bool) -> str:
    clean_username = (
        username.replace("@", "").replace("/", "_").replace("\\", "_")
    )
    output_dir = clean_username
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        if verbose:
            info(f"Created directory: {output_dir}")
    return output_dir


def _download_one(
    video_id: str,
    index: int,
    args: argparse.Namespace,
    output_dir: str,
    proxies: dict[str, str] | None,
) -> tuple[bool, str | None]:
    verbose = getattr(args, "verbose", False)
    quiet = getattr(args, "quiet", False)

    try:
        transcript = YouTubeTranscriptApi.get_transcript(
            video_id,
            languages=args.languages,
            proxies=proxies,
            cookies=args.cookies,
            preserve_formatting=args.preserve_formatting,
        )

        formatter = get_formatter(args.format)
        kwargs = build_formatter_kwargs(args.format)
        formatted = formatter.format_transcript(transcript, **kwargs)

        filename = f"{index}.{file_extension_for(args.format)}"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(formatted)

        if verbose:
            success(f"  Saved {filepath}")
        return True, None

    except TranscriptRetrievalError as e:
        if not quiet:
            warning(f"  No transcript for {video_id}: {e}")
            if hasattr(e, "suggestion"):
                warning(f"  Suggestion: {e.suggestion}")
        return False, str(e)
    except Exception as e:
        if not quiet:
            error(f"  Unexpected error for {video_id}: {e}")
        return False, str(e)


def _print_summary(
    successful: int,
    failed: list[tuple[str, str]],
    output_dir: str,
    args: argparse.Namespace,
) -> None:
    if getattr(args, "quiet", False):
        return
    print()
    success(f"Download completed! {successful} succeeded.")
    if failed:
        warning(f"{len(failed)} failed.")
        if getattr(args, "verbose", False):
            for video_id, err in failed:
                warning(f"  {video_id}: {err}")
    info(f"Transcripts saved in directory: {output_dir}")


def download_channel_transcripts(
    username: str, max_count: int, args: argparse.Namespace
) -> None:
    quiet = getattr(args, "quiet", False)
    verbose = getattr(args, "verbose", False)

    if not quiet:
        info(f"Getting video list for {username}...")

    try:
        video_ids = get_channel_video_ids(username, max_count)
    except Exception as e:
        raise RuntimeError(f"Failed to get video list: {e}")

    if not quiet:
        info(f"Found {len(video_ids)} videos")

    output_dir = _ensure_output_dir(username, verbose)
    proxies = build_proxies(args.proxy)

    successful = 0
    failed: list[tuple[str, str]] = []

    video_iter = get_progress_bar(
        enumerate(video_ids, 1),
        total=len(video_ids),
        desc="Downloading",
        disable=quiet,
    )

    for index, video_id in video_iter:
        if verbose:
            info(f"Processing video {index}/{len(video_ids)}: {video_id}")
        ok, err = _download_one(video_id, index, args, output_dir, proxies)
        if ok:
            successful += 1
        else:
            failed.append((video_id, err or ""))

    _print_summary(successful, failed, output_dir, args)
