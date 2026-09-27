# M1 — Foundation & Transcripts Implementation Plan

**Goal:** A zero-dependency `utmax` package that fetches, selects, parses and saves YouTube transcripts (`utmax.fetch`, `utmax.list_tracks`, `utmax.video_info`, `Transcript.save`) behind a layered, offline-testable architecture with green quality gates.

**Architecture:** Interfaces (`utmax/__init__.py` facade, `client.py`) → `services/transcripts.py` → pure `core/` (IDs, player/caption parsing, selection, formats, segmentation; no I/O) plus `adapters/` (urllib transport with retries, InnerTube client, watch-page fallback, atomic file writes). `models.py` is the shared data kernel. Tests use a scripted fake transport, a local HTTP server and recorded, redacted real responses.

**Tech Stack:** Python ≥ 3.11 standard library only · hatchling · uv · pytest + pytest-cov · ruff · mypy (strict) · GitHub Actions.

**Spec:** `docs/design/2026-09-27-u-transcript-max-design.md` (read §3–§8 before starting; this plan implements milestone M1 of §9).

## Global Constraints

- `requires-python = ">=3.11"`; tested on 3.11, 3.12, 3.13, 3.14 (Linux + Windows, macOS 3.14).
- Zero runtime dependencies: `dependencies = []`; `src/utmax` imports only the standard library.
- Distribution `u-transcript-max`, import package `utmax`, `__version__ = "0.1.0.dev0"` until M8 sets `0.1.0`.
- No CLI and no console scripts in M1.
- `utmax.core` never imports `urllib.request`, `urllib.error`, `http.client`, `http.server`, `http.cookiejar`, `socket`, `ssl`, `subprocess`, `threading`, `concurrent`, `asyncio`, or `utmax.adapters/.services/.client/.compat/.mcp`. Pure modules such as `urllib.parse`, `json`, `re`, `xml.etree`, `datetime`, `random`, `email.utils` are allowed; time is passed in as a parameter.
- `utmax.models` imports `utmax.core` only inside methods (never at module level).
- Absolute imports only (`ban-relative-imports = "all"`).
- The library never prints; it logs through `logging.getLogger("utmax.<area>")` and installs a `NullHandler` on `"utmax"`.
- Text files are written as UTF-8 without BOM, with `\n` newlines, atomically.
- Everything is English: code, docstrings, error messages, docs, commit messages.
- Every error class has a one-sentence English `suggestion` and carries `video_id` when known.
- Gates: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest --cov` (branch coverage ≥ 90 % overall) and `uv run coverage report --include="*/utmax/core/*" --fail-under=95`.
- Commits use a conventional prefix (`chore:`, `feat:`, `test:`, `docs:`) and end with the trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Work on branch `v4`; never push, merge to `main` or publish without the user's explicit approval.

## Review Focus

1. **Non-ASCII text** (♪, Turkish, CJK, emoji) in titles and captions → saved files are UTF-8 without BOM and LF-only on Windows, JSON keeps characters literal, nothing is printed. Pinned in Task 5.
2. **Pasted URL variants** (`&t=42s`, `&list=…`, `?si=…`, uppercase hosts, no scheme, surrounding whitespace, `m.`/`music.` hosts, trailing slashes) → the right ID; playlist-only or channel URLs → `InvalidVideoId`, never a wrong ID. Pinned in Task 4.
3. **Videos with no captions, only auto captions, or none in the requested languages**, and `languages="en"` passed as a bare string → typed errors whose message lists the available tracks; a bare string counts as one code. Pinned in Tasks 9 and 13.
4. **YouTube answering with HTML, empty bodies, odd JSON shapes, 5xx or 429** → typed `YouTubeError`/`NetworkError`, never `KeyError`, `TypeError` or `JSONDecodeError`. Pinned in Tasks 7, 8 and 12.
5. **Long videos (≥ 1 h) and messy cue timing** (overlaps, zero-length, unsorted) → hour timestamps, `[HH:MM:SS]` pretty stamps, clamped overlaps, dropped zero-length cues. Pinned in Task 5.

## File map

| File | Responsibility | Task |
|---|---|---|
| `pyproject.toml`, `uv.lock`, `LICENSE`, `.gitattributes`, `.gitignore`, `README.md`, `CLAUDE.md`, `.github/workflows/ci.yml` | Packaging, tooling, CI | 1 |
| `src/utmax/__init__.py` | Facade: version, public names, default client | 1, 13 |
| `src/utmax/_version.py`, `src/utmax/py.typed` | Version, typing marker | 1 |
| `src/utmax/errors.py` | Exception hierarchy (M1 subset) | 2 |
| `src/utmax/models.py` | Frozen dataclasses + thin methods | 3, 5, 6, 7, 9 |
| `src/utmax/core/ids.py` | `parse_video_id` | 4 |
| `src/utmax/core/formats.py` | SRT/VTT/JSON/TXT/pretty rendering | 5 |
| `src/utmax/adapters/files.py` | Atomic UTF-8 writes | 5 |
| `src/utmax/core/translate/protocol.py`, `core/translate/data/protocol.json` | Language-neutral thresholds | 6 |
| `src/utmax/core/segmentation.py` | `merge_sentences` | 6 |
| `src/utmax/core/ytdata.py` | Defensive JSON readers | 7 |
| `src/utmax/core/captions.py` | Caption URLs, json3/XML parsers | 7 |
| `src/utmax/core/clients.py`, `core/playability.py`, `core/player.py` | InnerTube profiles and player parsing | 8 |
| `src/utmax/core/selection.py` | `select_track` | 9 |
| `src/utmax/transport.py`, `src/utmax/core/retry.py` | HTTP seam, pure retry policy | 10 |
| `src/utmax/adapters/http.py` | `UrllibTransport`, `RetryingTransport` | 11 |
| `src/utmax/adapters/watch_page.py`, `src/utmax/adapters/innertube.py` | Watch-page fallback, InnerTube client | 12 |
| `src/utmax/services/transcripts.py`, `src/utmax/client.py` | Transcript service, `Client` | 13 |
| `scripts/record_fixtures.py`, `tests/fixtures/youtube/*` | Recorded, redacted fixtures | 14 |
| `tests/helpers/*` | Builders, fake transport, local server, YouTube payloads | 3, 7, 8, 11, 13 |

---

### Task 1: Project scaffold, tooling and CI

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `.gitattributes`, `.gitignore`, `README.md`, `CLAUDE.md`, `.github/workflows/ci.yml`
- Create: `src/utmax/__init__.py`, `src/utmax/_version.py`, `src/utmax/py.typed`, `src/utmax/core/__init__.py`
- Test: `tests/__init__.py`, `tests/test_package.py`, `tests/test_architecture.py`

**Interfaces:**
- Consumes: nothing.
- Produces: installable package `utmax` with `utmax.__version__: str`; the `"utmax"` logger has a `NullHandler`; `tests/test_architecture.py` guards core purity for every later task.

Note: `LICENSE` and `.gitattributes` currently show as deleted in `git status`; this task recreates them with new content.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling>=1.32"]
build-backend = "hatchling.build"

[project]
name = "u-transcript-max"
dynamic = ["version"]
description = "YouTube transcripts, AI translation and downloads for Python, with zero dependencies."
readme = "README.md"
license = "MIT"
license-files = ["LICENSE"]
requires-python = ">=3.11"
authors = [{ name = "U-C4N" }]
keywords = ["youtube", "transcript", "subtitles", "captions", "srt", "vtt", "translation"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3 :: Only",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
    "Topic :: Multimedia :: Video",
    "Topic :: Text Processing :: Linguistic",
    "Typing :: Typed",
]
dependencies = []

[project.urls]
Homepage = "https://github.com/U-C4N/U-transkript"
Issues = "https://github.com/U-C4N/U-transkript/issues"

[dependency-groups]
dev = [
    "mypy>=2.3",
    "pytest>=9.1",
    "pytest-cov>=7.1",
    "ruff>=0.16",
]

[tool.hatch.version]
path = "src/utmax/_version.py"

[tool.hatch.build.targets.wheel]
packages = ["src/utmax"]

[tool.hatch.build.targets.sdist]
include = ["/src", "/tests", "/README.md", "/LICENSE"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "UP", "B", "C4", "SIM", "PIE", "PERF", "RET", "PT", "N", "PL", "RUF", "TID"]
ignore = [
    "E501",    # the formatter owns line length; long literals are acceptable
    "N818",    # error names mirror youtube-transcript-api (VideoUnavailable, ...)
    "PLC0415", # models import core inside methods to avoid import cycles
    "PLR0911", # table-like functions return early by design
    "PLR0912",
    "PLR0913", # the public API takes many keyword-only options
    "PLR2004", # protocol constants and test values
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["RUF001", "RUF003"]

[tool.ruff.lint.isort]
known-first-party = ["utmax"]

[tool.ruff.lint.flake8-tidy-imports]
ban-relative-imports = "all"

[tool.mypy]
strict = true
python_version = "3.11"
files = ["src"]
warn_unreachable = true

[tool.pytest.ini_options]
minversion = "9.0"
testpaths = ["tests"]
addopts = ["-ra", "--strict-markers", "--strict-config", "-m", "not live"]
markers = ["live: talks to the real YouTube API; run with `uv run pytest -m live`"]
xfail_strict = true
filterwarnings = ["error"]

[tool.coverage.run]
branch = true
source = ["utmax"]

[tool.coverage.report]
fail_under = 90
show_missing = true
skip_covered = true
exclude_also = [
    "if TYPE_CHECKING:",
    "@overload",
    "raise NotImplementedError",
    "^\\s*\\.\\.\\.\\s*$",
]
```

- [ ] **Step 2: Write `LICENSE`, `.gitattributes`, `.gitignore`**

`LICENSE`:

```text
MIT License

Copyright (c) 2024-2026 U-C4N

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

`.gitattributes`:

```text
* text=auto eol=lf
*.bin binary
*.mp4 binary
*.m4a binary
*.png binary
```

`.gitignore`:

```text
__pycache__/
*.py[cod]
.venv/
build/
dist/
*.egg-info/
.coverage
.coverage.*
coverage.xml
htmlcov/
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.part
*.part.json
.claude/settings.local.json
```

- [ ] **Step 3: Write `README.md` (stub; M8 writes the real one) and `CLAUDE.md`**

`README.md`:

````markdown
# u-transcript max

YouTube transcripts, AI translation and downloads for Python — with zero dependencies.

> Work in progress: the first release (0.1.0) is being built milestone by milestone.
> The design lives in [`docs/design/`](docs/design/).

```python
import utmax

transcript = utmax.fetch("https://youtu.be/dQw4w9WgXcQ")
transcript.save("rick.srt")
```

## License

MIT
````

`CLAUDE.md`:

```markdown
# CLAUDE.md

Guidance for AI coding agents working in this repository.

## Project
u-transcript max — PyPI `u-transcript-max`, import `utmax`.
Design: `docs/design/2026-09-27-u-transcript-max-design.md`. Milestone plans: `docs/design/plans/`.

## Rules
- Zero runtime dependencies: only the standard library in `src/utmax` (optional extras arrive in later milestones and are imported lazily).
- Layers: interfaces (`utmax/__init__.py`, `client.py`) → `services/` → `core/` (pure, no I/O) + `adapters/` (all I/O). `tests/test_architecture.py` enforces core purity.
- `models.py` is the shared data kernel: `core` may import it; it imports `core` only inside methods.
- The library never prints; log with `logging.getLogger("utmax.<area>")`.
- Text files are UTF-8 with `\n` line endings, written atomically.
- Everything (code, docs, commits) is in English. Python ≥ 3.11, `mypy --strict`, absolute imports.

## Commands
- `uv sync` — create the environment
- `uv run pytest` — offline tests; `uv run pytest -m live` — live YouTube tests
- `uv run ruff check . && uv run ruff format --check . && uv run mypy`
```

- [ ] **Step 4: Write the CI workflow `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main, v4]
  pull_request:

permissions:
  contents: read

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10
        with:
          python-version: "3.14"
      - run: uv sync --locked
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy

  test:
    name: test (${{ matrix.os }}, ${{ matrix.python }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
        python: ["3.11", "3.12", "3.13", "3.14"]
        include:
          - os: macos-latest
            python: "3.14"
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10
        with:
          python-version: ${{ matrix.python }}
      - run: uv sync --locked
      - run: uv run pytest --cov --cov-report=term-missing
      - run: uv run coverage report --include="*/utmax/core/*" --fail-under=95

  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10
        with:
          python-version: "3.14"
      - run: uv build
      - run: uvx twine check --strict dist/*
      - name: The wheel contains only the utmax package
        run: >-
          uv run --no-project python -c "import glob, zipfile;
          names = zipfile.ZipFile(glob.glob('dist/*.whl')[0]).namelist();
          bad = [n for n in names if not n.startswith(('utmax/', 'u_transcript_max-'))];
          assert not bad, bad"
```

- [ ] **Step 5: Write the package skeleton**

`src/utmax/_version.py`:

```python
__version__ = "0.1.0.dev0"
```

`src/utmax/py.typed`: create an empty file.

`src/utmax/__init__.py`:

```python
"""u-transcript max: YouTube transcripts, AI translation and downloads with zero dependencies."""

from __future__ import annotations

import logging

from utmax._version import __version__

__all__ = ["__version__"]

logging.getLogger("utmax").addHandler(logging.NullHandler())
```

`src/utmax/core/__init__.py`:

```python
"""Pure building blocks: parsing, selection and formatting without any I/O.

Nothing in this package may touch the network, subprocesses, threads or the clock; reading the
package's own data files is the only file access allowed. ``tests/test_architecture.py``
enforces this.
"""
```

- [ ] **Step 6: Write the tests**

`tests/__init__.py`:

```python
"""Test suite for utmax."""
```

`tests/test_package.py`:

```python
"""Smoke tests for the installed package."""

from __future__ import annotations

import logging
import re

import utmax


def test_version_is_a_pep440_release_or_dev_version() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+(\.dev\d+)?", utmax.__version__)


def test_library_logger_has_a_null_handler() -> None:
    handlers = logging.getLogger("utmax").handlers
    assert any(isinstance(handler, logging.NullHandler) for handler in handlers)
```

`tests/test_architecture.py`:

```python
"""Architecture rules: the core stays pure and ``import utmax`` needs only the standard library."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import utmax

PACKAGE = Path(utmax.__file__).resolve().parent
CORE = PACKAGE / "core"

FORBIDDEN_IN_CORE = (
    "asyncio",
    "concurrent",
    "http.client",
    "http.cookiejar",
    "http.server",
    "socket",
    "ssl",
    "subprocess",
    "threading",
    "urllib.error",
    "urllib.request",
    "utmax.adapters",
    "utmax.client",
    "utmax.compat",
    "utmax.mcp",
    "utmax.services",
)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def is_forbidden(name: str) -> bool:
    return any(name == banned or name.startswith(f"{banned}.") for banned in FORBIDDEN_IN_CORE)


def test_core_never_imports_io_modules_or_outer_layers() -> None:
    offenders = [
        f"{path.relative_to(PACKAGE).as_posix()}: {name}"
        for path in sorted(CORE.rglob("*.py"))
        for name in sorted(imported_modules(path))
        if is_forbidden(name)
    ]
    assert offenders == []


def test_import_utmax_loads_only_the_standard_library() -> None:
    probe = (
        "import sys\n"
        "import utmax\n"
        "names = {name.partition('.')[0] for name in sys.modules}\n"
        "extra = sorted(n for n in names if not n.startswith('_') and n != 'utmax'"
        " and n not in sys.stdlib_module_names)\n"
        "print(','.join(extra))\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COV_", "COVERAGE_"))}
    env["PYTHONPATH"] = str(PACKAGE.parent)
    result = subprocess.run(
        [sys.executable, "-S", "-c", probe], capture_output=True, text=True, env=env, check=True
    )
    assert result.stdout.strip() == ""
```

(`-S` skips `site`, so `.pth` hooks from dev tools cannot pollute `sys.modules`; `PYTHONPATH` points at `src/`.)

- [ ] **Step 7: Lock, sync and run the tests**

Run: `uv lock && uv sync && uv run pytest -v`
Expected: 4 passed (`test_version_…`, `test_library_logger_…`, `test_core_never_…`, `test_import_utmax_…`).

- [ ] **Step 8: Run the quality gates**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: `All checks passed!`, `… files already formatted`, `Success: no issues found in 3 source files`. If `ruff format --check` reports files, run `uv run ruff format .` and re-check.

- [ ] **Step 9: Check the built wheel**

Run: `uv build && uv run --no-project python -c "import glob, zipfile; names = zipfile.ZipFile(glob.glob('dist/*.whl')[0]).namelist(); bad = [n for n in names if not n.startswith(('utmax/', 'u_transcript_max-'))]; print(bad); assert not bad"`
Expected: `[]` and exit code 0.

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml uv.lock LICENSE .gitattributes .gitignore README.md CLAUDE.md .github src tests
git commit -m "chore: scaffold the u-transcript max package

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 2: Exception hierarchy

**Files:**
- Create: `src/utmax/errors.py`
- Test: `tests/unit/__init__.py`, `tests/unit/test_errors.py`

**Interfaces:**
- Consumes: nothing.
- Produces (all in `utmax.errors`): `UTMaxError(message, *, video_id=None, suggestion=None)` with `.message`, `.video_id`, `.suggestion`; `InvalidVideoId`, `InvalidOption`, `UnsupportedFormat` (also `ValueError`); `NetworkError`; `YouTubeError` and its subclasses `VideoUnavailable`, `VideoUnplayable(message, *, reason="", sub_reasons=(), …)`, `AgeRestricted`, `RequestBlocked`, `IpBlocked(RequestBlocked)`, `PoTokenRequired`, `FailedToCreateConsentCookie`, `YouTubeRequestFailed(message, *, status_code, …)`, `YouTubeDataUnparsable`, `TranscriptsDisabled`, `NoTranscriptFound(message, *, requested=(), available=(), …)`, `NotTranslatable`, `TranslationLanguageNotAvailable(message, *, available=(), …)`. Tuples are stored for every sequence field. Every class pickles.

Later milestones add their own errors (download, translation, collections) to this module.

- [ ] **Step 1: Write the failing tests**

`tests/unit/__init__.py`:

```python
"""Unit tests (offline)."""
```

`tests/unit/test_errors.py`:

```python
"""Tests for the exception hierarchy."""

from __future__ import annotations

import pickle

import pytest

from utmax import errors


def test_every_public_error_has_a_real_suggestion() -> None:
    for name in errors.__all__:
        cls = getattr(errors, name)
        assert issubclass(cls, errors.UTMaxError)
        assert cls.suggestion.endswith(".")
        assert len(cls.suggestion) > 20


@pytest.mark.parametrize(
    ("child", "parent"),
    [
        (errors.InvalidVideoId, ValueError),
        (errors.InvalidOption, ValueError),
        (errors.UnsupportedFormat, ValueError),
        (errors.NetworkError, errors.UTMaxError),
        (errors.YouTubeError, errors.UTMaxError),
        (errors.RequestBlocked, errors.YouTubeError),
        (errors.IpBlocked, errors.RequestBlocked),
        (errors.NoTranscriptFound, errors.YouTubeError),
        (errors.TranscriptsDisabled, errors.YouTubeError),
    ],
)
def test_hierarchy(child: type[Exception], parent: type[Exception]) -> None:
    assert issubclass(child, parent)


def test_message_video_id_and_suggestion_override() -> None:
    error = errors.VideoUnavailable("gone", video_id="abc")
    assert str(error) == "gone"
    assert error.message == "gone"
    assert error.video_id == "abc"
    assert error.suggestion == errors.VideoUnavailable.suggestion
    custom = errors.VideoUnavailable("gone", suggestion="Try another video.")
    assert custom.suggestion == "Try another video."
    assert errors.VideoUnavailable.suggestion != "Try another video."


def test_specific_fields_are_stored_as_tuples() -> None:
    unplayable = errors.VideoUnplayable("no", reason="Private video", sub_reasons=["Sign in"])
    assert unplayable.reason == "Private video"
    assert unplayable.sub_reasons == ("Sign in",)
    assert errors.YouTubeRequestFailed("bad", status_code=403).status_code == 403
    missing = errors.NoTranscriptFound("none", requested=["tr"], available=["en (English, manual)"])
    assert missing.requested == ("tr",)
    assert missing.available == ("en (English, manual)",)
    assert errors.TranslationLanguageNotAvailable("no", available=["de"]).available == ("de",)


@pytest.mark.parametrize(
    "error",
    [
        errors.InvalidVideoId("bad id"),
        errors.VideoUnplayable("no", reason="r", sub_reasons=["s"], video_id="v"),
        errors.YouTubeRequestFailed("bad", status_code=500, video_id="v"),
        errors.NoTranscriptFound("none", requested=["tr"], available=["en"], video_id="v"),
        errors.IpBlocked("slow down", suggestion="Wait a minute."),
    ],
)
def test_errors_survive_pickling(error: errors.UTMaxError) -> None:
    clone = pickle.loads(pickle.dumps(error))
    assert type(clone) is type(error)
    assert str(clone) == str(error)
    assert clone.__dict__ == error.__dict__
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_errors.py -v`
Expected: collection error `ImportError: cannot import name 'errors' from 'utmax'`.

- [ ] **Step 3: Implement `src/utmax/errors.py`**

```python
"""The utmax exception hierarchy.

Every error carries a one-sentence English ``suggestion`` telling the caller what to do next
and, when known, the ``video_id`` it concerns. Names mirror youtube-transcript-api where the
meaning is the same, which keeps migrations simple.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

__all__ = [
    "AgeRestricted",
    "FailedToCreateConsentCookie",
    "InvalidOption",
    "InvalidVideoId",
    "IpBlocked",
    "NetworkError",
    "NoTranscriptFound",
    "NotTranslatable",
    "PoTokenRequired",
    "RequestBlocked",
    "TranscriptsDisabled",
    "TranslationLanguageNotAvailable",
    "UTMaxError",
    "UnsupportedFormat",
    "VideoUnavailable",
    "VideoUnplayable",
    "YouTubeDataUnparsable",
    "YouTubeError",
    "YouTubeRequestFailed",
]


def _restore(cls: type[UTMaxError], message: str, state: dict[str, Any]) -> UTMaxError:
    error = cls.__new__(cls)
    Exception.__init__(error, message)
    error.__dict__.update(state)
    return error


class UTMaxError(Exception):
    """Base class of every error raised by utmax."""

    suggestion: str = "Read the error message for details."

    def __init__(
        self, message: str, *, video_id: str | None = None, suggestion: str | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.video_id = video_id
        if suggestion is not None:
            self.suggestion = suggestion

    def __str__(self) -> str:
        return self.message

    def __reduce__(self) -> tuple[Any, ...]:
        return (_restore, (type(self), self.message, dict(self.__dict__)))


class InvalidVideoId(UTMaxError, ValueError):
    """The input does not contain a YouTube video ID."""

    suggestion = "Pass a YouTube URL or an 11-character video ID."


class InvalidOption(UTMaxError, ValueError):
    """An option value, or a combination of options, is not supported."""

    suggestion = "Check the options passed to this call against the documentation."


class UnsupportedFormat(UTMaxError, ValueError):
    """The requested output format is unknown."""

    suggestion = "Use a .srt, .vtt, .json or .txt file name, or pass format=... explicitly."


class NetworkError(UTMaxError):
    """The network failed and retries did not help."""

    suggestion = "Check your internet connection, proxy settings and firewall, then try again."


class YouTubeError(UTMaxError):
    """YouTube refused or could not serve the request."""

    suggestion = "YouTube could not serve this request; try again later."


class VideoUnavailable(YouTubeError):
    """The video does not exist or was removed."""

    suggestion = "Check that the video ID is correct and that the video is still public."


class VideoUnplayable(YouTubeError):
    """YouTube will not play the video for this client."""

    suggestion = "Private, members-only and region-locked videos are not supported."

    def __init__(
        self,
        message: str,
        *,
        reason: str = "",
        sub_reasons: Sequence[str] = (),
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.reason = reason
        self.sub_reasons = tuple(sub_reasons)


class AgeRestricted(YouTubeError):
    """The video is age-restricted."""

    suggestion = "Age-restricted videos need a signed-in session, which utmax does not support."


class RequestBlocked(YouTubeError):
    """YouTube is blocking requests from this IP address."""

    suggestion = (
        "Use a proxy (Client(proxy=...)) with block_retries, and avoid cloud-provider IP addresses."
    )


class IpBlocked(RequestBlocked):
    """YouTube rate-limited this IP address (HTTP 429 or a CAPTCHA)."""

    suggestion = "Wait before retrying, or use a rotating residential proxy with block_retries."


class PoTokenRequired(YouTubeError):
    """YouTube requires a proof-of-origin token that utmax cannot produce."""

    suggestion = (
        "YouTube changed how captions are served; please report it at "
        "https://github.com/U-C4N/U-transkript/issues."
    )


class FailedToCreateConsentCookie(YouTubeError):
    """YouTube kept showing its cookie-consent page."""

    suggestion = "Try again later, or from a different region or proxy."


class YouTubeRequestFailed(YouTubeError):
    """YouTube answered with an unexpected HTTP status."""

    suggestion = "YouTube answered with an unexpected HTTP status; try again later."

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.status_code = status_code


class YouTubeDataUnparsable(YouTubeError):
    """YouTube returned data utmax could not understand."""

    suggestion = "YouTube may have changed its responses; please report it with the video ID."


class TranscriptsDisabled(YouTubeError):
    """The video has no subtitles at all."""

    suggestion = "The uploader disabled subtitles for this video, so there is nothing to fetch."


class NoTranscriptFound(YouTubeError):
    """No track matches the requested languages or filters."""

    suggestion = "Pick one of the available languages, or call utmax.list_tracks() to see them."

    def __init__(
        self,
        message: str,
        *,
        requested: Sequence[str] = (),
        available: Sequence[str] = (),
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.requested = tuple(requested)
        self.available = tuple(available)


class NotTranslatable(YouTubeError):
    """YouTube cannot translate this track."""

    suggestion = "YouTube cannot translate this track; use AI translation instead."


class TranslationLanguageNotAvailable(YouTubeError):
    """YouTube cannot translate into the requested language."""

    suggestion = "Use a language from TrackList.translation_languages, or use AI translation."

    def __init__(
        self,
        message: str,
        *,
        available: Sequence[str] = (),
        video_id: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message, video_id=video_id, suggestion=suggestion)
        self.available = tuple(available)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_errors.py -v`
Expected: all tests PASS (1 + 9 + 1 + 1 + 5 = 17).

- [ ] **Step 5: Gates and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: clean.

```bash
git add src/utmax/errors.py tests/unit
git commit -m "feat: add the utmax exception hierarchy

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Data models

**Files:**
- Create: `src/utmax/models.py`
- Test: `tests/helpers/__init__.py`, `tests/helpers/builders.py`, `tests/unit/test_models.py`

**Interfaces:**
- Consumes: nothing from `utmax.core` (the kernel must stay import-cycle free).
- Produces (in `utmax.models`):
  - `FormatName = Literal["txt", "srt", "vtt", "json", "pretty"]`
  - `Word(text: str, start: float)`; `Segment(start, duration, text, words=())` with `.end`
  - `VideoInfo(video_id, title, channel, channel_id, duration: float, is_live_content: bool)` with `.url`
  - `Language(code, name)`
  - `TrackFetcher` protocol: `fetch_track(track: Track, *, preserve_formatting: bool) -> Transcript`
  - `Track(video: VideoInfo, language_code, language, is_generated, is_translatable, vss_id="", translation_of=None, _url="", _translation_languages=(), _fetcher=None)` with `.video_id` and `.fetch(*, preserve_formatting=False)`
  - `TrackList(video, tracks: tuple[Track, ...], translation_languages=())`: a `Sequence[Track]` with `.manual`, `.generated`
  - `Transcript(video, language_code, language, is_generated, segments: tuple[Segment, ...], translated_from=None, translator=None, source=None)`: a `Sequence[Segment]` with `.text`, `.is_bilingual`, `.to_dicts()`
- Test helpers (in `tests.helpers.builders`): `VIDEO`, `make_track(...)`, `make_transcript(*segments, ...)`.

Later tasks add `Transcript.to/.to_*/.save` (Task 5), `Transcript.merge_sentences` (Task 6), `Track.translate` (Task 7) and `TrackList.find` (Task 9).

- [ ] **Step 1: Write the test helpers**

`tests/helpers/__init__.py`:

```python
"""Shared helpers for the test suite."""
```

`tests/helpers/builders.py`:

```python
"""Tiny builders for model objects used across tests."""

