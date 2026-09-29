"""Translate transcripts with an AI model, batch by batch, keeping every timing."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from typing import Any

from utmax.adapters.providers import create_translator
from utmax.adapters.providers.base import Translator
from utmax.core.languages import english_name
from utmax.core.translate.batching import (
    Batch,
    InvalidResponse,
    build_request,
    parse_response,
    plan_batches,
    split_batch,
)
from utmax.core.translate.protocol import response_schema, system_prompt
from utmax.errors import InvalidOption, TranslationError, TranslationMismatch
from utmax.models import Language, Segment, Transcript

__all__ = ["check_language_code", "resolve_translator", "translate", "translate_transcript"]

log = logging.getLogger("utmax.translate")

_LANGUAGE_TAG = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*")
_EXCERPT_CHARS = 300


def translate(
    transcript: Transcript,
    to: str,
    *,
    model: str | Translator,
    instructions: str | None = None,
    resegment: bool | None = None,
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
    transcript: Transcript,
    to: str,
    translator: Translator,
    *,
    instructions: str | None = None,
    resegment: bool | None = None,
) -> Transcript:
    """Translate ``transcript`` into the language ``to``; see :func:`utmax.translate`.

    Auto-generated transcripts are merged into sentences first unless ``resegment=False``.
    Every non-blank cue is translated exactly once; the result keeps the source timings and
    remembers the source cues in ``source``. Nothing is returned unless every cue translated.
    """
    video_id = transcript.video.video_id
    target = check_language_code(to, video_id=video_id)
    if transcript.is_bilingual:
        raise InvalidOption(
            f"The {transcript.language_code} transcript is bilingual; translate the original "
            "transcript, then combine both with utmax.bilingual().",
            video_id=video_id,
        )
    merge = transcript.is_generated if resegment is None else resegment
    prepared = transcript.merge_sentences() if merge else transcript
    cues = tuple(segment for segment in prepared.segments if segment.text.strip())
    source = replace(prepared, segments=cues, source=None)
    job = _Job(
        translator=translator,
        texts=tuple(_clean(cue.text) for cue in cues),
        source=Language(source.language_code, _name(source.language_code, source.language)),
        target=Language(target, _name(target, target)),
        instructions=(instructions or "").strip() or None,
        video_id=video_id,
    )
    texts = job.run()
    return Transcript(
        video=source.video,
        language_code=target,
        language=job.target.name,
        is_generated=True,
        segments=tuple(
            Segment(start=cue.start, duration=cue.duration, text=texts[index])
            for index, cue in enumerate(cues)
        ),
        translated_from=source.language_code,
        translator=translator.name,
        source=source,
    )


@dataclass(frozen=True)
class _Job:
    translator: Translator
    texts: tuple[str, ...]
    source: Language
    target: Language
    instructions: str | None
    video_id: str

    def run(self) -> dict[int, str]:
        batches = plan_batches(
            self.texts,
            max_chars=self.translator.batch_chars,
            max_items=self.translator.batch_items,
            context_items=self.translator.context_items,
        )
        if not batches:
            return {}
        system, schema = system_prompt(), response_schema()
        results: dict[int, str] = {}
        workers = min(self.translator.concurrency, len(batches))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="utmax-translate") as pool:
            futures = [pool.submit(self._translate, batch, system, schema) for batch in batches]
            try:
                wait(futures, return_when=FIRST_EXCEPTION)
            finally:
                for future in futures:
                    future.cancel()
            # Only batches that never started are cancelled; they come after every started one,
            # so the first failure in list order is raised before a cancelled future is reached.
            try:
                for future in futures:
                    results.update(future.result())
            except TranslationError as error:
                if error.video_id is None:
                    error.video_id = self.video_id
                raise
        return results

    def _translate(self, batch: Batch, system: str, schema: dict[str, Any]) -> dict[int, str]:
        prompt = build_request(
            batch, source=self.source, target=self.target, instructions=self.instructions
        )
        name, attempts = self.translator.name, self.translator.max_attempts
        raw = reason = ""
        for attempt in range(1, attempts + 1):
            try:
                raw = self.translator.generate_json(system, prompt, schema)
                return parse_response(raw, batch.ids)
            except InvalidResponse as error:
                raw, reason = error.raw or raw, error.reason
                log.info(
                    "%s: cues %d-%d, attempt %d/%d unusable: %s",
                    name,
                    batch.ids[0],
                    batch.ids[-1],
                    attempt,
                    attempts,
                    reason,
                )
        if len(batch.items) == 1:
            raise TranslationMismatch(
                f"{name} kept returning unusable answers for cue {batch.ids[0]}: {reason}.",
                provider=self.translator.provider,
                ids=batch.ids,
                raw_excerpt=raw[:_EXCERPT_CHARS],
                video_id=self.video_id,
            )
        log.info("%s: splitting cues %d-%d in half", name, batch.ids[0], batch.ids[-1])
        first, second = split_batch(batch, self.texts, context_items=self.translator.context_items)
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
            f"{to!r} is not a language code; pass one such as 'tr', 'de' or 'pt-BR'.",
            video_id=video_id,
        )
    return code


def _name(code: str, fallback: str) -> str:
    return english_name(code) or fallback


def _clean(text: str) -> str:
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())
