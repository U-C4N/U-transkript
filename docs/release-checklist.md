# Release checklist

What to check before publishing a release, and how to publish it. Write the results (date,
pass or fail, notes) into the GitHub release notes, or into the pull request of the version
commit.

## Before the tag

1. **CI is green on `main`** for the commit to release, including the `lowest supported
   dependencies` and `muxer vs ffmpeg` jobs.
2. **Live tests from a home connection** (cloud machines are often blocked):
   `uv run pytest -m live -rs`, with every provider key at hand. Skips that say YouTube blocked
   the IP do not count as passes.
3. **One real download per file type**, played in a player such as VLC or mpv:
   - `.mp4` at the best quality;
   - `.mkv` of a video whose largest picture is VP9;
   - `.webm`;
   - `quality="low"`;
   - for each, check the picture, the sound and the subtitle tracks.
4. **The MCP server in a client**, such as Claude Code:
   - "download this video" downloads at once in the highest quality;
   - "in low quality" gives at most 360p;
   - with `UTMAX_TRANSLATOR` set, "with Turkish subtitles" is translated by the server.
5. **`uv build` and `uvx twine check --strict dist/*`** pass locally.
6. **The `pypi` environment** still requires the maintainer's approval
   (`gh api repos/U-C4N/U-transkript/environments/pypi`).

## Publishing

1. Make the version commit:
   - set `src/utmax/_version.py`;
   - set the `CHANGELOG.md` heading to `## <version> — <date>`;
   - update the README status if it changed.
2. Merge it into `main` and wait for CI.
3. Publish a GitHub release with the tag `v<version>`, its notes taken from the CHANGELOG.
4. The Release workflow runs CI again on that commit, checks that the commit is on `main`, and
   builds the package. Then it waits; approve the `pypi` environment to upload.
5. After the upload, check the release:
   - `pip install u-transcript-max==<version>` works in a clean environment;
   - `uvx --from "u-transcript-max[mcp]@latest" utmax-mcp` starts.
