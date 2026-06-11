from __future__ import annotations

import argparse
import os

from ai_translator import AITranscriptTranslator

from .url_parser import extract_video_id


def process_translation(args: argparse.Namespace) -> str:
    """Fetch a transcript and translate it with Gemini (--translate path)."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "--translate requires the GEMINI_API_KEY environment variable"
        )
    if args.format in ("srt", "vtt"):
        raise ValueError(
            "--translate supports only pretty, text or json output "
            "(translated text has no per-entry timing)"
        )

    video_id = extract_video_id(args.target)
    output_type = "json" if args.format == "json" else "txt"
    translator = AITranscriptTranslator(api_key)
    return (
        translator.set_lang(args.translate)
        .set_type(output_type)
        .translate_transcript(video_id, languages=args.languages)
    )
