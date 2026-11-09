# Changelog

All notable changes to u-transcript max are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[PEP 440](https://peps.python.org/pep-0440/).

## Unreleased

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

### Changed

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
