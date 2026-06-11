from __future__ import annotations

import argparse
import json

from youtube_transcript import YouTubeTranscriptApi

from .url_parser import extract_video_id


def list_available_transcripts(args: argparse.Namespace) -> str:
    """Return a human- or JSON-formatted list of available transcript languages."""
    video_id = extract_video_id(args.target)
    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
    # all_transcripts() keeps both variants when a language has manual AND auto tracks
    transcripts = transcript_list.all_transcripts()

    if args.format == "json":
        entries = [
            {
                "language_code": t.language_code,
                "language": t.language,
                "is_generated": t.is_generated,
                "is_translatable": t.is_translatable,
            }
            for t in transcripts
        ]
        return json.dumps(entries, indent=2, ensure_ascii=False)

    lines = [f"Available transcripts for {video_id}:"]
    for t in transcripts:
        kind = "auto" if t.is_generated else "manual"
        translatable = ", translatable" if t.is_translatable else ""
        lines.append(f"  {t.language_code:<8} {t.language} ({kind}{translatable})")
    return "\n".join(lines)
