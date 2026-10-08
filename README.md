# u-transcript max

YouTube transcripts, AI translation and downloads for Python — with zero dependencies.

> **Alpha.** The first full release (0.1.0) is being finished. The design lives in
> [docs/design](https://github.com/U-C4N/U-transkript/tree/main/docs/design).

```bash
pip install --pre u-transcript-max          # the library, no dependencies
pip install --pre "u-transcript-max[mcp]"   # plus the MCP server, utmax-mcp
```

```python
import utmax

transcript = utmax.fetch("https://youtu.be/dQw4w9WgXcQ")
transcript.save("rick.srt")
```

Add the MCP server to Claude Code (needs [uv](https://docs.astral.sh/uv/)):

```bash
claude mcp add --scope user utmax -- uvx --prerelease allow --from "u-transcript-max[mcp]" utmax-mcp
```

## License

MIT
