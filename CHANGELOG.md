# Changelog

All notable changes to u-transcript max are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[PEP 440](https://peps.python.org/pep-0440/).

## 0.2.0 — not yet released

The first beta: the newest AI models and Grok, translation inside the MCP server, quality
levels, downloads that start sooner, and `.mkv`/`.webm` files with every picture YouTube has.

### Added

- A `grok` provider for xAI's Grok models: `model="grok=grok-4.7"`, through the OpenAI SDK
  (`pip install "u-transcript-max[grok]"`, key in `XAI_API_KEY`).
- `effort` works with every provider, and lower values answer faster:
  - `"low"`, `"medium"` and `"high"` work everywhere;
  - `"xhigh"` works with claude, openai and grok, and `"max"` with claude only;
  - it is sent as `thinking_level` to Gemini, as `reasoning_effort` to OpenAI and Grok, and as
    `reasoning.effort` to OpenRouter.
- Two download quality levels, for `utmax.download` and the MCP `download` tool:
  - `quality="medium"` gives at most 720p;
  - `quality="low"` gives at most 360p with the smallest audio stream, and `.mp3` files at
    about 115 kbit/s;
  - with `resolution` as well, the smaller limit wins.
- The MCP server can translate subtitles itself. When `UTMAX_TRANSLATOR` names a model, such
  as `gemini=gemini-3.8-flash`:
  - `download` and `save_subtitles` take `translate_to`, and the server translates with that
    model, many lines at once, which is much faster than the assistant writing each
    translation;
  - `UTMAX_TRANSLATOR_EFFORT` defaults to `low`, the fastest.

  Without `UTMAX_TRANSLATOR` nothing changes, and the assistant translates as before.

- `.mkv` and `.webm` downloads (`utmax.download(video, "x.mkv")`, MCP `format`):
  - `.mkv` holds AV1, VP9 or H.264 video with Opus or AAC audio and text subtitles, so it
    gets the largest picture YouTube has, such as VP9 in 4K for videos without that size in
    AV1;
  - `.webm` holds AV1 or VP9 with Opus, and writes subtitles as `.srt` files next to it.

  utmax's own Matroska writer copies the streams as they are: the Cues come first so players
  can seek at once, clusters start at video keyframes, and HDR colour information is kept.
  No ffmpeg is needed.

### Changed

- The MCP `download` tool picks the file type when none is named: `.mp4`, or `.mkv` when only
  an `.mkv` holds the largest picture. A finished `.mp4` or `.mkv` of the video counts as
  already there.
- The MCP server starts a download at once, in the highest quality, without asking questions
  first. It calls `list_formats` only when you ask what a video offers or name a resolution
  to check.
- A download asks YouTube for the video's streams only once, even right after
  `list_formats`; they are reused for five minutes. Requested subtitles are fetched in
  parallel.
- Progress reports of the MCP `download` tool no longer make the download threads wait for
  the client.

- The `claude` extra allows anthropic 2.x (`anthropic>=1.8,<3`).
- The `gemini` extra allows google-genai 3.x and needs 2.30.1 or newer, which Gemini 4 Argon
  requires (`google-genai>=2.30.1,<4`). The Gemini translator no longer needs httpx and stays
  on API version v1beta.
- Examples, error messages and live tests use the newest models: `claude-opus-5-5`,
  `gemini-3.8-flash`, `gemini-4-argon`, `grok-4.7` and `gpt-6-astra`.

## 0.1.0a5 — 2026-10-09

No code changes. The README that PyPI shows lists what utmax does, the new download options
(`resolution=`, `quality="compat"`, `list_formats`) and example requests for the MCP server.

## 0.1.0a4 — 2026-10-09

### Fixed

- **Downloads work again.** YouTube's Android and iOS stream URLs serve only the start of a
  stream without a proof-of-origin token, and its VR client mostly answers with a bot check.
  utmax downloads through the VISIONOS client with a `visitorData` YouTube issues, which serves
  whole streams without JavaScript or a token. Ranges are 2 MiB, because YouTube slowed 8 MiB
  ranges to about 150 KB/s.

### Added

- `quality="best"`, the new default, takes the largest picture the file type holds: AV1 or
  H.264 up to 8K in `.mp4`, with HDR AV1 where it is the only way to a larger picture.
- `quality="compat"` keeps H.264 up to 1080p.
- `resolution=` caps the picture.
- `utmax.list_formats(video)` shows what a video has.
- Dubbed videos keep their original audio.
- `Transcript.from_srt(text, language_code, video=...)` reads SRT or WebVTT, such as a
  translation an assistant wrote.
- MCP:
  - new tools `list_formats` and `save_subtitles`;
  - `download` takes `resolution`, `translated_subtitles` (embedded and shown by default) and
    `overwrite`.

### Removed

- `quality="max"`.

## 0.1.0a3 — 2026-10-08

### Fixed

- Default subtitles follow the original audio: on videos with dubbed audio, the language of
  the track YouTube marks as original names the spoken language (`TrackList.spoken_language`).
- Videos for which YouTube wants a proof-of-origin token fail with `PoTokenRequired` and a plain
  explanation, instead of a vague `StreamForbidden`.

### Changed

- The README starts the MCP server with `uvx --from "u-transcript-max[mcp]@latest" utmax-mcp`,
  so registered servers move to new releases by themselves.

## 0.1.0a2 — 2026-10-08

No code changes. The README explains how to install from PyPI and how to add the MCP server to
Claude Code, Codex and Claude Desktop.

## 0.1.0a1 — 2026-10-08

The first alpha, with no runtime dependencies:

- YouTube transcripts;
- AI translation with Claude, OpenAI-compatible servers, Gemini or OpenRouter, and bilingual
  subtitles;
- video and audio downloads (mp4, mov, m4a, mp3) with embedded subtitles;
- playlists and channels;
- a drop-in replacement for youtube-transcript-api (`utmax.compat`);
- an MCP server (`utmax-mcp`, extra `mcp`).