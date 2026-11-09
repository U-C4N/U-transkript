"""The MCP server's settings, read from environment variables.

- ``UTMAX_DOWNLOAD_DIR``: where downloads go; default ``~/Downloads/utmax``. ``~`` and
  environment variables (``$HOME``, ``%USERPROFILE%`` on Windows) are expanded; a relative path
  counts from the folder the MCP client starts the server in, so prefer an absolute one.
- ``UTMAX_PROXY``: an ``http://[user:password@]host:port`` proxy for YouTube.
- ``UTMAX_TRANSLATOR``: a model, such as ``gemini=gemini-3.8-flash`` or ``grok=grok-4.7``, that
  the server translates subtitles with (``translate_to`` of ``download`` and
  ``save_subtitles``). Its API key comes from the provider's own variable
  (``GEMINI_API_KEY``, ``XAI_API_KEY``, ``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY`` or
  ``OPENROUTER_API_KEY``), and the provider's extra must be installed, for example
  ``uvx --from "u-transcript-max[mcp,gemini]@latest" utmax-mcp``. Without it the server calls
  no AI provider, needs no API key, and the assistant translates subtitles itself.
- ``UTMAX_TRANSLATOR_EFFORT``: how long that model thinks: ``low`` (the default, fastest),
  ``medium``, ``high`` and, where the provider has them, ``xhigh`` or ``max``; ``default``
  leaves it to the model.

utmax itself reads ``UTMAX_FFMPEG`` (the ffmpeg for MP3 files).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from utmax.core.translate.spec import parse_model_spec
from utmax.errors import InvalidOption
from utmax.providers import (
    ClaudeTranslator,
    GeminiTranslator,
    GrokTranslator,
    OpenAITranslator,
    OpenRouterTranslator,
)

__all__ = ["DEFAULT_TRANSLATOR_EFFORT", "Config", "default_download_dir"]

DEFAULT_TRANSLATOR_EFFORT = "low"

# The effort values each provider takes, from the translators' public classes.
_EFFORTS = {
    translator.PROVIDER: translator.EFFORTS
    for translator in (
        ClaudeTranslator,
        OpenAITranslator,
        GeminiTranslator,
        GrokTranslator,
        OpenRouterTranslator,
    )
}


def default_download_dir() -> Path:
    """``~/Downloads/utmax``."""
    return Path.home() / "Downloads" / "utmax"


@dataclass(frozen=True, slots=True)
class Config:
    """What the tools need beyond their arguments; the model never chooses a path.

    The proxy stays out of the ``repr``, because its URL may hold a password.
    """

    download_dir: Path = field(default_factory=default_download_dir)
    proxy: str | None = field(default=None, repr=False)
    translator: str | None = None
    translator_effort: str | None = DEFAULT_TRANSLATOR_EFFORT

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> Config:
        """The settings in ``environ``; unset and empty variables keep the defaults.

        Variables inside ``UTMAX_DOWNLOAD_DIR`` are expanded from the process environment.

        Raises:
            InvalidModelSpec: ``UTMAX_TRANSLATOR`` is not ``"provider=model-id"``.
            InvalidOption: the provider does not take ``UTMAX_TRANSLATOR_EFFORT``.
        """

        def value(name: str) -> str | None:
            text = environ.get(name, "").strip()
            return text or None

        directory = value("UTMAX_DOWNLOAD_DIR")
        model = value("UTMAX_TRANSLATOR")
        effort = (value("UTMAX_TRANSLATOR_EFFORT") or DEFAULT_TRANSLATOR_EFFORT).lower()
        translator = None
        if model is not None:
            spec = parse_model_spec(model)
            translator = str(spec)
            allowed = _EFFORTS[spec.provider]
            if effort != "default" and effort not in allowed:
                raise InvalidOption(
                    f"effort must be one of {', '.join(allowed)}, not {effort!r}.",
                    suggestion=(
                        f"Set UTMAX_TRANSLATOR_EFFORT to one of these for {spec.provider}, or "
                        "to default."
                    ),
                )
        return cls(
            download_dir=_folder(directory) if directory else default_download_dir(),
            proxy=value("UTMAX_PROXY"),
            translator=translator,
            translator_effort=None if effort == "default" else effort,
        )


def _folder(text: str) -> Path:
    return Path(os.path.expandvars(text)).expanduser().absolute()
