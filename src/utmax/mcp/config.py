"""The MCP server's settings, read from environment variables.

- ``UTMAX_MODEL``: the translation model (``"provider=model-id"``) used when a call names none.
- ``UTMAX_BASE_URL``: the server of ``openai=`` models. When it is set, ``OPENAI_API_KEY`` is not
  used (a placeholder key is sent instead), so only servers that need no API key work: Ollama,
  LM Studio, ...
- ``UTMAX_DOWNLOAD_DIR``: where downloads go; default ``~/Downloads/utmax``.
- ``UTMAX_PROXY``: an ``http://[user:password@]host:port`` proxy for YouTube.

utmax itself reads ``UTMAX_FFMPEG`` (the ffmpeg for MP3 files) and the provider SDKs read their
API keys (``ANTHROPIC_API_KEY``, ``GEMINI_API_KEY``, ``OPENROUTER_API_KEY`` and, unless
``UTMAX_BASE_URL`` is set, ``OPENAI_API_KEY``).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Config", "default_download_dir"]


def default_download_dir() -> Path:
    """``~/Downloads/utmax``."""
    return Path.home() / "Downloads" / "utmax"


@dataclass(frozen=True, slots=True)
class Config:
    """What the tools need beyond their arguments; the model never chooses a path."""

    model: str | None = None
    base_url: str | None = None
    download_dir: Path = field(default_factory=default_download_dir)
    proxy: str | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> Config:
        """The settings in ``environ``; unset and empty variables keep the defaults."""

        def value(name: str) -> str | None:
            text = environ.get(name, "").strip()
            return text or None

        directory = value("UTMAX_DOWNLOAD_DIR")
        return cls(
            model=value("UTMAX_MODEL"),
            base_url=value("UTMAX_BASE_URL"),
            download_dir=Path(directory).expanduser() if directory else default_download_dir(),
            proxy=value("UTMAX_PROXY"),
        )

    def translator_options(self, model: str) -> dict[str, str]:
        """Options for ``utmax.translator(model)``: ``base_url`` applies to ``openai=`` models."""
        provider = model.partition("=")[0].strip().lower()
        if self.base_url is not None and provider == "openai":
            return {"base_url": self.base_url}
        return {}
