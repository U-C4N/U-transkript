# CLAUDE.md

Guidance for AI coding agents working in this repository.

## Project
u-transcript max — PyPI `u-transcript-max`, import `utmax`.
Design: `docs/design/2026-09-27-u-transcript-max-design.md`; the current release: `docs/design/2026-11-09-v0.2.0-design.md`. Milestone plans: `docs/design/plans/`. Changes: `CHANGELOG.md`.

## Rules
- Zero runtime dependencies: only the standard library in `src/utmax`; the optional extras (AI providers, MCP) are imported lazily.
- Layers: interfaces (`utmax/__init__.py`, `client.py`) → `services/` → `core/` (pure, no I/O) + `adapters/` (all I/O). `tests/test_architecture.py` enforces core purity.
- `models.py` is the shared data kernel: `core` may import it; it imports `core` only inside methods.
- The library never prints; log with `logging.getLogger("utmax.<area>")`.
- Text files are UTF-8 with `\n` line endings, written atomically.
- Everything (code, docs, commits) is in English. Python ≥ 3.11, `mypy --strict`, absolute imports.
- Every user-visible change gets a line in `CHANGELOG.md`.

## Commands
- `uv sync --all-extras` — create the environment (without the extras, mypy and the provider and MCP tests cannot run)
- `uv run pytest` — offline tests; `uv run pytest -m live` — live YouTube tests; `uv run pytest -m ffmpeg` — needs ffmpeg and ffprobe
- `uv run ruff check . && uv run ruff format --check . && uv run mypy`
