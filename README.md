# u-transcript max

[![PyPI](https://img.shields.io/pypi/v/u-transcript-max)](https://pypi.org/project/u-transcript-max/)
[![Python](https://img.shields.io/pypi/pyversions/u-transcript-max)](https://pypi.org/project/u-transcript-max/)
[![CI](https://github.com/U-C4N/U-transkript/actions/workflows/ci.yml/badge.svg)](https://github.com/U-C4N/U-transkript/actions/workflows/ci.yml)

YouTube transcripts, AI translation and downloads for Python — with zero dependencies. Its MCP
server lets Claude, Codex and other AI assistants use them too.

> **Alpha.** The API can still change before 0.1.0. The design lives in
> [docs/design](https://github.com/U-C4N/U-transkript/tree/main/docs/design).

- **Transcripts** of any video, playlist or channel: every language, written by people or
  generated, as SRT, WebVTT, JSON or text.
- **AI translation** that keeps every timing (Claude, Gemini, Grok, OpenAI and compatible
  servers such as Ollama, OpenRouter), and bilingual subtitles.
- **Downloads in the best quality** a file holds: AV1 or H.264 up to 8K, HDR and 60 fps in
  `.mp4`; every picture and Opus audio in `.mkv`, including VP9 in 4K when YouTube has no AV1
  of that size (also `.webm`, `.mov`, `.m4a`, `.mp3`). Subtitles are switchable tracks, and
  dubbed videos keep their original audio. Parallel and resumable; no ffmpeg needed except
  for `.mp3`.
- **A drop-in replacement** for youtube-transcript-api.
- **An MCP server** for Claude, Codex and other AI assistants.

## Install

From [PyPI](https://pypi.org/project/u-transcript-max/), on Python 3.11 or newer:

```bash
pip install u-transcript-max          # the library, no dependencies
pip install "u-transcript-max[mcp]"   # plus the MCP server, utmax-mcp
```

AI translation calls the provider's official SDK with your own API key: add the `claude`,
`gemini`, `grok`, `openai` or `openrouter` extra, or `ai` for all of them. Any model id works;
these are the newest:

| Provider | Models | Key |
|---|---|---|
| `claude` | `claude-opus-5-5` and the other Claude 5 models | `ANTHROPIC_API_KEY` |
| `gemini` | `gemini-3.8-flash`, `gemini-4-argon` | `GEMINI_API_KEY` |
| `grok` | `grok-4.7` | `XAI_API_KEY` |
| `openai` | `gpt-6-astra`, or any model of an OpenAI-compatible server | `OPENAI_API_KEY` |
| `openrouter` | any OpenRouter model, such as `anthropic/claude-opus-5.5` | `OPENROUTER_API_KEY` |

`effort="low"` makes the thinking models answer faster.

## Quickstart

```python
import utmax

transcript = utmax.fetch("https://youtu.be/dQw4w9WgXcQ")  # the spoken language, manual first
transcript.save("rick.srt")  # also .vtt, .json and .txt

turkish = utmax.translate(transcript, "tr", model="claude=claude-opus-5-5")  # needs [claude]
utmax.bilingual(transcript, turkish).save("rick.en+tr.srt")

utmax.download("dQw4w9WgXcQ", "rick.mp4")  # the best picture (AV1 up to 8K), English subtitles
utmax.download("dQw4w9WgXcQ", "rick.mkv")  # every picture YouTube has (VP9 too) with Opus audio
utmax.download("dQw4w9WgXcQ", "rick-medium.mp4", quality="medium")  # at most 720p
utmax.download("dQw4w9WgXcQ", "rick-low.mp4", quality="low")  # at most 360p, smaller audio
utmax.download("dQw4w9WgXcQ", "rick-1080.mp4", resolution=1080)  # at most 1080p
utmax.download("dQw4w9WgXcQ", "rick.mp4", quality="compat")  # H.264 up to 1080p, plays anywhere
utmax.download("dQw4w9WgXcQ", "rick.m4a")  # the audio only
print([f.label for f in utmax.list_formats("dQw4w9WgXcQ") if f.kind == "video"])

videos = utmax.list_videos("@RickAstleyYT", kind="videos", limit=20)
utmax.fetch_many(videos, out_dir="subs")  # one .srt per video
```

Coming from youtube-transcript-api? Change one import:

```python
from utmax.compat import YouTubeTranscriptApi
```

## MCP server

`utmax-mcp` gives an AI assistant six tools: `list_tracks`, `get_transcript`, `list_formats`,
`list_videos`, `download` and `save_subtitles`. It needs no API key. Ask it to download a video
and it starts at once, in the highest quality (as `.mp4`, or `.mkv` when only that holds the
largest picture) with subtitles in the spoken language; say
"medium quality" (at most 720p), "low quality" (at most 360p), a resolution, a file type or
other subtitles when you want them. Ask for a translation and it translates the subtitles
itself. Things to ask:

- *"Download https://youtu.be/ZcDFZzsp3_Y with Turkish subtitles."* The assistant
  translates the English subtitles itself and downloads a 4K `.mp4` with English and Turkish
  tracks (Turkish on by default).
- *"Download this video in low quality."*
- *"Save the subtitles of this video, translated into German."*
- *"List the last 20 videos of @RickAstleyYT and summarize the newest one."*

Files go to `~/Downloads/utmax`. The commands below start the server with `uvx` from
[uv](https://docs.astral.sh/uv/getting-started/installation/), which installs it from PyPI;
`@latest` makes it move to each new release the next time the client starts the server.

### Claude Code

```bash
claude mcp add --scope user utmax -- uvx --from "u-transcript-max[mcp]@latest" utmax-mcp
```

`claude mcp get utmax` should say `Connected`; inside Claude Code, `/mcp` lists the server.

### Codex

```bash
codex mcp add utmax -- uvx --from "u-transcript-max[mcp]@latest" utmax-mcp
```

A long download can outlast Codex's default tool timeout, and the first start installs the
server, so give it more time in `~/.codex/config.toml` (the CLI and the IDE extension share this
file):

```toml
[mcp_servers.utmax]
command = "uvx"
args = ["--from", "u-transcript-max[mcp]@latest", "utmax-mcp"]
startup_timeout_sec = 60
tool_timeout_sec = 1800
```

### Claude Desktop

Open Settings → Developer → Edit Config, add the server to `claude_desktop_config.json` and
restart Claude Desktop:

```json
{
  "mcpServers": {
    "utmax": {
      "command": "uvx",
      "args": ["--from", "u-transcript-max[mcp]@latest", "utmax-mcp"]
    }
  }
}
```

If Claude Desktop cannot find `uvx`, put its full path in `command` (`which uvx`, or
`where uvx` on Windows).

### Other clients and settings

Any MCP client that starts stdio servers can run the same command, or `utmax-mcp` after
`pip install "u-transcript-max[mcp]"`. Environment variables change the defaults:

| Variable | Default | Meaning |
|---|---|---|
| `UTMAX_DOWNLOAD_DIR` | `~/Downloads/utmax` | where `download` saves files |
| `UTMAX_PROXY` | none | an `http://[user:password@]host:port` proxy for YouTube |
| `UTMAX_FFMPEG` | `ffmpeg` on `PATH` | the ffmpeg that makes `.mp3` files |
| `UTMAX_TRANSLATOR` | none | a model the server translates subtitles with, such as `gemini=gemini-3.8-flash` |
| `UTMAX_TRANSLATOR_EFFORT` | `low` | how long that model thinks: `low` is the fastest; `default` leaves it to the model |

Set them with `-e NAME=value` in Claude Code, `--env NAME=value` in Codex, or an `"env"` object
in Claude Desktop.

### Faster translated subtitles

Without `UTMAX_TRANSLATOR`, the assistant writes every translation itself, which takes a while
for a long video. With it, the server translates through the provider's API, many lines at
once. Add the provider's extra and its key, for example Gemini in Claude Code:

```bash
claude mcp add --scope user utmax -e UTMAX_TRANSLATOR=gemini=gemini-3.8-flash \
  -e GEMINI_API_KEY=... -- uvx --from "u-transcript-max[mcp,gemini]@latest" utmax-mcp
```

Any provider works the same way: `grok=grok-4.7` with `[mcp,grok]` and `XAI_API_KEY`,
`openai=gpt-6-astra` with `[mcp,openai]` and `OPENAI_API_KEY`, or `claude=claude-opus-5-5`
with `[mcp,claude]` and `ANTHROPIC_API_KEY`.

## License

MIT