from __future__ import annotations

from utmax.models import Language, Segment, Track, TrackFetcher, Transcript, VideoInfo

VIDEO = VideoInfo(
    video_id="dQw4w9WgXcQ",
    title="Rick Astley - Never Gonna Give You Up (Official Video)",
    channel="Rick Astley",
    channel_id="UCuAXFkgsw1L7xaCfnd5JJOw",
    duration=213.0,
    is_live_content=False,
)


def make_track(
    code: str = "en",
    *,
    generated: bool = False,
    name: str | None = None,
    translatable: bool = True,
    url: str | None = None,
    translation_languages: tuple[Language, ...] = (),
    fetcher: TrackFetcher | None = None,
) -> Track:
    return Track(
        video=VIDEO,
        language_code=code,
        language=name or code,
        is_generated=generated,
        is_translatable=translatable,
        vss_id=f"{'a' if generated else ''}.{code}",
        _url=url or f"https://www.youtube.com/api/timedtext?v={VIDEO.video_id}&lang={code}",
        _translation_languages=translation_languages,
        _fetcher=fetcher,
    )


def make_transcript(
    *segments: Segment,
    language_code: str = "en",
    language: str = "English",
    is_generated: bool = False,
) -> Transcript:
    return Transcript(
        video=VIDEO,
        language_code=language_code,
        language=language,
        is_generated=is_generated,
        segments=tuple(segments),
    )
```

- [ ] **Step 2: Write the failing tests**

`tests/unit/test_models.py`:

```python
"""Tests for the shared data types."""

from __future__ import annotations

import dataclasses

import pytest

from tests.helpers.builders import VIDEO, make_track, make_transcript
from utmax.models import Segment, Track, TrackList, Transcript, Word


def test_segment_end_and_video_url() -> None:
    assert Segment(1.5, 2.25, "hi").end == 3.75
    assert VIDEO.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_segments_can_carry_word_timings() -> None:
    segment = Segment(0.0, 1.0, "hello world", (Word("hello", 0.0), Word("world", 0.5)))
    assert [word.text for word in segment.words] == ["hello", "world"]


def test_models_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        VIDEO.title = "changed"  # type: ignore[misc]


def test_transcript_behaves_like_a_sequence_of_segments() -> None:
    first, second = Segment(0.0, 1.0, "a"), Segment(1.0, 1.0, "b")
    transcript = make_transcript(first, second)
    assert len(transcript) == 2
    assert transcript[0] is first
    assert transcript[-1] is second
    assert transcript[0:1] == (first,)
    assert list(transcript) == [first, second]
    assert second in transcript


def test_text_collapses_whitespace_and_skips_empty_segments() -> None:
    transcript = make_transcript(
        Segment(0, 1, "  hello\nworld "), Segment(1, 1, "   "), Segment(2, 1, "again")
    )
    assert transcript.text == "hello world again"


def test_is_bilingual_and_to_dicts() -> None:
    bilingual = make_transcript(Segment(0.0, 1.5, "hi"), language_code="en+tr")
    assert bilingual.is_bilingual
    assert not make_transcript().is_bilingual
    assert bilingual.to_dicts() == [{"text": "hi", "start": 0.0, "duration": 1.5}]


def test_transcript_equality_ignores_source() -> None:
    base = make_transcript(Segment(0, 1, "a"))
    with_source = dataclasses.replace(base, source=make_transcript(Segment(0, 1, "b")))
    assert base == with_source


class RecordingFetcher:
    def __init__(self) -> None:
        self.calls: list[tuple[Track, bool]] = []

    def fetch_track(self, track: Track, *, preserve_formatting: bool) -> Transcript:
        self.calls.append((track, preserve_formatting))
        return make_transcript(Segment(0, 1, "fetched"))


def test_track_fetch_delegates_to_its_fetcher() -> None:
    fetcher = RecordingFetcher()
    track = make_track("de-DE", fetcher=fetcher)
    assert track.fetch(preserve_formatting=True).text == "fetched"
    assert fetcher.calls == [(track, True)]
    assert track.video_id == "dQw4w9WgXcQ"


def test_unbound_track_cannot_fetch() -> None:
    with pytest.raises(RuntimeError, match="not bound"):
        make_track().fetch()


def test_track_equality_ignores_private_fields() -> None:
    assert make_track(url="https://a.example") == make_track(url="https://b.example")
    assert "https://" not in repr(make_track())


def test_track_list_is_a_sequence_with_filters() -> None:
    manual, auto = make_track("en"), make_track("en", generated=True)
    tracks = TrackList(video=VIDEO, tracks=(manual, auto))
    assert len(tracks) == 2
    assert tracks[1] is auto
    assert tracks[:1] == (manual,)
    assert list(tracks) == [manual, auto]
    assert tracks.manual == (manual,)
    assert tracks.generated == (auto,)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'utmax.models'`.

- [ ] **Step 4: Implement `src/utmax/models.py`**

```python
"""Immutable data types shared by every layer of utmax.

``models`` is the shared data kernel: ``utmax.core`` imports it, so this module imports
``utmax.core`` only inside methods (never at module level) to avoid import cycles.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, overload

__all__ = [
    "FormatName",
    "Language",
    "Segment",
    "Track",
    "TrackFetcher",
    "TrackList",
    "Transcript",
    "VideoInfo",
    "Word",
]

FormatName = Literal["txt", "srt", "vtt", "json", "pretty"]


@dataclass(frozen=True, slots=True)
class Word:
    """One timed word of an auto-generated track."""

    text: str
    start: float


@dataclass(frozen=True, slots=True)
class Segment:
    """One caption cue: ``text`` shown from ``start`` for ``duration`` seconds."""

    start: float
    duration: float
    text: str
    words: tuple[Word, ...] = ()

    @property
    def end(self) -> float:
        """When the cue disappears, in seconds."""
        return self.start + self.duration


@dataclass(frozen=True, slots=True)
class VideoInfo:
    """Basic facts about a video."""

    video_id: str
    title: str
    channel: str
    channel_id: str
    duration: float
    is_live_content: bool

    @property
    def url(self) -> str:
        """The canonical watch URL."""
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass(frozen=True, slots=True)
class Language:
    """A language YouTube can translate a track into."""

    code: str
    name: str


class TrackFetcher(Protocol):
    """Downloads a track; implemented by the transcripts service."""

    def fetch_track(self, track: Track, *, preserve_formatting: bool) -> Transcript: ...


@dataclass(frozen=True, slots=True)
class Track:
    """One subtitle track of a video, as listed by YouTube."""

    video: VideoInfo
    language_code: str
    language: str
    is_generated: bool
    is_translatable: bool
    vss_id: str = ""
    translation_of: str | None = None
    _url: str = field(default="", repr=False, compare=False)
    _translation_languages: tuple[Language, ...] = field(default=(), repr=False, compare=False)
    _fetcher: TrackFetcher | None = field(default=None, repr=False, compare=False)

    @property
    def video_id(self) -> str:
        """The ID of the video this track belongs to."""
        return self.video.video_id

    def fetch(self, *, preserve_formatting: bool = False) -> Transcript:
        """Download this track.

        Args:
            preserve_formatting: keep ``<b>``, ``<i>`` and ``<u>`` tags instead of plain text.
        """
        if self._fetcher is None:
            raise RuntimeError(
                "This Track is not bound to a client; get tracks from utmax.list_tracks()."
            )
        return self._fetcher.fetch_track(self, preserve_formatting=preserve_formatting)


@dataclass(frozen=True, slots=True)
class TrackList(Sequence[Track]):
    """All subtitle tracks of a video, in YouTube's order."""

    video: VideoInfo
    tracks: tuple[Track, ...]
    translation_languages: tuple[Language, ...] = ()

    @overload
    def __getitem__(self, index: int) -> Track: ...
    @overload
    def __getitem__(self, index: slice) -> tuple[Track, ...]: ...
    def __getitem__(self, index: int | slice) -> Track | tuple[Track, ...]:
        return self.tracks[index]

    def __len__(self) -> int:
        return len(self.tracks)

    def __iter__(self) -> Iterator[Track]:
        return iter(self.tracks)

    @property
    def manual(self) -> tuple[Track, ...]:
        """Tracks written by people."""
        return tuple(track for track in self.tracks if not track.is_generated)

    @property
    def generated(self) -> tuple[Track, ...]:
        """Tracks produced by YouTube's speech recognition."""
        return tuple(track for track in self.tracks if track.is_generated)


@dataclass(frozen=True, slots=True)
class Transcript(Sequence[Segment]):
    """A timed transcript: the segments of one track, or of a translation of one."""

    video: VideoInfo
    language_code: str
    language: str
    is_generated: bool
    segments: tuple[Segment, ...]
    translated_from: str | None = None
    translator: str | None = None
    source: Transcript | None = field(default=None, repr=False, compare=False)

    @overload
    def __getitem__(self, index: int) -> Segment: ...
    @overload
    def __getitem__(self, index: slice) -> tuple[Segment, ...]: ...
    def __getitem__(self, index: int | slice) -> Segment | tuple[Segment, ...]:
        return self.segments[index]

    def __len__(self) -> int:
        return len(self.segments)

    def __iter__(self) -> Iterator[Segment]:
        return iter(self.segments)

    @property
    def text(self) -> str:
        """All text, whitespace-collapsed and joined with single spaces."""
        return " ".join(
            " ".join(segment.text.split()) for segment in self.segments if segment.text.strip()
        )

    @property
    def is_bilingual(self) -> bool:
        """True for bilingual transcripts such as ``en+tr``."""
        return "+" in self.language_code

    def to_dicts(self) -> list[dict[str, str | float]]:
        """``[{"text", "start", "duration"}, ...]`` like youtube-transcript-api's ``to_raw_data()``."""
        return [
            {"text": segment.text, "start": segment.start, "duration": segment.duration}
            for segment in self.segments
        ]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: 12 passed.

- [ ] **Step 6: Gates and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: clean.

```bash
git add src/utmax/models.py tests/helpers tests/unit/test_models.py
git commit -m "feat: add the immutable data models

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Video ID parsing

**Files:**
- Create: `src/utmax/core/ids.py`
- Test: `tests/unit/core/__init__.py`, `tests/unit/core/test_ids.py`

**Interfaces:**
- Consumes: `utmax.errors.InvalidVideoId`.
- Produces: `utmax.core.ids.parse_video_id(value: str) -> str` (raises `InvalidVideoId`; never touches the network).

- [ ] **Step 1: Write the failing tests** (Review Focus #2)

`tests/unit/core/__init__.py`:

```python
"""Tests for the pure core."""
```

`tests/unit/core/test_ids.py`:

```python
"""Tests for video ID extraction."""

from __future__ import annotations

import pytest

from utmax.core.ids import parse_video_id
from utmax.errors import InvalidVideoId

ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "value",
    [
        ID,
        f"  {ID}\n",
        f"https://www.youtube.com/watch?v={ID}",
        f"https://www.youtube.com/watch?feature=share&v={ID}&t=42s",
        f"https://www.youtube.com/watch?v={ID}&list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI&index=2",
        f"http://youtube.com/watch?v={ID}",
        f"youtube.com/watch?v={ID}",
        f"HTTPS://WWW.YOUTUBE.COM/watch?v={ID}",
        f"https://m.youtube.com/watch?v={ID}",
        f"https://music.youtube.com/watch?v={ID}&feature=share",
        f"https://www.youtube.com/watch/?v={ID}",
        f"https://www.youtube.com/?v={ID}",
        f"https://youtu.be/{ID}",
        f"https://youtu.be/{ID}?si=Ab12Cd34&t=10",
        f"youtu.be/{ID}",
        f"https://www.youtube.com/shorts/{ID}?feature=share",
        f"https://www.youtube.com/shorts/{ID}/",
        f"https://www.youtube.com/live/{ID}?si=x",
        f"https://www.youtube.com/embed/{ID}?start=30",
        f"https://www.youtube-nocookie.com/embed/{ID}",
        f"https://www.youtube.com/v/{ID}",
    ],
)
def test_accepts_ids_and_every_common_url_shape(value: str) -> None:
    assert parse_video_id(value) == ID


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "not a video",
        ID[:-1],
        f"{ID}Q",
        "https://vimeo.com/123456789",
        "https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI",
        "https://www.youtube.com/@RickAstleyYT",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/",
        "https://youtu.be/",
        f"https://evil.example/watch?v={ID}",
        f"https://youtube.com.evil.example/watch?v={ID}",
        "http://[::1",
    ],
)
def test_rejects_anything_without_a_video_id(value: str) -> None:
    with pytest.raises(InvalidVideoId) as caught:
        parse_video_id(value)
    assert repr(value) in str(caught.value)
    assert "11-character" in caught.value.suggestion
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_ids.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'utmax.core.ids'`.

- [ ] **Step 3: Implement `src/utmax/core/ids.py`**

```python
"""Extract the 11-character video ID from anything a user might paste."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from utmax.errors import InvalidVideoId

__all__ = ["parse_video_id"]

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_WATCH_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }
)
_SHORT_HOSTS = frozenset({"youtu.be", "www.youtu.be"})
_ID_PATH_PREFIXES = frozenset({"shorts", "live", "embed", "v", "e"})


def parse_video_id(value: str) -> str:
    """Return the video ID in ``value``: a bare ID or any common YouTube URL.

    Raises:
        InvalidVideoId: if no video ID can be found. No network request is ever made.
    """
    text = value.strip()
    if _VIDEO_ID.fullmatch(text):
        return text
    candidate = _id_from_url(text)
    if candidate is None:
        raise InvalidVideoId(f"Could not find a YouTube video ID in {value!r}.")
    return candidate


def _id_from_url(text: str) -> str | None:
    if not text:
        return None
    if "://" not in text:
        text = f"https://{text}"
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    segments = [segment for segment in parts.path.split("/") if segment]
    if host in _SHORT_HOSTS:
        candidate = segments[0] if segments else ""
    elif host in _WATCH_HOSTS:
        if len(segments) > 1 and segments[0].lower() in _ID_PATH_PREFIXES:
            candidate = segments[1]
        elif not segments or segments[0].lower() == "watch":
            candidate = parse_qs(parts.query).get("v", [""])[0]
        else:
            return None
    else:
        return None
    return candidate if _VIDEO_ID.fullmatch(candidate) else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_ids.py -v`
Expected: 35 passed.

- [ ] **Step 5: Gates and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: clean; the architecture test still passes (`urllib.parse` is allowed).

```bash
git add src/utmax/core/ids.py tests/unit/core
git commit -m "feat: parse video IDs from IDs and YouTube URLs

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Output formats and atomic saving

**Files:**
- Create: `src/utmax/core/formats.py`, `src/utmax/adapters/__init__.py`, `src/utmax/adapters/files.py`
- Modify: `src/utmax/models.py` (imports; `Transcript.to`, `to_srt`, `to_vtt`, `to_json`, `to_text`, `to_pretty`, `save`)
- Test: `tests/unit/core/test_formats.py`, `tests/unit/adapters/__init__.py`, `tests/unit/adapters/test_files.py`, `tests/unit/test_transcript_output.py`

**Interfaces:**
- Consumes: `Segment`, `Transcript`, `FormatName` (Task 3); `UnsupportedFormat` (Task 2).
- Produces:
  - `utmax.core.formats`: `FORMATS: tuple[FormatName, ...]`, `EXTENSIONS: dict[str, FormatName]`, `format_for_path(path: str | PathLike[str], explicit: str | None = None) -> FormatName`, `render(transcript: Transcript, fmt: str) -> str`, `to_srt(segments) -> str`, `to_vtt(segments) -> str`, `to_json(transcript, *, indent: int | None = 2) -> str`, `to_text(segments, *, separator=" ") -> str`, `to_pretty(segments) -> str`. Every renderer returns text ending in `\n` (or `""` when there is nothing to show).
  - `utmax.adapters.files`: `write_text_atomic(path, text) -> Path`, `replace_with_retry(source, target, *, replace=os.replace, sleep=time.sleep) -> None`, `REPLACE_RETRY_DELAYS`.
  - `Transcript.to(format)`, `.to_srt()`, `.to_vtt()`, `.to_json(*, indent=2)`, `.to_text(*, separator=" ")`, `.to_pretty()`, `.save(path, format=None) -> Path`.

- [ ] **Step 1: Write the failing format tests** (Review Focus #5)

`tests/unit/core/test_formats.py`:

```python
"""Tests for the transcript renderers."""

from __future__ import annotations

import json

import pytest

from tests.helpers.builders import make_transcript
from utmax.core.formats import (
    EXTENSIONS,
    FORMATS,
    format_for_path,
    render,
    to_json,
    to_pretty,
    to_srt,
    to_text,
    to_vtt,
)
from utmax.errors import UnsupportedFormat
from utmax.models import Segment

SEGMENTS = (
    Segment(1.36, 1.68, "[♪♪♪]"),
    Segment(18.64, 3.24, "♪ We're no strangers to love ♪"),
    Segment(22.64, 4.32, "♪ You know the rules\nand so do I ♪"),
)


def test_srt_numbers_cues_and_keeps_line_breaks() -> None:
    assert to_srt(SEGMENTS) == (
        "1\n00:00:01,360 --> 00:00:03,040\n[♪♪♪]\n\n"
        "2\n00:00:18,640 --> 00:00:21,880\n♪ We're no strangers to love ♪\n\n"
        "3\n00:00:22,640 --> 00:00:26,960\n♪ You know the rules\nand so do I ♪\n"
    )


def test_overlaps_are_clamped_and_empty_or_zero_length_cues_dropped() -> None:
    segments = (
        Segment(0.0, 5.0, "a"),
        Segment(3.0, 2.0, "b"),
        Segment(4.0, 0.0, "zero"),
        Segment(6.0, 1.0, "   "),
    )
    assert to_srt(segments) == (
        "1\n00:00:00,000 --> 00:00:03,000\na\n\n2\n00:00:03,000 --> 00:00:04,000\nb\n"
    )


def test_cues_are_sorted_by_start() -> None:
    srt = to_srt((Segment(5.0, 1.0, "late"), Segment(1.0, 1.0, "early")))
    assert srt.index("early") < srt.index("late")


def test_long_videos_get_hour_timestamps() -> None:
    assert "01:02:03,500 --> 01:02:04,750" in to_srt((Segment(3723.5, 1.25, "late"),))
    assert "01:02:03.500 --> 01:02:04.750" in to_vtt((Segment(3723.5, 1.25, "late"),))


def test_vtt_escapes_text_but_keeps_basic_styling() -> None:
    vtt = to_vtt((Segment(1.0, 2.0, "a < b & c > d"), Segment(4.0, 1.0, "<i>styled</i> -->")))
    assert vtt == (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\na &lt; b &amp; c &gt; d\n\n"
        "00:00:04.000 --> 00:00:05.000\n<i>styled</i> --&gt;\n"
    )


def test_json_has_metadata_and_keeps_non_ascii_literal() -> None:
    transcript = make_transcript(
        Segment(0.5, 1.0, "♪ Ğüş 日本語"), language_code="tr", language="Turkish"
    )
    text = to_json(transcript)
    assert "♪ Ğüş 日本語" in text
    assert text.endswith("\n")
    data = json.loads(text)
    assert data["video"]["video_id"] == "dQw4w9WgXcQ"
    assert data["video"]["channel"] == "Rick Astley"
    assert (data["language_code"], data["language"], data["is_generated"]) == ("tr", "Turkish", False)
    assert data["translated_from"] is None
    assert data["translator"] is None
    assert data["segments"] == [{"start": 0.5, "duration": 1.0, "text": "♪ Ğüş 日本語"}]


def test_text_joins_segments() -> None:
    segments = (Segment(0, 1, "  hello\nworld "), Segment(1, 1, ""), Segment(2, 1, "again"))
    assert to_text(segments) == "hello world again\n"
    assert to_text(segments, separator="\n") == "hello world\nagain\n"
    assert to_text(()) == ""


def test_pretty_uses_minutes_and_indents_extra_lines() -> None:
    assert to_pretty((Segment(5.2, 1, "first"), Segment(65.9, 1, "second\nline two"))) == (
        "[00:05] first\n[01:05] second\n        line two\n"
    )


def test_pretty_switches_to_hours_past_one_hour() -> None:
    assert to_pretty((Segment(5, 1, "a"), Segment(3725, 1, "b"))) == "[00:00:05] a\n[01:02:05] b\n"
    assert to_pretty(()) == ""


@pytest.mark.parametrize(
    ("name", "expected"),
    [("a.srt", "srt"), ("a.VTT", "vtt"), ("dir/a.json", "json"), ("a.txt", "txt")],
)
def test_format_from_extension(name: str, expected: str) -> None:
    assert format_for_path(name) == expected


def test_explicit_format_wins() -> None:
    assert format_for_path("a.txt", "pretty") == "pretty"


@pytest.mark.parametrize(("path", "explicit"), [("a.docx", None), ("noext", None), ("a.srt", "doc")])
def test_unknown_formats_raise(path: str, explicit: str | None) -> None:
    with pytest.raises(UnsupportedFormat):
        format_for_path(path, explicit)


def test_render_dispatches_every_format() -> None:
    transcript = make_transcript(*SEGMENTS)
    assert render(transcript, "srt") == to_srt(SEGMENTS)
    assert render(transcript, "vtt") == to_vtt(SEGMENTS)
    assert render(transcript, "json") == to_json(transcript)
    assert render(transcript, "txt") == to_text(SEGMENTS)
    assert render(transcript, "pretty") == to_pretty(SEGMENTS)
    assert set(FORMATS) == {"srt", "vtt", "json", "txt", "pretty"}
    assert EXTENSIONS[".srt"] == "srt"
```

- [ ] **Step 2: Write the failing file and save tests** (Review Focus #1)

`tests/unit/adapters/__init__.py`:

```python
"""Tests for the I/O adapters."""
```

`tests/unit/adapters/test_files.py`:

```python
"""Tests for atomic file writes."""

from __future__ import annotations

from pathlib import Path

import pytest

from utmax.adapters import files
from utmax.adapters.files import REPLACE_RETRY_DELAYS, replace_with_retry, write_text_atomic


def test_writes_utf8_with_lf_and_creates_parent_directories(tmp_path: Path) -> None:
    path = write_text_atomic(tmp_path / "sub" / "out.txt", "a\nb ♪\n")
    assert path == tmp_path / "sub" / "out.txt"
    assert path.read_bytes() == "a\nb ♪\n".encode()
    assert [child.name for child in path.parent.iterdir()] == ["out.txt"]


def test_replaces_existing_files(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("old", encoding="utf-8")
    write_text_atomic(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_failed_writes_leave_no_temporary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(source: Path, target: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(files, "replace_with_retry", broken)
    with pytest.raises(OSError, match="disk full"):
        write_text_atomic(tmp_path / "out.txt", "x")
    assert list(tmp_path.iterdir()) == []


def test_replace_waits_out_transient_locks(tmp_path: Path) -> None:
    attempts: list[Path] = []

    def flaky(source: Path, target: Path) -> None:
        attempts.append(source)
        if len(attempts) < 3:
            raise PermissionError("locked")

    sleeps: list[float] = []
    replace_with_retry(tmp_path / "a", tmp_path / "b", replace=flaky, sleep=sleeps.append)
    assert len(attempts) == 3
    assert sleeps == [0.1, 0.2]


def test_replace_gives_up_after_the_last_delay(tmp_path: Path) -> None:
    def locked(source: Path, target: Path) -> None:
        raise PermissionError("locked")

    sleeps: list[float] = []
    with pytest.raises(PermissionError):
        replace_with_retry(tmp_path / "a", tmp_path / "b", replace=locked, sleep=sleeps.append)
    assert sleeps == list(REPLACE_RETRY_DELAYS)
```

`tests/unit/test_transcript_output.py`:

```python
"""Tests for Transcript rendering and saving."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.builders import make_transcript
from utmax.errors import UnsupportedFormat
from utmax.models import Segment

