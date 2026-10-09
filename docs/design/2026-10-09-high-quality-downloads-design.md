# High-quality downloads — design

Approved in conversation on 2026-10-09. Adds two milestones before the docs-and-release one:
**M8** (access, formats, MCP flow; released as 0.1.0a4) and **M9** (MKV/WebM; 0.1.0a5). The old
M8 (docs & release 0.1.0) becomes **M10**.

## 1. Goal: the MCP conversation

The MCP server only offers tools; the assistant asks the user and calls them accordingly:

- **"download this"** → the assistant calls `list_formats`, then asks for the file type
  (mp4, mkv, webm, m4a, mp3), a resolution the video really has (e.g. 2160p60 HDR, 1440p,
  1080p) and whether to embed subtitles in the original language, in a translation, or not at
  all → `download`.
- **"download the subtitles"** → `save_subtitles` writes an `.srt` into the download folder.
- **"download and translate"** → `get_transcript(format="srt")`, the assistant translates the
  text lines itself (the server calls no AI provider), then `download(translated_subtitles=…)`
  embeds the translation, or `save_subtitles(translated_srt=…)` saves it.

The server's instructions spell this flow out so Claude, Codex and other clients follow it.

## 2. Findings (2026-10-08/09)

- Without `visitorData` every no-JS client (ANDROID_VR, VISIONOS) answered "Sign in to confirm
  you're not a bot" for 8 of 10 test videos; only dQw4w9WgXcQ played.
- ANDROID and IOS stream URLs serve only the start of a stream and answer 403 after it unless a
  GVS PO token is attached (tail probes on 8 videos); utmax cannot mint PO tokens (BotGuard
  needs a JavaScript engine and a DOM).
- **VISIONOS** (`clientName` VISIONOS, `clientVersion` 1.02, client id 101) with a
  `visitorData` from `POST /youtubei/v1/visitor_id` played all 9 available test videos; every
  stream downloaded to its last byte with plain `Range` requests, without `n` or a signature.
  yt-dlp (default `visionos,web`), pytubefix and NewPipeExtractor switched to it in 2026.
  It refuses "made for kids" videos; ANDROID_VR still fails with a `visitorData`.
- VISIONOS lists H.264 up to 1080p, AV1 (8- and 10-bit HDR, up to 8K on some videos), VP9 and
  VP9.2 HDR up to 2160p60 (WebM), AAC and Opus (WebM), and every dubbed audio track; the
  original one is labelled "<language> original" and tagged `acont=original` in its URL.
- Every project that solves the signature or `n` challenges runs a JavaScript engine; no pure
  parser works on 2026 players. WEB is SABR-only and needs a PO token. Not pursued.

## 3. M8 — access, formats and the MCP flow (0.1.0a4)

### Access
- `core/clients.py`: a `VISIONOS` profile (Safari user agent, `deviceMake` Apple,
  `deviceModel` RealityDevice17,1, `osName` visionOS) in `PROFILES`; stream order
  `VISIONOS → ANDROID_VR` (ANDROID and IOS leave it; caption and browse orders stay).
- `adapters/innertube.py`: a visitor session per `InnerTubeClient`: the first request fetches
  `visitorData` once (thread-safe) through `visitor_id`; every InnerTube request sends it as
  `context.client.visitorData` and `X-Goog-Visitor-Id`. A bot-check answer renews it once and
  retries, and a download that refreshes its URLs after a 403 asks as a new visitor (YouTube
  restricted the streams of about one fresh visitor in six). The PO-token probe of the
  downloader stays as a safety net.
- Downloads use 2 MiB ranges: YouTube slowed 8 MiB ranges of VISIONOS to about 150 KB/s after a
  burst, while 4 MiB and smaller ones kept full speed.

### Formats and selection
- `Format` gains `hdr`, `bit_depth`, `language` (of an audio track) and `is_original` (the
  original audio of a dubbed video).
- `quality` becomes `"best"` (default) or `"compat"` (`"max"` is removed; alpha) and a new
  `resolution: int | None` caps the short side (`1080` means at most 1080p).

| Target | Video | Audio |
|---|---|---|
| `.mp4` | H.264, AV1 (8/10-bit, SDR/HDR) | AAC |
| `.mov` | H.264 | AAC, stereo ≤ 65535 Hz |
| `.m4a`, `.mp3` | – | AAC (mp3 through ffmpeg) |
| `.mkv` (M9) | AV1, VP9, H.264 | Opus, AAC |
| `.webm` (M9) | VP9, AV1 | Opus |

