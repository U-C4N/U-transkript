# u-transcript max

[![PyPI](https://img.shields.io/pypi/v/u-transcript-max)](https://pypi.org/project/u-transcript-max/)
[![Python](https://img.shields.io/pypi/pyversions/u-transcript-max)](https://pypi.org/project/u-transcript-max/)
[![CI](https://github.com/U-C4N/U-transkript/actions/workflows/ci.yml/badge.svg)](https://github.com/U-C4N/U-transkript/actions/workflows/ci.yml)

YouTube transcripts, AI translation and downloads for Python — with zero dependencies. Its MCP
server lets Claude, Codex and other AI assistants use them too.

> **Alpha.** The API can still change before 0.1.0. The design lives in
> [docs/design](https://github.com/U-C4N/U-transkript/tree/main/docs/design).

## Install

From [PyPI](https://pypi.org/project/u-transcript-max/), on Python 3.11 or newer:

```bash
pip install u-transcript-max          # the library, no dependencies
pip install "u-transcript-max[mcp]"   # plus the MCP server, utmax-mcp
```

AI translation calls the provider's official SDK with your own API key: add the `claude`,
`openai`, `gemini` or `openrouter` extra, or `ai` for all of them.

## Quickstart

```python
import utmax

transcript = utmax.fetch("https://youtu.be/dQw4w9WgXcQ")   # the spoken language, manual first
transcript.save("rick.srt")                                # also .vtt, .json and .txt

turkish = utmax.translate(transcript, "tr", model="claude=claude-opus-5-5")  # needs [claude]
utmax.bilingual(transcript, turkish).save("rick.en+tr.srt")

utmax.download("dQw4w9WgXcQ", "rick.mp4")   # H.264 up to 1080p with English subtitles
videos = utmax.list_videos("@RickAstleyYT", kind="videos", limit=20)
```

Coming from youtube-transcript-api? Change one import:

```python
from utmax.compat import YouTubeTranscriptApi
```

## MCP server

`utmax-mcp` gives an AI assistant four tools: `list_tracks`, `get_transcript`, `list_videos`
and `download`. It needs no API key: ask for a translation and the assistant translates the
transcript itself. The commands below start it with `uvx` from
[uv](https://docs.astral.sh/uv/getting-started/installation/), which installs it from PyPI on
first use.

### Claude Code

```bash
claude mcp add --scope user utmax -- uvx --from "u-transcript-max[mcp]" utmax-mcp
```

`claude mcp get utmax` should say `Connected`; inside Claude Code, `/mcp` lists the server.

### Codex

```bash
codex mcp add utmax -- uvx --from "u-transcript-max[mcp]" utmax-mcp
```

A long download can outlast Codex's default tool timeout, and the first start installs the
server, so give it more time in `~/.codex/config.toml` (the CLI and the IDE extension share this
file):

```toml
[mcp_servers.utmax]
command = "uvx"
args = ["--from", "u-transcript-max[mcp]", "utmax-mcp"]
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
      "args": ["--from", "u-transcript-max[mcp]", "utmax-mcp"]
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

Set them with `-e NAME=value` in Claude Code, `--env NAME=value` in Codex, or an `"env"` object
in Claude Desktop.

## License

MIT
