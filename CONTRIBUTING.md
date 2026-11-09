# Contributing

Thanks for helping with u-transcript max. Issues and pull requests are welcome at
[github.com/U-C4N/U-transkript](https://github.com/U-C4N/U-transkript).

## Set up

You need [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer.

```bash
git clone https://github.com/U-C4N/U-transkript
cd U-transkript
uv sync --all-extras   # the extras are needed for mypy and the provider and MCP tests
```

## Check your change

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest                 # offline; no network, keys or ffmpeg needed
```

Some tests need more:

- **Live tests:** `uv run pytest -m live` talks to YouTube, and the translation tests run
  only for provider keys you have set (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`,
  `OPENAI_API_KEY`, `OPENROUTER_API_KEY`). Cloud machines are often blocked by YouTube, so run
  them from home. `UTMAX_LIVE_<PROVIDER>_MODEL` picks another model, such as
  `UTMAX_LIVE_GEMINI_MODEL=gemini-4-argon`.
- **ffmpeg tests:** `uv run pytest -m ffmpeg` needs ffmpeg and ffprobe on `PATH`.

CI runs all of this on Linux, Windows and macOS, for Python 3.11 to 3.15. It also runs the
tests with the lowest dependency versions the extras allow.

## Rules of the code

`CLAUDE.md` has the short version:

- The library has no runtime dependencies.
- `core/` does no I/O.
- The library never prints.
- Text files are UTF-8 with `\n` line endings.
- `mypy --strict` passes.
- Everything is in English.

The design lives in [docs/design](docs/design). Larger changes start there.

## Commits and changes

- Keep a commit to one change, with its tests.
- Write commit messages that say what changed and why, like the history.
- Add a line to `CHANGELOG.md` for anything a user can notice.

## Releases

Only the maintainer releases:

1. Bump `src/utmax/_version.py` and give `CHANGELOG.md` the version and date.
2. Merge into `main` and wait for CI to pass.
3. Publish a GitHub release whose tag is `v<version>`.

The release workflow then runs CI on that commit, checks that the commit is on `main`, and
builds the package. It uploads to PyPI after the maintainer approves the `pypi` environment.
`docs/release-checklist.md` lists what to check by hand first.