- **best:** the largest short side (≤ `resolution`), then the higher frame rate, then SDR over
  HDR, then AV1 over VP9 over H.264, then the higher bitrate. **compat:** H.264 SDR ≤ 1080p.
- **audio:** the original track (else YouTube's default), then without DRC, then Opus over AAC
  where the container takes both, then the higher bitrate.
- HDR AV1 goes into `.mp4` as YouTube's sample entry is copied verbatim (colour boxes kept);
  verified with ffprobe.

### Library API
- `utmax.list_formats(video) -> FormatList` (`video` + the downloadable formats).
- `download(..., quality="best", resolution=None)`; `download_many` the same.
- `Transcript.from_srt(text, language_code, *, video=None)` parses SRT (and WebVTT) so text
  from elsewhere, such as an assistant's translation, can be embedded or saved.

### MCP tools
- `list_formats(video)`: title, duration, the resolutions (height, fps, HDR, the file types that
  hold each), audio languages (original marked) and subtitle tracks.
- `download(video, format, resolution=None, subtitles=None, translated_subtitles=None,
  subtitle_mode="embed", quality="best")`: `translated_subtitles` is a list of
  `{language, srt}` written by the assistant.
- `save_subtitles(video, languages=None, translated_srt=None, language=None, format="srt")`:
  writes `"{title} [{id}].{language}.srt"` (or `.vtt`) into the download folder and returns
  its path; YouTube's track, or the given translation.
- `INSTRUCTIONS` describe the conversation of section 1.

### Errors
- No client plays the video → the reason YouTube gave (e.g. made for kids) as today's
  playability errors; a stream that serves only its start → `PoTokenRequired` (kept).
- A `resolution` or file type the video does not have → `FormatNotAvailable` listing what it
  has; an `srt` that does not parse → `InvalidOption`.

### Tests
- Fake-transport tests for the visitor session (one fetch, header and context, renewal on a
  bot check or a download's 403 refresh, threads sharing one value), the VISIONOS profile and
  the stream order; selection tables for every target, quality and resolution on payloads
  shaped like the 2026-10-09 VISIONOS answers (dubbed audio tracks, HDR AV1); SRT/VTT parsing;
  MCP tools in memory (flow, errors, paths inside the download folder).
- Live: three videos (two met the bot check without a visitorData) list their formats; a
  `resolution=144` download of a dubbed video keeps its original audio; a 4K HDR `.mp4` is
  checked by hand with ffprobe.

## 4. M9 — MKV and WebM (0.1.0a5)

- **Shared media model** (`core/media/model.py`): per track the kind, codec, timescale, sample
  table (offset, size, dts, cts, duration, sync), codec configuration, colour/HDR, language,
  start delay, picture size, channels and sample rate, and the source's MP4 sample entry.
- **Readers:** the fragmented-MP4 index maps onto the model; a new `core/media/webm.py` reads
  EBML (Segment Info, Tracks with CodecID/CodecPrivate/CodecDelay/Colour, Clusters with
  SimpleBlock and BlockGroup; YouTube uses no lacing) without reading frame data.
- **Codec configuration** (`core/media/codecs.py`): `avcC`, `av1C` and `esds` to Matroska
  CodecPrivate; OpusHead and pre-skip.
- **Writers:** the MP4/MOV/M4A muxer reads the model; its output stays byte-identical (tested).
  A new `core/media/matroska.py` writes EBML header, SeekHead, Info, Tracks, Clusters (≤ 5 s,
  starting at a video keyframe), Cues and S_TEXT/UTF8 subtitle tracks; every size is planned up
  front, and the existing plan executor copies frame data from the `.part` files.
- **Targets:** `.mkv` (anything in the table) and `.webm` (VP9/AV1 + Opus; subtitles only as
  sidecar files); MCP `format` gains `mkv` and `webm`.
- **Tests:** a synthetic EBML/WebM builder; hollow WebM fixtures from Big Buck Bunny
  (aqz-KE-bpKQ, CC BY 3.0); round trips through our reader with per-sample hashes; the
  byte-identical MP4 check; the CI ffmpeg job muxes lavfi VP9+Opus and AV1+Opus into `.mkv`
  and `.webm`, then ffprobe and a clean decode.

## 5. Not now

Choosing a dubbed audio language, HLS "premium" formats (itag 616), a JavaScript runtime
(deno/node) for WEB/TV clients, PO token minting, SABR, Ogg/Opus audio files.