NASTY = "♪ Ğüşiöç 日本語 😀"


@pytest.mark.parametrize(
    ("name", "fmt"), [("t.srt", "srt"), ("t.vtt", "vtt"), ("t.json", "json"), ("t.txt", "txt")]
)
def test_save_writes_utf8_without_bom_and_lf_only(tmp_path: Path, name: str, fmt: str) -> None:
    transcript = make_transcript(Segment(0, 1, NASTY), Segment(1, 1, "line one\nline two"))
    path = transcript.save(tmp_path / name)
    data = path.read_bytes()
    assert data.decode("utf-8") == transcript.to(fmt)  # type: ignore[arg-type]
    assert NASTY.encode() in data
    assert b"\r\n" not in data
    assert not data.startswith(b"\xef\xbb\xbf")


def test_save_accepts_str_paths_and_explicit_formats(tmp_path: Path) -> None:
    path = make_transcript(Segment(5, 1, "hello")).save(str(tmp_path / "notes.txt"), format="pretty")
    assert isinstance(path, Path)
    assert path.read_text(encoding="utf-8") == "[00:05] hello\n"


def test_save_rejects_unknown_extensions_without_writing(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedFormat):
        make_transcript().save(tmp_path / "t.docx")
    assert list(tmp_path.iterdir()) == []


def test_to_methods_match_the_renderers() -> None:
    transcript = make_transcript(Segment(0, 1, "a"))
    assert transcript.to_srt() == transcript.to("srt")
    assert transcript.to_vtt() == transcript.to("vtt")
    assert transcript.to_json() == transcript.to("json")
    assert transcript.to_json(indent=None).count("\n") == 1
    assert transcript.to_text(separator="|") == "a\n"
    assert transcript.to_pretty() == transcript.to("pretty")
    with pytest.raises(UnsupportedFormat):
        transcript.to("docx")  # type: ignore[arg-type]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_formats.py tests/unit/adapters/test_files.py tests/unit/test_transcript_output.py -v`
Expected: collection errors (`No module named 'utmax.core.formats'`, `No module named 'utmax.adapters'`) and `AttributeError: 'Transcript' object has no attribute 'save'`.

- [ ] **Step 4: Implement `src/utmax/core/formats.py`**

```python
"""Render transcripts as SRT, WebVTT, JSON, plain text or timestamped ("pretty") text."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from os import PathLike
from pathlib import PurePath
from typing import cast

from utmax.errors import UnsupportedFormat
from utmax.models import FormatName, Segment, Transcript

__all__ = [
    "EXTENSIONS",
    "FORMATS",
    "format_for_path",
    "render",
    "to_json",
    "to_pretty",
    "to_srt",
    "to_text",
    "to_vtt",
]

FORMATS: tuple[FormatName, ...] = ("srt", "vtt", "json", "txt", "pretty")
EXTENSIONS: dict[str, FormatName] = {".srt": "srt", ".vtt": "vtt", ".json": "json", ".txt": "txt"}

_ALLOWED_VTT_TAG = re.compile(r"&lt;(/?)([biu])&gt;")


@dataclass(frozen=True, slots=True)
class _Cue:
    start_ms: int
    end_ms: int
    text: str


def format_for_path(path: str | PathLike[str], explicit: str | None = None) -> FormatName:
    """Pick the output format: ``explicit`` wins, otherwise the file extension decides."""
    if explicit is not None:
        if explicit not in FORMATS:
            raise UnsupportedFormat(
                f"Unknown format {explicit!r}; choose one of: {', '.join(FORMATS)}."
            )
        return cast(FormatName, explicit)
    pure = PurePath(path)
    fmt = EXTENSIONS.get(pure.suffix.lower())
    if fmt is None:
        raise UnsupportedFormat(f"Cannot tell the subtitle format from the file name {pure.name!r}.")
    return fmt


def render(transcript: Transcript, fmt: str) -> str:
    """Render ``transcript`` in ``fmt``, one of :data:`FORMATS`."""
    name = format_for_path("", fmt)
    if name == "json":
        return to_json(transcript)
    return _SEGMENT_RENDERERS[name](transcript.segments)


def to_srt(segments: Sequence[Segment]) -> str:
    """SubRip: numbered cues with ``HH:MM:SS,mmm`` times."""
    blocks = [
        f"{index}\n{_clock(cue.start_ms, ',')} --> {_clock(cue.end_ms, ',')}\n{cue.text}\n"
        for index, cue in enumerate(_cues(segments), start=1)
    ]
    return "\n".join(blocks)


def to_vtt(segments: Sequence[Segment]) -> str:
    """WebVTT with escaped text; ``<b>``, ``<i>`` and ``<u>`` tags survive."""
    blocks = [
        f"{_clock(cue.start_ms, '.')} --> {_clock(cue.end_ms, '.')}\n{_vtt_text(cue.text)}\n"
        for cue in _cues(segments)
    ]
    return "WEBVTT\n\n" + "\n".join(blocks)


def to_json(transcript: Transcript, *, indent: int | None = 2) -> str:
    """JSON with the video, language and translation metadata plus every segment."""
    video = transcript.video
    payload = {
        "video": {
            "video_id": video.video_id,
            "title": video.title,
            "channel": video.channel,
            "channel_id": video.channel_id,
            "duration": video.duration,
            "is_live_content": video.is_live_content,
        },
        "language_code": transcript.language_code,
        "language": transcript.language,
        "is_generated": transcript.is_generated,
        "translated_from": transcript.translated_from,
        "translator": transcript.translator,
        "segments": [
            {"start": segment.start, "duration": segment.duration, "text": segment.text}
            for segment in transcript.segments
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=indent) + "\n"


def to_text(segments: Sequence[Segment], *, separator: str = " ") -> str:
    """Plain text: each segment whitespace-collapsed, joined by ``separator``."""
    parts = [" ".join(segment.text.split()) for segment in segments if segment.text.strip()]
    return separator.join(parts) + "\n" if parts else ""


def to_pretty(segments: Sequence[Segment]) -> str:
    """One ``[MM:SS] text`` line per segment; ``[HH:MM:SS]`` once the video passes an hour."""
    visible = [segment for segment in segments if segment.text.strip()]
    if not visible:
        return ""
    with_hours = max(segment.start for segment in visible) >= 3600
    lines: list[str] = []
    for segment in visible:
        stamp = _stamp(segment.start, with_hours=with_hours)
        text_lines = _lines(segment.text)
        lines.append(f"{stamp} {text_lines[0]}")
        indent = " " * (len(stamp) + 1)
        lines.extend(f"{indent}{line}" for line in text_lines[1:])
    return "\n".join(lines) + "\n"


def _cues(segments: Sequence[Segment]) -> list[_Cue]:
    timed = sorted(
        (
            (round(segment.start * 1000), round(segment.duration * 1000), "\n".join(_lines(segment.text)))
            for segment in segments
            if segment.text.strip()
        ),
        key=lambda item: item[0],
    )
    cues: list[_Cue] = []
    for index, (start, duration, text) in enumerate(timed):
        end = start + duration
        if index + 1 < len(timed):
            end = min(end, timed[index + 1][0])
        if end > start:
            cues.append(_Cue(start, end, text))
    return cues


def _lines(text: str) -> list[str]:
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def _clock(milliseconds: int, separator: str) -> str:
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def _stamp(seconds: float, *, with_hours: bool) -> str:
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if with_hours:
        return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"
    return f"[{minutes:02d}:{secs:02d}]"


def _vtt_text(text: str) -> str:
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _ALLOWED_VTT_TAG.sub(r"<\1\2>", escaped)


_SEGMENT_RENDERERS: dict[str, Callable[[Sequence[Segment]], str]] = {
    "srt": to_srt,
    "vtt": to_vtt,
    "txt": to_text,
    "pretty": to_pretty,
}
```

- [ ] **Step 5: Implement the file adapter**

`src/utmax/adapters/__init__.py`:

```python
"""Adapters: every piece of I/O utmax performs (network, files) lives in this package."""
```

`src/utmax/adapters/files.py`:

```python
"""Filesystem helpers: atomic text writes that tolerate Windows file locks."""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Callable
from pathlib import Path

__all__ = ["REPLACE_RETRY_DELAYS", "replace_with_retry", "write_text_atomic"]

REPLACE_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.6, 3.2)


def write_text_atomic(path: str | os.PathLike[str], text: str) -> Path:
    """Write ``text`` as UTF-8 with ``\\n`` newlines; readers never see a half-written file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def replace_with_retry(
    source: Path,
    target: Path,
    *,
    replace: Callable[[Path, Path], None] = os.replace,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """``os.replace`` that retries while antivirus or indexers briefly hold the file (Windows)."""
    for delay in REPLACE_RETRY_DELAYS:
        try:
            replace(source, target)
        except PermissionError:
            sleep(delay)
        else:
            return
    replace(source, target)
```

- [ ] **Step 6: Add the output methods to `Transcript`**

In `src/utmax/models.py`, replace the import block

```python
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, overload
```

with

```python
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, overload
```

and append these methods to `class Transcript`, directly after `to_dicts`:

```python
    def to(self, format: FormatName) -> str:
        """Render as ``"srt"``, ``"vtt"``, ``"json"``, ``"txt"`` or ``"pretty"``."""
        from utmax.core.formats import render

        return render(self, format)

    def to_srt(self) -> str:
        """SubRip text."""
        from utmax.core.formats import to_srt

        return to_srt(self.segments)

    def to_vtt(self) -> str:
        """WebVTT text."""
        from utmax.core.formats import to_vtt

        return to_vtt(self.segments)

    def to_json(self, *, indent: int | None = 2) -> str:
        """JSON with the metadata and every segment."""
        from utmax.core.formats import to_json

        return to_json(self, indent=indent)

    def to_text(self, *, separator: str = " ") -> str:
        """Plain text, segments joined by ``separator``."""
        from utmax.core.formats import to_text

        return to_text(self.segments, separator=separator)

    def to_pretty(self) -> str:
        """``[MM:SS] text`` lines (``[HH:MM:SS]`` for videos longer than an hour)."""
        from utmax.core.formats import to_pretty

        return to_pretty(self.segments)

    def save(self, path: str | os.PathLike[str], format: FormatName | None = None) -> Path:
        """Write the transcript to ``path``; the extension picks the format unless ``format`` is set.

        Works the same for originals, translations and bilingual transcripts. The file is UTF-8
        with ``\\n`` line endings and is replaced atomically.
        """
        from utmax.adapters.files import write_text_atomic
        from utmax.core.formats import format_for_path, render

        return write_text_atomic(path, render(self, format_for_path(path, format)))
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_formats.py tests/unit/adapters/test_files.py tests/unit/test_transcript_output.py -v`
Expected: all PASS (18 + 5 + 7).

- [ ] **Step 8: Gates and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: clean, whole suite passes.

```bash
git add src/utmax/core/formats.py src/utmax/adapters src/utmax/models.py tests/unit
git commit -m "feat: render transcripts as srt, vtt, json, txt and pretty text and save them atomically

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Sentence merging and the shared protocol data

**Files:**
- Create: `src/utmax/core/translate/__init__.py`, `src/utmax/core/translate/protocol.py`, `src/utmax/core/translate/data/protocol.json`, `src/utmax/core/segmentation.py`
- Modify: `src/utmax/models.py` (imports; `Transcript.merge_sentences`)
- Test: `tests/unit/core/test_segmentation.py`

**Interfaces:**
- Consumes: `Segment`, `Word`, `Transcript` (Task 3).
- Produces:
  - `utmax.core.translate.protocol.SegmentationRules(terminal_punctuation: str, closing_characters: str, max_gap_seconds: float, max_duration_seconds: float, max_characters: int)` and `segmentation_rules() -> SegmentationRules` (cached, read from `data/protocol.json`).
  - `utmax.core.segmentation.merge_sentences(segments: Sequence[Segment], rules: SegmentationRules | None = None) -> tuple[Segment, ...]`.
  - `Transcript.merge_sentences() -> Transcript` (same metadata, merged segments, `source=None`).
- M2 extends `protocol.json` and `protocol.py` with the translation protocol; the future browser extension reads the same file.

- [ ] **Step 1: Write the failing tests**

`tests/unit/core/test_segmentation.py`:

```python
"""Tests for merge_sentences."""

from __future__ import annotations

import pytest

from tests.helpers.builders import make_transcript
from utmax.core.segmentation import merge_sentences
from utmax.core.translate.protocol import SegmentationRules, segmentation_rules
from utmax.models import Segment, Word


def asr(end: float, *words: tuple[str, float]) -> Segment:
    """An auto-generated segment whose words start at the given times and which ends at ``end``."""
    start = words[0][1]
    return Segment(
        start=start,
        duration=end - start,
        text=" ".join(text for text, _ in words),
        words=tuple(Word(text, at) for text, at in words),
    )


def texts(segments: tuple[Segment, ...]) -> list[str]:
    return [segment.text for segment in segments]


def test_protocol_file_provides_the_default_rules() -> None:
    rules = segmentation_rules()
    assert rules.terminal_punctuation == ".!?…。！？"
    assert (rules.max_gap_seconds, rules.max_duration_seconds, rules.max_characters) == (1.0, 7.0, 100)
    assert '"' in rules.closing_characters


def test_sentence_punctuation_closes_cues_using_word_timings() -> None:
    merged = merge_sentences(
        (asr(1.2, ("Hello", 0.0), ("world.", 0.4), ("How", 0.8)), asr(2.0, ("are", 1.2), ("you?", 1.5)))
    )
    assert texts(merged) == ["Hello world.", "How are you?"]
    assert (merged[0].start, merged[0].end) == pytest.approx((0.0, 0.8))
    assert (merged[1].start, merged[1].end) == pytest.approx((0.8, 2.0))
    assert [word.text for word in merged[1].words] == ["How", "are", "you?"]


def test_a_long_pause_closes_a_cue() -> None:
    merged = merge_sentences((asr(0.5, ("one", 0.0)), asr(2.5, ("two", 2.0))))
    assert texts(merged) == ["one", "two"]


def test_cues_stop_growing_at_seven_seconds() -> None:
    words = tuple((f"w{i}", float(i)) for i in range(10))
    merged = merge_sentences((asr(10.0, *words),))
    assert texts(merged) == ["w0 w1 w2 w3 w4 w5 w6", "w7 w8 w9"]
    assert (merged[0].start, merged[0].end) == pytest.approx((0.0, 7.0))


def test_cues_stop_growing_at_one_hundred_characters() -> None:
    words = tuple(("abcd", i * 0.1) for i in range(30))
    merged = merge_sentences((asr(3.0, *words),))
    assert len(merged[0].text) == 104
    assert len(merged[0].words) == 21


def test_bracketed_sound_tags_stand_alone() -> None:
    merged = merge_sentences(
        (
            Segment(0.0, 2.0, "[Music]"),
            asr(3.0, ("we're", 2.0), ("no", 2.3)),
            Segment(3.5, 1.0, "[Applause]"),
        )
    )
    assert texts(merged) == ["[Music]", "we're no", "[Applause]"]


def test_rolling_captions_never_overlap_after_merging() -> None:
    merged = merge_sentences((asr(6.0, ("a", 0.0), ("b.", 0.5)), asr(5.0, ("c", 1.0), ("d", 1.5))))
    assert len(merged) == 2
    starts = [segment.start for segment in merged]
    assert starts == sorted(starts)
    for current, following in zip(merged, merged[1:], strict=False):
        assert current.end <= following.start


def test_segments_without_words_are_merged_until_punctuation() -> None:
    merged = merge_sentences((Segment(0, 1, "Hello"), Segment(1, 1, "world."), Segment(2, 1, "Bye")))
    assert texts(merged) == ["Hello world.", "Bye"]
    assert (merged[0].start, merged[0].end) == (0, 2)


def test_closing_quotes_and_cjk_punctuation_end_sentences() -> None:
    merged = merge_sentences(
        (
            Segment(0, 1, 'He said "stop."'),
            Segment(1, 1, "すごい。"),
            Segment(2, 1, "done"),
        )
    )
    assert texts(merged) == ['He said "stop."', "すごい。", "done"]


def test_empty_input_and_blank_segments() -> None:
    assert merge_sentences(()) == ()
    assert merge_sentences((Segment(0, 1, "  "),)) == ()


def test_custom_rules_override_the_defaults() -> None:
    rules = SegmentationRules(".", "", 1.0, 7.0, 5)
    merged = merge_sentences((Segment(0, 1, "abc"), Segment(1, 1, "def"), Segment(2, 1, "g")), rules)
    assert texts(merged) == ["abc def", "g"]


