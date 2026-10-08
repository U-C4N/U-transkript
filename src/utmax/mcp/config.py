"""The MCP server's settings, read from environment variables.

- ``UTMAX_DOWNLOAD_DIR``: where downloads go; default ``~/Downloads/utmax``. ``~`` and
  environment variables (``$HOME``, ``%USERPROFILE%`` on Windows) are expanded; a relative path
  counts from the folder the MCP client starts the server in, so prefer an absolute one.
- ``UTMAX_PROXY``: an ``http://[user:password@]host:port`` proxy for YouTube.

utmax itself reads ``UTMAX_FFMPEG`` (the ffmpeg for MP3 files). The server calls no AI provider
and needs no API key: the assistant that uses it translates transcripts itself.
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
    """What the tools need beyond their arguments; the model never chooses a path.

    The proxy stays out of the ``repr``, because its URL may hold a password.
    """

    download_dir: Path = field(default_factory=default_download_dir)
    proxy: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> Config:
        """The settings in ``environ``; unset and empty variables keep the defaults.

        Variables inside ``UTMAX_DOWNLOAD_DIR`` are expanded from the process environment.
        """

        def value(name: str) -> str | None:
            text = environ.get(name, "").strip()
            return text or None

        directory = value("UTMAX_DOWNLOAD_DIR")
        return cls(
            download_dir=_folder(directory) if directory else default_download_dir(),
            proxy=value("UTMAX_PROXY"),
        )


def _folder(text: str) -> Path:
    return Path(os.path.expandvars(text)).expanduser().absolute()
