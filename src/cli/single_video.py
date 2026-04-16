from __future__ import annotations

import argparse
import sys

from youtube_transcript import YouTubeTranscriptApi
from formatters import get_formatter
from utils.console import error, info

from .helpers import EXIT_USER_ERROR, build_formatter_kwargs, build_proxies
from .url_parser import extract_video_id


def _format_transcript_list(transcript_list, video_id: str) -> str:
    lines = [f"Available transcripts for video {video_id}:", "-" * 50]
    for transcript in transcript_list:
        status_flags = ["AUTO-GENERATED" if transcript.is_generated else "MANUAL"]
        if transcript.is_translatable:
            status_flags.append("TRANSLATABLE")
        status_str = " [" + ", ".join(status_flags) + "]"
        lines.append(
            f"  {transcript.language_code}: {transcript.language}{status_str}"
        )
        if transcript.is_translatable and transcript.translation_languages:
            lines.append(
                f"    Translation languages: {len(transcript.translation_languages)} available"
            )
    return "\n".join(lines)


def _apply_type_filters(transcript_list, args: argparse.Namespace):
    languages = args.languages or ["en"]
    if args.generated_only:
        return transcript_list.find_generated_transcript(languages)
    if args.manual_only:
        return transcript_list.find_manually_created_transcript(languages)

    available = list(transcript_list)
    if args.exclude_generated:
        available = [t for t in available if not t.is_generated]
    if args.exclude_manual:
        available = [t for t in available if t.is_generated]
    if not available:
        error("No transcripts available after applying filters")
        sys.exit(EXIT_USER_ERROR)
    return available[0]


def process_single_video(args: argparse.Namespace) -> str:
    video_id = extract_video_id(args.video)
    verbose = getattr(args, "verbose", False)

    if verbose:
        info(f"Extracting transcript for video: {video_id}")

    proxies = build_proxies(args.proxy)

    if args.list_transcripts:
        transcript_list = YouTubeTranscriptApi.list_transcripts(
            video_id, proxies=proxies, cookies=args.cookies
        )
        return _format_transcript_list(transcript_list, video_id)

    transcript = YouTubeTranscriptApi.get_transcript(
        video_id,
        languages=args.languages,
        proxies=proxies,
        cookies=args.cookies,
        preserve_formatting=args.preserve_formatting,
    )

    if verbose:
        info(f"Retrieved {len(transcript)} transcript entries")

    if (
        args.generated_only
        or args.manual_only
        or args.exclude_generated
        or args.exclude_manual
    ):
        transcript_list = YouTubeTranscriptApi.list_transcripts(
            video_id, proxies=proxies, cookies=args.cookies
        )
        transcript_obj = _apply_type_filters(transcript_list, args)
        transcript = transcript_obj.fetch(
            preserve_formatting=args.preserve_formatting
        )

    formatter = get_formatter(args.format)
    kwargs = build_formatter_kwargs(args.format)
    return formatter.format_transcript(transcript, **kwargs)