def test_transcript_merge_sentences_keeps_metadata() -> None:
    transcript = make_transcript(
        Segment(0, 1, "Hello"), Segment(1, 1, "world."), language_code="en", is_generated=True
    )
    merged = transcript.merge_sentences()
    assert merged.text == "Hello world."
    assert len(merged) == 1
    assert (merged.video, merged.language_code, merged.is_generated) == (transcript.video, "en", True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_segmentation.py -v`
Expected: collection error `No module named 'utmax.core.segmentation'`.

- [ ] **Step 3: Write the protocol data and loader**

`src/utmax/core/translate/data/protocol.json`:

```json
{
  "version": 1,
  "segmentation": {
    "terminal_punctuation": ".!?…。！？",
    "closing_characters": "\"')]”’»」』",
    "max_gap_seconds": 1.0,
    "max_duration_seconds": 7.0,
    "max_characters": 100
  }
}
```

`src/utmax/core/translate/__init__.py`:

```python
"""Translation building blocks; ``data/`` holds the language-neutral protocol files."""
```

`src/utmax/core/translate/protocol.py`:

```python
"""The language-neutral protocol shared with the future browser extension.

The numbers live in ``data/protocol.json`` so another implementation (the TypeScript extension)
can load exactly the same values. M1 uses only the segmentation rules; M2 adds the translation
protocol.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

__all__ = ["SegmentationRules", "segmentation_rules"]


@dataclass(frozen=True, slots=True)
class SegmentationRules:
    """Thresholds used by :func:`utmax.core.segmentation.merge_sentences`."""

    terminal_punctuation: str
    closing_characters: str
    max_gap_seconds: float
    max_duration_seconds: float
    max_characters: int


@cache
def _protocol() -> dict[str, Any]:
    text = files("utmax.core.translate").joinpath("data", "protocol.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


@cache
def segmentation_rules() -> SegmentationRules:
    """The default segmentation thresholds from ``protocol.json``."""
    raw = _protocol()["segmentation"]
    return SegmentationRules(
        terminal_punctuation=str(raw["terminal_punctuation"]),
        closing_characters=str(raw["closing_characters"]),
        max_gap_seconds=float(raw["max_gap_seconds"]),
        max_duration_seconds=float(raw["max_duration_seconds"]),
        max_characters=int(raw["max_characters"]),
    )
```

- [ ] **Step 4: Implement `src/utmax/core/segmentation.py`**

```python
"""Merge fragmentary auto-generated captions into readable, sentence-sized cues."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from utmax.core.translate.protocol import SegmentationRules, segmentation_rules
from utmax.models import Segment, Word

__all__ = ["merge_sentences"]

_BRACKETED = re.compile(r"\[[^\]]*\]")


@dataclass(frozen=True, slots=True)
class _Unit:
    text: str
    start: float
    end: float
    words: tuple[Word, ...]


def merge_sentences(
    segments: Sequence[Segment], rules: SegmentationRules | None = None
) -> tuple[Segment, ...]:
    """Regroup ``segments`` into cues that end at sentence boundaries.

    Word timings are used when present (auto-generated tracks); otherwise whole segments are the
    units. A cue closes after sentence-ending punctuation, before a pause of at least
    ``max_gap_seconds``, or once it reaches ``max_duration_seconds`` or ``max_characters``.
    Bracketed sound tags such as ``[Music]`` always stand alone, and cues never overlap.
    """
    active = rules or segmentation_rules()
    units = _units(segments)
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    for index, unit in enumerate(units):
        if _BRACKETED.fullmatch(unit.text):
            if current:
                groups.append(current)
                current = []
            groups.append([unit])
            continue
        current.append(unit)
        following = units[index + 1] if index + 1 < len(units) else None
        if _closes(current, following, active):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return tuple(_segment(group) for group in groups)


def _units(segments: Sequence[Segment]) -> list[_Unit]:
    provisional: list[_Unit] = []
    for segment in segments:
        if not segment.text.strip():
            continue
        words = [word for word in segment.words if word.text.strip()]
        if not words:
            text = " ".join(segment.text.split())
            provisional.append(_Unit(text, segment.start, segment.end, ()))
            continue
        for position, word in enumerate(words):
            end = words[position + 1].start if position + 1 < len(words) else segment.end
            text = word.text.strip()
            provisional.append(_Unit(text, word.start, end, (Word(text, word.start),)))
    provisional.sort(key=lambda unit: unit.start)
    units: list[_Unit] = []
    for index, unit in enumerate(provisional):
        end = unit.end
        if index + 1 < len(provisional):
            end = min(end, provisional[index + 1].start)
        units.append(_Unit(unit.text, unit.start, max(end, unit.start), unit.words))
    return units


def _closes(current: list[_Unit], following: _Unit | None, rules: SegmentationRules) -> bool:
    last = current[-1]
    if following is None or _ends_sentence(last.text, rules):
        return True
    return (
        following.start - last.end >= rules.max_gap_seconds
        or last.end - current[0].start >= rules.max_duration_seconds
        or len(" ".join(unit.text for unit in current)) >= rules.max_characters
    )


def _ends_sentence(text: str, rules: SegmentationRules) -> bool:
    body = text.rstrip(rules.closing_characters)
    return bool(body) and body[-1] in rules.terminal_punctuation


def _segment(group: list[_Unit]) -> Segment:
    start = group[0].start
    end = max(unit.end for unit in group)
    return Segment(
        start=start,
        duration=end - start,
        text=" ".join(unit.text for unit in group),
        words=tuple(word for unit in group for word in unit.words),
    )
```

- [ ] **Step 5: Add `Transcript.merge_sentences`**

In `src/utmax/models.py`, change `from dataclasses import dataclass, field` to `from dataclasses import dataclass, field, replace`, then append to `class Transcript`, after `save`:

```python
    def merge_sentences(self) -> Transcript:
        """A copy whose cues are regrouped into sentences (best for auto-generated tracks)."""
        from utmax.core.segmentation import merge_sentences

        return replace(self, segments=merge_sentences(self.segments), source=None)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_segmentation.py -v`
Expected: 12 passed.

- [ ] **Step 7: Check the JSON ships in the wheel, run the gates and commit**

Run: `uv build && uv run --no-project python -c "import glob, zipfile; assert 'utmax/core/translate/data/protocol.json' in zipfile.ZipFile(glob.glob('dist/*.whl')[0]).namelist()"`
Expected: exit code 0.

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: clean.

```bash
git add src/utmax/core/translate src/utmax/core/segmentation.py src/utmax/models.py tests/unit/core/test_segmentation.py
git commit -m "feat: merge auto-generated captions into sentences with shared protocol thresholds

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Caption URLs, json3/XML parsers and YouTube's own translation

**Files:**
- Create: `src/utmax/core/ytdata.py`, `src/utmax/core/captions.py`
- Modify: `src/utmax/models.py` (import errors; `Track.translate`)
- Test: `tests/helpers/youtube.py`, `tests/unit/core/test_ytdata.py`, `tests/unit/core/test_captions.py`, `tests/unit/test_track_translate.py`

**Interfaces:**
- Consumes: `Segment`, `Word`, `Track`, `Language` (Task 3); `PoTokenRequired`, `YouTubeDataUnparsable`, `NotTranslatable`, `TranslationLanguageNotAvailable` (Task 2).
- Produces:
  - `utmax.core.ytdata`: `mapping(value) -> Mapping[str, Any]`, `items(value) -> list[Any]`, `text_of(value) -> str`, `texts_of(value) -> tuple[str, ...]`.
  - `utmax.core.captions`: `set_query_param(url, name, value: str | None) -> str`, `caption_url(base_url, *, fmt: str | None = "json3") -> str`, `check_caption_url(url, *, video_id) -> None`, `parse_json3(data, *, is_generated, preserve_formatting=False) -> tuple[Segment, ...]`, `parse_xml(text, *, is_generated, preserve_formatting=False, video_id=None) -> tuple[Segment, ...]`, `parse_captions(body: bytes, content_type: str, *, is_generated, preserve_formatting=False, video_id=None) -> tuple[Segment, ...]`.
  - `Track.translate(language_code: str) -> Track` (adds `tlang`, sets `translation_of`, `is_generated=True`).
  - Test data in `tests.helpers.youtube`: `VIDEO_ID`, `MANUAL_JSON3`, `ASR_JSON3`, `LEGACY_XML`, `SRV3_ASR_XML`, `json3_payload(*cues)`.
- Rules: auto-generated segments always carry word timings (one word per json3 `seg`/srv3 `<s>`, or the whole text when YouTube gives no word split); manual segments never do.

- [ ] **Step 1: Write the shared YouTube test data**

`tests/helpers/youtube.py`:

```python
"""Real-shaped YouTube payloads for tests (captured 2026-09-27 from dQw4w9WgXcQ, trimmed)."""

from __future__ import annotations

from typing import Any

VIDEO_ID = "dQw4w9WgXcQ"

MANUAL_JSON3: dict[str, Any] = {
    "wireMagic": "pb3",
    "pens": [{}],
    "events": [
        {"tStartMs": 1360, "dDurationMs": 1680, "segs": [{"utf8": "[♪♪♪]"}]},
        {"tStartMs": 18640, "dDurationMs": 3240, "segs": [{"utf8": "♪ We're no strangers to love ♪"}]},
        {"tStartMs": 22640, "dDurationMs": 4320, "segs": [{"utf8": "♪ You know the rules\nand so do I ♪"}]},
    ],
}

ASR_JSON3: dict[str, Any] = {
    "wireMagic": "pb3",
    "events": [
        {"tStartMs": 0, "dDurationMs": 211879, "id": 1, "wpWinPosId": 1, "wsWinStyleId": 1},
        {"tStartMs": 320, "dDurationMs": 14260, "wWinId": 1, "segs": [{"utf8": "[Music]"}]},
        {"tStartMs": 18790, "wWinId": 1, "aAppend": 1, "segs": [{"utf8": "\n"}]},
        {
            "tStartMs": 18800,
            "dDurationMs": 7160,
            "wWinId": 1,
            "segs": [
                {"utf8": "We're", "acAsrConf": 0},
                {"utf8": " no", "tOffsetMs": 239, "acAsrConf": 0},
                {"utf8": " strangers", "tOffsetMs": 559, "acAsrConf": 0},
                {"utf8": " to", "tOffsetMs": 1040, "acAsrConf": 0},
            ],
        },
    ],
}

LEGACY_XML = (
    '<?xml version="1.0" encoding="utf-8" ?><transcript>'
    '<text start="1.36" dur="1.68">[♪♪♪]</text>'
    '<text start="18.64" dur="3.24">♪ We&amp;#39;re no strangers to love ♪</text>'
    '<text start="22.64" dur="4.32">♪ You know the rules\nand so do I ♪</text>'
    "</transcript>"
)

SRV3_ASR_XML = (
    '<?xml version="1.0" encoding="utf-8" ?><timedtext format="3">\n<body>\n'
    '<w t="0" id="1" wp="1" ws="1"/>\n'
    '<p t="320" d="14260" w="1">[Music]</p>\n'
    '<p t="18790" w="1" a="1">\n</p>\n'
    '<p t="18800" d="7160" w="1"><s ac="0">We&#39;re</s><s t="239" ac="0"> no</s>'
    '<s t="559" ac="0"> strangers</s><s t="1040" ac="0"> to</s></p>\n'
    "</body></timedtext>"
)


def json3_payload(*cues: tuple[int, int, str]) -> dict[str, Any]:
    """A minimal manual json3 document built from ``(start_ms, duration_ms, text)`` cues."""
    return {
        "wireMagic": "pb3",
        "pens": [{}],
        "events": [
            {"tStartMs": start, "dDurationMs": duration, "segs": [{"utf8": text}]}
            for start, duration, text in cues
        ],
    }
```

- [ ] **Step 2: Write the failing tests** (Review Focus #4)

`tests/unit/core/test_ytdata.py`:

```python
"""Tests for the defensive JSON readers."""

from __future__ import annotations

from utmax.core.ytdata import items, mapping, text_of, texts_of


def test_mapping_and_items_ignore_wrong_types() -> None:
    assert mapping({"a": 1}) == {"a": 1}
    assert mapping([1]) == {}
    assert items([1, 2]) == [1, 2]
    assert items({"a": 1}) == []


def test_text_objects() -> None:
    assert text_of({"simpleText": "Hello"}) == "Hello"
    assert text_of({"runs": [{"text": "Hel"}, {"text": "lo"}, {"bold": True}]}) == "Hello"
    assert text_of(None) == ""
    assert texts_of({"runs": [{"text": "a"}, {"text": ""}, "junk", {"text": "b"}]}) == ("a", "b")
```

`tests/unit/core/test_captions.py`:

```python
"""Tests for caption URLs and the json3/XML parsers."""

from __future__ import annotations

import json

import pytest

from tests.helpers.youtube import ASR_JSON3, LEGACY_XML, MANUAL_JSON3, SRV3_ASR_XML, VIDEO_ID
from utmax.core.captions import (
    caption_url,
    check_caption_url,
    parse_captions,
    parse_json3,
    parse_xml,
    set_query_param,
)
from utmax.errors import PoTokenRequired, YouTubeDataUnparsable
from utmax.models import Segment, Word

BASE = f"https://www.youtube.com/api/timedtext?v={VIDEO_ID}&lang=en&fmt=srv3"


def test_set_query_param_replaces_adds_and_removes() -> None:
    root = f"https://www.youtube.com/api/timedtext?v={VIDEO_ID}&lang=en"
    assert set_query_param(BASE, "fmt", "json3") == f"{root}&fmt=json3"
    assert set_query_param(BASE, "tlang", "tr") == f"{root}&fmt=srv3&tlang=tr"
    assert set_query_param(BASE, "fmt", None) == root
    assert set_query_param("https://x.youtube.com/a?empty=&k=1", "k", "2") == (
        "https://x.youtube.com/a?empty=&k=2"
    )


def test_caption_url_sets_the_format() -> None:
    assert caption_url(BASE).endswith("&lang=en&fmt=json3")
    assert "fmt=" not in caption_url(BASE, fmt=None)


@pytest.mark.parametrize(
    "url",
    [
        BASE,
        "https://youtube.com/api/timedtext?v=x",
        "https://m.youtube.com/api/timedtext?v=x&exp=abc,def",
    ],
)
def test_youtube_caption_urls_are_accepted(url: str) -> None:
    check_caption_url(url, video_id=VIDEO_ID)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.youtube.com/api/timedtext?v=x",
        "https://evil.example/api/timedtext",
        "https://youtube.com.evil.example/x",
        "https://notyoutube.com/x",
        "not a url",
    ],
)
def test_other_hosts_are_refused(url: str) -> None:
    with pytest.raises(YouTubeDataUnparsable):
        check_caption_url(url, video_id=VIDEO_ID)


@pytest.mark.parametrize("exp", ["xpe", "abc,xpe"])
def test_proof_of_origin_urls_are_refused(exp: str) -> None:
    with pytest.raises(PoTokenRequired):
        check_caption_url(f"{BASE}&exp={exp}", video_id=VIDEO_ID)


def test_manual_json3_keeps_line_breaks_and_has_no_words() -> None:
    assert parse_json3(MANUAL_JSON3, is_generated=False) == (
        Segment(1.36, 1.68, "[♪♪♪]"),
        Segment(18.64, 3.24, "♪ We're no strangers to love ♪"),
        Segment(22.64, 4.32, "♪ You know the rules\nand so do I ♪"),
    )


def test_auto_json3_skips_window_and_newline_events_and_keeps_words() -> None:
    music, words = parse_json3(ASR_JSON3, is_generated=True)
    assert (music.start, music.duration, music.text) == (0.32, 14.26, "[Music]")
    assert music.words == (Word("[Music]", 0.32),)
    assert (words.start, words.text) == (18.8, "We're no strangers to")
    assert [word.text for word in words.words] == ["We're", "no", "strangers", "to"]
    assert [word.start for word in words.words] == pytest.approx([18.8, 19.039, 19.359, 19.84])


def test_json3_formatting_tags_are_optional() -> None:
    styled = {
        "pens": [{}, {"bAttr": 1}, {"iAttr": 1, "uAttr": 1}],
        "events": [
            {
                "tStartMs": 0,
                "dDurationMs": 1000,
                "segs": [
                    {"utf8": "plain "},
                    {"utf8": "bold", "pPenId": 1},
                    {"utf8": " and "},
                    {"utf8": "fancy", "pPenId": 2},
                ],
            }
        ],
    }
    assert parse_json3(styled, is_generated=False)[0].text == "plain bold and fancy"
    assert parse_json3(styled, is_generated=False, preserve_formatting=True)[0].text == (
        "plain <b>bold</b> and <i><u>fancy</u></i>"
    )


def test_json3_entities_are_unescaped_and_odd_shapes_are_ignored() -> None:
    data = {
        "events": [
            {"tStartMs": 0, "dDurationMs": 500, "segs": [{"utf8": "Tom &amp; Jerry"}]},
            "not an event",
            {"segs": "not a list"},
            {"tStartMs": 1000},
        ]
    }
    assert parse_json3(data, is_generated=False) == (Segment(0.0, 0.5, "Tom & Jerry"),)
    assert parse_json3({"events": "nope"}, is_generated=False) == ()


def test_legacy_xml_unescapes_double_escaped_entities() -> None:
    segments = parse_xml(LEGACY_XML, is_generated=False)
    assert [segment.text for segment in segments] == [
        "[♪♪♪]",
        "♪ We're no strangers to love ♪",
        "♪ You know the rules\nand so do I ♪",
    ]
    assert (segments[1].start, segments[1].duration, segments[1].words) == (18.64, 3.24, ())
    assert parse_xml(LEGACY_XML, is_generated=True)[0].words == (Word("[♪♪♪]", 1.36),)


def test_srv3_auto_captions_have_word_timings() -> None:
    music, words = parse_xml(SRV3_ASR_XML, is_generated=True)
    assert (music.text, music.words) == ("[Music]", (Word("[Music]", 0.32),))
    assert words.text == "We're no strangers to"
    assert [word.start for word in words.words] == pytest.approx([18.8, 19.039, 19.359, 19.84])


def test_xml_formatting_tags() -> None:
    xml = (
        '<transcript><text start="0" dur="1">'
        '&lt;i&gt;hi&lt;/i&gt; &lt;font color="red"&gt;x&lt;/font&gt;</text></transcript>'
    )
    assert parse_xml(xml, is_generated=False)[0].text == "hi x"
    assert parse_xml(xml, is_generated=False, preserve_formatting=True)[0].text == "<i>hi</i> x"


@pytest.mark.parametrize(
    "xml", ['<!DOCTYPE x [<!ENTITY a "b">]><transcript/>', "<transcript><text>", "<unknown/>"]
)
def test_unsafe_malformed_or_unknown_xml_is_unparsable(xml: str) -> None:
    with pytest.raises(YouTubeDataUnparsable):
        parse_xml(xml, is_generated=False, video_id=VIDEO_ID)


def test_parse_captions_dispatches_on_content() -> None:
    body = json.dumps(MANUAL_JSON3).encode()
    assert len(parse_captions(body, "application/json; charset=UTF-8", is_generated=False)) == 3
    assert len(parse_captions(body, "text/plain", is_generated=False)) == 3
    assert len(parse_captions(LEGACY_XML.encode(), "text/xml", is_generated=False)) == 3
    assert len(parse_captions(b"\xef\xbb\xbf" + LEGACY_XML.encode(), "", is_generated=False)) == 3


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"   ",
        b"hello",
        b"{oops",
        b"[1, 2]",
        b'{"events": [{"tStartMs": "soon", "segs": [{"utf8": "x"}]}]}',
        b'<transcript><text start="x">a</text></transcript>',
    ],
)
def test_parse_captions_turns_bad_bodies_into_typed_errors(body: bytes) -> None:
    with pytest.raises(YouTubeDataUnparsable):
        parse_captions(body, "", is_generated=False, video_id=VIDEO_ID)


def test_empty_caption_files_suggest_a_proof_of_origin_change() -> None:
    with pytest.raises(YouTubeDataUnparsable) as caught:
        parse_captions(b"", "application/json", is_generated=False)
    assert "proof-of-origin" in caught.value.suggestion


def test_json_captions_must_be_an_object() -> None:
    with pytest.raises(YouTubeDataUnparsable):
        parse_captions(b"[1, 2]", "application/json", is_generated=False)


def test_srv3_without_a_body_has_no_segments() -> None:
    assert parse_xml('<timedtext format="3"/>', is_generated=False) == ()
```

`tests/unit/test_track_translate.py`:

```python
"""Tests for YouTube's own track translation (tlang)."""

from __future__ import annotations

import pytest

from tests.helpers.builders import make_track
from utmax.errors import NotTranslatable, TranslationLanguageNotAvailable
from utmax.models import Language

LANGUAGES = (Language("tr", "Turkish"), Language("de", "German"))


def test_translate_adds_tlang_and_marks_the_track() -> None:
    track = make_track("en", name="English", translation_languages=LANGUAGES)
    translated = track.translate("tr")
    assert (translated.language_code, translated.language) == ("tr", "Turkish")
    assert translated.is_generated
    assert not translated.is_translatable
    assert translated.translation_of == "en"
    assert translated._url.endswith("&tlang=tr")
    assert translated.video == track.video


def test_unknown_translation_languages_are_rejected() -> None:
    with pytest.raises(TranslationLanguageNotAvailable) as caught:
        make_track(translation_languages=LANGUAGES).translate("ko")
    assert caught.value.available == ("tr", "de")


def test_without_a_language_list_translation_is_best_effort() -> None:
    assert make_track().translate("ko").language == "ko"


def test_untranslatable_tracks_raise() -> None:
    with pytest.raises(NotTranslatable):
        make_track(translatable=False).translate("tr")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_ytdata.py tests/unit/core/test_captions.py tests/unit/test_track_translate.py -v`
Expected: collection errors (`No module named 'utmax.core.ytdata'`, `… 'utmax.core.captions'`) and `AttributeError: 'Track' object has no attribute 'translate'`.

- [ ] **Step 4: Implement `src/utmax/core/ytdata.py`**

```python
"""Defensive readers for YouTube's loosely structured JSON."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["items", "mapping", "text_of", "texts_of"]


def mapping(value: object) -> Mapping[str, Any]:
    """``value`` if it is a JSON object, else an empty mapping."""
    return value if isinstance(value, Mapping) else {}


def items(value: object) -> list[Any]:
    """``value`` if it is a JSON array, else an empty list."""
    return value if isinstance(value, list) else []


def text_of(value: object) -> str:
    """Read a YouTube text object: ``{"simpleText": ...}`` or ``{"runs": [{"text": ...}]}``."""
    simple = mapping(value).get("simpleText")
    if isinstance(simple, str):
        return simple
    return "".join(texts_of(value))


def texts_of(value: object) -> tuple[str, ...]:
    """The non-empty ``runs[].text`` strings of a YouTube text object."""
    runs = (mapping(run).get("text") for run in items(mapping(value).get("runs")))
    return tuple(text for text in runs if isinstance(text, str) and text)
```

- [ ] **Step 5: Implement `src/utmax/core/captions.py`**

```python
"""Caption URL handling and parsers for YouTube's json3 and XML timed-text formats."""

from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from utmax.core.ytdata import items, mapping
from utmax.errors import PoTokenRequired, YouTubeDataUnparsable
from utmax.models import Segment, Word

__all__ = [
    "caption_url",
    "check_caption_url",
    "parse_captions",
    "parse_json3",
    "parse_xml",
    "set_query_param",
]

_FORMAT_ATTRIBUTES = (("bAttr", "b"), ("iAttr", "i"), ("uAttr", "u"))
_ANY_TAG = re.compile(r"<[^>]*>")
_NON_FORMAT_TAG = re.compile(r"</?(?!(?:b|i|u|em|strong)\b)[^>]*>", re.IGNORECASE)
_UNSAFE_XML = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)", re.IGNORECASE)


def set_query_param(url: str, name: str, value: str | None) -> str:
    """``url`` with query parameter ``name`` replaced, or removed when ``value`` is None."""
    parts = urlsplit(url)
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True) if key != name]
    if value is not None:
        query.append((name, value))
    return urlunsplit(parts._replace(query=urlencode(query)))


def caption_url(base_url: str, *, fmt: str | None = "json3") -> str:
    """The download URL of a caption track in ``fmt`` (``None`` = YouTube's legacy XML)."""
    return set_query_param(base_url, "fmt", fmt)


def check_caption_url(url: str, *, video_id: str) -> None:
    """Refuse URLs outside youtube.com and ones that need a proof-of-origin token."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not (host == "youtube.com" or host.endswith(".youtube.com")):
        raise YouTubeDataUnparsable(
            f"Refusing to download captions from unexpected host {host or url!r}.",
            video_id=video_id,
        )
    experiments = dict(parse_qsl(parts.query)).get("exp", "")
    if "xpe" in experiments.split(","):
        raise PoTokenRequired(
            "YouTube requires a proof-of-origin token for these captions.", video_id=video_id
        )


def parse_captions(
    body: bytes,
    content_type: str,
    *,
    is_generated: bool,
    preserve_formatting: bool = False,
    video_id: str | None = None,
) -> tuple[Segment, ...]:
    """Parse a caption download, whichever format YouTube answered with."""
    text = body.decode("utf-8", errors="replace").lstrip("﻿").strip()
    if not text:
        raise YouTubeDataUnparsable(
            "YouTube returned an empty caption file.",
            video_id=video_id,
            suggestion=(
                "YouTube may now require a proof-of-origin token or changed its caption "
                "format; please report it with the video ID."
            ),
        )
    try:
        if text.startswith("{") or "json" in content_type.lower():
            data = json.loads(text)
            if not isinstance(data, dict):
                raise YouTubeDataUnparsable(
                    "YouTube returned unexpected caption JSON.", video_id=video_id
                )
            return parse_json3(data, is_generated=is_generated, preserve_formatting=preserve_formatting)
        if text.startswith("<"):
            return parse_xml(
                text,
                is_generated=is_generated,
                preserve_formatting=preserve_formatting,
                video_id=video_id,
            )
    except (TypeError, ValueError) as error:
        raise YouTubeDataUnparsable(
            f"YouTube returned captions utmax could not parse ({error}).", video_id=video_id
        ) from error
    raise YouTubeDataUnparsable("YouTube returned captions in an unknown format.", video_id=video_id)


def parse_json3(
    data: Mapping[str, Any], *, is_generated: bool, preserve_formatting: bool = False
) -> tuple[Segment, ...]:
    """Parse YouTube's ``fmt=json3`` captions."""
    pens = items(data.get("pens"))
    segments: list[Segment] = []
    for event in map(mapping, items(data.get("events"))):
        pieces = [
            (html.unescape(str(seg.get("utf8", ""))), seg)
            for seg in map(mapping, items(event.get("segs")))
        ]
        if not "".join(piece for piece, _ in pieces).strip():
            continue
        start_ms = int(event.get("tStartMs") or 0)
        if preserve_formatting:
            text = "".join(_styled(piece, seg, pens) for piece, seg in pieces)
        else:
            text = "".join(piece for piece, _ in pieces)
        words: tuple[Word, ...] = ()
        if is_generated:
            words = tuple(
                Word(piece.strip(), (start_ms + int(seg.get("tOffsetMs") or 0)) / 1000)
                for piece, seg in pieces
                if piece.strip()
            )
        segments.append(
            Segment(
                start=start_ms / 1000,
                duration=int(event.get("dDurationMs") or 0) / 1000,
                text=_normalize(text, is_generated=is_generated),
                words=words,
            )
        )
    return tuple(segments)


def parse_xml(
    text: str,
    *,
    is_generated: bool,
    preserve_formatting: bool = False,
    video_id: str | None = None,
) -> tuple[Segment, ...]:
    """Parse YouTube's XML captions: ``srv3`` (``<timedtext>``) or legacy (``<transcript>``)."""
    if _UNSAFE_XML.search(text):
        raise YouTubeDataUnparsable(
            "Refusing caption XML that declares a DOCTYPE or entities.", video_id=video_id
        )
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        raise YouTubeDataUnparsable("YouTube returned malformed caption XML.", video_id=video_id) from None
    if root.tag == "timedtext":
        return _parse_srv3(root, is_generated=is_generated, preserve_formatting=preserve_formatting)
    if root.tag == "transcript":
        return _parse_legacy(root, is_generated=is_generated, preserve_formatting=preserve_formatting)
    raise YouTubeDataUnparsable(f"Unknown caption XML root element <{root.tag}>.", video_id=video_id)


def _parse_srv3(
    root: ElementTree.Element, *, is_generated: bool, preserve_formatting: bool
) -> tuple[Segment, ...]:
    body = root.find("body")
    if body is None:
        return ()
    segments: list[Segment] = []
    for paragraph in body.iter("p"):
        raw = "".join(paragraph.itertext())
        text = _xml_text(raw, is_generated=is_generated, preserve_formatting=preserve_formatting)
        if not text:
            continue
        start_ms = int(paragraph.get("t", "0"))
        words: tuple[Word, ...] = ()
        if is_generated:
            spans = [
                (html.unescape(span.text or "").strip(), int(span.get("t", "0")))
                for span in paragraph.findall("s")
            ]
            words = tuple(Word(word, (start_ms + offset) / 1000) for word, offset in spans if word)
            words = words or (Word(text, start_ms / 1000),)
        segments.append(Segment(start_ms / 1000, int(paragraph.get("d", "0")) / 1000, text, words))
    return tuple(segments)


def _parse_legacy(
    root: ElementTree.Element, *, is_generated: bool, preserve_formatting: bool
) -> tuple[Segment, ...]:
    segments: list[Segment] = []
    for element in root.iter("text"):
        text = _xml_text(
            element.text or "", is_generated=is_generated, preserve_formatting=preserve_formatting
        )
        if not text:
            continue
        start = float(element.get("start", "0"))
        words = (Word(text, start),) if is_generated else ()
        segments.append(Segment(start, float(element.get("dur", "0")), text, words))
    return tuple(segments)


def _xml_text(raw: str, *, is_generated: bool, preserve_formatting: bool) -> str:
    text = html.unescape(raw)
    text = (_NON_FORMAT_TAG if preserve_formatting else _ANY_TAG).sub("", text)
    return _normalize(text, is_generated=is_generated)


def _styled(text: str, seg: Mapping[str, Any], pens: list[Any]) -> str:
    pen_id = seg.get("pPenId")
    pen: Mapping[str, Any] = (
        mapping(pens[pen_id]) if isinstance(pen_id, int) and 0 <= pen_id < len(pens) else {}
    )
    tags = [tag for attribute, tag in _FORMAT_ATTRIBUTES if pen.get(attribute)]
    if not tags or not text.strip():
        return text
    opening = "".join(f"<{tag}>" for tag in tags)
    closing = "".join(f"</{tag}>" for tag in reversed(tags))
    return f"{opening}{text}{closing}"


def _normalize(text: str, *, is_generated: bool) -> str:
    if is_generated:
        return " ".join(text.split())
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)
```

- [ ] **Step 6: Add `Track.translate`**

In `src/utmax/models.py`, add below the `typing` import:

```python
from utmax.errors import NotTranslatable, TranslationLanguageNotAvailable
```

and append this method to `class Track`, after `fetch`:

```python
    def translate(self, language_code: str) -> Track:
        """This track machine-translated by YouTube (``tlang``).

        Best effort only: YouTube rate-limits these requests heavily. The track list's
        ``translation_languages`` is checked when YouTube provided one.
        """
        from utmax.core.captions import set_query_param

        if not self.is_translatable:
            raise NotTranslatable(
                f"YouTube cannot translate the {self.language_code} track of {self.video_id}.",
                video_id=self.video_id,
            )
        names = {language.code: language.name for language in self._translation_languages}
        if names and language_code not in names:
            raise TranslationLanguageNotAvailable(
                f"YouTube cannot translate video {self.video_id} into {language_code!r}.",
                available=tuple(names),
                video_id=self.video_id,
            )
        return replace(
            self,
            language_code=language_code,
            language=names.get(language_code, language_code),
            is_generated=True,
            is_translatable=False,
            vss_id="",
            translation_of=self.language_code,
            _url=set_query_param(self._url, "tlang", language_code),
        )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_ytdata.py tests/unit/core/test_captions.py tests/unit/test_track_translate.py -v`
Expected: all PASS.

- [ ] **Step 8: Gates and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: clean.

```bash
git add src/utmax/core/ytdata.py src/utmax/core/captions.py src/utmax/models.py tests/helpers/youtube.py tests/unit
git commit -m "feat: parse json3 and XML captions and support YouTube track translation

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: InnerTube client profiles and player-response parsing

**Files:**
- Create: `src/utmax/core/clients.py`, `src/utmax/core/playability.py`, `src/utmax/core/player.py`
- Modify: `tests/helpers/youtube.py` (append player builders)
- Test: `tests/unit/core/test_clients.py`, `tests/unit/core/test_playability.py`, `tests/unit/core/test_player.py`

**Interfaces:**
- Consumes: `ytdata` helpers (Task 7); `VideoInfo`, `Language` (Task 3); playability errors (Task 2).
- Produces:
  - `utmax.core.clients`: `Purpose = Literal["captions", "streams", "browse", "resolve"]`, `DESKTOP_USER_AGENT: str`, `ClientProfile(name, client_id, version, user_agent, extra=())` with `.context_payload() -> dict[str, Any]` and `.request_headers() -> dict[str, str]`; profiles `ANDROID`, `IOS`, `ANDROID_VR`, `WEB`; `ORDER: Mapping[Purpose, tuple[ClientProfile, ...]]`.
  - `utmax.core.playability`: `Playability(status, reason="", sub_reasons=())`, `parse_playability(player: Mapping[str, Any]) -> Playability`, `check_playability(playability, *, video_id) -> None`.
  - `utmax.core.player`: `CaptionTrackInfo(base_url, language_code, name, is_generated, is_translatable, vss_id)`, `PlayerData(video, playability, caption_tracks: tuple[CaptionTrackInfo, ...] | None, translation_languages)`, `parse_player_response(data, *, video_id) -> PlayerData` (never raises on odd shapes; `caption_tracks` is `None` when there are no usable tracks).
  - Test builders in `tests.helpers.youtube`: `DEFAULT_TRACKS`, `caption_track(code, name, generated, *, video_id=VIDEO_ID)`, `player_payload(**options)`.

- [ ] **Step 1: Append the player builders to `tests/helpers/youtube.py`**

```python
DEFAULT_TRACKS: tuple[tuple[str, str, bool], ...] = (
    ("en", "English", False),
    ("en", "English (auto-generated)", True),
    ("de-DE", "German (Germany)", False),
    ("ja", "Japanese", False),
    ("pt-BR", "Portuguese (Brazil)", False),
    ("es-419", "Spanish (Latin America)", False),
)


def caption_track(code: str, name: str, generated: bool, *, video_id: str = VIDEO_ID) -> dict[str, Any]:
    """One ``captionTracks`` entry shaped like the ANDROID client's."""
    url = f"https://www.youtube.com/api/timedtext?v={video_id}&lang={code}&fmt=srv3"
    track: dict[str, Any] = {
        "baseUrl": url + ("&kind=asr" if generated else ""),
        "name": {"runs": [{"text": name}]},
        "vssId": f"{'a' if generated else ''}.{code}",
        "languageCode": code,
        "isTranslatable": True,
        "trackName": "",
    }
    if generated:
        track["kind"] = "asr"
    return track


def player_payload(
    *,
    video_id: str = VIDEO_ID,
    status: str = "OK",
    reason: str | None = None,
    sub_reasons: tuple[str, ...] = (),
    tracks: tuple[tuple[str, str, bool], ...] = DEFAULT_TRACKS,
    translation_languages: tuple[tuple[str, str], ...] = (("tr", "Turkish"), ("de", "German")),
    captions: bool = True,
    title: str = "Rick Astley - Never Gonna Give You Up (Official Video)",
    author: str = "Rick Astley",
    length_seconds: str = "213",
) -> dict[str, Any]:
    """A ``/player`` response shaped like YouTube's (only the fields utmax reads)."""
    playability: dict[str, Any] = {"status": status}
    if reason is not None:
        playability["reason"] = reason
    if sub_reasons:
        playability["errorScreen"] = {
            "playerErrorMessageRenderer": {"subreason": {"runs": [{"text": s} for s in sub_reasons]}}
        }
    payload: dict[str, Any] = {
        "playabilityStatus": playability,
        "videoDetails": {
            "videoId": video_id,
            "title": title,
            "lengthSeconds": length_seconds,
            "channelId": "UCuAXFkgsw1L7xaCfnd5JJOw",
            "author": author,
            "isLiveContent": False,
        },
    }
    if captions:
        payload["captions"] = {
            "playerCaptionsTracklistRenderer": {
                "captionTracks": [caption_track(c, n, g, video_id=video_id) for c, n, g in tracks],
                "translationLanguages": [
                    {"languageCode": c, "languageName": {"runs": [{"text": n}]}}
                    for c, n in translation_languages
                ],
            }
        }
    return payload
```

- [ ] **Step 2: Write the failing tests** (Review Focus #4)

`tests/unit/core/test_clients.py`:

```python
"""Tests for the InnerTube client profiles."""

from __future__ import annotations

from utmax.core.clients import ANDROID, ANDROID_VR, IOS, ORDER, WEB


def test_context_payload_introduces_the_app_in_english() -> None:
    client = ANDROID.context_payload()["client"]
    assert client["clientName"] == "ANDROID"
    assert client["clientVersion"] == "20.10.38"
    assert client["androidSdkVersion"] == 30
    assert (client["hl"], client["gl"]) == ("en", "US")


def test_request_headers_match_the_profile() -> None:
    headers = ANDROID_VR.request_headers()
    assert headers["X-YouTube-Client-Name"] == "28"
    assert headers["X-YouTube-Client-Version"] == "1.62.27"
    assert headers["User-Agent"].startswith("com.google.android.apps.youtube.vr.oculus/")
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept-Encoding"] == "gzip"


def test_fallback_orders() -> None:
    assert ORDER["captions"] == (ANDROID, IOS, ANDROID_VR)
    assert ORDER["streams"] == (ANDROID_VR, ANDROID, IOS)
    assert ORDER["browse"] == (ANDROID_VR, WEB)
    assert ORDER["resolve"] == (ANDROID_VR, WEB)
    assert len({profile.name for profile in (ANDROID, IOS, ANDROID_VR, WEB)}) == 4
```

`tests/unit/core/test_playability.py`:

```python
"""Tests for the playabilityStatus → error table."""

from __future__ import annotations

from typing import Any

import pytest

from utmax.core.playability import Playability, check_playability, parse_playability
from utmax.errors import (
    AgeRestricted,
    RequestBlocked,
    UTMaxError,
    VideoUnavailable,
    VideoUnplayable,
)


@pytest.mark.parametrize(
    ("status", "error"),
    [
        ({"status": "LOGIN_REQUIRED", "reason": "Sign in to confirm you’re not a bot"}, RequestBlocked),
        ({"status": "LOGIN_REQUIRED", "reason": "Sign in to confirm your age"}, AgeRestricted),
        ({"status": "LOGIN_REQUIRED", "reason": "This video may be inappropriate for some users."}, AgeRestricted),
        ({"status": "LOGIN_REQUIRED", "reason": "Please sign in"}, VideoUnplayable),
        ({"status": "ERROR", "reason": "This video is unavailable"}, VideoUnavailable),
        ({"status": "UNPLAYABLE", "reason": "This live stream recording is not available."}, VideoUnplayable),
        ({"status": "ERROR", "reason": "Something else"}, VideoUnplayable),
        ({"status": "CONTENT_CHECK_REQUIRED"}, VideoUnplayable),
    ],
)
def test_every_non_ok_status_maps_to_a_typed_error(
    status: dict[str, Any], error: type[UTMaxError]
) -> None:
    with pytest.raises(error) as caught:
        check_playability(parse_playability({"playabilityStatus": status}), video_id="v")
    assert type(caught.value) is error
    assert caught.value.video_id == "v"


@pytest.mark.parametrize("player", [{"playabilityStatus": {"status": "OK"}}, {}, {"playabilityStatus": "odd"}])
def test_ok_or_missing_status_passes(player: dict[str, Any]) -> None:
    check_playability(parse_playability(player), video_id="v")


def test_reason_and_sub_reasons_come_from_the_error_screen() -> None:
    playability = parse_playability(
        {
            "playabilityStatus": {
                "status": "UNPLAYABLE",
                "errorScreen": {
                    "playerErrorMessageRenderer": {
                        "reason": {"simpleText": "Video unavailable"},
                        "subreason": {"runs": [{"text": "The uploader has not made this video "}, {"text": "available in your country"}]},
                    }
                },
            }
        }
    )
    assert playability == Playability(
        "UNPLAYABLE",
        "Video unavailable",
        ("The uploader has not made this video ", "available in your country"),
    )
    with pytest.raises(VideoUnplayable) as caught:
        check_playability(playability, video_id="v")
    assert caught.value.sub_reasons == playability.sub_reasons
    assert caught.value.reason == "Video unavailable"


def test_private_videos_explain_that_sign_in_is_unsupported() -> None:
    with pytest.raises(VideoUnplayable) as caught:
        check_playability(Playability("LOGIN_REQUIRED", "Please sign in"), video_id="v")
    assert "signed-in" in caught.value.suggestion
```

`tests/unit/core/test_player.py`:

```python
"""Tests for player-response parsing."""

from __future__ import annotations

from typing import Any

import pytest

from tests.helpers.youtube import VIDEO_ID, player_payload
from utmax.core.player import CaptionTrackInfo, parse_player_response
from utmax.models import Language, VideoInfo


def test_video_details_become_video_info() -> None:
    player = parse_player_response(player_payload(), video_id=VIDEO_ID)
    assert player.video == VideoInfo(
        VIDEO_ID,
        "Rick Astley - Never Gonna Give You Up (Official Video)",
        "Rick Astley",
        "UCuAXFkgsw1L7xaCfnd5JJOw",
        213.0,
        False,
    )
    assert player.playability.status == "OK"


def test_caption_tracks_keep_youtube_order_and_kinds() -> None:
    player = parse_player_response(player_payload(), video_id=VIDEO_ID)
    tracks = player.caption_tracks or ()
    assert [track.language_code for track in tracks] == ["en", "en", "de-DE", "ja", "pt-BR", "es-419"]
    assert [track.is_generated for track in tracks] == [False, True, False, False, False, False]
    assert tracks[1] == CaptionTrackInfo(
        base_url=f"https://www.youtube.com/api/timedtext?v={VIDEO_ID}&lang=en&fmt=srv3&kind=asr",
        language_code="en",
        name="English (auto-generated)",
        is_generated=True,
        is_translatable=True,
        vss_id="a.en",
    )
    assert player.translation_languages == (Language("tr", "Turkish"), Language("de", "German"))


def test_names_fall_back_to_simple_text_then_the_code() -> None:
    data = player_payload()
    tracks = data["captions"]["playerCaptionsTracklistRenderer"]["captionTracks"]
    tracks[0]["name"] = {"simpleText": "English (simple)"}
    del tracks[2]["name"]
    parsed = parse_player_response(data, video_id=VIDEO_ID).caption_tracks or ()
    assert (parsed[0].name, parsed[2].name) == ("English (simple)", "de-DE")


@pytest.mark.parametrize(
    "captions",
    [
        None,
        {},
        {"playerCaptionsTracklistRenderer": {"captionTracks": []}},
        {"playerCaptionsTracklistRenderer": {"captionTracks": [{"languageCode": "en"}]}},
        ["not", "an", "object"],
    ],
)
def test_missing_or_unusable_captions_mean_none(captions: Any) -> None:
    data = player_payload(captions=False)
    if captions is not None:
        data["captions"] = captions
    player = parse_player_response(data, video_id=VIDEO_ID)
    assert player.caption_tracks is None
    assert player.translation_languages == ()


def test_malformed_video_details_fall_back_to_defaults() -> None:
    player = parse_player_response({"videoDetails": {"lengthSeconds": "soon"}}, video_id=VIDEO_ID)
    assert player.video == VideoInfo(VIDEO_ID, "", "", "", 0.0, False)
    assert parse_player_response({"videoDetails": "odd"}, video_id=VIDEO_ID).video.video_id == VIDEO_ID
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_clients.py tests/unit/core/test_playability.py tests/unit/core/test_player.py -v`
Expected: collection errors (`No module named 'utmax.core.clients'`, `… 'utmax.core.playability'`, `… 'utmax.core.player'`).

- [ ] **Step 4: Implement `src/utmax/core/clients.py`**

```python
"""InnerTube client profiles: the single place to update when YouTube changes its apps.

Verified on 2026-09-27: ANDROID, IOS and ANDROID_VR return captions and direct stream URLs
without an API key or proof-of-origin token; ANDROID_VR returns no ``translationLanguages``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

__all__ = [
    "ANDROID",
    "ANDROID_VR",
    "DESKTOP_USER_AGENT",
    "IOS",
    "ORDER",
    "WEB",
    "ClientProfile",
    "Purpose",
]

Purpose = Literal["captions", "streams", "browse", "resolve"]

DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


@dataclass(frozen=True, slots=True)
class ClientProfile:
    """How utmax introduces itself to InnerTube as one of YouTube's apps."""

    name: str
    client_id: int
    version: str
    user_agent: str
    extra: tuple[tuple[str, str | int], ...] = ()

    def context_payload(self) -> dict[str, Any]:
        """The ``context`` object of an InnerTube request body."""
        client: dict[str, Any] = {"clientName": self.name, "clientVersion": self.version}
        client.update(self.extra)
        client.update({"hl": "en", "gl": "US"})
        return {"client": client}

    def request_headers(self) -> dict[str, str]:
        """HTTP headers for an InnerTube request made as this app."""
        return {
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
            "X-YouTube-Client-Name": str(self.client_id),
            "X-YouTube-Client-Version": self.version,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip",
        }


ANDROID = ClientProfile(
    name="ANDROID",
    client_id=3,
    version="20.10.38",
    user_agent="com.google.android.youtube/20.10.38 (Linux; U; Android 11) gzip",
    extra=(("androidSdkVersion", 30), ("osName", "Android"), ("osVersion", "11")),
)
IOS = ClientProfile(
    name="IOS",
    client_id=5,
    version="20.10.4",
    user_agent="com.google.ios.youtube/20.10.4 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)",
    extra=(
        ("deviceMake", "Apple"),
        ("deviceModel", "iPhone16,2"),
        ("osName", "iPhone"),
        ("osVersion", "18.3.2.22D82"),
    ),
)
ANDROID_VR = ClientProfile(
    name="ANDROID_VR",
    client_id=28,
    version="1.62.27",
    user_agent=(
        "com.google.android.apps.youtube.vr.oculus/1.62.27 "
        "(Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip"
    ),
    extra=(
        ("deviceMake", "Oculus"),
        ("deviceModel", "Quest 3"),
        ("androidSdkVersion", 32),
        ("osName", "Android"),
        ("osVersion", "12L"),
    ),
)
WEB = ClientProfile(name="WEB", client_id=1, version="2.20260925.01.00", user_agent=DESKTOP_USER_AGENT)

ORDER: Mapping[Purpose, tuple[ClientProfile, ...]] = MappingProxyType(
    {
        "captions": (ANDROID, IOS, ANDROID_VR),
        "streams": (ANDROID_VR, ANDROID, IOS),
        "browse": (ANDROID_VR, WEB),
        "resolve": (ANDROID_VR, WEB),
    }
)
```

- [ ] **Step 5: Implement `src/utmax/core/playability.py`**

```python
"""Map InnerTube's ``playabilityStatus`` to utmax errors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from utmax.core.ytdata import mapping, text_of, texts_of
from utmax.errors import AgeRestricted, RequestBlocked, VideoUnavailable, VideoUnplayable

__all__ = ["Playability", "check_playability", "parse_playability"]


@dataclass(frozen=True, slots=True)
class Playability:
    """What YouTube said about playing the video."""

    status: str
    reason: str = ""
    sub_reasons: tuple[str, ...] = ()


def parse_playability(player: Mapping[str, Any]) -> Playability:
    """Read ``playabilityStatus`` from a player response; a missing status means OK."""
    status = mapping(player.get("playabilityStatus"))
    renderer = mapping(mapping(status.get("errorScreen")).get("playerErrorMessageRenderer"))
    reason = status.get("reason")
    return Playability(
        status=str(status.get("status") or "OK"),
        reason=reason if isinstance(reason, str) and reason else text_of(renderer.get("reason")),
        sub_reasons=texts_of(renderer.get("subreason")),
    )


def check_playability(playability: Playability, *, video_id: str) -> None:
    """Raise the utmax error that matches a non-OK status (substring match, case-insensitive)."""
    status = playability.status.upper()
    if status == "OK":
        return
    reason = playability.reason.replace("’", "'").lower()
    message = playability.reason or f"YouTube reported playability status {playability.status}."
    if status == "LOGIN_REQUIRED":
        if "not a bot" in reason:
            raise RequestBlocked(message, video_id=video_id)
        if "confirm your age" in reason or "inappropriate" in reason:
            raise AgeRestricted(message, video_id=video_id)
        raise VideoUnplayable(
            message,
            reason=playability.reason,
            sub_reasons=playability.sub_reasons,
            video_id=video_id,
            suggestion=(
                "This video needs a signed-in session (private or members-only), "
                "which utmax does not support."
            ),
        )
    if status == "ERROR" and "unavailable" in reason:
        raise VideoUnavailable(message, video_id=video_id)
    raise VideoUnplayable(
        message, reason=playability.reason, sub_reasons=playability.sub_reasons, video_id=video_id
    )
```

- [ ] **Step 6: Implement `src/utmax/core/player.py`**

```python
"""Parse InnerTube ``/player`` responses into typed data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from utmax.core.playability import Playability, parse_playability
from utmax.core.ytdata import items, mapping, text_of
from utmax.models import Language, VideoInfo

__all__ = ["CaptionTrackInfo", "PlayerData", "parse_player_response"]


@dataclass(frozen=True, slots=True)
class CaptionTrackInfo:
    """A caption track as listed in the player response."""

    base_url: str
    language_code: str
    name: str
    is_generated: bool
    is_translatable: bool
    vss_id: str


@dataclass(frozen=True, slots=True)
class PlayerData:
    """The parts of a player response utmax uses."""

    video: VideoInfo
    playability: Playability
    caption_tracks: tuple[CaptionTrackInfo, ...] | None
    translation_languages: tuple[Language, ...]


def parse_player_response(data: Mapping[str, Any], *, video_id: str) -> PlayerData:
    """Parse ``data``; missing or malformed parts become defaults instead of errors."""
    details = mapping(data.get("videoDetails"))
    video = VideoInfo(
        video_id=str(details.get("videoId") or video_id),
        title=str(details.get("title") or ""),
        channel=str(details.get("author") or ""),
        channel_id=str(details.get("channelId") or ""),
        duration=_seconds(details.get("lengthSeconds")),
        is_live_content=bool(details.get("isLiveContent", False)),
    )
    renderer = mapping(mapping(data.get("captions")).get("playerCaptionsTracklistRenderer"))
    tracks = tuple(
        _track(raw)
        for raw in map(mapping, items(renderer.get("captionTracks")))
        if isinstance(raw.get("baseUrl"), str)
    )
    languages = tuple(
        Language(code=str(raw["languageCode"]), name=text_of(raw.get("languageName")) or str(raw["languageCode"]))
        for raw in map(mapping, items(renderer.get("translationLanguages")))
        if raw.get("languageCode")
    )
    return PlayerData(
        video=video,
        playability=parse_playability(data),
        caption_tracks=tracks or None,
        translation_languages=languages if tracks else (),
    )


def _track(raw: Mapping[str, Any]) -> CaptionTrackInfo:
    code = str(raw.get("languageCode") or "")
    return CaptionTrackInfo(
        base_url=str(raw["baseUrl"]),
        language_code=code,
        name=text_of(raw.get("name")) or code,
        is_generated=raw.get("kind") == "asr",
        is_translatable=bool(raw.get("isTranslatable", False)),
        vss_id=str(raw.get("vssId") or ""),
    )


def _seconds(value: object) -> float:
    try:
        return float(str(value))
    except ValueError:
        return 0.0
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_clients.py tests/unit/core/test_playability.py tests/unit/core/test_player.py -v`
Expected: all PASS.

- [ ] **Step 8: Gates and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: clean.

```bash
git add src/utmax/core/clients.py src/utmax/core/playability.py src/utmax/core/player.py tests/helpers/youtube.py tests/unit/core
git commit -m "feat: parse InnerTube player responses and map playability to errors

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Track selection

**Files:**
- Create: `src/utmax/core/selection.py`
- Modify: `src/utmax/models.py` (`TrackList.find`)
- Test: `tests/unit/core/test_selection.py`

**Interfaces:**
- Consumes: `Track`, `TrackList` (Task 3); `NoTranscriptFound` (Task 2); `tests.helpers.builders.make_track`.
- Produces:
  - `utmax.core.selection.select_track(tracks: Sequence[Track], languages: Sequence[str] | str | None = None, *, include_manual=True, include_generated=True) -> Track` (raises `NoTranscriptFound` listing every track).
  - `utmax.core.selection.describe_track(track) -> str`, e.g. `"de-DE (German (Germany), manual)"`.
  - `TrackList.find(languages=None, *, include_manual=True, include_generated=True) -> Track`.
- Rules (spec §5): with languages, per code: exact code match (manual first) beats a base-language match (manual first); without languages: spoken language (first auto track's code) manual → spoken auto → first manual → first auto. A bare string counts as one code. YouTube translation is never used.

- [ ] **Step 1: Write the failing tests** (Review Focus #3)

`tests/unit/core/test_selection.py`:

```python
"""Tests for select_track."""

from __future__ import annotations

import pytest

from tests.helpers.builders import VIDEO, make_track
from utmax.core.selection import describe_track, select_track
from utmax.errors import NoTranscriptFound
from utmax.models import Track, TrackList

EN = make_track("en", name="English")
EN_AUTO = make_track("en", generated=True, name="English (auto-generated)")
DE = make_track("de-DE", name="German (Germany)")
JA = make_track("ja", name="Japanese")
RICK = (EN, EN_AUTO, DE, JA)


def pick(tracks: tuple[Track, ...], languages: object = None, **flags: bool) -> Track:
    return select_track(tracks, languages, **flags)  # type: ignore[arg-type]


def test_manual_beats_auto_for_the_same_code() -> None:
    assert pick(RICK, ["en"]) is EN


def test_requested_languages_are_tried_in_order() -> None:
    assert pick(RICK, ["tr", "ja", "en"]) is JA


def test_base_language_matches_regional_tracks() -> None:
    assert pick(RICK, ["de"]) is DE
    assert pick((make_track("de"),), ["de-AT"]).language_code == "de"


def test_an_exact_code_beats_a_base_language_match() -> None:
    en_gb = make_track("en-GB")
    assert pick((en_gb, EN_AUTO), ["en"]) is EN_AUTO


def test_codes_are_case_insensitive_and_a_bare_string_is_one_code() -> None:
    assert pick(RICK, ["EN"]) is EN
    assert pick(RICK, "ja") is JA


def test_filters() -> None:
    assert pick(RICK, ["en"], include_manual=False) is EN_AUTO
    assert pick(RICK, ["en"], include_generated=False) is EN


def test_default_prefers_the_spoken_language_manual_track() -> None:
    assert pick((DE, EN_AUTO, EN)) is EN
    assert pick((DE, make_track("en-GB"), EN_AUTO)).language_code == "en-GB"


def test_default_falls_back_to_spoken_auto_then_first_manual_then_first_auto() -> None:
    assert pick((DE, EN_AUTO)) is EN_AUTO
    assert pick((JA, DE)) is JA
    assert pick((EN_AUTO,), include_generated=True) is EN_AUTO
    assert pick((DE, EN_AUTO), include_generated=False) is DE


def test_missing_languages_list_what_is_available() -> None:
    with pytest.raises(NoTranscriptFound) as caught:
        pick(RICK, ["tr", "ko"])
    error = caught.value
    assert error.requested == ("tr", "ko")
    assert error.available == tuple(describe_track(track) for track in RICK)
    assert "de-DE (German (Germany), manual)" in str(error)
    assert "en (English (auto-generated), auto-generated)" in str(error)
    assert error.video_id == VIDEO.video_id


def test_filters_that_exclude_everything_raise() -> None:
    with pytest.raises(NoTranscriptFound):
        pick((EN,), include_manual=False)
    with pytest.raises(NoTranscriptFound):
        pick(())


def test_track_list_find_uses_the_same_rules() -> None:
    tracks = TrackList(video=VIDEO, tracks=RICK)
    assert tracks.find(["de"]) is DE
    assert tracks.find() is EN
    assert tracks.find(["en"], include_manual=False) is EN_AUTO
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_selection.py -v`
Expected: collection error `No module named 'utmax.core.selection'`.

- [ ] **Step 3: Implement `src/utmax/core/selection.py`**

```python
"""Choose the right subtitle track: manual before auto-generated, in the user's language order."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from utmax.errors import NoTranscriptFound
from utmax.models import Track

__all__ = ["describe_track", "select_track"]


def select_track(
    tracks: Sequence[Track],
    languages: Sequence[str] | str | None = None,
    *,
    include_manual: bool = True,
    include_generated: bool = True,
) -> Track:
    """Pick one track from ``tracks``.

    With ``languages``, each code is tried in order: an exact code match first (manual before
    auto-generated), then a base-language match (``de`` finds ``de-DE``). Without ``languages``
    the spoken language (that of the auto-generated track) wins, manual first. YouTube's own
    translation is never used implicitly.

    Raises:
        NoTranscriptFound: nothing matches; the error lists every available track.
    """
    requested = [languages] if isinstance(languages, str) else list(languages or [])
    candidates = [
        track for track in tracks if (include_generated if track.is_generated else include_manual)
    ]
    if requested:
        for code in requested:
            exact = [track for track in candidates if track.language_code.lower() == code.lower()]
            related = [track for track in candidates if _base(track.language_code) == _base(code)]
            match = _manual_first(exact) or _manual_first(related)
            if match is not None:
                return match
        raise _not_found(tracks, requested)
    spoken = next((track.language_code for track in tracks if track.is_generated), None)
    if spoken is not None:
        manual = _in_language([track for track in candidates if not track.is_generated], spoken)
        if manual:
            return manual[0]
        automatic = [track for track in _in_language(candidates, spoken) if track.is_generated]
        if automatic:
            return automatic[0]
    match = _manual_first(candidates)
    if match is None:
        raise _not_found(tracks, [])
    return match


def describe_track(track: Track) -> str:
    """A short human-readable label such as ``"de-DE (German (Germany), manual)"``."""
    kind = "auto-generated" if track.is_generated else "manual"
    return f"{track.language_code} ({track.language}, {kind})"


def _in_language(tracks: Sequence[Track], code: str) -> list[Track]:
    exact = [track for track in tracks if track.language_code.lower() == code.lower()]
    return exact or [track for track in tracks if _base(track.language_code) == _base(code)]


def _manual_first(tracks: Iterable[Track]) -> Track | None:
    ordered = list(tracks)
    manual = next((track for track in ordered if not track.is_generated), None)
    return manual if manual is not None else next(iter(ordered), None)


def _base(code: str) -> str:
    return code.split("-")[0].lower()


def _not_found(tracks: Sequence[Track], requested: list[str]) -> NoTranscriptFound:
    video_id = tracks[0].video_id if tracks else None
    available = tuple(describe_track(track) for track in tracks)
    wanted = f"in {', '.join(requested)} " if requested else ""
    return NoTranscriptFound(
        f"No subtitles {wanted}match the filters for video {video_id}. "
        f"Available: {'; '.join(available) or 'none'}.",
        requested=tuple(requested),
        available=available,
        video_id=video_id,
    )
```

- [ ] **Step 4: Add `TrackList.find`**

Append to `class TrackList` in `src/utmax/models.py`, after `generated`:

```python
    def find(
        self,
        languages: Sequence[str] | str | None = None,
        *,
        include_manual: bool = True,
        include_generated: bool = True,
    ) -> Track:
        """Pick the best track; see :func:`utmax.core.selection.select_track` for the rules."""
        from utmax.core.selection import select_track

        return select_track(
            self.tracks,
            languages,
            include_manual=include_manual,
            include_generated=include_generated,
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/core/test_selection.py -v`
Expected: 11 passed.

- [ ] **Step 6: Gates and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: clean.

```bash
git add src/utmax/core/selection.py src/utmax/models.py tests/unit/core/test_selection.py
git commit -m "feat: select subtitle tracks by language order, manual first

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: The HTTP seam and the pure retry policy

**Files:**
- Create: `src/utmax/transport.py`, `src/utmax/core/retry.py`
- Test: `tests/unit/test_transport.py`, `tests/unit/core/test_retry.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `utmax.transport.HttpRequest(method: Literal["GET", "POST"], url: str, headers: Mapping[str, str] = {}, body: bytes | None = None)`.
  - `utmax.transport.HttpResponse(status: int, url: str, headers: Mapping[str, str] = {}, body: bytes = b"")`: header keys are lower-cased on construction; `.header(name) -> str | None` (case-insensitive), `.content_type -> str`, `.text -> str`, `.json() -> Any` (raises `ValueError` on bad JSON).
  - `utmax.transport.Transport` protocol: `send(request: HttpRequest) -> HttpResponse` — returns a response for **any** HTTP status and raises only on network failure.
  - `utmax.core.retry`: `TRANSIENT_STATUSES`, `MAX_RETRY_AFTER = 30.0`, `is_transient_status(status) -> bool`, `backoff_delay(attempt: int, rng: random.Random) -> float`, `parse_retry_after(value: str | None, *, now: datetime) -> float | None`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_transport.py`:

```python
"""Tests for the HTTP value types."""

from __future__ import annotations

import pytest

from utmax.transport import HttpRequest, HttpResponse


def test_response_headers_are_case_insensitive() -> None:
    response = HttpResponse(status=200, url="u", headers={"Content-Type": "application/json", "X-A": "1"})
    assert response.header("content-type") == "application/json"
    assert response.header("CONTENT-TYPE") == "application/json"
    assert response.content_type == "application/json"
    assert response.header("missing") is None
    assert dict(response.headers) == {"content-type": "application/json", "x-a": "1"}


def test_response_text_and_json() -> None:
    response = HttpResponse(status=200, url="u", body='{"ok": "♪"}'.encode())
    assert response.text == '{"ok": "♪"}'
    assert response.json() == {"ok": "♪"}
    assert HttpResponse(status=200, url="u").content_type == ""
    with pytest.raises(ValueError):
        HttpResponse(status=200, url="u", body=b"<html>").json()


def test_request_defaults() -> None:
    request = HttpRequest("GET", "https://www.youtube.com/")
    assert (request.headers, request.body) == ({}, None)
```

`tests/unit/core/test_retry.py`:

```python
"""Tests for the pure retry policy."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from utmax.core.retry import MAX_RETRY_AFTER, backoff_delay, is_transient_status, parse_retry_after

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(("status", "transient"), [(408, True), (500, True), (502, True), (503, True), (504, True), (404, False), (429, False), (200, False)])
def test_transient_statuses(status: int, transient: bool) -> None:
    assert is_transient_status(status) is transient


def test_backoff_grows_and_is_capped() -> None:
    rng = random.Random(1)
    delays = [backoff_delay(attempt, rng) for attempt in range(6)]
    for attempt, delay in enumerate(delays):
        base = min(8.0, 0.5 * 2**attempt)
        assert base <= delay <= base + 0.25
    assert backoff_delay(20, rng) <= 8.25


def test_retry_after_in_seconds() -> None:
    assert parse_retry_after("3", now=NOW) == 3.0
    assert parse_retry_after(" 120 ", now=NOW) == MAX_RETRY_AFTER


def test_retry_after_as_an_http_date() -> None:
    assert parse_retry_after(format_datetime(NOW + timedelta(seconds=5), usegmt=True), now=NOW) == 5.0
    assert parse_retry_after(format_datetime(NOW - timedelta(seconds=5), usegmt=True), now=NOW) == 0.0
    assert parse_retry_after("Sun, 27 Sep 2026 12:00:07 -0000", now=NOW) == 7.0


@pytest.mark.parametrize("value", [None, "", "   ", "soon", "-5"])
def test_unusable_retry_after_values(value: str | None) -> None:
    assert parse_retry_after(value, now=NOW) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_transport.py tests/unit/core/test_retry.py -v`
Expected: collection errors (`No module named 'utmax.transport'`, `… 'utmax.core.retry'`).

- [ ] **Step 3: Implement `src/utmax/transport.py`**

```python
"""The HTTP seam: every YouTube request goes through a ``Transport``, which tests replace."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

__all__ = ["HttpRequest", "HttpResponse", "Transport"]


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """One HTTP request."""

    method: Literal["GET", "POST"]
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """One HTTP response, whatever its status; header names are stored lower-cased."""

    status: int
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", {k.lower(): v for k, v in self.headers.items()})

    def header(self, name: str) -> str | None:
        """A header value, looked up case-insensitively."""
        return self.headers.get(name.lower())

    @property
    def content_type(self) -> str:
        return self.header("content-type") or ""

    @property
    def text(self) -> str:
        """The body decoded as UTF-8 (undecodable bytes are replaced)."""
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        """The body parsed as JSON; raises ``ValueError`` when it is not JSON."""
        return json.loads(self.body.decode("utf-8"))


class Transport(Protocol):
    """Sends requests. Returns a response for any HTTP status; raises only on network failure."""

    def send(self, request: HttpRequest) -> HttpResponse: ...
```

- [ ] **Step 4: Implement `src/utmax/core/retry.py`**

```python
"""Pure retry policy: which HTTP statuses are transient and how long to wait."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

__all__ = [
    "MAX_RETRY_AFTER",
    "TRANSIENT_STATUSES",
    "backoff_delay",
    "is_transient_status",
    "parse_retry_after",
]

TRANSIENT_STATUSES = frozenset({408, 500, 502, 503, 504})
MAX_RETRY_AFTER = 30.0


def is_transient_status(status: int) -> bool:
    """True for statuses worth retrying: 408 and 500/502/503/504 (429 is handled separately)."""
    return status in TRANSIENT_STATUSES


def backoff_delay(attempt: int, rng: random.Random) -> float:
    """Exponential backoff: 0.5 s, 1 s, 2 s … capped at 8 s, plus up to 0.25 s of jitter."""
    return min(8.0, 0.5 * 2**attempt) + rng.uniform(0.0, 0.25)


def parse_retry_after(value: str | None, *, now: datetime) -> float | None:
    """Seconds to wait from a ``Retry-After`` header (seconds or HTTP date), capped at 30 s."""
    if value is None or not value.strip():
        return None
    text = value.strip()
    if text.isdigit():
        return min(float(text), MAX_RETRY_AFTER)
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, min((when - now).total_seconds(), MAX_RETRY_AFTER))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_transport.py tests/unit/core/test_retry.py -v`
Expected: all PASS.

- [ ] **Step 6: Gates and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: clean.

```bash
git add src/utmax/transport.py src/utmax/core/retry.py tests/unit/test_transport.py tests/unit/core/test_retry.py
git commit -m "feat: add the HTTP seam and the pure retry policy

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: urllib transport and retry wrapper

**Files:**
- Create: `src/utmax/adapters/http.py`
- Test: `tests/helpers/fake_transport.py`, `tests/helpers/http_server.py`, `tests/unit/adapters/test_http.py`

**Interfaces:**
- Consumes: `HttpRequest`, `HttpResponse`, `Transport` (Task 10); `backoff_delay`, `is_transient_status`, `parse_retry_after` (Task 10); `InvalidOption`, `NetworkError` (Task 2).
- Produces:
  - `utmax.adapters.http.UrllibTransport(*, proxy: str | None = None, timeout: float = 30.0)` — `.send()` returns responses for every HTTP status, decompresses gzip, raises raw network exceptions; `proxy` must be `http://[user:pass@]host:port` (else `InvalidOption`); without `proxy`, environment proxies apply.
  - `utmax.adapters.http.RetryingTransport(inner: Transport, *, retries=2, sleep=time.sleep, rng=None, clock=...)` — retries 408/5xx and transient network errors (`1 + retries` attempts, honours `Retry-After`), then returns the last response or raises `NetworkError` (with `__cause__`); certificate errors, unknown hosts and 4xx are never retried; non-network exceptions propagate unchanged.
  - `utmax.adapters.http.redact(url) -> str` — scheme, host, port and path only (no credentials, no query).
  - Test helpers: `tests.helpers.fake_transport.FakeTransport` (`add(method, url_fragment, *replies, repeat=False)`, `.requests`, `.urls(method=None)`), `json_response(payload, *, status=200)`, `text_response(text, *, status=200, content_type=...)`; `tests.helpers.http_server.local_server()` context manager yielding a base URL.

- [ ] **Step 1: Write the test helpers**

`tests/helpers/fake_transport.py`:

```python
"""A scripted, thread-safe Transport for tests: no network, full control over replies."""

from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

from utmax.transport import HttpRequest, HttpResponse

Reply = HttpResponse | BaseException


def json_response(payload: Any, *, status: int = 200) -> HttpResponse:
    return HttpResponse(
        status=status,
        url="https://www.youtube.com/",
        headers={"Content-Type": "application/json; charset=UTF-8"},
        body=json.dumps(payload).encode("utf-8"),
    )


def text_response(
    text: str, *, status: int = 200, content_type: str = "text/html; charset=utf-8"
) -> HttpResponse:
    return HttpResponse(
        status=status,
        url="https://www.youtube.com/",
        headers={"Content-Type": content_type},
        body=text.encode("utf-8"),
    )


@dataclass
class _Route:
    method: str
    fragment: str
    replies: deque[Reply]
    repeat: bool


class FakeTransport:
    """Answers requests from scripted routes.

    Routes are checked in the order they were added; the first route whose method matches, whose
    ``url_fragment`` occurs in the URL and which still has replies wins. Replies are consumed in
    order unless ``repeat=True`` (then the first reply is served forever). Exceptions are raised.
    """

    def __init__(self) -> None:
        self.requests: list[HttpRequest] = []
        self._routes: list[_Route] = []
        self._lock = threading.Lock()

    def add(self, method: str, url_fragment: str, *replies: Reply, repeat: bool = False) -> None:
        self._routes.append(_Route(method, url_fragment, deque(replies), repeat))

    def send(self, request: HttpRequest) -> HttpResponse:
        with self._lock:
            self.requests.append(request)
            for route in self._routes:
                if route.method == request.method and route.fragment in request.url and route.replies:
                    reply = route.replies[0] if route.repeat else route.replies.popleft()
                    break
            else:
                raise AssertionError(f"unexpected request: {request.method} {request.url}")
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def urls(self, method: str | None = None) -> list[str]:
        return [r.url for r in self.requests if method is None or r.method == method]
```

`tests/helpers/http_server.py`:

```python
"""A throwaway local HTTP server for real-socket transport tests."""

from __future__ import annotations

import gzip
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class _Server(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        """Clients that time out on purpose make writes fail; that is expected here."""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        """Keep test output quiet."""

    def _send(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/json":
            self._send(200, b'{"ok": true}', {"Content-Type": "application/json"})
        elif self.path == "/gzip":
            body = gzip.compress("zipped ♪".encode())
            self._send(200, body, {"Content-Type": "text/plain; charset=utf-8", "Content-Encoding": "gzip"})
        elif self.path == "/missing":
            self._send(404, b"nope", {"Content-Type": "text/plain"})
        elif self.path == "/slow":
            time.sleep(1.0)
            self._send(200, b"late", {})
        else:
            self._send(200, json.dumps({"path": self.path}).encode(), {"Content-Type": "application/json"})

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = {
            "path": self.path,
            "body": body.decode(),
            "content_type": self.headers.get("Content-Type"),
            "user_agent": self.headers.get("User-Agent"),
        }
        self._send(200, json.dumps(payload).encode(), {"Content-Type": "application/json"})


@contextmanager
def local_server() -> Iterator[str]:
    """Serve on 127.0.0.1 in a background thread and yield the base URL."""
    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
```

- [ ] **Step 2: Write the failing tests** (Review Focus #4)

`tests/unit/adapters/test_http.py`:

```python
"""Tests for the urllib transport and the retry wrapper."""

from __future__ import annotations

import random
import socket
import ssl
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from tests.helpers.fake_transport import FakeTransport
from tests.helpers.http_server import local_server
from utmax.adapters.http import RetryingTransport, UrllibTransport, redact
from utmax.errors import InvalidOption, NetworkError
from utmax.transport import HttpRequest, HttpResponse

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
REQUEST = HttpRequest("GET", "https://www.youtube.com/api?secret=1")


@pytest.fixture(autouse=True)
def no_environment_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "getproxies", dict)


@pytest.fixture
def server() -> Iterator[str]:
    with local_server() as url:
        yield url


def test_get_returns_status_headers_and_body(server: str) -> None:
    response = UrllibTransport().send(HttpRequest("GET", f"{server}/json"))
    assert response.status == 200
    assert response.header("Content-Type") == "application/json"
    assert response.json() == {"ok": True}


def test_gzip_bodies_are_decompressed(server: str) -> None:
    response = UrllibTransport().send(HttpRequest("GET", f"{server}/gzip", {"Accept-Encoding": "gzip"}))
    assert response.text == "zipped ♪"


def test_http_errors_are_returned_not_raised(server: str) -> None:
    response = UrllibTransport().send(HttpRequest("GET", f"{server}/missing"))
    assert (response.status, response.body) == (404, b"nope")


def test_post_sends_body_and_headers(server: str) -> None:
    headers = {"Content-Type": "application/json", "User-Agent": "utmax-test"}
    response = UrllibTransport().send(HttpRequest("POST", f"{server}/echo", headers, b'{"a": 1}'))
    assert response.json() == {
        "path": "/echo",
        "body": '{"a": 1}',
        "content_type": "application/json",
        "user_agent": "utmax-test",
    }


def test_timeouts_raise_so_the_retry_layer_can_decide(server: str) -> None:
    with pytest.raises((TimeoutError, urllib.error.URLError)):
        UrllibTransport(timeout=0.2).send(HttpRequest("GET", f"{server}/slow"))


def test_an_http_proxy_receives_absolute_urls(server: str) -> None:
    response = UrllibTransport(proxy=server).send(HttpRequest("GET", "http://example.invalid/hello"))
    assert response.json() == {"path": "http://example.invalid/hello"}


@pytest.mark.parametrize(
    "proxy", ["https://proxy.example:443", "socks5://127.0.0.1:1080", "proxy.example:8080", "http://"]
)
def test_unsupported_proxy_urls_are_rejected(proxy: str) -> None:
    with pytest.raises(InvalidOption):
        UrllibTransport(proxy=proxy)


def test_redact_drops_credentials_and_queries() -> None:
    assert redact("http://user:pw@proxy.example:8080/p?token=1") == "http://proxy.example:8080/p"
    assert redact("http://[::1") == "<invalid url>"


def ok(status: int = 200, headers: dict[str, str] | None = None) -> HttpResponse:
    return HttpResponse(status=status, url=REQUEST.url, headers=headers or {})


def retrying(
    *replies: HttpResponse | BaseException, retries: int = 2
) -> tuple[RetryingTransport, FakeTransport, list[float]]:
    inner = FakeTransport()
    inner.add("GET", "", *replies)
    sleeps: list[float] = []
    transport = RetryingTransport(
        inner, retries=retries, sleep=sleeps.append, rng=random.Random(0), clock=lambda: NOW
    )
    return transport, inner, sleeps


def test_transient_statuses_are_retried_with_backoff() -> None:
    transport, inner, sleeps = retrying(ok(503), ok(502), ok(200))
    assert transport.send(REQUEST).status == 200
    assert len(inner.requests) == 3
    assert 0.5 <= sleeps[0] <= 0.75
    assert 1.0 <= sleeps[1] <= 1.25


def test_retry_after_is_honoured() -> None:
    transport, _, sleeps = retrying(ok(503, {"Retry-After": "3"}), ok(200))
    assert transport.send(REQUEST).status == 200
    assert sleeps == [3.0]


def test_exhausted_retries_return_the_last_response() -> None:
    transport, inner, sleeps = retrying(ok(503), ok(503), ok(503))
    assert transport.send(REQUEST).status == 503
    assert (len(inner.requests), len(sleeps)) == (3, 2)


@pytest.mark.parametrize("status", [400, 403, 404, 429])
def test_client_errors_are_not_retried(status: int) -> None:
    transport, inner, sleeps = retrying(ok(status))
    assert transport.send(REQUEST).status == status
    assert (len(inner.requests), sleeps) == (1, [])


def test_connection_resets_are_retried() -> None:
    transport, _, _ = retrying(ConnectionResetError("reset"), ok())
    assert transport.send(REQUEST).status == 200


def test_exhausted_network_errors_become_network_error() -> None:
    transport, inner, _ = retrying(TimeoutError("slow"), TimeoutError("slow"), TimeoutError("slow"))
    with pytest.raises(NetworkError) as caught:
        transport.send(REQUEST)
    assert isinstance(caught.value.__cause__, TimeoutError)
    assert "secret" not in str(caught.value)
    assert len(inner.requests) == 3


def test_certificate_errors_fail_fast_with_a_hint() -> None:
    transport, inner, _ = retrying(urllib.error.URLError(ssl.SSLCertVerificationError("bad cert")))
    with pytest.raises(NetworkError) as caught:
        transport.send(REQUEST)
    assert "certificate" in caught.value.suggestion
    assert len(inner.requests) == 1


def test_temporary_dns_failures_are_retried_but_unknown_hosts_are_not() -> None:
    try_again = urllib.error.URLError(socket.gaierror(socket.EAI_AGAIN, "try again"))
    transport, _, _ = retrying(try_again, ok())
    assert transport.send(REQUEST).status == 200
    unknown = urllib.error.URLError(socket.gaierror(socket.EAI_NONAME, "unknown host"))
    transport, inner, _ = retrying(unknown)
    with pytest.raises(NetworkError):
        transport.send(REQUEST)
    assert len(inner.requests) == 1


def test_programming_errors_propagate_unchanged() -> None:
    transport, _, _ = retrying(ValueError("bad url"))
    with pytest.raises(ValueError, match="bad url"):
        transport.send(REQUEST)


def test_zero_retries_means_one_attempt() -> None:
    transport, inner, sleeps = retrying(ok(503), retries=0)
    assert transport.send(REQUEST).status == 503
    assert (len(inner.requests), sleeps) == (1, [])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/adapters/test_http.py -v`
Expected: collection error `No module named 'utmax.adapters.http'`.

- [ ] **Step 4: Implement `src/utmax/adapters/http.py`**

```python
"""The only module that talks to the network: a urllib transport plus a retry wrapper."""

from __future__ import annotations

import gzip
import http.client
import logging
import random
import socket
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from urllib.parse import urlsplit

from utmax.core.retry import backoff_delay, is_transient_status, parse_retry_after
from utmax.errors import InvalidOption, NetworkError
from utmax.transport import HttpRequest, HttpResponse, Transport

__all__ = ["RetryingTransport", "UrllibTransport", "redact"]

log = logging.getLogger("utmax.http")

_NETWORK_ERRORS = (OSError, http.client.HTTPException, EOFError)


class UrllibTransport:
    """Sends requests with the standard library; every request uses a fresh connection."""

    def __init__(self, *, proxy: str | None = None, timeout: float = 30.0) -> None:
        handlers: list[urllib.request.BaseHandler] = [
            urllib.request.HTTPSHandler(context=ssl.create_default_context())
        ]
        if proxy is not None:
            _check_proxy(proxy)
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self._opener = urllib.request.build_opener(*handlers)
        self._timeout = timeout

    def send(self, request: HttpRequest) -> HttpResponse:
        prepared = urllib.request.Request(
            request.url, data=request.body, headers=dict(request.headers), method=request.method
        )
        status: int
        headers: dict[str, str]
        body: bytes
        try:
            with self._opener.open(prepared, timeout=self._timeout) as response:
                status = response.status
                headers = dict(response.headers.items())
                body = response.read()
        except urllib.error.HTTPError as error:
            with error:
                status = error.code
                headers = dict(error.headers.items()) if error.headers else {}
                body = error.read()
        if _header(headers, "content-encoding").lower() == "gzip":
            body = gzip.decompress(body)
        log.debug("%s %s -> %d", request.method, redact(request.url), status)
        return HttpResponse(status=status, url=request.url, headers=headers, body=body)


class RetryingTransport:
    """Retries timeouts, connection resets and HTTP 408/5xx with exponential backoff."""

    def __init__(
        self,
        inner: Transport,
        *,
        retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._inner = inner
        self._retries = retries
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._clock = clock or _utc_now

    def send(self, request: HttpRequest) -> HttpResponse:
        attempt = 0
        while True:
            try:
                response = self._inner.send(request)
            except _NETWORK_ERRORS as error:
                if attempt >= self._retries or not _is_transient(error):
                    raise _network_error(error, request) from error
                delay = backoff_delay(attempt, self._rng)
                log.info("%s %s failed (%s); retrying in %.1fs", request.method, redact(request.url), error, delay)
            else:
                if attempt >= self._retries or not is_transient_status(response.status):
                    return response
                retry_after = parse_retry_after(response.header("retry-after"), now=self._clock())
                delay = backoff_delay(attempt, self._rng) if retry_after is None else retry_after
                log.info(
                    "%s %s answered %d; retrying in %.1fs",
                    request.method,
                    redact(request.url),
                    response.status,
                    delay,
                )
            self._sleep(delay)
            attempt += 1


def redact(url: str) -> str:
    """``url`` without credentials or query string, safe for logs and error messages."""
    try:
        parts = urlsplit(url)
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return "<invalid url>"
    return f"{parts.scheme}://{parts.hostname or ''}{port}{parts.path}"


def _check_proxy(proxy: str) -> None:
    try:
        parts = urlsplit(proxy)
        host = parts.hostname
    except ValueError:
        host = None
    if not proxy.startswith("http://") or not host:
        raise InvalidOption(
            f"Unsupported proxy URL {redact(proxy)!r}: use http://[user:password@]host:port "
            "(HTTPS traffic is tunnelled through it).",
            suggestion="For SOCKS or https:// proxies, pass your own transport= to utmax.Client.",
        )


def _header(headers: Mapping[str, str], name: str) -> str:
    return next((value for key, value in headers.items() if key.lower() == name), "")


def _is_transient(error: BaseException) -> bool:
    reason: object = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return False
    if isinstance(reason, socket.gaierror):
        return reason.errno == socket.EAI_AGAIN
    return isinstance(
        reason,
        (TimeoutError, ConnectionError, ssl.SSLError, http.client.HTTPException, EOFError, gzip.BadGzipFile),
    )


def _network_error(error: BaseException, request: HttpRequest) -> NetworkError:
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    message = f"Could not complete {request.method} {redact(request.url)}: {reason}"
    if isinstance(reason, ssl.SSLCertVerificationError):
        return NetworkError(
            message,
            suggestion=(
                "TLS certificate verification failed; a proxy or antivirus may be "
                "intercepting HTTPS traffic."
            ),
        )
    return NetworkError(message)


def _utc_now() -> datetime:
    return datetime.now(UTC)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/adapters/test_http.py -v`
Expected: all PASS (the slow-server test takes about one second).

- [ ] **Step 6: Gates and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: clean; the architecture test still passes (`adapters` may import `urllib.request`).

```bash
git add src/utmax/adapters/http.py tests/helpers/fake_transport.py tests/helpers/http_server.py tests/unit/adapters/test_http.py
git commit -m "feat: add the urllib transport with retries, proxies and gzip support

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: InnerTube adapter with client fallback and the watch-page fallback

**Files:**
- Create: `src/utmax/adapters/watch_page.py`, `src/utmax/adapters/innertube.py`
- Test: `tests/unit/adapters/test_watch_page.py`, `tests/unit/adapters/test_innertube.py`

**Interfaces:**
- Consumes: `Transport`, `HttpRequest`, `HttpResponse` (Task 10); `ORDER`, `ANDROID`, `DESKTOP_USER_AGENT`, `ClientProfile`, `Purpose` (Task 8); `parse_player_response`, `PlayerData`, `check_playability` (Task 8); `caption_url`, `check_caption_url` (Task 7); errors (Task 2); `FakeTransport`, `json_response`, `text_response` (Task 11); `player_payload`, `MANUAL_JSON3`, `VIDEO_ID` (Tasks 7–8).
- Produces:
  - `utmax.adapters.watch_page.fetch_api_key(transport, video_id) -> str` and `extract_api_key(html, *, video_id) -> str`.
  - `utmax.adapters.innertube.InnerTubeClient(transport, *, block_retries=0)` with:
    - `player(video_id, *, purpose: Purpose = "captions") -> PlayerData` — tries `ORDER[purpose]`; moves to the next profile on HTTP 4xx≠429 / 5xx (after transport retries), non-JSON bodies, `VideoUnplayable` or `RequestBlocked`; stops at once on `IpBlocked` (429), `VideoUnavailable`, `AgeRestricted`; when every profile failed at the HTTP level, reads the API key from the watch page and retries ANDROID with `?key=`; otherwise raises the first profile's error.
    - `player_json(profile, video_id, *, api_key=None) -> dict[str, Any]` — one raw player response (used by the fixture recorder); raises `IpBlocked` on 429, `YouTubeRequestFailed` on other non-200, `YouTubeDataUnparsable` on non-JSON.
    - `fetch_captions(base_url, *, video_id) -> HttpResponse` — validates the URL, requests `fmt=json3`, maps 429 → `IpBlocked` (with an AI-translation hint for `tlang` URLs) and other non-200 → `YouTubeRequestFailed`.
  - `block_retries` repeats the same request after `RequestBlocked`/`IpBlocked` (urllib opens a new connection each time, which rotates rotating proxies).

- [ ] **Step 1: Write the failing watch-page tests**

`tests/unit/adapters/test_watch_page.py`:

```python
"""Tests for the watch-page fallback."""

from __future__ import annotations

import pytest

from tests.helpers.fake_transport import FakeTransport, text_response
from tests.helpers.youtube import VIDEO_ID
from utmax.adapters.watch_page import extract_api_key, fetch_api_key
from utmax.errors import (
    FailedToCreateConsentCookie,
    IpBlocked,
    YouTubeDataUnparsable,
    YouTubeRequestFailed,
)

WATCH_HTML = '<script>ytcfg.set({"INNERTUBE_API_KEY": "AIzaTestKey_123-abc"});</script>'
CONSENT_HTML = (
    '<form action="https://consent.youtube.com/s" method="POST">'
    '<input type="hidden" name="v" value="cb.20260927-00-p0.en+FX+123"></form>'
)


def test_extract_api_key() -> None:
    assert extract_api_key(WATCH_HTML, video_id=VIDEO_ID) == "AIzaTestKey_123-abc"


def test_a_captcha_means_this_ip_is_blocked() -> None:
    with pytest.raises(IpBlocked):
        extract_api_key('<div class="g-recaptcha" data-sitekey="x"></div>', video_id=VIDEO_ID)


def test_a_page_without_the_key_is_unparsable() -> None:
    with pytest.raises(YouTubeDataUnparsable):
        extract_api_key("<html></html>", video_id=VIDEO_ID)


def test_the_consent_cookie_is_sent_on_the_second_request() -> None:
    transport = FakeTransport()
    transport.add("GET", "/watch?v=", text_response(CONSENT_HTML), text_response(WATCH_HTML))
    assert fetch_api_key(transport, VIDEO_ID) == "AIzaTestKey_123-abc"
    first, second = transport.requests
    assert first.url == f"https://www.youtube.com/watch?v={VIDEO_ID}"
    assert "Cookie" not in first.headers
    assert second.headers["Cookie"] == "CONSENT=YES+cb.20260927-00-p0.en+FX+123"


@pytest.mark.parametrize(
    "pages",
    [
        (CONSENT_HTML, CONSENT_HTML),
        ('<form action="https://consent.youtube.com/s"></form>',),
    ],
)
def test_a_consent_wall_that_cannot_be_passed(pages: tuple[str, ...]) -> None:
    transport = FakeTransport()
    transport.add("GET", "/watch?v=", *(text_response(page) for page in pages))
    with pytest.raises(FailedToCreateConsentCookie):
        fetch_api_key(transport, VIDEO_ID)


@pytest.mark.parametrize(("status", "error"), [(429, IpBlocked), (500, YouTubeRequestFailed)])
def test_watch_page_http_errors(status: int, error: type[Exception]) -> None:
    transport = FakeTransport()
    transport.add("GET", "/watch?v=", text_response("", status=status))
    with pytest.raises(error):
        fetch_api_key(transport, VIDEO_ID)
```

- [ ] **Step 2: Write the failing InnerTube tests** (Review Focus #4)

`tests/unit/adapters/test_innertube.py`:

```python
"""Tests for the InnerTube adapter."""

from __future__ import annotations

import json

import pytest

from tests.helpers.fake_transport import FakeTransport, json_response, text_response
from tests.helpers.youtube import MANUAL_JSON3, VIDEO_ID, player_payload
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.clients import IOS
from utmax.errors import (
    AgeRestricted,
    IpBlocked,
    PoTokenRequired,
    UTMaxError,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeRequestFailed,
)
from utmax.transport import HttpResponse

WATCH_HTML = '<script>ytcfg.set({"INNERTUBE_API_KEY": "AIzaTestKey_123-abc"});</script>'
CAPTION_URL = f"https://www.youtube.com/api/timedtext?v={VIDEO_ID}&lang=en&fmt=srv3"


def client_names(transport: FakeTransport) -> list[str]:
    return [json.loads(r.body or b"{}")["context"]["client"]["clientName"] for r in transport.requests if r.method == "POST"]


def test_player_uses_the_first_profile_when_it_works() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(player_payload()))
    player = InnerTubeClient(transport).player(VIDEO_ID)
    assert player.video.title.startswith("Rick Astley")
    assert len(player.caption_tracks or ()) == 6
    (request,) = transport.requests
    assert request.url == "https://www.youtube.com/youtubei/v1/player?prettyPrint=false"
    body = json.loads(request.body or b"{}")
    assert body["videoId"] == VIDEO_ID
    assert body["contentCheckOk"] is True
    assert body["context"]["client"]["clientName"] == "ANDROID"
    assert request.headers["X-YouTube-Client-Name"] == "3"


@pytest.mark.parametrize(
    "first_reply",
    [
        text_response("bad request", status=400),
        text_response("server error", status=503),
        text_response("<html>not json</html>"),
        json_response(["not", "an", "object"]),
        json_response(player_payload(status="UNPLAYABLE", reason="Not available on this app")),
        json_response(player_payload(status="LOGIN_REQUIRED", reason="Sign in to confirm you're not a bot")),
    ],
)
def test_falls_back_to_the_next_profile(first_reply: HttpResponse) -> None:
    transport = FakeTransport()
    transport.add("POST", "/player", first_reply, json_response(player_payload()))
    assert InnerTubeClient(transport).player(VIDEO_ID).playability.status == "OK"
    assert client_names(transport) == ["ANDROID", "IOS"]


def test_the_first_error_wins_when_every_profile_is_unplayable() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        "/player",
        *(json_response(player_payload(status="UNPLAYABLE", reason=f"reason {i}")) for i in range(3)),
    )
    with pytest.raises(VideoUnplayable, match="reason 0"):
        InnerTubeClient(transport).player(VIDEO_ID)
    assert client_names(transport) == ["ANDROID", "IOS", "ANDROID_VR"]


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (text_response("slow down", status=429), IpBlocked),
        (json_response(player_payload(status="ERROR", reason="This video is unavailable")), VideoUnavailable),
        (json_response(player_payload(status="LOGIN_REQUIRED", reason="Sign in to confirm your age")), AgeRestricted),
    ],
)
def test_final_errors_stop_the_chain(reply: HttpResponse, error: type[UTMaxError]) -> None:
    transport = FakeTransport()
    transport.add("POST", "/player", reply)
    with pytest.raises(error):
        InnerTubeClient(transport).player(VIDEO_ID)
    assert len(transport.requests) == 1


def test_block_retries_repeat_the_same_profile() -> None:
    transport = FakeTransport()
    blocked = text_response("", status=429)
    transport.add("POST", "/player", blocked, blocked, json_response(player_payload()))
    InnerTubeClient(transport, block_retries=2).player(VIDEO_ID)
    assert client_names(transport) == ["ANDROID", "ANDROID", "ANDROID"]


def test_watch_page_fallback_when_every_profile_fails_at_the_http_level() -> None:
    transport = FakeTransport()
    transport.add("POST", "&key=AIzaTestKey_123-abc", json_response(player_payload()))
    transport.add("POST", "/player", *[text_response("forbidden", status=403)] * 3)
    transport.add("GET", "/watch?v=", text_response(WATCH_HTML))
    player = InnerTubeClient(transport).player(VIDEO_ID)
    assert player.playability.status == "OK"
    assert [r.method for r in transport.requests] == ["POST", "POST", "POST", "GET", "POST"]
    assert transport.urls()[-1].endswith("/player?prettyPrint=false&key=AIzaTestKey_123-abc")
    assert client_names(transport)[-1] == "ANDROID"


def test_player_json_returns_the_raw_response_of_one_profile() -> None:
    transport = FakeTransport()
    transport.add("POST", "/player", json_response(player_payload()), text_response("x", status=404))
    client = InnerTubeClient(transport)
    assert client.player_json(IOS, VIDEO_ID)["videoDetails"]["videoId"] == VIDEO_ID
    assert client_names(transport) == ["IOS"]
    with pytest.raises(YouTubeRequestFailed) as caught:
        client.player_json(IOS, VIDEO_ID)
    assert caught.value.status_code == 404


def test_fetch_captions_requests_json3() -> None:
    transport = FakeTransport()
    transport.add("GET", "/api/timedtext", json_response(MANUAL_JSON3))
    response = InnerTubeClient(transport).fetch_captions(CAPTION_URL, video_id=VIDEO_ID)
    assert response.status == 200
    assert transport.urls() == [f"https://www.youtube.com/api/timedtext?v={VIDEO_ID}&lang=en&fmt=json3"]


@pytest.mark.parametrize(
    ("url", "error"),
    [
        ("https://evil.example/api/timedtext?v=x", YouTubeDataUnparsable),
        (f"{CAPTION_URL}&exp=xpe", PoTokenRequired),
    ],
)
def test_fetch_captions_refuses_unsafe_urls_without_a_request(url: str, error: type[UTMaxError]) -> None:
    transport = FakeTransport()
    with pytest.raises(error):
        InnerTubeClient(transport).fetch_captions(url, video_id=VIDEO_ID)
    assert transport.requests == []


def test_caption_rate_limits_and_http_errors() -> None:
    transport = FakeTransport()
    transport.add(
        "GET",
        "/api/timedtext",
        text_response("", status=429),
        text_response("", status=429),
        text_response("", status=404),
    )
    client = InnerTubeClient(transport)
    with pytest.raises(IpBlocked) as plain:
        client.fetch_captions(CAPTION_URL, video_id=VIDEO_ID)
    assert plain.value.suggestion == IpBlocked.suggestion
    with pytest.raises(IpBlocked) as translated:
        client.fetch_captions(f"{CAPTION_URL}&tlang=tr", video_id=VIDEO_ID)
    assert "AI translation" in translated.value.suggestion
    with pytest.raises(YouTubeRequestFailed) as missing:
        client.fetch_captions(CAPTION_URL, video_id=VIDEO_ID)
    assert missing.value.status_code == 404
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/adapters/test_watch_page.py tests/unit/adapters/test_innertube.py -v`
Expected: collection errors (`No module named 'utmax.adapters.watch_page'`, `… 'utmax.adapters.innertube'`).

- [ ] **Step 4: Implement `src/utmax/adapters/watch_page.py`**

```python
"""Last resort: read the InnerTube API key from the watch page, passing the EU consent wall."""

from __future__ import annotations

import re

from utmax.core.clients import DESKTOP_USER_AGENT
from utmax.errors import (
    FailedToCreateConsentCookie,
    IpBlocked,
    YouTubeDataUnparsable,
    YouTubeRequestFailed,
)
from utmax.transport import HttpRequest, Transport

__all__ = ["extract_api_key", "fetch_api_key"]

_WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
_API_KEY = re.compile(r'"INNERTUBE_API_KEY":\s*"([a-zA-Z0-9_-]+)"')
_CONSENT_FORM = 'action="https://consent.youtube.com/s"'
_CONSENT_VALUE = re.compile(r'name="v" value="(.*?)"')
_HEADERS = {
    "User-Agent": DESKTOP_USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
}


def fetch_api_key(transport: Transport, video_id: str) -> str:
    """Download the watch page (accepting cookies for this call only) and read the API key."""
    page = _watch_page(transport, video_id, cookie=None)
    if _CONSENT_FORM in page:
        match = _CONSENT_VALUE.search(page)
        if match is None:
            raise FailedToCreateConsentCookie(
                "Could not read YouTube's cookie-consent form.", video_id=video_id
            )
        page = _watch_page(transport, video_id, cookie=f"CONSENT=YES+{match.group(1)}")
        if _CONSENT_FORM in page:
            raise FailedToCreateConsentCookie(
                "YouTube kept asking for cookie consent.", video_id=video_id
            )
    return extract_api_key(page, video_id=video_id)


def extract_api_key(page: str, *, video_id: str) -> str:
    """The ``INNERTUBE_API_KEY`` embedded in a watch page."""
    match = _API_KEY.search(page)
    if match is not None:
        return match.group(1)
    if 'class="g-recaptcha"' in page:
        raise IpBlocked("YouTube answered with a CAPTCHA page.", video_id=video_id)
    raise YouTubeDataUnparsable(
        "Could not find the InnerTube API key on the watch page.", video_id=video_id
    )


def _watch_page(transport: Transport, video_id: str, *, cookie: str | None) -> str:
    headers = dict(_HEADERS)
    if cookie is not None:
        headers["Cookie"] = cookie
    response = transport.send(HttpRequest("GET", _WATCH_URL.format(video_id=video_id), headers))
    if response.status == 429:
        raise IpBlocked("YouTube rate-limited the watch page request (HTTP 429).", video_id=video_id)
    if response.status != 200:
        raise YouTubeRequestFailed(
            f"The watch page answered HTTP {response.status}.",
            status_code=response.status,
            video_id=video_id,
        )
    return response.text
```

- [ ] **Step 5: Implement `src/utmax/adapters/innertube.py`**

```python
"""InnerTube (YouTube's internal API): player requests with client fallback, and captions."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from functools import partial
from typing import Any, TypeVar

from utmax.adapters.watch_page import fetch_api_key
from utmax.core.captions import caption_url, check_caption_url
from utmax.core.clients import ANDROID, DESKTOP_USER_AGENT, ORDER, ClientProfile, Purpose
from utmax.core.playability import check_playability
from utmax.core.player import PlayerData, parse_player_response
from utmax.errors import (
    IpBlocked,
    RequestBlocked,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeError,
    YouTubeRequestFailed,
)
from utmax.transport import HttpRequest, HttpResponse, Transport

__all__ = ["API_BASE", "InnerTubeClient"]

API_BASE = "https://www.youtube.com/youtubei/v1"
log = logging.getLogger("utmax.youtube")
T = TypeVar("T")

_HTTP_LEVEL_FAILURES = (YouTubeRequestFailed, YouTubeDataUnparsable)


class InnerTubeClient:
    """Talks to InnerTube with a chain of client profiles (see ``utmax.core.clients``)."""

    def __init__(self, transport: Transport, *, block_retries: int = 0) -> None:
        self._transport = transport
        self._block_retries = block_retries

    def player(self, video_id: str, *, purpose: Purpose = "captions") -> PlayerData:
        """A playable player response, trying each profile for ``purpose`` in order."""
        profiles = ORDER[purpose]
        failures: list[YouTubeError] = []
        http_failures = 0
        for profile in profiles:
            try:
                return self._with_block_retries(partial(self._playable, profile, video_id, None))
            except _HTTP_LEVEL_FAILURES as error:
                http_failures += 1
                failures.append(error)
            except (VideoUnplayable, RequestBlocked) as error:
                if isinstance(error, IpBlocked):
                    raise
                failures.append(error)
            log.info("InnerTube client %s failed for %s: %s", profile.name, video_id, failures[-1])
        if http_failures == len(profiles):
            log.info("every InnerTube client failed at the HTTP level; trying the watch page")
            api_key = fetch_api_key(self._transport, video_id)
            return self._with_block_retries(partial(self._playable, ANDROID, video_id, api_key))
        raise failures[0]

    def player_json(
        self, profile: ClientProfile, video_id: str, *, api_key: str | None = None
    ) -> dict[str, Any]:
        """The raw player response of one profile (low level; used by the fixture recorder)."""
        url = f"{API_BASE}/player?prettyPrint=false"
        if api_key is not None:
            url += f"&key={api_key}"
        payload = {
            "context": profile.context_payload(),
            "videoId": video_id,
            "contentCheckOk": True,
            "racyCheckOk": True,
        }
        body = json.dumps(payload).encode("utf-8")
        response = self._transport.send(HttpRequest("POST", url, profile.request_headers(), body))
        return _json_object(response, video_id=video_id)

    def fetch_captions(self, base_url: str, *, video_id: str) -> HttpResponse:
        """Download a caption track as json3."""
        check_caption_url(base_url, video_id=video_id)
        url = caption_url(base_url, fmt="json3")
        return self._with_block_retries(partial(self._caption_response, url, video_id))

    def _playable(self, profile: ClientProfile, video_id: str, api_key: str | None) -> PlayerData:
        data = self.player_json(profile, video_id, api_key=api_key)
        player = parse_player_response(data, video_id=video_id)
        check_playability(player.playability, video_id=video_id)
        return player

    def _caption_response(self, url: str, video_id: str) -> HttpResponse:
        headers = {
            "User-Agent": DESKTOP_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip",
        }
        response = self._transport.send(HttpRequest("GET", url, headers))
        if response.status == 429:
            hint = (
                "YouTube's own translation is heavily rate-limited; use AI translation or a proxy."
                if "tlang=" in url
                else None
            )
            raise IpBlocked(
                "YouTube rate-limited the caption download (HTTP 429).",
                video_id=video_id,
                suggestion=hint,
            )
        if response.status != 200:
            raise YouTubeRequestFailed(
                f"The caption download answered HTTP {response.status}.",
                status_code=response.status,
                video_id=video_id,
            )
        return response

    def _with_block_retries(self, action: Callable[[], T]) -> T:
        attempt = 0
        while True:
            try:
                return action()
            except RequestBlocked as error:
                if attempt >= self._block_retries:
                    raise
                attempt += 1
                log.info("blocked by YouTube (%s); retry %d/%d", error, attempt, self._block_retries)


def _json_object(response: HttpResponse, *, video_id: str) -> dict[str, Any]:
    if response.status == 429:
        raise IpBlocked("YouTube rate-limited this IP address (HTTP 429).", video_id=video_id)
    if response.status != 200:
        raise YouTubeRequestFailed(
            f"InnerTube answered HTTP {response.status}.",
            status_code=response.status,
            video_id=video_id,
        )
    try:
        data = response.json()
    except ValueError:
        raise YouTubeDataUnparsable(
            "InnerTube returned a response that is not JSON.", video_id=video_id
        ) from None
    if not isinstance(data, dict):
        raise YouTubeDataUnparsable("InnerTube returned an unexpected JSON value.", video_id=video_id)
    return data
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/adapters/test_watch_page.py tests/unit/adapters/test_innertube.py -v`
Expected: all PASS.

- [ ] **Step 7: Gates and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: clean.

```bash
git add src/utmax/adapters/watch_page.py src/utmax/adapters/innertube.py tests/unit/adapters
git commit -m "feat: talk to InnerTube with client fallback, block retries and the watch-page fallback

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Transcript service, `Client` and the `utmax` facade

**Files:**
- Create: `src/utmax/services/__init__.py`, `src/utmax/services/transcripts.py`, `src/utmax/client.py`
- Modify: `src/utmax/__init__.py` (full facade), `tests/helpers/youtube.py` (append `standard_youtube`)
- Test: `tests/unit/services/__init__.py`, `tests/unit/services/test_transcripts.py`, `tests/unit/test_client.py`, `tests/unit/test_facade.py`

**Interfaces:**
- Consumes: `InnerTubeClient` (Task 12); `UrllibTransport`, `RetryingTransport` (Task 11); `parse_video_id` (Task 4); `parse_captions` (Task 7); `Track`, `TrackList`, `Transcript`, `VideoInfo` (Task 3); `TrackList.find` (Task 9); `Track.translate` (Task 7).
- Produces:
  - `utmax.services.transcripts.TranscriptService(innertube)` implementing `TrackFetcher`: `list_tracks(video) -> TrackList`, `fetch(video, languages=None, *, include_manual=True, include_generated=True, preserve_formatting=False, youtube_translation=None) -> Transcript`, `video_info(video) -> VideoInfo`, `fetch_track(track, *, preserve_formatting) -> Transcript`.
  - `utmax.client.Client(*, proxy=None, timeout=30.0, retries=2, block_retries=0, transport=None)` with the same `fetch`, `list_tracks`, `video_info` plus `close()` and context-manager support.
  - `utmax.fetch`, `utmax.list_tracks`, `utmax.video_info` bound to a lazily created, lock-protected default `Client`; `utmax.__all__` lists the public API (functions, `Client`, models, errors, `__version__`).
  - Test helper `tests.helpers.youtube.standard_youtube(*, repeat=False) -> FakeTransport`.
- Rules: videos without usable caption tracks raise `TranscriptsDisabled`; `youtube_translation` runs `Track.translate` explicitly and marks the result `translated_from=<source code>`, `translator="youtube"`.

- [ ] **Step 1: Append `standard_youtube` to `tests/helpers/youtube.py`**

Add this import at the top of the file (below `from typing import Any`):

```python
from tests.helpers.fake_transport import FakeTransport, json_response
```

and append:

```python
def standard_youtube(*, repeat: bool = False) -> FakeTransport:
    """A FakeTransport serving one playable video with the default tracks.

    Caption routes: manual English (``lang=en&fmt=json3``), auto English (``kind=asr``) and
    German (``lang=de-DE``). With ``repeat=True`` every route answers forever (thread tests).
    """
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(player_payload()), repeat=repeat)
    transport.add("GET", "lang=en&fmt=json3", json_response(MANUAL_JSON3), repeat=repeat)
    transport.add("GET", "kind=asr", json_response(ASR_JSON3), repeat=repeat)
    transport.add(
        "GET", "lang=de-DE", json_response(json3_payload((1000, 2000, "Wir sind keine Fremden"))), repeat=repeat
    )
    return transport
```

- [ ] **Step 2: Write the failing service tests** (Review Focus #3)

`tests/unit/services/__init__.py`:

```python
"""Tests for the services layer."""
```

`tests/unit/services/test_transcripts.py`:

```python
"""Tests for the transcript service (InnerTube faked, everything else real)."""

from __future__ import annotations

import pytest

from tests.helpers.fake_transport import FakeTransport, json_response
from tests.helpers.youtube import ASR_JSON3, VIDEO_ID, json3_payload, player_payload, standard_youtube
from utmax.adapters.innertube import InnerTubeClient
from utmax.errors import InvalidVideoId, NoTranscriptFound, TranscriptsDisabled
from utmax.services.transcripts import TranscriptService


def service(transport: FakeTransport) -> TranscriptService:
    return TranscriptService(InnerTubeClient(transport))


def test_list_tracks_returns_bound_tracks_in_youtube_order() -> None:
    tracks = service(standard_youtube()).list_tracks(f"https://youtu.be/{VIDEO_ID}")
    assert [track.language_code for track in tracks] == ["en", "en", "de-DE", "ja", "pt-BR", "es-419"]
    assert tracks.video.title.startswith("Rick Astley")
    assert [language.code for language in tracks.translation_languages] == ["tr", "de"]
    assert tracks[0].fetch().segments[1].text == "♪ We're no strangers to love ♪"


def test_fetch_defaults_to_the_spoken_language_manual_track() -> None:
    transport = standard_youtube()
    transcript = service(transport).fetch(VIDEO_ID)
    assert (transcript.language_code, transcript.language, transcript.is_generated) == ("en", "English", False)
    assert transcript.segments[1].text == "♪ We're no strangers to love ♪"
    assert transcript.translated_from is None
    assert transport.urls("GET") == [f"https://www.youtube.com/api/timedtext?v={VIDEO_ID}&lang=en&fmt=json3"]


def test_base_language_match() -> None:
    transcript = service(standard_youtube()).fetch(VIDEO_ID, languages=["de"])
    assert (transcript.language_code, transcript.text) == ("de-DE", "Wir sind keine Fremden")


def test_language_order_never_falls_back_to_youtube_translation() -> None:
    transport = standard_youtube()
    assert service(transport).fetch(VIDEO_ID, languages=["tr", "en"]).language_code == "en"
    assert not any("tlang=" in url for url in transport.urls())


def test_explicit_youtube_translation_is_marked() -> None:
    transport = standard_youtube()
    transport.add("GET", "tlang=tr", json_response(json3_payload((18640, 3240, "Aşka yabancı değiliz"))))
    transcript = service(transport).fetch(VIDEO_ID, youtube_translation="tr")
    assert (transcript.language_code, transcript.language) == ("tr", "Turkish")
    assert (transcript.translated_from, transcript.translator) == ("en", "youtube")
    assert transcript.text == "Aşka yabancı değiliz"


def test_videos_with_only_auto_captions_use_them() -> None:
    transport = FakeTransport()
    only_auto = (("en", "English (auto-generated)", True),)
    transport.add("POST", "/player", json_response(player_payload(tracks=only_auto)))
    transport.add("GET", "kind=asr", json_response(ASR_JSON3))
    transcript = service(transport).fetch(VIDEO_ID)
    assert transcript.is_generated
    assert transcript.segments[0].text == "[Music]"
    assert transcript.segments[1].words


def test_missing_languages_list_what_is_available() -> None:
    with pytest.raises(NoTranscriptFound) as caught:
        service(standard_youtube()).fetch(VIDEO_ID, languages="ko")
    assert caught.value.requested == ("ko",)
    assert "de-DE (German (Germany), manual)" in str(caught.value)


def test_videos_without_captions_raise_transcripts_disabled() -> None:
    transport = FakeTransport()
    transport.add("POST", "/player", json_response(player_payload(captions=False)))
    with pytest.raises(TranscriptsDisabled) as caught:
        service(transport).fetch(VIDEO_ID)
    assert caught.value.video_id == VIDEO_ID


def test_video_info_works_without_captions() -> None:
    transport = FakeTransport()
    transport.add("POST", "/player", json_response(player_payload(captions=False)))
    info = service(transport).video_info(f"https://www.youtube.com/watch?v={VIDEO_ID}")
    assert (info.video_id, info.channel, info.duration) == (VIDEO_ID, "Rick Astley", 213.0)


def test_invalid_input_never_reaches_the_network() -> None:
    transport = FakeTransport()
    with pytest.raises(InvalidVideoId):
        service(transport).fetch("not a video")
    assert transport.requests == []


def test_preserve_formatting_reaches_the_parser() -> None:
    styled = {
        "pens": [{}, {"iAttr": 1}],
        "events": [{"tStartMs": 0, "dDurationMs": 900, "segs": [{"utf8": "so "}, {"utf8": "cool", "pPenId": 1}]}],
    }
    transport = FakeTransport()
    transport.add("POST", "/player", json_response(player_payload()))
    transport.add("GET", "lang=en&fmt=json3", json_response(styled))
    transcript = service(transport).fetch(VIDEO_ID, preserve_formatting=True)
    assert transcript.text == "so <i>cool</i>"
```

- [ ] **Step 3: Write the failing client and facade tests**

`tests/unit/test_client.py`:

```python
"""Tests for utmax.Client."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.helpers.fake_transport import FakeTransport, json_response, text_response
from tests.helpers.youtube import MANUAL_JSON3, VIDEO_ID, player_payload, standard_youtube
from utmax import Client
from utmax.errors import InvalidOption


@pytest.mark.parametrize(
    "options",
    [
        {"timeout": 0},
        {"retries": -1},
        {"block_retries": -1},
        {"proxy": "http://proxy.example:8080", "transport": FakeTransport()},
        {"proxy": "socks5://127.0.0.1:1080"},
    ],
)
def test_bad_options_are_rejected(options: dict[str, object]) -> None:
    with pytest.raises(InvalidOption):
        Client(**options)  # type: ignore[arg-type]


def test_client_fetches_and_is_a_context_manager() -> None:
    with Client(transport=standard_youtube(repeat=True)) as client:
        assert client.fetch(VIDEO_ID).segments[1].text == "♪ We're no strangers to love ♪"
        assert client.list_tracks(VIDEO_ID).video.video_id == VIDEO_ID
        assert client.video_info(VIDEO_ID).title.startswith("Rick Astley")


def test_one_client_is_safe_to_share_between_threads() -> None:
    client = Client(transport=standard_youtube(repeat=True))
    with ThreadPoolExecutor(max_workers=8) as pool:
        texts = list(pool.map(lambda _: client.fetch(VIDEO_ID).text, range(32)))
    assert len(texts) == 32
    assert len(set(texts)) == 1


def test_block_retries_reach_innertube() -> None:
    transport = FakeTransport()
    transport.add("POST", "/player", text_response("", status=429), json_response(player_payload()))
    transport.add("GET", "lang=en&fmt=json3", json_response(MANUAL_JSON3))
    assert Client(transport=transport, block_retries=1).fetch(VIDEO_ID).language_code == "en"
```

`tests/unit/test_facade.py`:

```python
"""Tests for the module-level facade."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

import utmax
from tests.helpers.fake_transport import FakeTransport
from tests.helpers.youtube import VIDEO_ID, standard_youtube


def test_every_public_name_exists() -> None:
    for name in utmax.__all__:
        assert hasattr(utmax, name), name
    assert {"fetch", "list_tracks", "video_info", "Client", "Transcript", "NoTranscriptFound"} <= set(utmax.__all__)


def test_module_functions_use_the_default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(utmax, "_default_client", utmax.Client(transport=standard_youtube(repeat=True)))
    assert utmax.fetch(f"https://youtu.be/{VIDEO_ID}").segments[1].text == "♪ We're no strangers to love ♪"
    assert len(utmax.list_tracks(VIDEO_ID)) == 6
    assert utmax.video_info(VIDEO_ID).channel == "Rick Astley"


def test_the_default_client_is_created_once_under_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[utmax.Client] = []

    class CountingClient(utmax.Client):
        def __init__(self) -> None:
            created.append(self)
            super().__init__(transport=FakeTransport())

    monkeypatch.setattr(utmax, "_default_client", None)
    monkeypatch.setattr(utmax, "Client", CountingClient)
    with ThreadPoolExecutor(max_workers=8) as pool:
        clients = list(pool.map(lambda _: utmax._client(), range(32)))
    assert len(created) == 1
    assert all(client is created[0] for client in clients)
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/services tests/unit/test_client.py tests/unit/test_facade.py -v`
Expected: collection errors (`No module named 'utmax.services'`, `cannot import name 'Client' from 'utmax'`).

- [ ] **Step 5: Implement the service**

`src/utmax/services/__init__.py`:

```python
"""Services: orchestrate the pure core and the adapters for each feature."""
```

`src/utmax/services/transcripts.py`:

```python
"""List, select and download subtitle tracks."""

from __future__ import annotations

from collections.abc import Sequence

from utmax.adapters.innertube import InnerTubeClient
from utmax.core.captions import parse_captions
from utmax.core.ids import parse_video_id
from utmax.errors import TranscriptsDisabled
from utmax.models import Track, TrackList, Transcript, VideoInfo

__all__ = ["TranscriptService"]


class TranscriptService:
    """Transcript use cases on top of the InnerTube adapter; binds tracks to itself for fetching."""

    def __init__(self, innertube: InnerTubeClient) -> None:
        self._innertube = innertube

    def list_tracks(self, video: str) -> TrackList:
        video_id = parse_video_id(video)
        player = self._innertube.player(video_id, purpose="captions")
        if not player.caption_tracks:
            raise TranscriptsDisabled(f"Video {video_id} has no subtitles.", video_id=video_id)
        tracks = tuple(
            Track(
                video=player.video,
                language_code=info.language_code,
                language=info.name,
                is_generated=info.is_generated,
                is_translatable=info.is_translatable,
                vss_id=info.vss_id,
                _url=info.base_url,
                _translation_languages=player.translation_languages,
                _fetcher=self,
            )
            for info in player.caption_tracks
        )
        return TrackList(
            video=player.video, tracks=tracks, translation_languages=player.translation_languages
        )

    def fetch(
        self,
        video: str,
        languages: Sequence[str] | str | None = None,
        *,
        include_manual: bool = True,
        include_generated: bool = True,
        preserve_formatting: bool = False,
        youtube_translation: str | None = None,
    ) -> Transcript:
        track = self.list_tracks(video).find(
            languages, include_manual=include_manual, include_generated=include_generated
        )
        if youtube_translation is not None:
            track = track.translate(youtube_translation)
        return track.fetch(preserve_formatting=preserve_formatting)

    def video_info(self, video: str) -> VideoInfo:
        return self._innertube.player(parse_video_id(video), purpose="captions").video

    def fetch_track(self, track: Track, *, preserve_formatting: bool) -> Transcript:
        response = self._innertube.fetch_captions(track._url, video_id=track.video_id)
        segments = parse_captions(
            response.body,
            response.content_type,
            is_generated=track.is_generated,
            preserve_formatting=preserve_formatting,
            video_id=track.video_id,
        )
        return Transcript(
            video=track.video,
            language_code=track.language_code,
            language=track.language,
            is_generated=track.is_generated,
            segments=segments,
            translated_from=track.translation_of,
            translator="youtube" if track.translation_of else None,
        )
```

- [ ] **Step 6: Implement `src/utmax/client.py`**

```python
"""The Client: configuration plus one connection pipeline that every call goes through."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Self

from utmax.adapters.http import RetryingTransport, UrllibTransport
from utmax.adapters.innertube import InnerTubeClient
from utmax.errors import InvalidOption
from utmax.models import TrackList, Transcript, VideoInfo
from utmax.services.transcripts import TranscriptService
from utmax.transport import Transport

__all__ = ["Client"]


class Client:
    """A configured, thread-safe connection to YouTube.

    Module-level functions such as :func:`utmax.fetch` share a default ``Client``. Create your
    own for a proxy, timeouts or a retry policy::

        with utmax.Client(proxy="http://user:pass@host:8080", timeout=20) as client:
            transcript = client.fetch("dQw4w9WgXcQ")

    Args:
        proxy: ``http://[user:password@]host:port`` used for all YouTube traffic.
        timeout: seconds before a request is abandoned.
        retries: extra attempts for timeouts, connection resets and HTTP 408/5xx.
        block_retries: extra attempts, each on a new connection, when YouTube blocks the IP
            (useful with rotating proxies).
        transport: a custom :class:`utmax.transport.Transport` replacing the whole HTTP stack;
            ``timeout`` and ``retries`` are then ignored and ``proxy`` must not be set.
    """

    def __init__(
        self,
        *,
        proxy: str | None = None,
        timeout: float = 30.0,
        retries: int = 2,
        block_retries: int = 0,
        transport: Transport | None = None,
    ) -> None:
        if timeout <= 0:
            raise InvalidOption("timeout must be a positive number of seconds.")
        if retries < 0 or block_retries < 0:
            raise InvalidOption("retries and block_retries cannot be negative.")
        if transport is not None and proxy is not None:
            raise InvalidOption(
                "Pass either proxy= or transport=, not both; configure the proxy in your transport."
            )
        if transport is None:
            transport = RetryingTransport(UrllibTransport(proxy=proxy, timeout=timeout), retries=retries)
        self._transcripts = TranscriptService(InnerTubeClient(transport, block_retries=block_retries))

    def fetch(
        self,
        video: str,
        languages: Sequence[str] | str | None = None,
        *,
        include_manual: bool = True,
        include_generated: bool = True,
        preserve_formatting: bool = False,
        youtube_translation: str | None = None,
    ) -> Transcript:
        """Fetch the best subtitle track of ``video``; see :func:`utmax.fetch`."""
        return self._transcripts.fetch(
            video,
            languages,
            include_manual=include_manual,
            include_generated=include_generated,
            preserve_formatting=preserve_formatting,
            youtube_translation=youtube_translation,
        )

    def list_tracks(self, video: str) -> TrackList:
        """Every subtitle track of ``video``, in YouTube's order."""
        return self._transcripts.list_tracks(video)

    def video_info(self, video: str) -> VideoInfo:
        """Title, channel and duration of ``video``."""
        return self._transcripts.video_info(video)

    def close(self) -> None:
        """Release resources; utmax keeps no open connections today, so this does nothing yet."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
```

- [ ] **Step 7: Replace `src/utmax/__init__.py` with the full facade**

```python
"""u-transcript max: YouTube transcripts, AI translation and downloads with zero dependencies.

Quick start::

    import utmax

    transcript = utmax.fetch("https://youtu.be/dQw4w9WgXcQ")
    transcript.save("rick.srt")
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence

from utmax._version import __version__
from utmax.client import Client
from utmax.errors import (
    AgeRestricted,
    FailedToCreateConsentCookie,
    InvalidOption,
    InvalidVideoId,
    IpBlocked,
    NetworkError,
    NoTranscriptFound,
    NotTranslatable,
    PoTokenRequired,
    RequestBlocked,
    TranscriptsDisabled,
    TranslationLanguageNotAvailable,
    UnsupportedFormat,
    UTMaxError,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeError,
    YouTubeRequestFailed,
)
from utmax.models import FormatName, Language, Segment, Track, TrackList, Transcript, VideoInfo, Word

__all__ = [
    "AgeRestricted",
    "Client",
    "FailedToCreateConsentCookie",
    "FormatName",
    "InvalidOption",
    "InvalidVideoId",
    "IpBlocked",
    "Language",
    "NetworkError",
    "NoTranscriptFound",
    "NotTranslatable",
    "PoTokenRequired",
    "RequestBlocked",
    "Segment",
    "Track",
    "TrackList",
    "Transcript",
    "TranscriptsDisabled",
    "TranslationLanguageNotAvailable",
    "UTMaxError",
    "UnsupportedFormat",
    "VideoInfo",
    "VideoUnavailable",
    "VideoUnplayable",
    "Word",
    "YouTubeDataUnparsable",
    "YouTubeError",
    "YouTubeRequestFailed",
    "__version__",
    "fetch",
    "list_tracks",
    "video_info",
]

logging.getLogger("utmax").addHandler(logging.NullHandler())

_default_client: Client | None = None
_default_lock = threading.Lock()


def _client() -> Client:
    """The shared default client, created on first use (thread-safe)."""
    global _default_client  # noqa: PLW0603
    client = _default_client
    if client is None:
        with _default_lock:
            if _default_client is None:
                _default_client = Client()
            client = _default_client
    return client


def fetch(
    video: str,
    languages: Sequence[str] | str | None = None,
    *,
    include_manual: bool = True,
    include_generated: bool = True,
    preserve_formatting: bool = False,
    youtube_translation: str | None = None,
) -> Transcript:
    """Fetch the best subtitle track of a video.

    Args:
        video: a video ID or any YouTube URL (watch, youtu.be, shorts, live, embed …).
        languages: language codes in order of preference, e.g. ``["tr", "en"]``; ``de`` also
            matches ``de-DE``. By default the video's spoken language is used.
        include_manual: consider subtitles written by people.
        include_generated: consider YouTube's auto-generated subtitles.
        preserve_formatting: keep ``<b>``, ``<i>`` and ``<u>`` tags.
        youtube_translation: ask YouTube to machine-translate the chosen track (best effort,
            often rate-limited; AI translation arrives in a later release).

    Manual subtitles win over auto-generated ones, and YouTube's translation is never used
    unless you ask for it.
    """
    return _client().fetch(
        video,
        languages,
        include_manual=include_manual,
        include_generated=include_generated,
        preserve_formatting=preserve_formatting,
        youtube_translation=youtube_translation,
    )


def list_tracks(video: str) -> TrackList:
    """Every subtitle track of a video, in YouTube's order."""
    return _client().list_tracks(video)


def video_info(video: str) -> VideoInfo:
    """Title, channel and duration of a video."""
    return _client().video_info(video)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/services tests/unit/test_client.py tests/unit/test_facade.py -v`
Expected: all PASS.

- [ ] **Step 9: Gates and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: clean; `tests/test_architecture.py` still passes (`import utmax` loads only the standard library).

```bash
git add src/utmax/services src/utmax/client.py src/utmax/__init__.py tests/helpers/youtube.py tests/unit
git commit -m "feat: add the transcript service, Client and the utmax facade

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Recorded fixtures and live tests

**Files:**
- Create: `scripts/record_fixtures.py`, `tests/fixtures/youtube/` (generated), `tests/unit/test_recorded_fixtures.py`, `tests/live/__init__.py`, `tests/live/conftest.py`, `tests/live/test_transcripts_live.py`

**Interfaces:**
- Consumes: `InnerTubeClient.player_json` (Task 12); `UrllibTransport`, `RetryingTransport` (Task 11); `ANDROID`, `IOS`, `ANDROID_VR` (Task 8); `caption_url` (Task 7); parsers and `Client` (Tasks 7–13).
- Produces: redacted fixture files `player_android.json`, `player_ios.json`, `player_android_vr.json`, `json3_en_manual.json`, `json3_en_asr.json` (first 40 events), `legacy_en_manual.xml` (first 12 cues), `srv3_en_asr.xml` (first 16 paragraphs), `README.md`; offline tests over them; live tests (`-m live`) that turn `RequestBlocked` into a skip.
- Redaction: the values of `ei`, `expire`, `ip`, `key`, `lsig`, `sig`, `signature` in every URL become `REDACTED`; player responses keep only `playabilityStatus` (`status`, `reason`), six `videoDetails` fields and `captions`.

- [ ] **Step 1: Write `scripts/record_fixtures.py`**

```python
"""Record trimmed, redacted real YouTube responses into tests/fixtures/youtube/.

Run from the repository root (needs network access):

    uv run python scripts/record_fixtures.py

Re-run when YouTube changes its responses, then review the diff before committing.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from utmax.adapters.http import RetryingTransport, UrllibTransport
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.captions import caption_url
from utmax.core.clients import ANDROID, ANDROID_VR, IOS
from utmax.transport import HttpRequest

VIDEO_ID = "dQw4w9WgXcQ"
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "youtube"
SECRET_PARAMS = frozenset({"ei", "expire", "ip", "key", "lsig", "sig", "signature"})
KEPT_DETAILS = ("videoId", "title", "lengthSeconds", "channelId", "author", "isLiveContent")


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    query = [
        (key, "REDACTED" if key in SECRET_PARAMS else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


def trim_player(data: dict[str, Any]) -> dict[str, Any]:
    status = data.get("playabilityStatus", {})
    details = data.get("videoDetails", {})
    trimmed: dict[str, Any] = {
        "playabilityStatus": {k: status[k] for k in ("status", "reason") if k in status},
        "videoDetails": {k: details[k] for k in KEPT_DETAILS if k in details},
    }
    renderer = data.get("captions", {}).get("playerCaptionsTracklistRenderer")
    if renderer:
        renderer = json.loads(json.dumps(renderer))
        for track in renderer.get("captionTracks", []):
            track["baseUrl"] = redact_url(track["baseUrl"])
        trimmed["captions"] = {"playerCaptionsTracklistRenderer": renderer}
    return trimmed


def first_elements(xml: str, tag: str, count: int, *, head_end: str, tail: str) -> str:
    head = xml[: xml.index(head_end) + len(head_end)]
    elements = re.findall(rf"<{tag}\b.*?</{tag}>", xml, flags=re.DOTALL)[:count]
    return head + "\n".join(elements) + tail


def write(name: str, content: str) -> None:
    path = OUT / name
    path.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {path.name} ({len(content)} characters)")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    transport = RetryingTransport(UrllibTransport(timeout=30.0))
    innertube = InnerTubeClient(transport)
    players: dict[str, dict[str, Any]] = {}
    for profile, name in ((ANDROID, "android"), (IOS, "ios"), (ANDROID_VR, "android_vr")):
        players[name] = innertube.player_json(profile, VIDEO_ID)
        write(f"player_{name}.json", json.dumps(trim_player(players[name]), ensure_ascii=False, indent=1) + "\n")

    tracks = players["android"]["captions"]["playerCaptionsTracklistRenderer"]["captionTracks"]
    manual = next(t for t in tracks if t.get("kind") != "asr" and t["languageCode"] == "en")
    auto = next(t for t in tracks if t.get("kind") == "asr")

    def download(url: str) -> str:
        response = transport.send(HttpRequest("GET", url, {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"}))
        if response.status != 200:
            raise SystemExit(f"caption download failed with HTTP {response.status}")
        return response.text

    manual_json3 = json.loads(download(caption_url(manual["baseUrl"], fmt="json3")))
    write("json3_en_manual.json", json.dumps(manual_json3, ensure_ascii=False, indent=1) + "\n")
    auto_json3 = json.loads(download(caption_url(auto["baseUrl"], fmt="json3")))
    auto_json3["events"] = auto_json3["events"][:40]
    write("json3_en_asr.json", json.dumps(auto_json3, ensure_ascii=False, indent=1) + "\n")
    legacy = download(caption_url(manual["baseUrl"], fmt=None))
    write("legacy_en_manual.xml", first_elements(legacy, "text", 12, head_end="<transcript>", tail="</transcript>\n"))
    srv3 = download(caption_url(auto["baseUrl"], fmt="srv3"))
    write("srv3_en_asr.xml", first_elements(srv3, "p", 16, head_end="<body>", tail="\n</body></timedtext>\n"))
    write(
        "README.md",
        f"# YouTube fixtures\n\nRecorded {date.today().isoformat()} from video `{VIDEO_ID}` with\n"
        "`uv run python scripts/record_fixtures.py`. URL parameters "
        f"{', '.join(sorted(SECRET_PARAMS))} are replaced with `REDACTED`.\n",
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Record the fixtures and inspect them**

Run: `uv run python scripts/record_fixtures.py`
Expected: eight `wrote …` lines. Then run `git diff --stat` and open `tests/fixtures/youtube/player_android.json`: confirm six caption tracks, `REDACTED` in every `baseUrl` for `ei`/`expire`/`ip`/`key`/`signature`, and no other personal data. If YouTube answers `LOGIN_REQUIRED … not a bot`, run it again later or from another network; do not commit a blocked response.

- [ ] **Step 3: Write the tests over the recorded fixtures**

`tests/unit/test_recorded_fixtures.py`:

```python
"""Offline tests over real, redacted YouTube responses (see scripts/record_fixtures.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.helpers.fake_transport import FakeTransport, json_response
from utmax import Client
from utmax.core.captions import parse_json3, parse_xml
from utmax.core.player import parse_player_response
from utmax.core.segmentation import merge_sentences

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "youtube"
VIDEO_ID = "dQw4w9WgXcQ"
SECOND_LINE = "♪ We're no strangers to love ♪"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["player_android.json", "player_ios.json", "player_android_vr.json"])
def test_every_profile_lists_the_same_six_tracks(name: str) -> None:
    player = parse_player_response(load(name), video_id=VIDEO_ID)
    assert player.playability.status == "OK"
    assert "Never Gonna Give You Up" in player.video.title
    assert player.video.channel == "Rick Astley"
    tracks = player.caption_tracks or ()
    assert [track.language_code for track in tracks] == ["en", "en", "de-DE", "ja", "pt-BR", "es-419"]
    assert [track.is_generated for track in tracks] == [False, True, False, False, False, False]
    assert all("REDACTED" in track.base_url for track in tracks)


def test_only_android_and_ios_list_translation_languages() -> None:
    assert parse_player_response(load("player_android.json"), video_id=VIDEO_ID).translation_languages
    assert parse_player_response(load("player_ios.json"), video_id=VIDEO_ID).translation_languages
    assert parse_player_response(load("player_android_vr.json"), video_id=VIDEO_ID).translation_languages == ()


def test_manual_json3() -> None:
    segments = parse_json3(load("json3_en_manual.json"), is_generated=False)
    assert segments[1].text == SECOND_LINE
    assert (segments[1].start, segments[1].duration) == (18.64, 3.24)
    assert "\n" in segments[2].text
    assert all(not segment.words for segment in segments)


def test_auto_json3_has_words_and_merges_cleanly() -> None:
    segments = parse_json3(load("json3_en_asr.json"), is_generated=True)
    assert segments[0].text == "[Music]"
    assert all(segment.text and segment.words for segment in segments)
    merged = merge_sentences(segments)
    assert merged
    assert all(segment.text for segment in merged)
    for current, following in zip(merged, merged[1:], strict=False):
        assert current.start <= following.start
        assert current.end <= following.start + 1e-9


def test_legacy_and_srv3_xml() -> None:
    legacy = parse_xml((FIXTURES / "legacy_en_manual.xml").read_text(encoding="utf-8"), is_generated=False)
    assert legacy[1].text == SECOND_LINE
    srv3 = parse_xml((FIXTURES / "srv3_en_asr.xml").read_text(encoding="utf-8"), is_generated=True)
    assert srv3[0].text == "[Music]"
    assert any(len(segment.words) > 1 for segment in srv3)


def test_end_to_end_over_recorded_responses() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(load("player_android.json")))
    transport.add("GET", "/api/timedtext", json_response(load("json3_en_manual.json")))
    transcript = Client(transport=transport).fetch(f"https://youtu.be/{VIDEO_ID}")
    assert (transcript.language_code, transcript.is_generated) == ("en", False)
    assert transcript.segments[1].text == SECOND_LINE
```

- [ ] **Step 4: Write the live tests**

`tests/live/__init__.py`:

```python
"""Live tests against the real YouTube API (run with `uv run pytest -m live`)."""
```

`tests/live/conftest.py`:

```python
"""Treat YouTube blocking this machine's IP as a skip, not a failure (cloud CI runners)."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from utmax.errors import RequestBlocked


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, object, object]:
    try:
        return (yield)
    except RequestBlocked as error:
        pytest.skip(f"YouTube is blocking this IP address: {error}")
```

`tests/live/test_transcripts_live.py`:

```python
"""Live acceptance checks (spec §8.10) on dQw4w9WgXcQ."""

from __future__ import annotations

from pathlib import Path

import pytest

import utmax
from utmax.adapters.http import RetryingTransport, UrllibTransport
from utmax.transport import HttpRequest, HttpResponse

pytestmark = pytest.mark.live

VIDEO = "dQw4w9WgXcQ"


class RecordingTransport:
    def __init__(self) -> None:
        self.inner = RetryingTransport(UrllibTransport())
        self.urls: list[str] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.urls.append(request.url)
        return self.inner.send(request)


def test_default_fetch_returns_the_manual_english_track() -> None:
    transcript = utmax.fetch(f"https://youtu.be/{VIDEO}")
    assert (transcript.language_code, transcript.is_generated) == ("en", False)
    assert transcript.segments[1].text == "♪ We're no strangers to love ♪"


def test_language_order_never_uses_youtube_translation() -> None:
    transport = RecordingTransport()
    transcript = utmax.Client(transport=transport).fetch(VIDEO, languages=["tr", "en"])
    assert (transcript.language_code, transcript.is_generated) == ("en", False)
    assert not any("tlang=" in url for url in transport.urls)


def test_base_language_match() -> None:
    assert utmax.fetch(VIDEO, languages=["de"]).language_code == "de-DE"


def test_list_tracks() -> None:
    tracks = utmax.list_tracks(VIDEO)
    assert len(tracks) == 6
    english = [track for track in tracks if track.language_code == "en"]
    assert sorted(track.is_generated for track in english) == [False, True]
    assert tracks.video.title


def test_auto_track_merges_into_ordered_cues() -> None:
    auto = utmax.fetch(VIDEO, include_manual=False)
    merged = auto.merge_sentences()
    assert merged
    assert auto.is_generated
    for current, following in zip(merged, merged[1:], strict=False):
        assert current.end <= following.start + 1e-9


def test_every_format_saves_as_utf8(tmp_path: Path) -> None:
    transcript = utmax.fetch(VIDEO)
    for name in ("r.srt", "r.vtt", "r.json", "r.txt"):
        data = transcript.save(tmp_path / name).read_bytes()
        assert "♪".encode() in data
        assert b"\r\n" not in data
```

- [ ] **Step 5: Run the offline and live suites**

Run: `uv run pytest tests/unit/test_recorded_fixtures.py -v`
Expected: all PASS.

Run: `uv run pytest -m live -v`
Expected: 6 passed (or skipped with "YouTube is blocking this IP address" on a blocked network).

Run: `uv run pytest`
Expected: the default run excludes live tests (`deselected` count shown) and passes.

- [ ] **Step 6: Gates and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: clean.

```bash
git add scripts tests/fixtures tests/unit/test_recorded_fixtures.py tests/live
git commit -m "test: record redacted YouTube fixtures and add live acceptance tests

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 15: M1 verification and CI

**Files:**
- Modify: only files that the checks below prove wrong.

**Interfaces:**
- Consumes: everything above.
- Produces: evidence that M1 meets its acceptance criteria (spec §9): gates green on Linux and Windows, core coverage ≥ 95 %, the 8-thread test, live transcript checks, a wheel that contains only `utmax/`.

- [ ] **Step 1: Run every gate locally**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov --cov-report=term-missing
uv run coverage report --include="*/utmax/core/*" --fail-under=95
```

Expected: no lint or type errors; all tests pass; total coverage ≥ 90 % (the run fails otherwise because of `fail_under`); core coverage ≥ 95 %. If a line is uncovered, add a test for the behaviour it implements rather than excluding it.

- [ ] **Step 2: Run the live checks**

Run: `uv run pytest -m live -v`
Expected: 6 passed. If they are skipped because YouTube blocks the network, say so in the report instead of claiming they passed.

- [ ] **Step 3: Verify packaging from a clean environment**

Run:

```bash
uv build
uvx twine check --strict dist/*
uv run --no-project python -c "import glob, zipfile; names = zipfile.ZipFile(glob.glob('dist/*.whl')[0]).namelist(); bad = [n for n in names if not n.startswith(('utmax/', 'u_transcript_max-'))]; print(bad); assert not bad"
uv run --isolated --no-project --with dist/u_transcript_max-0.1.0.dev0-py3-none-any.whl python -c "import utmax, sys; print(utmax.__version__); print(sorted(m for m in sys.modules if m.startswith('utmax')))"
```

Expected: `PASSED` for both distributions; `[]`; the version `0.1.0.dev0` followed by the loaded `utmax` modules.

- [ ] **Step 4: Ask before pushing, then watch CI**

Ask the user for approval to push branch `v4` to `origin` (the CI matrix covers Linux, Windows and macOS). Only after an explicit yes:

```bash
git push -u origin v4
gh run watch --exit-status
```

Expected: `lint`, every `test (…)` job and `build` succeed. If a job fails, reproduce it locally, fix it, commit and push again (the push was already approved for this branch in this step).

- [ ] **Step 5: Report**

Summarise for the user: test counts, total and core coverage, live-test outcome (passed or skipped and why), CI result or that the push is still awaiting approval, and anything deferred.

---

## Out of scope for M1 (later milestones, per the spec)

- `Client(force_ipv4=...)`, stream selection, the parallel downloader, `core/filenames.py` → M4.
- `core/languages.py`, the MP4/MOV muxer → M3.
- AI translation, `utmax.translate`/`translator`/`bilingual`, provider extras in `pyproject.toml` → M2.
- Playlist/channel listing and bulk helpers → M5; `utmax.compat` → M6; MCP server and the `mcp` extra → M7.
- The real README, `CHANGELOG.md`, `CONTRIBUTING.md`, `live.yml`, `release.yml`, version `0.1.0` → M8.
