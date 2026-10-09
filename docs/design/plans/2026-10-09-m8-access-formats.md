# M8 — Access, Formats and the MCP Download Conversation Implementation Plan

**Goal:** Downloads work again for every playable video (VISIONOS with a `visitorData` YouTube issued), take the best stream the file type holds (AV1 up to 8K and HDR in `.mp4`, a `resolution` cap, the original audio of dubbed videos), and the MCP server supports the conversation "download this" → file type → resolution → subtitles (original, translated by the assistant, or none), plus saving subtitles as files.

**Architecture:** `core/clients.py` gains the VISIONOS profile and `needs_visitor`; `adapters/innertube.py` asks `POST /youtubei/v1/visitor_id` once per client and renews the value after a bot check or a 403 refresh. `models.Format` gains `hdr`, `bit_depth`, `language` and `is_original`; `core/streams.choose_streams` picks by file type, `quality` (`"best"`/`"compat"`) and `resolution`. `utmax.list_formats` returns a `FormatList`; `core/formats.parse_subtitles` and `Transcript.from_srt` read SRT/WebVTT back. `utmax/mcp/server.py` adds `list_formats` and `save_subtitles`, and `download` takes `resolution`, `translated_subtitles` and `overwrite`.

**Tech Stack:** Python ≥ 3.11 standard library only in `src/utmax` (the MCP server uses the optional `mcp` extra) · pytest · ruff · mypy (strict) · uv.

**Spec:** `docs/design/2026-10-09-high-quality-downloads-design.md` (sections 1–3 are M8; section 4 is M9) and `docs/design/2026-09-27-u-transcript-max-design.md` §4.1, §4.3, §4.5, §4.7, §5. Base: commit `e7f9614` on `main` (the design commit); the baseline suite there is 1664 passed, 28 deselected with all extras installed.

## Global Constraints

- Zero runtime dependencies: only the standard library in `src/utmax`; `utmax.mcp` alone imports the SDK (pydantic, anyio, mcp). Layers: interfaces → services → pure `core` + `adapters`; `utmax.mcp` never imports `utmax.adapters`, `utmax.services` or `utmax.compat` (it may import pure `core` modules such as `core.ids`, `core.filenames`, `core.streams`).
- Python sources under `src/` are ASCII: a non-ASCII character appears only as an eight-digit escape such as `\U0000feff` (editing tools silently turn four-digit backslash-u escapes into raw characters, and `sed` reads `\U` in a replacement as "upper-case the rest"). Tests may contain raw UTF-8 such as `♪`.
- Never write stream URLs, IP addresses or signed query values (`ip`, `ei`, `sig`, `lsig`, `signature`, `key`, `expire`) into files, logs or reports; never log a `visitorData` value.
- Lint lessons: `pytest.raises` with a specific exception and a raw `match=`, at most five positional parameters (tool options are keyword-only), `filterwarnings = error`. After writing a file run `uv run ruff format <file>`: the code below is formatted, so a formatter change points at a transcription slip.
- Edits: each "In `path`, replace … with …" quotes the old text exactly; every old block occurs exactly once at that point, and the blocks of a step are applied in order.
- Gates after every task: `uv run ruff check .` · `uv run ruff format --check .` · `uv run mypy` · `uv run pytest` (branch coverage ≥ 90 %). Each task states the suite total afterwards; if a count differs, find out why before moving on.
- Commits use a conventional prefix, stage explicit paths only and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push, merge or publish without the user's explicit approval.

## Review Focus

1. **A visitorData YouTube will not issue** — `visitor_id` answering 5xx, non-JSON or an empty value: requests go out without one and the next call asks again; HTTP 429 is final (`IpBlocked`). Pinned in Task 1 (`test_without_a_visitor_data_the_request_goes_out_without_one`, `test_a_rate_limit_while_asking_for_a_visitor_data_is_final`).
2. **Many threads, one visitor** — bulk downloads share a client: the value is fetched once and a renewal after a bot check happens once. Pinned in Task 1 (`test_threads_share_one_visitor_data`, `test_a_bot_check_renews_the_visitor_data_once`).
3. **Visitors whose streams YouTube restricts** — about one in six on 2026-10-09: URLs serve only the start; each 403 refresh asks as a new visitor, and three failures end in `PoTokenRequired`. Pinned in Task 1 (`test_renew_visitor_asks_for_a_new_visitor_data_first`, `test_failed_downloads_keep_their_parts`).
4. **Dubbed videos** — about twenty auto-dubbed audio tracks and an auto-generated caption track per dub: the original audio and the original language's subtitles win. Pinned in Task 2 (`test_audio_prefers_the_original_track_of_a_dubbed_video`, `test_audio_tracks_hdr_and_bit_depth_are_parsed`) and live in Task 6.
5. **Subtitles an assistant wrote** — CRLF, a byte-order mark, missing cue numbers or blank lines, WebVTT headers and notes, and text that is no subtitles at all (refused before any download). Pinned in Task 4 (`test_srt_from_elsewhere_is_read_leniently`, `test_text_without_cues_is_refused`) and Task 5 (`test_a_translation_that_is_not_subtitles_is_refused_before_any_download`).

## Verified facts this plan relies on (2026-10-09, from this machine)

- Without `visitorData`, VISIONOS and ANDROID_VR answered `LOGIN_REQUIRED` "Sign in to confirm you're not a bot" for 8 of 10 test videos (only dQw4w9WgXcQ played); the watch page played them.
- ANDROID and IOS stream URLs answered 206 for the first bytes and 403 for the last kilobyte of 8 of 8 tested videos (a missing GVS PO token).
- VISIONOS (`clientName` VISIONOS, `clientVersion` 1.02, client id 101, `deviceMake` Apple, `deviceModel` RealityDevice17,1, `osName` visionOS, Safari user agent) with a `visitorData` from `POST /youtubei/v1/visitor_id` (body: the VISIONOS context; answer: `responseContext.visitorData`) played all 9 available test videos, and every tested stream answered 206 for its last kilobyte: H.264 ≤ 1080p, AV1 8/10-bit (HDR) ≤ 2160p, VP9/VP9.2 HDR ≤ 2160p60 (WebM), AAC, Opus (WebM) and every dubbed audio track. ANDROID_VR 1.62.27 still met the bot check with a `visitorData`.
- About one fresh visitor in six got stream URLs that served only the start (same URL parameters as the others); a new visitor fixed it.
- A dubbed video's original audio track is named "<language> original" (`audioTrack.displayName`, utmax asks in English), has `audioTrack.id` like `en-US.4`, and its URLs carry `xtags=acont%3Doriginal%3Alang%3Den-US`; dubs carry `acont=dubbed-auto`.
- Range requests of 8 MiB on VISIONOS URLs ran at about 3 MB/s for a burst, then at about 150 KB/s; 4 MiB and smaller ones kept full speed (a 14.5 MB download: 79 s with 8 MiB chunks, 5.5–6 s with 1–4 MiB).
- yt-dlp (master `51bab8a0`), pytubefix 11.2.0 and NewPipeExtractor use VISIONOS for streams in 2026; every project that solves the signature or `n` challenges runs a JavaScript engine.

---

### Task 1: Streams through VISIONOS with a visitorData

**Files:**
- Modify: `src/utmax/core/clients.py`, `src/utmax/adapters/innertube.py`, `src/utmax/core/downloads.py`, `src/utmax/services/download.py`, `src/utmax/__init__.py`
- Modify (test helpers): `tests/helpers/youtube.py`, `tests/helpers/downloads.py`, `tests/helpers/bulk.py`
- Test: `tests/unit/adapters/test_innertube_visitor.py` (create), `tests/unit/core/test_clients.py`, `tests/unit/adapters/test_innertube.py`, `tests/unit/services/test_download_audio.py`, `tests/unit/services/test_download_video.py`, `tests/unit/test_download_api.py`

**Interfaces:**
- Produces: `utmax.core.clients.VISIONOS` (in `PROFILES`; `ORDER["streams"] == (VISIONOS, ANDROID_VR)`); `ClientProfile.needs_visitor: bool = False`, `ClientProfile.context_payload(visitor_data: str | None = None)` and `request_headers(visitor_data: str | None = None)` (adding `visitorData` and `X-Goog-Visitor-Id`); `InnerTubeClient.visitor_data() -> str | None`; `InnerTubeClient.player(video_id, *, purpose="captions", renew_visitor: bool = False)`; `InnerTubeClient.player_json(profile, video_id, *, api_key=None, visitor_data=None)`; `DEFAULT_CHUNK_SIZE == 2 * MIB`. Test helpers: `tests.helpers.youtube.VISITOR_DATA` and `visitor_payload(value=VISITOR_DATA)`; `FakeYouTube` and `ManyVideos` answer `/youtubei/v1/visitor_id`, and `FakeYouTube`'s stream URLs carry `c=VISIONOS`.
- Consumes: `check_playability` raising `RequestBlocked` for the bot check; `utmax.core.ytdata.mapping`.

- [ ] **Step 1: Write the failing tests**

**In `tests/helpers/youtube.py`, replace:**

```python
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "youtube"
```

**with:**

```python
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "youtube"
VISITOR_DATA = "CgtWaXNpdG9yRGF0YSiA"


def visitor_payload(value: str = VISITOR_DATA) -> dict[str, Any]:
    """The ``/youtubei/v1/visitor_id`` answer (only the field utmax reads)."""
    return {"responseContext": {"visitorData": value}}
```

Replace `tests/unit/core/test_clients.py` and add the visitor tests:

**In `tests/unit/core/test_clients.py`, replace:**

```python
from utmax.core.clients import ANDROID, ANDROID_VR, IOS, ORDER, WEB
```

**with:**

```python
from utmax.core.clients import ANDROID, ANDROID_VR, IOS, ORDER, PROFILES, VISIONOS, WEB
```

**In `tests/unit/core/test_clients.py`, replace:**

```python
    assert (client["hl"], client["gl"]) == ("en", "US")
```

**with:**

```python
    assert (client["hl"], client["gl"]) == ("en", "US")
    assert "visitorData" not in client
```

**In `tests/unit/core/test_clients.py`, replace:**

```python
    assert headers["Accept-Encoding"] == "gzip"
```

**with:**

```python
    assert headers["Accept-Encoding"] == "gzip"
    assert "X-Goog-Visitor-Id" not in headers


def test_visionos_introduces_itself_as_the_vision_pro_app_with_a_visitor() -> None:
    client = VISIONOS.context_payload("visitor-1")["client"]
    assert (client["clientName"], client["clientVersion"]) == ("VISIONOS", "1.02")
    assert (client["deviceMake"], client["deviceModel"]) == ("Apple", "RealityDevice17,1")
    assert (client["osName"], client["hl"]) == ("visionOS", "en")
    assert client["visitorData"] == "visitor-1"
    headers = VISIONOS.request_headers("visitor-1")
    assert headers["X-YouTube-Client-Name"] == "101"
    assert headers["X-Goog-Visitor-Id"] == "visitor-1"
    assert "Safari/" in headers["User-Agent"]
    assert VISIONOS.needs_visitor
    assert not any(profile.needs_visitor for profile in (ANDROID, IOS, ANDROID_VR, WEB))
```

**In `tests/unit/core/test_clients.py`, replace:**

```python
    assert ORDER["streams"] == (ANDROID_VR, ANDROID, IOS)
    assert ORDER["browse"] == (ANDROID_VR, WEB)
    assert ORDER["resolve"] == (ANDROID_VR, WEB)
    assert len({profile.name for profile in (ANDROID, IOS, ANDROID_VR, WEB)}) == 4
```

**with:**

```python
    assert ORDER["streams"] == (VISIONOS, ANDROID_VR)
    assert ORDER["browse"] == (ANDROID_VR, WEB)
    assert ORDER["resolve"] == (ANDROID_VR, WEB)
    assert len({profile.name for profile in (ANDROID, IOS, ANDROID_VR, VISIONOS, WEB)}) == 5
    assert PROFILES["VISIONOS"] is VISIONOS
```

**Create `tests/unit/adapters/test_innertube_visitor.py`:**

```python
"""Tests for the visitorData that VISIONOS player requests carry.

Without one, YouTube answered VISIONOS with "Sign in to confirm you're not a bot" for 8 of 10
test videos on 2026-10-09; with one issued by ``visitor_id``, every one played.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import pytest

from tests.helpers.fake_transport import FakeTransport, json_response, text_response
from tests.helpers.youtube import (
    VIDEO_ID,
    VISITOR_DATA,
    player_payload,
    streaming_data,
    visitor_payload,
)
from utmax.adapters.innertube import InnerTubeClient
from utmax.errors import IpBlocked
from utmax.transport import HttpRequest

BOT_CHECK = player_payload(status="LOGIN_REQUIRED", reason="Sign in to confirm you're not a bot")


def playable() -> dict[str, Any]:
    return player_payload(streaming_data=streaming_data())


def players(transport: FakeTransport) -> list[HttpRequest]:
    return [request for request in transport.requests if "/youtubei/v1/player" in request.url]


def sent(request: HttpRequest) -> tuple[str, str | None, str | None]:
    """(client name, visitorData in the body, X-Goog-Visitor-Id header) of a player request."""
    client = json.loads(request.body or b"{}")["context"]["client"]
    return client["clientName"], client.get("visitorData"), request.headers.get("X-Goog-Visitor-Id")


def visitor_requests(transport: FakeTransport) -> int:
    return sum("/youtubei/v1/visitor_id" in url for url in transport.urls("POST"))


def test_visionos_asks_once_for_a_visitor_data_and_sends_it() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/visitor_id", json_response(visitor_payload()))
    transport.add("POST", "/youtubei/v1/player", json_response(playable()), repeat=True)
    innertube = InnerTubeClient(transport)
    innertube.player(VIDEO_ID, purpose="streams")
    innertube.player(VIDEO_ID, purpose="streams")
    assert transport.urls("POST")[0] == (
        "https://www.youtube.com/youtubei/v1/visitor_id?prettyPrint=false"
    )
    visitor_body = json.loads(transport.requests[0].body or b"{}")
    assert visitor_body["context"]["client"]["clientName"] == "VISIONOS"
    assert "visitorData" not in visitor_body["context"]["client"]
    assert [sent(request) for request in players(transport)] == [
        ("VISIONOS", VISITOR_DATA, VISITOR_DATA)
    ] * 2
    assert players(transport)[0].headers["X-YouTube-Client-Name"] == "101"
    assert innertube.visitor_data() == VISITOR_DATA
    assert visitor_requests(transport) == 1


def test_a_bot_check_renews_the_visitor_data_once() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        "/youtubei/v1/visitor_id",
        json_response(visitor_payload("first")),
        json_response(visitor_payload("second")),
    )
    transport.add(
        "POST", "/youtubei/v1/player", json_response(BOT_CHECK), json_response(playable())
    )
    player = InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert player.playability.status == "OK"
    assert [sent(request)[:2] for request in players(transport)] == [
        ("VISIONOS", "first"),
        ("VISIONOS", "second"),
    ]


def test_a_second_bot_check_moves_on_to_android_vr_without_a_visitor_data() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        "/youtubei/v1/visitor_id",
        json_response(visitor_payload("first")),
        json_response(visitor_payload("second")),
    )
    transport.add(
        "POST",
        "/youtubei/v1/player",
        json_response(BOT_CHECK),
        json_response(BOT_CHECK),
        json_response(playable()),
    )
    InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert [sent(request) for request in players(transport)] == [
        ("VISIONOS", "first", "first"),
        ("VISIONOS", "second", "second"),
        ("ANDROID_VR", None, None),
    ]


@pytest.mark.parametrize(
    "answer",
    [
        text_response("server error", status=503),
        text_response("<html>not json</html>"),
        json_response({"responseContext": {}}),
        json_response({"responseContext": {"visitorData": ""}}),
    ],
)
def test_without_a_visitor_data_the_request_goes_out_without_one(answer: Any) -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/visitor_id", answer, repeat=True)
    transport.add("POST", "/youtubei/v1/player", json_response(playable()), repeat=True)
    innertube = InnerTubeClient(transport)
    innertube.player(VIDEO_ID, purpose="streams")
    innertube.player(VIDEO_ID, purpose="streams")
    assert [sent(request) for request in players(transport)] == [("VISIONOS", None, None)] * 2
    assert visitor_requests(transport) == 2


def test_a_rate_limit_while_asking_for_a_visitor_data_is_final() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/visitor_id", json_response({}, status=429))
    with pytest.raises(IpBlocked):
        InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert players(transport) == []


def test_threads_share_one_visitor_data() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/visitor_id", json_response(visitor_payload()), repeat=True)
    transport.add("POST", "/youtubei/v1/player", json_response(playable()), repeat=True)
    innertube = InnerTubeClient(transport)
    barrier = threading.Barrier(8, timeout=5)
    errors: list[BaseException] = []

    def work() -> None:
        try:
            barrier.wait()
            innertube.player(VIDEO_ID, purpose="streams")
        except BaseException as error:  # pragma: no cover - reported below
            errors.append(error)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert visitor_requests(transport) == 1
    assert len(players(transport)) == 8


def test_renew_visitor_asks_for_a_new_visitor_data_first() -> None:
    """YouTube restricts the streams of some visitors (about one in six on 2026-10-09: their
    URLs serve only the start), so a download that meets 403s refreshes as a new visitor."""
    transport = FakeTransport()
    transport.add(
        "POST",
        "/youtubei/v1/visitor_id",
        json_response(visitor_payload("first")),
        json_response(visitor_payload("second")),
    )
    transport.add("POST", "/youtubei/v1/player", json_response(playable()), repeat=True)
    innertube = InnerTubeClient(transport)
    innertube.player(VIDEO_ID, purpose="streams")
    innertube.player(VIDEO_ID, purpose="streams", renew_visitor=True)
    assert [sent(request)[1] for request in players(transport)] == ["first", "second"]
    assert innertube.visitor_data() == "second"


def test_caption_requests_need_no_visitor_data() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(player_payload()))
    InnerTubeClient(transport).player(VIDEO_ID)
    assert [sent(request) for request in transport.requests] == [("ANDROID", None, None)]
```

The stream-order tests of the InnerTube adapter now expect VISIONOS first and count only player requests:

**In `tests/unit/adapters/test_innertube.py`, replace:**

```python
from tests.helpers.youtube import MANUAL_JSON3, VIDEO_ID, player_payload, streaming_data
```

**with:**

```python
from tests.helpers.youtube import (
    MANUAL_JSON3,
    VIDEO_ID,
    player_payload,
    streaming_data,
    visitor_payload,
)
```

**In `tests/unit/adapters/test_innertube.py`, replace:**

```python
    return [
        json.loads(r.body or b"{}")["context"]["client"]["clientName"]
        for r in transport.requests
        if r.method == "POST"
    ]
```

**with:**

```python
    """The client of every player request, in order."""
    return [
        json.loads(r.body or b"{}")["context"]["client"]["clientName"]
        for r in transport.requests
        if "/youtubei/v1/player" in r.url
    ]


def stream_transport() -> FakeTransport:
    """A transport that issues a visitorData, which the VISIONOS stream profile asks for."""
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/visitor_id", json_response(visitor_payload()), repeat=True)
    return transport
```

**In `tests/unit/adapters/test_innertube.py`, replace:**

```python
def test_stream_players_skip_profiles_without_direct_mp4_urls() -> None:
    transport = FakeTransport()
    transport.add(
```

**with:**

```python
def test_stream_players_skip_profiles_without_direct_mp4_urls() -> None:
    transport = stream_transport()
    transport.add(
```

**In `tests/unit/adapters/test_innertube.py`, replace:**

```python
    player = InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert client_names(transport) == ["ANDROID_VR", "ANDROID"]
    assert any(stream.url for stream in player.streams)
```

**with:**

```python
    player = InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert client_names(transport) == ["VISIONOS", "ANDROID_VR"]
    assert any(stream.url for stream in player.streams)
```

**In `tests/unit/adapters/test_innertube.py`, replace:**

```python
def test_stream_players_fall_back_to_the_watch_page_then_give_up() -> None:
    transport = FakeTransport()
    transport.add(
```

**with:**

```python
def test_stream_players_fall_back_to_the_watch_page_then_give_up() -> None:
    transport = stream_transport()
    transport.add(
```

**In `tests/unit/adapters/test_innertube.py`, replace:**

```python
    assert client_names(transport) == ["ANDROID_VR", "ANDROID", "IOS", "ANDROID"]
```

**with:**

```python
    assert client_names(transport) == ["VISIONOS", "ANDROID_VR", "ANDROID"]
```

**In `tests/unit/adapters/test_innertube.py`, replace:**

```python
    blocked = player_payload(status="LOGIN_REQUIRED", reason="Sign in to confirm you're not a bot")
    transport = FakeTransport()
```

**with:**

```python
    """VISIONOS is asked twice (the second time with a new visitorData) before ANDROID_VR."""
    blocked = player_payload(status="LOGIN_REQUIRED", reason="Sign in to confirm you're not a bot")
    transport = stream_transport()
```

**In `tests/unit/adapters/test_innertube.py`, replace:**

```python
        json_response(streams_payload(direct=True)),
    )
    InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert client_names(transport) == ["ANDROID_VR", "ANDROID"]
```

**with:**

```python
        json_response(blocked),
        json_response(streams_payload(direct=True)),
    )
    InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert client_names(transport) == ["VISIONOS", "VISIONOS", "ANDROID_VR"]
```

The download fakes issue a visitorData, and the service tests count player requests and the visitors of a failed download:

**In `tests/helpers/downloads.py`, replace:**

```python
from tests.helpers.youtube import MANUAL_JSON3, json3_payload, player_payload
```

**with:**

```python
from tests.helpers.youtube import MANUAL_JSON3, json3_payload, player_payload, visitor_payload
```

**In `tests/helpers/downloads.py`, replace:**

```python
        "url": f"{url}?c=ANDROID_VR",
```

**with:**

```python
        "url": f"{url}?c=VISIONOS",
```

**In `tests/helpers/downloads.py`, replace:**

```python
        self.api = FakeTransport()
```

**with:**

```python
        self.api = FakeTransport()
        self.api.add(
            "POST", "/youtubei/v1/visitor_id", json_response(visitor_payload()), repeat=True
        )
```

**In `tests/helpers/bulk.py`, replace:**

```python
from tests.helpers.youtube import MANUAL_JSON3, json3_payload, player_payload
```

**with:**

```python
from tests.helpers.youtube import MANUAL_JSON3, json3_payload, player_payload, visitor_payload
```

**In `tests/helpers/bulk.py`, replace:**

```python
    def send(self, request: HttpRequest) -> HttpResponse:
```

**with:**

```python
    def send(self, request: HttpRequest) -> HttpResponse:
        if "/youtubei/v1/visitor_id" in request.url:
            return json_response(visitor_payload())
```

**In `tests/unit/services/test_download_audio.py`, replace:**

```python
    youtube.media.expired.add("https://media.test/140?c=ANDROID_VR")
```

**with:**

```python
    youtube.media.expired.add("https://media.test/140?c=VISIONOS")
```

**In `tests/unit/services/test_download_audio.py`, replace:**

```python
    assert (tmp_path / "rick.m4a.140.part.json").exists()
```

**with:**

```python
    assert (tmp_path / "rick.m4a.140.part.json").exists()
    visitors = [url for url in youtube.api.urls("POST") if "/youtubei/v1/visitor_id" in url]
    assert len(visitors) == 4  # the first visitor, then a new one for each of three refreshes
```

**In `tests/unit/services/test_download_video.py`, replace:**

```python
    assert len(youtube.api.urls("POST")) == 1  # one player response serves streams and captions
```

**with:**

```python
    players = [url for url in youtube.api.urls("POST") if "/youtubei/v1/player" in url]
    assert len(players) == 1  # one player response serves streams and captions
```

**In `tests/unit/test_download_api.py`, replace:**

```python
    assert parameters["chunk_size"].default == 8 * 2**20
```

**with:**

```python
    assert parameters["chunk_size"].default == 2 * 2**20
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_clients.py tests/unit/adapters/test_innertube_visitor.py -q`
Expected: collection errors — `ImportError: cannot import name 'VISIONOS' from 'utmax.core.clients'`.

- [ ] **Step 3: Add the VISIONOS profile and the visitorData to the profiles**

**In `src/utmax/core/clients.py`, replace:**

```python
without an API key or proof-of-origin token; ANDROID_VR returns no ``translationLanguages``.
```

**with:**

```python
without an API key or proof-of-origin token; ANDROID_VR returns no ``translationLanguages``.

Verified on 2026-10-09: the stream URLs of ANDROID and IOS serve only the start of a stream
without a proof-of-origin token, and ANDROID_VR mostly answers with a bot check. VISIONOS, sent
with a ``visitorData`` that YouTube issued, serves whole streams of every quality (H.264, AV1
and VP9 up to 2160p and HDR, AAC and Opus) without JavaScript or a token.
```

**In `src/utmax/core/clients.py`, replace:**

```python
    "PROFILES",
    "WEB",
```

**with:**

```python
    "PROFILES",
    "VISIONOS",
    "WEB",
```

**In `src/utmax/core/clients.py`, replace:**

```python
    """How utmax introduces itself to InnerTube as one of YouTube's apps."""
```

**with:**

```python
    """How utmax introduces itself to InnerTube as one of YouTube's apps.

    ``needs_visitor``: YouTube answers this app with a bot check unless the request carries a
    ``visitorData`` that it issued (``POST /youtubei/v1/visitor_id``).
    """
```

**In `src/utmax/core/clients.py`, replace:**

```python

    def context_payload(self) -> dict[str, Any]:
```

**with:**

```python
    needs_visitor: bool = False

    def context_payload(self, visitor_data: str | None = None) -> dict[str, Any]:
```

**In `src/utmax/core/clients.py`, replace:**

```python
        return {"client": client}

    def request_headers(self) -> dict[str, str]:
        """HTTP headers for an InnerTube request made as this app."""
        return {
```

**with:**

```python
        if visitor_data is not None:
            client["visitorData"] = visitor_data
        return {"client": client}

    def request_headers(self, visitor_data: str | None = None) -> dict[str, str]:
        """HTTP headers for an InnerTube request made as this app."""
        headers = {
```

**In `src/utmax/core/clients.py`, replace:**

```python
            "Accept-Encoding": "gzip",
        }


```

**with:**

```python
            "Accept-Encoding": "gzip",
        }
        if visitor_data is not None:
            headers["X-Goog-Visitor-Id"] = visitor_data
        return headers


```

**In `src/utmax/core/clients.py`, replace:**

```python
)
WEB = ClientProfile(
```

**with:**

```python
)
VISIONOS = ClientProfile(
    name="VISIONOS",
    client_id=101,
    version="1.02",
    user_agent=(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_7_3) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/26.0 Safari/605.1.15"
    ),
    extra=(
        ("deviceMake", "Apple"),
        ("deviceModel", "RealityDevice17,1"),
        ("osName", "visionOS"),
        ("osVersion", "26.5.23O471"),
    ),
    needs_visitor=True,
)
WEB = ClientProfile(
```

**In `src/utmax/core/clients.py`, replace:**

```python
        "streams": (ANDROID_VR, ANDROID, IOS),
```

**with:**

```python
        "streams": (VISIONOS, ANDROID_VR),
```

**In `src/utmax/core/clients.py`, replace:**

```python
    {profile.name: profile for profile in (ANDROID, IOS, ANDROID_VR, WEB)}
```

**with:**

```python
    {profile.name: profile for profile in (ANDROID, IOS, ANDROID_VR, VISIONOS, WEB)}
```

- [ ] **Step 4: Ask for, send and renew the visitorData in the InnerTube adapter**

**In `src/utmax/adapters/innertube.py`, replace:**

```python
import logging
from collections.abc import Callable
```

**with:**

```python
import logging
import threading
from collections.abc import Callable
```

**In `src/utmax/adapters/innertube.py`, replace:**

```python
from utmax.core.clients import ANDROID, DESKTOP_USER_AGENT, ORDER, ClientProfile, Purpose
from utmax.core.playability import check_playability
from utmax.core.player import PlayerData, parse_player_response
```

**with:**

```python
from utmax.core.clients import (
    ANDROID,
    DESKTOP_USER_AGENT,
    ORDER,
    VISIONOS,
    ClientProfile,
    Purpose,
)
from utmax.core.playability import check_playability
from utmax.core.player import PlayerData, parse_player_response
from utmax.core.ytdata import mapping
```

**In `src/utmax/adapters/innertube.py`, replace:**

```python
    """Talks to InnerTube with a chain of client profiles (see ``utmax.core.clients``)."""
```

**with:**

```python
    """Talks to InnerTube with a chain of client profiles (see ``utmax.core.clients``).

    Profiles that need a ``visitorData`` send the one this client asked YouTube for on first
    use, shared by every thread; a bot check renews it once per player request.
    """
```

**In `src/utmax/adapters/innertube.py`, replace:**

```python

    def player(self, video_id: str, *, purpose: Purpose = "captions") -> PlayerData:
        """A playable player response, trying each profile for ``purpose`` in order.

        For ``"streams"``, a response without a direct MP4 stream URL counts as a failed profile.
        """
```

**with:**

```python
        self._visitor: str | None = None
        self._visitor_lock = threading.Lock()

    def player(
        self, video_id: str, *, purpose: Purpose = "captions", renew_visitor: bool = False
    ) -> PlayerData:
        """A playable player response, trying each profile for ``purpose`` in order.

        For ``"streams"``, a response without a direct MP4 stream URL counts as a failed profile.
        ``renew_visitor`` first asks YouTube for a new ``visitorData``: it restricts the streams
        of some visitors, so a download that keeps meeting 403s refreshes as a new one.
        """
        if renew_visitor:
            self._renew_visitor_data(self._visitor)
```

**In `src/utmax/adapters/innertube.py`, replace:**

```python
                    partial(self._playable, profile, video_id, None, purpose=purpose)
```

**with:**

```python
                    partial(self._playable_as_visitor, profile, video_id, purpose=purpose)
```

**In `src/utmax/adapters/innertube.py`, replace:**

```python
        self, profile: ClientProfile, video_id: str, *, api_key: str | None = None
```

**with:**

```python
        self,
        profile: ClientProfile,
        video_id: str,
        *,
        api_key: str | None = None,
        visitor_data: str | None = None,
```

**In `src/utmax/adapters/innertube.py`, replace:**

```python
            "context": profile.context_payload(),
```

**with:**

```python
            "context": profile.context_payload(visitor_data),
```

**In `src/utmax/adapters/innertube.py`, replace:**

```python
        response = self._transport.send(HttpRequest("POST", url, profile.request_headers(), body))
        return _json_object(response, video_id=video_id)
```

**with:**

```python
        headers = profile.request_headers(visitor_data)
        response = self._transport.send(HttpRequest("POST", url, headers, body))
        return _json_object(response, video_id=video_id)

    def visitor_data(self) -> str | None:
        """The ``visitorData`` YouTube issued to this client, asked for on first use.

        ``None`` when YouTube issued none; the next call asks again.
        """
        with self._visitor_lock:
            if self._visitor is None:
                self._visitor = self._new_visitor_data()
            return self._visitor
```

**In `src/utmax/adapters/innertube.py`, replace:**

```python
    def _playable(
        self, profile: ClientProfile, video_id: str, api_key: str | None, *, purpose: Purpose
    ) -> PlayerData:
        data = self.player_json(profile, video_id, api_key=api_key)
```

**with:**

```python
    def _new_visitor_data(self) -> str | None:
        try:
            data = self._post(VISIONOS, "visitor_id", {"context": VISIONOS.context_payload()})
        except (YouTubeRequestFailed, YouTubeDataUnparsable) as error:
            log.info("YouTube issued no visitorData: %s", error)
            return None
        value = mapping(data.get("responseContext")).get("visitorData")
        return value if isinstance(value, str) and value else None

    def _renew_visitor_data(self, seen: str | None) -> str | None:
        """A new ``visitorData``, unless another thread already replaced ``seen``."""
        with self._visitor_lock:
            if self._visitor == seen:
                self._visitor = self._new_visitor_data()
            return self._visitor

    def _playable_as_visitor(
        self, profile: ClientProfile, video_id: str, *, purpose: Purpose
    ) -> PlayerData:
        """``_playable`` for ``profile``; one that needs a ``visitorData`` and meets a bot check
        tries once more with a new one."""
        if not profile.needs_visitor:
            return self._playable(profile, video_id, None, purpose=purpose)
        visitor = self.visitor_data()
        try:
            return self._playable(profile, video_id, None, purpose=purpose, visitor_data=visitor)
        except RequestBlocked as error:
            if isinstance(error, IpBlocked):
                raise
            log.info(
                "%s met a bot check for %s; asking for a new visitorData", profile.name, video_id
            )
            visitor = self._renew_visitor_data(visitor)
            return self._playable(profile, video_id, None, purpose=purpose, visitor_data=visitor)

    def _playable(
        self,
        profile: ClientProfile,
        video_id: str,
        api_key: str | None,
        *,
        purpose: Purpose,
        visitor_data: str | None = None,
    ) -> PlayerData:
        data = self.player_json(profile, video_id, api_key=api_key, visitor_data=visitor_data)
```

- [ ] **Step 5: Refresh stream URLs as a new visitor, in 2 MiB chunks**

**In `src/utmax/services/download.py`, replace:**

```python
            refresh=lambda: self._innertube.player(video_id, purpose="streams").streams,
```

**with:**

```python
            refresh=lambda: (
                self._innertube.player(video_id, purpose="streams", renew_visitor=True).streams
            ),
```

**In `src/utmax/core/downloads.py`, replace:**

```python
DEFAULT_CHUNK_SIZE = 8 * MIB
```

**with:**

```python
# YouTube slows VISIONOS range requests of 8 MiB to about 150 KB/s after a burst, while 4 MiB
# and smaller ones run at full speed (measured 2026-10-09); 2 MiB leaves a margin.
DEFAULT_CHUNK_SIZE = 2 * MIB
```

**In `src/utmax/__init__.py`, replace:**

```python
        chunk_size: bytes per range request, at least 256 KiB.
```

**with:**

```python
        chunk_size: bytes per range request, at least 256 KiB (YouTube slows down larger
            requests of 8 MiB, so the default is 2 MiB).
```

- [ ] **Step 6: Run the gates**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: all clean; **1676 passed, 28 deselected** (12 new tests).

- [ ] **Step 7: Commit**

```bash
git add src/utmax/core/clients.py src/utmax/adapters/innertube.py src/utmax/core/downloads.py src/utmax/services/download.py src/utmax/__init__.py tests/helpers/youtube.py tests/helpers/downloads.py tests/helpers/bulk.py tests/unit/core/test_clients.py tests/unit/adapters/test_innertube.py tests/unit/adapters/test_innertube_visitor.py tests/unit/services/test_download_audio.py tests/unit/services/test_download_video.py tests/unit/test_download_api.py
git commit -m "feat: download streams through VISIONOS with a visitorData YouTube issued"
```

### Task 2: The best stream a file type holds

**Files:**
- Modify: `src/utmax/models.py`, `src/utmax/core/streams.py`, `src/utmax/core/player.py`, `src/utmax/services/download.py`, `src/utmax/services/bulk.py`, `src/utmax/client.py`, `src/utmax/__init__.py`, `src/utmax/mcp/server.py`
- Test: `tests/unit/core/test_streams.py`, `tests/unit/services/test_download_video.py`, `tests/unit/services/test_download_audio.py`, `tests/unit/services/test_bulk_downloads.py`, `tests/unit/test_download_api.py`

**Interfaces:**
- Produces: `Quality = Literal["best", "compat"]` (default `"best"` everywhere; `"max"` is gone); `Format.hdr: bool = False`, `Format.bit_depth: int = 8`, `Format.language: str | None = None`, `Format.is_original: bool = False` (and labels such as `"701 mp4 av1 2160p60 hdr"`, `"140 mp4 aac 44.1kHz en-US original"`); `Stream.problem` only for DRM, live, signature, progressive and unknown codecs; `choose_streams(streams, *, container, quality, resolution: int | None = None, video_id)`.
- Consumes: Task 1's VISIONOS URLs (`xtags`) as test data shape; `PlayerData.spoken_language` now comes from the parsed streams.

- [ ] **Step 1: Write the failing tests**

**In `tests/unit/core/test_streams.py`, replace:**

```python
    found: tuple[Stream, ...], container: Container = "mp4", quality: Quality = "compat"
) -> tuple[int | None, int]:
    picked, sound = choose_streams(found, container=container, quality=quality, video_id="v")
    return (picked.format.itag if picked else None, sound.format.itag)
```

**with:**

```python
    found: tuple[Stream, ...],
    container: Container = "mp4",
    quality: Quality = "best",
    resolution: int | None = None,
) -> tuple[int | None, int]:
    picked, sound = choose_streams(
        found, container=container, quality=quality, resolution=resolution, video_id="v"
    )
    return (picked.format.itag if picked else None, sound.format.itag)


def track_url(itag: int, xtags: str) -> str:
    """A stream URL with YouTube's ``xtags`` (percent-encoded, as YouTube sends it)."""
    return f"https://rr1.googlevideo.com/videoplayback?itag={itag}&c=VISIONOS&xtags={xtags}"
```

**In `tests/unit/core/test_streams.py`, replace:**

```python
        ("mp4", "max", (401, 140)),
        ("mov", "compat", (137, 140)),
        ("m4a", "compat", (None, 140)),
        ("mp3", "max", (None, 140)),
```

**with:**

```python
        ("mp4", "best", (401, 140)),
        ("mov", "compat", (137, 140)),
        ("mov", "best", (137, 140)),
        ("m4a", "best", (None, 140)),
        ("mp3", "compat", (None, 140)),
```

**In `tests/unit/core/test_streams.py`, replace:**

```python
        (video(248, "vp9", 1920, 1080), "WebM"),
        (video(337, "vp09.02.51.10.01.09.16.09.00", 3840, 2160), "WebM"),
        (video(701, "av01.0.12M.10.0.110.09.16.09.0", 3840, 2160), "HDR or more than 8 bits"),
        (
            video(
                399,
                "av01.0.08M.08",
                1920,
                1080,
                colorInfo={"transferCharacteristics": "COLOR_TRANSFER_CHARACTERISTICS_SMPTEST2084"},
            ),
            "HDR or more than 8 bits",
        ),
        (
            video(400, "av01.0.12M.08", 2560, 1440, qualityLabel="1440p60 HDR"),
            "HDR or more than 8 bits",
        ),
        (audio(328, "ec-3"), "other codec"),
        (audio(251, "opus"), "WebM"),
```

**with:**

```python
        (video(248, "vp9", 1920, 1080), None),
        (video(337, "vp09.02.51.10.01.09.16.09.00", 3840, 2160), None),
        (video(701, "av01.0.12M.10.0.110.09.16.09.0", 3840, 2160), None),
        (audio(328, "ec-3"), "other codec"),
        (audio(251, "opus"), None),
```

**In `tests/unit/core/test_streams.py`, replace:**

```python
def test_max_prefers_av1_at_equal_size_then_frame_rate_and_bitrate() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080, bitrate=4_000_000),
        video(399, "av01.0.08M.08", 1920, 1080, bitrate=1_600_000),
        video(299, "avc1.64002a", 1920, 1080, fps=50, bitrate=5_000_000),
        audio(140),
    )
    assert choose(found, quality="compat") == (299, 140)
    assert choose(found, quality="max") == (399, 140)


def test_quality_caps_the_size() -> None:
```

**with:**

```python
def test_best_prefers_size_then_frame_rate_then_av1_then_bitrate() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080, bitrate=4_000_000),
        video(399, "av01.0.08M.08", 1920, 1080, bitrate=1_600_000),
        video(136, "avc1.4d401f", 1280, 720, fps=50, bitrate=3_000_000),
        audio(140),
    )
    assert choose(found) == (399, 140)
    assert choose(found, quality="compat") == (137, 140)
    faster = streams(
        video(299, "avc1.64002a", 1920, 1080, fps=50, bitrate=5_000_000),
        video(399, "av01.0.08M.08", 1920, 1080, bitrate=1_600_000),
        audio(140),
    )
    assert choose(faster) == (299, 140)


def test_best_has_no_size_limit_and_resolution_caps_it() -> None:
```

**In `tests/unit/core/test_streams.py`, replace:**

```python
    assert choose(found) == (137, 140)
    assert choose(found, quality="max") == (401, 140)
```

**with:**

```python
    assert choose(found) == (571, 140)
    assert choose(found, resolution=2160) == (401, 140)
    assert choose(found, resolution=1440) == (137, 140)
    assert choose(found, quality="compat") == (137, 140)
    assert choose(found, quality="compat", resolution=4320) == (137, 140)
    with pytest.raises(FormatNotAvailable, match=r"has no H\.264 or AV1 video up to 720p in MP4"):
        choose(found, resolution=720)
    with pytest.raises(FormatNotAvailable, match=r"has no H\.264 video up to 720p"):
        choose(found, quality="compat", resolution=720)


def test_hdr_is_chosen_only_where_it_is_bigger_and_never_for_compat() -> None:
    hdr = {"qualityLabel": "HDR", "fps": 60}
    found = streams(
        video(701, "av01.0.12M.10.0.110.09.16.09.0", 3840, 2160, **hdr),
        video(699, "av01.0.08M.10.0.110.09.16.09.0", 1920, 1080, **hdr),
        video(399, "av01.0.08M.08", 1920, 1080, fps=60),
        video(299, "avc1.64002a", 1920, 1080, fps=60),
        audio(140),
    )
    assert choose(found) == (701, 140)
    assert choose(found, resolution=1080) == (399, 140)
    assert choose(found, quality="compat") == (299, 140)


def test_mov_takes_h264_only() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080),
        video(401, "av01.0.12M.08", 3840, 2160),
        audio(140),
    )
    assert choose(found, "mov") == (137, 140)
    with pytest.raises(FormatNotAvailable, match=r"has no H\.264 video\."):
        choose(streams(video(401, "av01.0.12M.08", 3840, 2160), audio(140)), "mov")


def test_webm_streams_do_not_fit_mp4_files() -> None:
    found = streams(video(313, "vp9", 3840, 2160), video(137, "avc1.640028", 1920, 1080))
    with pytest.raises(FormatNotAvailable, match="has no AAC audio in MP4"):
        choose((*found, *streams(audio(251, "opus"))))
    assert choose((*found, *streams(audio(140)))) == (137, 140)


def test_audio_tracks_hdr_and_bit_depth_are_parsed() -> None:
    dub, original, tagged, picture = streams(
        audio(
            140,
            url=track_url(140, "acont%3Ddubbed-auto%3Alang%3Dar"),
            audioTrack={"id": "ar.10", "displayName": "Arabic", "audioIsDefault": True},
        ),
        audio(
            140,
            url=track_url(140, "acont%3Doriginal%3Adrc%3D1%3Alang%3Den-US"),
            audioTrack={"id": "en-US.4", "displayName": "English (US) original"},
        ),
        audio(251, "opus", url=track_url(251, "acont%3Doriginal%3Alang%3Dde")),
        video(701, "av01.0.12M.10.0.110.09.16.09.0", 3840, 2160, qualityLabel="2160p60 HDR"),
    )
    assert (dub.format.language, dub.format.is_original) == ("ar", False)
    assert (original.format.language, original.format.is_original) == ("en-US", True)
    assert (tagged.format.language, tagged.format.is_original) == ("de", True)
    assert (picture.format.hdr, picture.format.bit_depth) == (True, 10)
    assert original.format.label == "140 mp4 aac 44.1kHz en-US original"
    assert picture.format.label == "701 mp4 av1 2160p25 hdr"


def test_audio_prefers_the_original_track_of_a_dubbed_video() -> None:
    found = streams(
        video(137, "avc1.640028", 1920, 1080),
        audio(
            140,
            bitrate=140_000,
            url=track_url(140, "acont%3Ddubbed-auto%3Alang%3Dar"),
            audioTrack={"id": "ar.10", "displayName": "Arabic", "audioIsDefault": True},
        ),
        audio(
            140,
            bitrate=129_000,
            url=track_url(140, "acont%3Doriginal%3Alang%3Den-US"),
            audioTrack={"id": "en-US.4", "displayName": "English (US) original"},
        ),
    )
    _, chosen = choose_streams(found, container="m4a", quality="best", video_id="v")
    assert (chosen.format.language, chosen.format.is_original) == ("en-US", True)
```

**In `tests/unit/core/test_streams.py`, replace:**

```python
    _, chosen = choose_streams(found, container="mp4", quality="compat", video_id="v")
```

**with:**

```python
    _, chosen = choose_streams(found, container="mp4", quality="best", video_id="v")
```

**In `tests/unit/core/test_streams.py`, replace:**

```python
        choose_streams(found, container="mp4", quality="compat", video_id="abc")
    assert caught.value.available == (
        "248 webm vp9 1080p25 (WebM)",
        "251 webm opus 44.1kHz (WebM)",
    )
```

**with:**

```python
        choose_streams(found, container="mp4", quality="best", video_id="abc")
    assert caught.value.available == ("248 webm vp9 1080p25", "251 webm opus 44.1kHz")
```

**In `tests/unit/core/test_streams.py`, replace:**

```python
    (webm,) = streams(video(248, "vp9", 1920, 1080))
    assert describe_stream(webm) == "248 webm vp9 1080p25 (WebM)"
```

**with:**

```python
    (protected,) = streams(video(137, "avc1.640028", 1920, 1080, drmFamilies=["WIDEVINE"]))
    assert describe_stream(protected) == "137 mp4 h264 1080p25 (DRM-protected)"
```

The fake downloads now pick AV1 by default (H.264 with `quality="compat"`), and `"max"` is an unknown quality:

**In `tests/unit/services/test_download_video.py`, replace:**

```python
    assert (result.video_format.itag, result.audio_format.itag) == (137, 140)
    assert result.embedded_subtitles == ("en",)
    movie = read_movie(result.path)
    assert [track.handler for track in movie.tracks] == ["vide", "soun", "sbtl"]
    assert [codec_of(track) for track in movie.tracks] == [b"avc1", b"mp4a", b"tx3g"]
```

**with:**

```python
    assert (result.video_format.itag, result.audio_format.itag) == (399, 140)
    assert result.embedded_subtitles == ("en",)
    movie = read_movie(result.path)
    assert [track.handler for track in movie.tracks] == ["vide", "soun", "sbtl"]
    assert [codec_of(track) for track in movie.tracks] == [b"av01", b"mp4a", b"tx3g"]
```

**In `tests/unit/services/test_download_video.py`, replace:**

```python
def test_max_quality_prefers_av1(tmp_path: Path) -> None:
    options = DownloadOptions(quality="max")
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.mp4", options)
    assert result.video_format is not None
    assert result.video_format.itag == 399
    assert codec_of(read_movie(result.path).tracks[0]) == b"av01"
```

**with:**

```python
def test_compat_quality_keeps_h264(tmp_path: Path) -> None:
    options = DownloadOptions(quality="compat")
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.mp4", options)
    assert result.video_format is not None
    assert result.video_format.itag == 137
    assert codec_of(read_movie(result.path).tracks[0]) == b"avc1"
```

**In `tests/unit/services/test_download_audio.py`, replace:**

```python
        ("rick.mp4", DownloadOptions(quality="best"), InvalidOption, "quality="),
```

**with:**

```python
        ("rick.mp4", DownloadOptions(quality="max"), InvalidOption, 'is not "best" or "compat"'),
```

**In `tests/unit/services/test_download_audio.py`, replace:**

```python
        ),
        ("rick.mov", DownloadOptions(quality="max"), InvalidOption, r"needs \.mp4"),
```

**with:**

```python
        ),
```

**In `tests/unit/services/test_bulk_downloads.py`, replace:**

```python
        assert [codec_of(track) for track in tracks] == [b"avc1", b"mp4a", b"tx3g"]
```

**with:**

```python
        assert [codec_of(track) for track in tracks] == [b"av01", b"mp4a", b"tx3g"]
```

**In `tests/unit/services/test_bulk_downloads.py`, replace:**

```python
    assert [codec_of(track) for track in tracks] == [b"avc1", b"mp4a", b"tx3g"]
```

**with:**

```python
    assert [codec_of(track) for track in tracks] == [b"av01", b"mp4a", b"tx3g"]
```

**In `tests/unit/services/test_bulk_downloads.py`, replace:**

```python
        {"quality": "best"},
        {"format": "mov", "quality": "max"},
```

**with:**

```python
        {"quality": "max"},
```

**In `tests/unit/test_download_api.py`, replace:**

```python
    assert (parameters["quality"].default, parameters["subtitle_mode"].default) == (
        "compat",
        "embed",
```

**with:**

```python
    assert (parameters["quality"].default, parameters["subtitle_mode"].default) == (
        "best",
        "embed",
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_streams.py tests/unit/services tests/unit/test_download_api.py -q`
Expected: 26 failed — among them `'HDR or more than 8 bits' == None`, `'WebM' == None`, `[b'avc1', ...] == [b'av01', ...]` and `('compat', 'embed') == ('best', 'embed')`.

- [ ] **Step 3: Give formats their picture and audio-track facts**

**In `src/utmax/models.py`, replace:**

```python
Quality = Literal["compat", "max"]
```

**with:**

```python
Quality = Literal["best", "compat"]
```

**In `src/utmax/models.py`, replace:**

```python
    """One stream YouTube offers for a video; its URL never leaves utmax."""
```

**with:**

```python
    """One stream YouTube offers for a video; its URL never leaves utmax.

    ``hdr`` and ``bit_depth`` describe the picture; ``language`` is the language of an audio
    track (``None`` when YouTube does not say), and ``is_original`` marks the original audio
    of a video that also has dubbed tracks.
    """
```

**In `src/utmax/models.py`, replace:**

```python

    @property
    def label(self) -> str:
        """A short description such as ``"137 mp4 h264 1080p25"`` or ``"140 mp4 aac 44.1kHz"``."""
```

**with:**

```python
    hdr: bool = False
    bit_depth: int = 8
    language: str | None = None
    is_original: bool = False

    @property
    def label(self) -> str:
        """A short description such as ``"137 mp4 h264 1080p25"``, ``"701 mp4 av1 2160p60 hdr"``
        or ``"140 mp4 aac 44.1kHz en-US original"``."""
```

**In `src/utmax/models.py`, replace:**

```python
        else:
            if self.audio_sample_rate:
                words.append(f"{self.audio_sample_rate / 1000:g}kHz")
```

**with:**

```python
            if self.hdr:
                words.append("hdr")
        else:
            if self.audio_sample_rate:
                words.append(f"{self.audio_sample_rate / 1000:g}kHz")
            if self.language:
                words.append(self.language)
            if self.is_original:
                words.append("original")
```

- [ ] **Step 4: Parse them and choose by file type, quality and resolution**

**In `src/utmax/core/streams.py`, replace:**

```python
downloads one adaptive MP4 video stream and one AAC audio stream and muxes them itself.
```

**with:**

```python
downloads one adaptive video stream and one audio stream that fit the target file and muxes
them itself.
```

**In `src/utmax/core/streams.py`, replace:**

```python
    "COMPAT_MAX_SIDE",
    "MAX_MAX_SIDE",
```

**with:**

```python
    "COMPAT_MAX_SIDE",
```

**In `src/utmax/core/streams.py`, replace:**

```python
COMPAT_MAX_SIDE = 1080
MAX_MAX_SIDE = 2160
```

**with:**

```python
COMPAT_MAX_SIDE = 1080
```

**In `src/utmax/core/streams.py`, replace:**

```python
_MUXABLE: frozenset[str] = frozenset({"h264", "av1", "aac", "he-aac"})
```

**with:**

```python
# The video codecs each file type holds, the preferred one first.
_VIDEO_CODECS: Mapping[Container, tuple[Codec, ...]] = {"mp4": ("av1", "h264"), "mov": ("h264",)}
_AUDIO_CODECS: tuple[Codec, ...] = ("aac", "he-aac")
_CODEC_NAMES: tuple[tuple[Codec, str], ...] = (("h264", "H.264"), ("av1", "AV1"))
```

**In `src/utmax/core/streams.py`, replace:**

```python
    user_agent: str = DESKTOP_USER_AGENT
    bit_depth: int = 8
    hdr: bool = False
```

**with:**

```python
    user_agent: str = DESKTOP_USER_AGENT
```

**In `src/utmax/core/streams.py`, replace:**

```python
        """Why utmax cannot download and mux this stream, or ``None`` when it can."""
```

**with:**

```python
        """Why utmax can never download this stream, or ``None`` when it can.

        Whether a usable stream fits a file type is :func:`choose_streams`' business.
        """
```

**In `src/utmax/core/streams.py`, replace:**

```python
        if self.format.container != "mp4":
            return "WebM"
        if self.hdr or self.bit_depth > 8:
            return "HDR or more than 8 bits"
        if self.format.codec not in _MUXABLE:
            return f"{self.format.codec} codec"
```

**with:**

```python
        if self.format.codec == "other":
            return "other codec"
```

**In `src/utmax/core/streams.py`, replace:**

```python
    streams: Sequence[Stream], *, container: Container, quality: Quality, video_id: str
) -> tuple[Stream | None, Stream]:
    """The video stream (``None`` for audio files) and the audio stream to download.

    Video: MP4 H.264 up to 1080p for ``"compat"``; MP4 H.264 or 8-bit AV1 up to 2160p for
    ``"max"``, AV1 first at the same size; then the higher frame rate and bitrate. Sizes are
    measured on the short side, so vertical videos count like their landscape twins. Audio: MP4
    AAC, preferring the video's default audio track, then streams without dynamic range
    compression, then the higher bitrate; ``.mov`` accepts only stereo at most 65535 Hz.
```

**with:**

```python
    streams: Sequence[Stream],
    *,
    container: Container,
    quality: Quality,
    resolution: int | None = None,
    video_id: str,
) -> tuple[Stream | None, Stream]:
    """The video stream (``None`` for audio files) and the audio stream to download.

    Video, sizes measured on the short side so that vertical videos count like their landscape
    twins: ``"best"`` takes the largest picture the file type holds (``.mp4``: AV1 or H.264,
    HDR included; ``.mov``: H.264) up to ``resolution`` lines, then the higher frame rate, then
    SDR over HDR, then AV1 over H.264, then the higher bitrate. ``"compat"`` takes SDR H.264 up
    to 1080p (or ``resolution``, when smaller), which plays everywhere. Audio: AAC, preferring
    the original track of a dubbed video, then YouTube's default track, then streams without
    dynamic range compression, then the higher bitrate; ``.mov`` accepts only stereo at most
    65535 Hz.
```

**In `src/utmax/core/streams.py`, replace:**

```python
    video = _best_video(usable, quality)
    if video is None:
        wanted = (
            "H.264 or 8-bit AV1 video up to 2160p in MP4"
            if quality == "max"
            else "H.264 video up to 1080p in MP4"
        )
        raise _not_available(streams, wanted, video_id)
    return video, audio


def _best_video(streams: Sequence[Stream], quality: Quality) -> Stream | None:
    limit = MAX_MAX_SIDE if quality == "max" else COMPAT_MAX_SIDE
    codecs = ("h264", "av1") if quality == "max" else ("h264",)
```

**with:**

```python
    codecs = ("h264",) if quality == "compat" else _VIDEO_CODECS[container]
    limit = resolution
    if quality == "compat":
        limit = min(resolution or COMPAT_MAX_SIDE, COMPAT_MAX_SIDE)
    video = _best_video(usable, codecs, limit, sdr_only=quality == "compat")
    if video is None:
        raise _not_available(streams, _wanted_video(container, codecs, limit), video_id)
    return video, audio


def _best_video(
    streams: Sequence[Stream], codecs: tuple[Codec, ...], limit: int | None, *, sdr_only: bool
) -> Stream | None:
```

**In `src/utmax/core/streams.py`, replace:**

```python
        and 0 < _short_side(stream.format) <= limit
```

**with:**

```python
        and 0 < _short_side(stream.format) <= (limit or _short_side(stream.format))
        and not (sdr_only and stream.format.hdr)
```

**In `src/utmax/core/streams.py`, replace:**

```python
            stream.format.codec == "av1",
            stream.format.fps or 0,
```

**with:**

```python
            stream.format.fps or 0,
            not stream.format.hdr,
            -codecs.index(stream.format.codec),
```

**In `src/utmax/core/streams.py`, replace:**

```python

def _best_audio(streams: Sequence[Stream], container: Container) -> Stream | None:
```

**with:**

```python

def _wanted_video(container: Container, codecs: tuple[Codec, ...], limit: int | None) -> str:
    """``"H.264 or AV1 video up to 720p in MP4"`` and the like, for an error message."""
    names = " or ".join(name for codec, name in _CODEC_NAMES if codec in codecs)
    size = f" up to {limit}p" if limit is not None else ""
    where = " in MP4" if container == "mp4" and len(codecs) > 1 else ""
    return f"{names} video{size}{where}"


def _best_audio(streams: Sequence[Stream], container: Container) -> Stream | None:
```

**In `src/utmax/core/streams.py`, replace:**

```python
        if stream.format.kind == "audio" and stream.format.codec in ("aac", "he-aac")
```

**with:**

```python
        if stream.format.kind == "audio" and stream.format.codec in _AUDIO_CODECS
```

**In `src/utmax/core/streams.py`, replace:**

```python
        key=lambda stream: (
            stream.format.is_default_audio,
```

**with:**

```python
        key=lambda stream: (
            stream.format.is_original,
            stream.format.is_default_audio,
```

**In `src/utmax/core/streams.py`, replace:**

```python
    track = mapping(raw.get("audioTrack"))
```

**with:**

```python
    track = mapping(raw.get("audioTrack"))
    tags = _xtags(query.get("xtags", ""))
    name = str(track.get("displayName") or "")
```

**In `src/utmax/core/streams.py`, replace:**

```python
            last_modified=str(raw.get("lastModified") or ""),
```

**with:**

```python
            last_modified=str(raw.get("lastModified") or ""),
            hdr=_is_hdr(raw),
            bit_depth=_bit_depth(first),
            language=str(track.get("id") or "").partition(".")[0] or tags.get("lang") or None,
            is_original=tags.get("acont") == "original" or name.lower().endswith(" original"),
```

**In `src/utmax/core/streams.py`, replace:**

```python
        user_agent=profile.user_agent if profile is not None else DESKTOP_USER_AGENT,
        bit_depth=_bit_depth(first),
        hdr=_is_hdr(raw),
```

**with:**

```python
        user_agent=profile.user_agent if profile is not None else DESKTOP_USER_AGENT,
```

**In `src/utmax/core/streams.py`, replace:**

```python

def _is_hdr(raw: Mapping[str, Any]) -> bool:
```

**with:**

```python

def _xtags(text: str) -> dict[str, str]:
    """YouTube's ``xtags`` of a stream, such as ``acont=original:lang=en-US``, as a dict."""
    pairs = (part.partition("=") for part in text.split(":") if part)
    return {key: value for key, _, value in pairs}


def _is_hdr(raw: Mapping[str, Any]) -> bool:
```

**In `src/utmax/core/player.py`, replace:**

```python
    streaming = mapping(data.get("streamingData"))
```

**with:**

```python
    streams = parse_streams(mapping(data.get("streamingData")))
    # Videos with dubbed audio mark their original track (videos with one track mark nothing).
    spoken = next((stream.format.language for stream in streams if stream.format.is_original), None)
```

**In `src/utmax/core/player.py`, replace:**

```python
        streams=parse_streams(streaming),
        spoken_language=_original_audio_language(streaming),
    )


def _original_audio_language(streaming: Mapping[str, Any]) -> str | None:
    """The language of the original audio of a video with dubbed audio tracks, like ``en-US``.

    YouTube names that track "<language> original" (utmax always asks in English) and tags its
    stream URLs ``acont=original``; videos with a single audio track mark nothing.
    """
    for raw in map(mapping, items(streaming.get("adaptiveFormats"))):
        track = mapping(raw.get("audioTrack"))
        name = str(track.get("displayName") or "").lower()
        url = str(raw.get("url") or "").lower()
        original = name.endswith(" original") or any(
            mark in url for mark in ("acont%3doriginal", "acont=original")
        )
        code = str(track.get("id") or "").partition(".")[0]
        if original and code:
            return code
    return None
```

**with:**

```python
        streams=streams,
        spoken_language=spoken,
    )
```

- [ ] **Step 5: "best" through the services, the client, the facade and the MCP server**

**In `src/utmax/services/download.py`, replace:**

```python
_QUALITIES = ("compat", "max")
```

**with:**

```python
_QUALITIES = ("best", "compat")
```

**In `src/utmax/services/download.py`, replace:**

```python
    quality: Quality = "compat"
```

**with:**

```python
    quality: Quality = "best"
```

**In `src/utmax/services/download.py`, replace:**

```python
            raise InvalidOption(f'quality={self.quality!r} is not "compat" or "max".')
```

**with:**

```python
            raise InvalidOption(f'quality={self.quality!r} is not "best" or "compat".')
```

**In `src/utmax/services/download.py`, replace:**

```python
        container = target.container
        if container == "mov" and options.quality == "max":
            raise InvalidOption(
                'quality="max" needs .mp4: QuickTime .mov files cannot hold AV1 video.',
                suggestion='Save max quality as .mp4, or use quality="compat" for .mov.',
                video_id=video_id,
            )
```

**with:**

```python
        container = target.container
```

**In `src/utmax/services/bulk.py`, replace:**

```python
        quality: Quality = "compat",
```

**with:**

```python
        quality: Quality = "best",
```

**In `src/utmax/client.py`, replace:**

```python
        format: Container | None = None,
        quality: Quality = "compat",
        subtitles: Sequence[str | Transcript] | None = None,
```

**with:**

```python
        format: Container | None = None,
        quality: Quality = "best",
        subtitles: Sequence[str | Transcript] | None = None,
```

**In `src/utmax/client.py`, replace:**

```python
        quality: Quality = "compat",
```

**with:**

```python
        quality: Quality = "best",
```

**In `src/utmax/__init__.py`, replace:**

```python
    format: Container | None = None,
    quality: Quality = "compat",
    subtitles: Sequence[str | Transcript] | None = None,
```

**with:**

```python
    format: Container | None = None,
    quality: Quality = "best",
    subtitles: Sequence[str | Transcript] | None = None,
```

**In `src/utmax/__init__.py`, replace:**

```python
        utmax.download("dQw4w9WgXcQ", "videos/", quality="max")  # AV1 up to 4K, named by title
```

**with:**

```python
        utmax.download("dQw4w9WgXcQ", "videos/")  # the best MP4 (AV1 up to 8K), named by title
```

**In `src/utmax/__init__.py`, replace:**

```python
        quality: ``"compat"`` (H.264 up to 1080p, plays everywhere) or ``"max"`` (AV1 or
            H.264 up to 2160p; ``.mp4`` only).
```

**with:**

```python
        quality: ``"best"`` (the largest picture the file type holds: AV1 or H.264 in
            ``.mp4``, HDR where it is the only way to a larger picture; H.264 in ``.mov``) or
            ``"compat"`` (H.264 up to 1080p, plays everywhere).
```

**In `src/utmax/__init__.py`, replace:**

```python
    quality: Quality = "compat",
```

**with:**

```python
    quality: Quality = "best",
```

**In `src/utmax/mcp/server.py`, replace:**

```python
    Field(description="compat: H.264 up to 1080p (plays everywhere); max: up to 4K (mp4 only)."),
```

**with:**

```python
    Field(
        description=(
            "best: the largest picture the file type holds (mp4: AV1 or H.264, up to 8K); "
            "compat: H.264 up to 1080p, plays everywhere."
        )
    ),
```

**In `src/utmax/mcp/server.py`, replace:**

```python
        quality: QualityArg = "compat",
```

**with:**

```python
        quality: QualityArg = "best",
```

**In `src/utmax/mcp/server.py`, replace:**

```python
    quality: Quality = "compat",
```

**with:**

```python
    quality: Quality = "best",
```

- [ ] **Step 6: Run the gates**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: all clean; **1678 passed, 28 deselected**.

- [ ] **Step 7: Commit**

```bash
git add src/utmax/models.py src/utmax/core/streams.py src/utmax/core/player.py src/utmax/services/download.py src/utmax/services/bulk.py src/utmax/client.py src/utmax/__init__.py src/utmax/mcp/server.py tests/unit/core/test_streams.py tests/unit/services/test_download_video.py tests/unit/services/test_download_audio.py tests/unit/services/test_bulk_downloads.py tests/unit/test_download_api.py
git commit -m "feat: choose the best stream a file type holds, HDR AV1 and original audio included"
```

### Task 3: list_formats and a resolution cap

**Files:**
- Modify: `src/utmax/models.py`, `src/utmax/core/streams.py`, `src/utmax/services/download.py`, `src/utmax/services/bulk.py`, `src/utmax/client.py`, `src/utmax/__init__.py`
- Test: `tests/unit/test_download_api.py`, `tests/unit/services/test_download_audio.py`, `tests/unit/services/test_bulk_downloads.py`, `tests/unit/core/test_streams.py`, `tests/unit/test_collections_api.py`

**Interfaces:**
- Produces: `utmax.FormatList(Sequence[Format])` with `video: VideoInfo` and `formats: tuple[Format, ...]`; `utmax.list_formats(video) -> FormatList` and `Client.list_formats` (the usable streams of the streams player response); `core.streams.file_types(fmt) -> tuple[Container, ...]` (`("mp4", "mov")` for H.264, `("mp4",)` for AV1, `("mp4", "mov", "m4a", "mp3")` for AAC, `()` otherwise); `DownloadOptions.resolution: int | None` (positive, else `InvalidOption`), and `resolution=` on `download`, `download_many` and their client methods.
- Consumes: Task 2's `choose_streams(..., resolution=...)` and `Format`.

- [ ] **Step 1: Write the failing tests**

**In `tests/unit/test_download_api.py`, replace:**

```python
    "quality",
    "subtitles",
```

**with:**

```python
    "quality",
    "resolution",
    "subtitles",
```

**In `tests/unit/test_download_api.py`, replace:**

```python

def test_download_signature_matches_the_spec() -> None:
```

**with:**

```python

def test_resolution_caps_the_picture(tmp_path: Path) -> None:
    with Client(transport=FakeYouTube()) as client:
        with pytest.raises(utmax.FormatNotAvailable, match="up to 720p"):
            client.download(VIDEO_ID, tmp_path / "rick.mp4", resolution=720)
        result = client.download(VIDEO_ID, tmp_path / "rick.mp4", resolution=1080)
    assert result.video_format is not None
    assert result.video_format.itag == 399


def test_list_formats_names_what_a_download_can_choose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(utmax, "_default_client", Client(transport=FakeYouTube()))
    formats = utmax.list_formats(f"https://youtu.be/{VIDEO_ID}")
    assert formats.video.video_id == VIDEO_ID
    assert [fmt.label for fmt in formats] == [
        "137 mp4 h264 1080p25",
        "399 mp4 av1 1080p25",
        "140 mp4 aac 44.1kHz",
    ]
    assert len(formats) == 3
    assert formats[1].codec == "av1"


def test_download_signature_matches_the_spec() -> None:
```

**In `tests/unit/services/test_download_audio.py`, replace:**

```python
        ("rick.mp4", DownloadOptions(subtitle_mode="burn"), InvalidOption, "subtitle_mode="),
```

**with:**

```python
        ("rick.mp4", DownloadOptions(subtitle_mode="burn"), InvalidOption, "subtitle_mode="),
        ("rick.mp4", DownloadOptions(resolution=0), InvalidOption, "resolution must be"),
        ("rick.mp4", DownloadOptions(resolution=True), InvalidOption, "resolution must be"),
```

**In `tests/unit/services/test_bulk_downloads.py`, replace:**

```python
from utmax.errors import FFmpegNotFound, InvalidOption, IpBlocked, VideoUnavailable
```

**with:**

```python
from utmax.errors import (
    FFmpegNotFound,
    FormatNotAvailable,
    InvalidOption,
    IpBlocked,
    VideoUnavailable,
)
```

**In `tests/unit/services/test_bulk_downloads.py`, replace:**

```python

@pytest.mark.parametrize(
```

**with:**

```python

def test_resolution_reaches_every_download(tmp_path: Path) -> None:
    youtube = ManyVideos()
    report = youtube.bulk().download_many(IDS, tmp_path / "videos", resolution=720)
    assert len(report.failed) == len(IDS)
    assert all(isinstance(result.error, FormatNotAvailable) for result in report.failed)


@pytest.mark.parametrize(
```

**In `tests/unit/services/test_bulk_downloads.py`, replace:**

```python
        {"quality": "max"},
        {"format": "avi"},
```

**with:**

```python
        {"quality": "max"},
        {"resolution": -1},
        {"format": "avi"},
```

**In `tests/unit/core/test_streams.py`, replace:**

```python
from utmax.core.streams import Stream, choose_streams, describe_stream, parse_streams
```

**with:**

```python
from utmax.core.streams import (
    Stream,
    choose_streams,
    describe_stream,
    file_types,
    parse_streams,
)
```

**In `tests/unit/core/test_streams.py`, replace:**

```python

def test_audio_tracks_hdr_and_bit_depth_are_parsed() -> None:
```

**with:**

```python

def test_file_types_name_where_a_format_fits() -> None:
    h264, av1, vp9, aac, opus = (
        stream.format
        for stream in streams(
            video(137, "avc1.640028", 1920, 1080),
            video(401, "av01.0.12M.08", 3840, 2160),
            video(313, "vp9", 3840, 2160),
            audio(140),
            audio(251, "opus"),
        )
    )
    assert file_types(h264) == ("mp4", "mov")
    assert file_types(av1) == ("mp4",)
    assert file_types(vp9) == ()
    assert file_types(aac) == ("mp4", "mov", "m4a", "mp3")
    assert file_types(opus) == ()


def test_audio_tracks_hdr_and_bit_depth_are_parsed() -> None:
```

**In `tests/unit/test_collections_api.py`, replace:**

```python
        "quality",
        "subtitles",
```

**with:**

```python
        "quality",
        "resolution",
        "subtitles",
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_download_api.py tests/unit/services tests/unit/core/test_streams.py -q`
Expected: collection errors — `ImportError: cannot import name 'file_types'` and `TypeError: DownloadOptions.__init__() got an unexpected keyword argument 'resolution'`.

- [ ] **Step 3: FormatList and file_types**

**In `src/utmax/models.py`, replace:**

```python
    "Format",
    "FormatName",
```

**with:**

```python
    "Format",
    "FormatList",
    "FormatName",
```

**In `src/utmax/models.py`, replace:**

```python
@dataclass(frozen=True, slots=True)
class Progress:
```

**with:**

```python
@dataclass(frozen=True, slots=True)
class FormatList(Sequence[Format]):
    """The streams of a video that utmax can download, in YouTube's order."""

    video: VideoInfo
    formats: tuple[Format, ...]

    @overload
    def __getitem__(self, index: int) -> Format: ...
    @overload
    def __getitem__(self, index: slice) -> tuple[Format, ...]: ...
    def __getitem__(self, index: int | slice) -> Format | tuple[Format, ...]:
        return self.formats[index]

    def __len__(self) -> int:
        return len(self.formats)

    def __iter__(self) -> Iterator[Format]:
        return iter(self.formats)


@dataclass(frozen=True, slots=True)
class Progress:
```

**In `src/utmax/core/streams.py`, replace:**

```python
    "describe_stream",
    "parse_streams",
```

**with:**

```python
    "describe_stream",
    "file_types",
    "parse_streams",
```

**In `src/utmax/core/streams.py`, replace:**

```python
    return stream.format.label if problem is None else f"{stream.format.label} ({problem})"
```

**with:**

```python
    return stream.format.label if problem is None else f"{stream.format.label} ({problem})"


def file_types(fmt: Format) -> tuple[Container, ...]:
    """The file types a stream can go into with ``quality="best"``."""
    if fmt.kind == "video":
        return tuple(
            container for container, codecs in _VIDEO_CODECS.items() if fmt.codec in codecs
        )
    if fmt.codec in _AUDIO_CODECS:
        return ("mp4", "mov", "m4a", "mp3")
    return ()
```

- [ ] **Step 4: The resolution option and list_formats in the services, the client and the facade**

**In `src/utmax/services/download.py`, replace:**

```python
    DownloadResult,
    Progress,
```

**with:**

```python
    DownloadResult,
    FormatList,
    Progress,
```

**In `src/utmax/services/download.py`, replace:**

```python
    quality: Quality = "best"
```

**with:**

```python
    quality: Quality = "best"
    resolution: int | None = None
```

**In `src/utmax/services/download.py`, replace:**

```python
            raise InvalidOption(f'quality={self.quality!r} is not "best" or "compat".')
```

**with:**

```python
            raise InvalidOption(f'quality={self.quality!r} is not "best" or "compat".')
        if self.resolution is not None and (
            isinstance(self.resolution, bool)
            or not isinstance(self.resolution, int)
            or self.resolution < 1
        ):
            raise InvalidOption(
                "resolution must be a positive number of lines, such as 1080, "
                f"not {self.resolution!r}."
            )
```

**In `src/utmax/services/download.py`, replace:**

```python

    def check(self, path: str | os.PathLike[str], options: DownloadOptions) -> None:
```

**with:**

```python

    def list_formats(self, video: str) -> FormatList:
        """The streams of ``video`` that a download can choose from."""
        player = self._innertube.player(parse_video_id(video), purpose="streams")
        usable = tuple(stream.format for stream in player.streams if stream.problem is None)
        return FormatList(video=player.video, formats=usable)

    def check(self, path: str | os.PathLike[str], options: DownloadOptions) -> None:
```

**In `src/utmax/services/download.py`, replace:**

```python
            player.streams, container=container, quality=options.quality, video_id=video_id
```

**with:**

```python
            player.streams,
            container=container,
            quality=options.quality,
            resolution=options.resolution,
            video_id=video_id,
```

**In `src/utmax/services/bulk.py`, replace:**

```python
        quality: Quality = "best",
```

**with:**

```python
        quality: Quality = "best",
        resolution: int | None = None,
```

**In `src/utmax/services/bulk.py`, replace:**

```python
            quality=quality,
            subtitles=subtitles,
```

**with:**

```python
            quality=quality,
            resolution=resolution,
            subtitles=subtitles,
```

**In `src/utmax/client.py`, replace:**

```python
    DownloadResult,
    FormatName,
```

**with:**

```python
    DownloadResult,
    FormatList,
    FormatName,
```

**In `src/utmax/client.py`, replace:**

```python

    def video_info(self, video: str) -> VideoInfo:
```

**with:**

```python

    def list_formats(self, video: str) -> FormatList:
        """The streams of ``video`` a download can choose from; see :func:`utmax.list_formats`."""
        return self._downloads.list_formats(video)

    def video_info(self, video: str) -> VideoInfo:
```

**In `src/utmax/client.py`, replace:**

```python
        quality: Quality = "best",
        subtitles: Sequence[str | Transcript] | None = None,
```

**with:**

```python
        quality: Quality = "best",
        resolution: int | None = None,
        subtitles: Sequence[str | Transcript] | None = None,
```

**In `src/utmax/client.py`, replace:**

```python
        options = DownloadOptions(
            format=format,
            quality=quality,
            subtitles=subtitles,
            subtitle_mode=subtitle_mode,
            default_subtitle=default_subtitle,
```

**with:**

```python
        options = DownloadOptions(
            format=format,
            quality=quality,
            resolution=resolution,
            subtitles=subtitles,
            subtitle_mode=subtitle_mode,
            default_subtitle=default_subtitle,
```

**In `src/utmax/client.py`, replace:**

```python
        quality: Quality = "best",
        subtitles: Sequence[str] | None = None,
```

**with:**

```python
        quality: Quality = "best",
        resolution: int | None = None,
        subtitles: Sequence[str] | None = None,
```

**In `src/utmax/client.py`, replace:**

```python
            quality=quality,
            subtitles=subtitles,
```

**with:**

```python
            quality=quality,
            resolution=resolution,
            subtitles=subtitles,
```

**In `src/utmax/__init__.py`, replace:**

```python
    Format,
    FormatName,
```

**with:**

```python
    Format,
    FormatList,
    FormatName,
```

**In `src/utmax/__init__.py`, replace:**

```python
    "Format",
    "FormatName",
```

**with:**

```python
    "Format",
    "FormatList",
    "FormatName",
```

**In `src/utmax/__init__.py`, replace:**

```python
    "fetch_many",
    "list_tracks",
```

**with:**

```python
    "fetch_many",
    "list_formats",
    "list_tracks",
```

**In `src/utmax/__init__.py`, replace:**

```python
    return _client().list_tracks(video)
```

**with:**

```python
    return _client().list_tracks(video)


def list_formats(video: str) -> FormatList:
    """The streams of a video that :func:`download` can choose from, in YouTube's order.

    Example::

        formats = utmax.list_formats("dQw4w9WgXcQ")
        sizes = sorted({f.height for f in formats if f.kind == "video"}, reverse=True)
        utmax.download("dQw4w9WgXcQ", "rick.mp4", resolution=sizes[1])

    Raises:
        InvalidVideoId: ``video`` is not a YouTube video URL or ID.
        VideoUnavailable, VideoUnplayable, AgeRestricted, RequestBlocked: YouTube refused.
    """
    return _client().list_formats(video)
```

**In `src/utmax/__init__.py`, replace:**

```python
    quality: Quality = "best",
    subtitles: Sequence[str | Transcript] | None = None,
```

**with:**

```python
    quality: Quality = "best",
    resolution: int | None = None,
    subtitles: Sequence[str | Transcript] | None = None,
```

**In `src/utmax/__init__.py`, replace:**

```python
            ``"compat"`` (H.264 up to 1080p, plays everywhere).
```

**with:**

```python
            ``"compat"`` (H.264 up to 1080p, plays everywhere).
        resolution: the largest picture to take, in lines of its short side (``1080`` means at
            most 1080p); ``None`` takes the largest. :func:`list_formats` shows what exists.
```

**In `src/utmax/__init__.py`, replace:**

```python
        path,
        format=format,
        quality=quality,
        subtitles=subtitles,
        subtitle_mode=subtitle_mode,
        default_subtitle=default_subtitle,
```

**with:**

```python
        path,
        format=format,
        quality=quality,
        resolution=resolution,
        subtitles=subtitles,
        subtitle_mode=subtitle_mode,
        default_subtitle=default_subtitle,
```

**In `src/utmax/__init__.py`, replace:**

```python
    quality: Quality = "best",
    subtitles: Sequence[str] | None = None,
```

**with:**

```python
    quality: Quality = "best",
    resolution: int | None = None,
    subtitles: Sequence[str] | None = None,
```

**In `src/utmax/__init__.py`, replace:**

```python
        format, quality, subtitles, subtitle_mode, ffmpeg: as in :func:`download`, for every
            video; ``subtitles`` takes language codes only.
```

**with:**

```python
        format, quality, resolution, subtitles, subtitle_mode, ffmpeg: as in :func:`download`,
            for every video; ``subtitles`` takes language codes only.
```

**In `src/utmax/__init__.py`, replace:**

```python
        quality=quality,
        subtitles=subtitles,
```

**with:**

```python
        quality=quality,
        resolution=resolution,
        subtitles=subtitles,
```

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: all clean; **1685 passed, 28 deselected** (7 new tests).

- [ ] **Step 6: Commit**

```bash
git add src/utmax/models.py src/utmax/core/streams.py src/utmax/services/download.py src/utmax/services/bulk.py src/utmax/client.py src/utmax/__init__.py tests/unit/test_download_api.py tests/unit/services/test_download_audio.py tests/unit/services/test_bulk_downloads.py tests/unit/core/test_streams.py tests/unit/test_collections_api.py
git commit -m "feat: list a video's formats and cap downloads at a resolution"
```

### Task 4: SRT and WebVTT back into a transcript

**Files:**
- Modify: `src/utmax/core/formats.py`, `src/utmax/models.py`
- Test: `tests/unit/core/test_subtitle_parsing.py` (create)

**Interfaces:**
- Produces: `core.formats.parse_subtitles(text: str) -> tuple[Segment, ...]` (SubRip or WebVTT; raises `InvalidOption` "The text holds no subtitle cue; ..."); `Transcript.from_srt(text, language_code, *, video: VideoInfo, language=None, translated_from=None, translator=None) -> Transcript` (`language` defaults to the English name of the code; a `translator` marks it generated and names subtitle tracks "Turkish (AI: assistant)").
- Consumes: `core.languages.english_name`; the existing writers `to_srt`/`to_vtt` (the tests read their output back).

- [ ] **Step 1: Write the failing tests**

**Create `tests/unit/core/test_subtitle_parsing.py`:**

```python
"""Tests for reading SRT and WebVTT text back into segments (e.g. an assistant's translation)."""

from __future__ import annotations

import pytest

from tests.helpers.builders import VIDEO
from utmax.core.formats import parse_subtitles, to_srt, to_vtt
from utmax.errors import InvalidOption
from utmax.models import Segment, Transcript

SEGMENTS = (
    Segment(1.36, 1.68, "[♪♪♪]"),
    Segment(18.64, 3.24, "♪ We're no strangers to love ♪"),
    Segment(22.64, 4.4, "♪ You know the rules\nand so do I ♪"),
    Segment(3725.5, 2.0, "an hour in"),
)


def test_srt_reads_back_what_utmax_writes() -> None:
    assert parse_subtitles(to_srt(SEGMENTS)) == SEGMENTS


def test_vtt_reads_back_what_utmax_writes_escapes_and_styling_included() -> None:
    styled = (*SEGMENTS, Segment(4000.0, 1.5, "Fish & <i>chips</i> > 3"))
    assert parse_subtitles(to_vtt(styled)) == styled


def test_srt_from_elsewhere_is_read_leniently() -> None:
    text = (
        "\U0000feff1\r\n00:00:01,000 --> 00:00:02,500\r\nMerhaba\r\n\r\n"
        "00:00:03,000 --> 00:00:04,000\r\n  iki satir  \r\nalt satir\r\n"
        "3\r\n00:00:05,000 --> 00:00:06,00\r\nnumarasiz bosluk yok\r\n"
    )
    assert parse_subtitles(text) == (
        Segment(1.0, 1.5, "Merhaba"),
        Segment(3.0, 1.0, "iki satir\nalt satir"),
        Segment(5.0, 1.0, "numarasiz bosluk yok"),
    )


def test_vtt_headers_notes_settings_and_cue_tags_are_skipped() -> None:
    text = (
        "WEBVTT - Turkish\nKind: captions\n\nNOTE written by hand\nover two lines\n\n"
        "STYLE\n::cue { color: lime }\n\n"
        "intro\n00:01.000 --> 00:02.000 align:start position:10%\n"
        "<v Rick>Merhaba <c.yellow>dunya</c><00:00:01.500> &amp; <b>herkes</b>\n"
    )
    assert parse_subtitles(text) == (Segment(1.0, 1.0, "Merhaba dunya & <b>herkes</b>"),)


def test_a_cue_that_ends_before_it_starts_lasts_no_time() -> None:
    (segment,) = parse_subtitles("00:00:05,000 --> 00:00:04,000\nback in time\n")
    assert (segment.start, segment.duration) == (5.0, 0.0)


@pytest.mark.parametrize("text", ["", "WEBVTT\n\n", "just some words\nno times\n"])
def test_text_without_cues_is_refused(text: str) -> None:
    with pytest.raises(InvalidOption, match="no subtitle cue"):
        parse_subtitles(text)


def test_transcript_from_srt_describes_the_translation() -> None:
    turkish = Transcript.from_srt(
        "1\n00:00:01,000 --> 00:00:02,000\nMerhaba\n",
        "tr",
        video=VIDEO,
        translated_from="en",
        translator="assistant",
    )
    assert turkish.segments == (Segment(1.0, 1.0, "Merhaba"),)
    assert (turkish.video, turkish.language_code, turkish.language) == (VIDEO, "tr", "Turkish")
    assert (turkish.translated_from, turkish.translator, turkish.is_generated) == (
        "en",
        "assistant",
        True,
    )
    unknown = Transcript.from_srt("00:00:01,000 --> 00:00:02,000\nx\n", "xx-YY", video=VIDEO)
    assert (unknown.language, unknown.is_generated, unknown.translator) == ("xx-YY", False, None)
    named = Transcript.from_srt(
        "00:00:01,000 --> 00:00:02,000\nx\n", "tr", video=VIDEO, language="Turkce"
    )
    assert named.language == "Turkce"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_subtitle_parsing.py -q`
Expected: a collection error — `ImportError: cannot import name 'parse_subtitles' from 'utmax.core.formats'`.

- [ ] **Step 3: Read SRT and WebVTT**

**In `src/utmax/core/formats.py`, replace:**

```python
"""Render transcripts as SRT, WebVTT, JSON, plain text or timestamped ("pretty") text."""

from __future__ import annotations

```

**with:**

```python
"""Render transcripts as SRT, WebVTT, JSON, plain text or timestamped ("pretty") text, and read
SRT and WebVTT text back into segments."""

from __future__ import annotations

import html
```

**In `src/utmax/core/formats.py`, replace:**

```python
from utmax.errors import UnsupportedFormat
```

**with:**

```python
from utmax.errors import InvalidOption, UnsupportedFormat
```

**In `src/utmax/core/formats.py`, replace:**

```python
    "format_for_path",
    "render",
```

**with:**

```python
    "format_for_path",
    "parse_subtitles",
    "render",
```

**In `src/utmax/core/formats.py`, replace:**

```python
_ALLOWED_VTT_TAG = re.compile(r"&lt;(/?)([biu])&gt;")
```

**with:**

```python
_ALLOWED_VTT_TAG = re.compile(r"&lt;(/?)([biu])&gt;")
_TIMING = re.compile(
    r"\s*(?P<start>(?:\d+:)?\d{1,2}:\d{1,2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>(?:\d+:)?\d{1,2}:\d{1,2}[,.]\d{1,3})"
)
# WebVTT tags other than <b>, <i> and <u>: voices, classes, timestamps.
_OTHER_VTT_TAG = re.compile(r"<(?!/?[biu]>)[^>]*>")
```

**In `src/utmax/core/formats.py`, replace:**

```python

def _cues(segments: Sequence[Segment]) -> list[_Cue]:
```

**with:**

```python

def parse_subtitles(text: str) -> tuple[Segment, ...]:
    """Segments from SubRip (SRT) or WebVTT text, in cue order.

    Cue numbers and identifiers, WebVTT headers, ``NOTE``/``STYLE``/``REGION`` blocks, cue
    settings and WebVTT tags other than ``<b>``, ``<i>`` and ``<u>`` are left out; the lines of
    a cue stay separate lines. Any line endings, a byte-order mark and a missing blank line
    between cues are fine. A cue that ends before it starts lasts no time.

    Raises:
        InvalidOption: the text holds no subtitle cue.
    """
    lines = text.removeprefix("\U0000feff").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    webvtt = lines[0].startswith("WEBVTT")
    segments: list[Segment] = []
    index = 0
    while index < len(lines):
        timing = _TIMING.match(lines[index])
        index += 1
        if timing is None:
            continue
        body: list[str] = []
        while index < len(lines) and lines[index].strip() and not _starts_cue(lines, index):
            body.append(lines[index].strip())
            index += 1
        cue = "\n".join(body)
        if webvtt:
            cue = html.unescape(_OTHER_VTT_TAG.sub("", cue))
        start, end = _milliseconds(timing["start"]), _milliseconds(timing["end"])
        segments.append(Segment(start / 1000, max(0, end - start) / 1000, cue))
    if not segments:
        raise InvalidOption("The text holds no subtitle cue; utmax reads SRT and WebVTT.")
    return tuple(segments)


def _starts_cue(lines: list[str], index: int) -> bool:
    """Whether ``lines[index]`` begins a cue: a timing line, or a number just before one."""
    if _TIMING.match(lines[index]):
        return True
    following = lines[index + 1] if index + 1 < len(lines) else ""
    return lines[index].strip().isdigit() and _TIMING.match(following) is not None


def _milliseconds(stamp: str) -> int:
    """``"01:02:03,450"`` or ``"02:03.45"`` in milliseconds."""
    clock, fraction = re.split(r"[,.]", stamp)
    seconds = 0
    for part in clock.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds * 1000 + int(fraction.ljust(3, "0"))


def _cues(segments: Sequence[Segment]) -> list[_Cue]:
```

- [ ] **Step 4: Build a transcript from such text**

**In `src/utmax/models.py`, replace:**

```python
        return "+" in self.language_code
```

**with:**

```python
        return "+" in self.language_code

    @classmethod
    def from_srt(
        cls,
        text: str,
        language_code: str,
        *,
        video: VideoInfo,
        language: str | None = None,
        translated_from: str | None = None,
        translator: str | None = None,
    ) -> Transcript:
        """A transcript of ``video`` from SRT or WebVTT text, such as a translation made elsewhere.

        ``language`` defaults to the English name of ``language_code``. ``translator`` names
        who or what translated the text (subtitle tracks show it) and marks it as generated.

        Raises:
            InvalidOption: the text holds no subtitle cue.
        """
        from utmax.core.formats import parse_subtitles
        from utmax.core.languages import english_name

        return cls(
            video=video,
            language_code=language_code,
            language=language or english_name(language_code) or language_code,
            is_generated=translator is not None,
            segments=parse_subtitles(text),
            translated_from=translated_from,
            translator=translator,
        )
```

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: all clean; **1694 passed, 28 deselected** (9 new tests).

- [ ] **Step 6: Commit**

```bash
git add src/utmax/core/formats.py src/utmax/models.py tests/unit/core/test_subtitle_parsing.py
git commit -m "feat: read SRT and WebVTT text back into a transcript"
```

### Task 5: The MCP tools of the download conversation

**Files:**
- Modify: `src/utmax/mcp/server.py`
- Test: `tests/mcp/test_flow.py` (create), `tests/mcp/test_server.py`, `tests/mcp/test_stdio.py`, `tests/mcp/conftest.py`

**Interfaces:**
- Produces: tools `list_formats(video) -> FormatsOut` (video, `file_types`, `resolutions` of `ResolutionOut`: `resolution` label such as `"2160p60 HDR"`, `height`, `fps`, `hdr`, `file_types`) and `save_subtitles(video, *, languages=None, source="any", translated_srt=None, translated_language=None, format="srt") -> SavedOut` (path, video_id, title, language_code, language, format, cues); `download(video, *, format, quality="best", resolution=None, subtitles=None, translated_subtitles=None, subtitle_mode="embed", overwrite=False)`, where `translated_subtitles` is a list of `TranslatedSubtitle(language, srt)`; module functions `formats_out(formats)` and `save_subtitle_file(reader, client, directory, video, ...)`; `INSTRUCTIONS` describing the conversation. The tool order is `list_tracks`, `get_transcript`, `list_formats`, `list_videos`, `download`, `save_subtitles`.
- Consumes: Task 3's `Client.list_formats`, `core.streams.file_types`, `DownloadOptions.resolution`; Task 4's `Transcript.from_srt`; `core.filenames.default_filename`.

- [ ] **Step 1: Write the failing tests**

**Create `tests/mcp/test_flow.py`:**

```python
"""The conversation the server is built for: list the formats, download one with the
subtitles the user wants (YouTube's own or the assistant's translation), or save subtitles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
from mcp import Client as MCPClient
from mcp.types import CallToolResult

from tests.helpers.bulk import IDS, TITLES, ManyVideos
from tests.helpers.downloads import FakeYouTube, read_movie
from tests.helpers.youtube import VIDEO_ID
from utmax import Client
from utmax.mcp.config import Config
from utmax.mcp.server import build_server, formats_out
from utmax.models import Format, FormatList, VideoInfo

VIDEO = IDS[0]
NAME = f"{TITLES[VIDEO]} [{VIDEO}]"
RICK = "Rick Astley - Never Gonna Give You Up (Official Video)"
TURKISH = "1\n00:00:01,000 --> 00:00:02,000\nMerhaba\n\n2\n00:00:02,000 --> 00:00:03,500\nDunya\n"


def call(server: Any, name: str, arguments: dict[str, Any]) -> CallToolResult:
    async def main() -> CallToolResult:
        async with MCPClient(server, raise_exceptions=True) as client:
            return await client.call_tool(name, arguments)

    return anyio.run(main)


def output(result: CallToolResult) -> dict[str, Any]:
    assert result.is_error is False, result.content
    assert result.structured_content is not None
    return result.structured_content


def error_text(result: CallToolResult) -> str:
    assert result.is_error is True
    return " ".join(block.text for block in result.content if block.type == "text")


def video(itag: int, codec: str, height: int, *, fps: int = 25, hdr: bool = False) -> Format:
    return Format(
        itag, "video", "mp4", codec, codec, width=height * 16 // 9, height=height, fps=fps, hdr=hdr
    )


def test_list_formats_offers_file_types_and_resolutions() -> None:
    server = build_server(Client(transport=FakeYouTube()), Config())

    result = output(call(server, "list_formats", {"video": f"https://youtu.be/{VIDEO_ID}"}))

    assert result["video"]["title"] == RICK
    assert result["file_types"] == ["mp4", "mov", "m4a", "mp3"]
    assert result["resolutions"] == [
        {
            "resolution": "1080p",
            "height": 1080,
            "fps": 25,
            "hdr": False,
            "file_types": ["mp4", "mov"],
        }
    ]


def test_resolutions_are_grouped_labelled_and_largest_first() -> None:
    info = VideoInfo("abcdefghijk", "Clip", "Channel", "UC", 60.0, False)
    formats = FormatList(
        info,
        (
            video(299, "h264", 1080, fps=60),
            video(701, "av1", 2160, fps=60, hdr=True),
            video(315, "vp9", 2160, fps=60),
            video(399, "av1", 1080, fps=60),
            video(136, "h264", 720, fps=30),
            Format(140, "audio", "mp4", "aac", "mp4a.40.2"),
            Format(251, "audio", "webm", "opus", "opus"),
        ),
    )

    result = formats_out(formats).model_dump()

    assert result["file_types"] == ["mp4", "mov", "m4a", "mp3"]
    assert [(r["resolution"], r["file_types"]) for r in result["resolutions"]] == [
        ("2160p60 HDR", ["mp4"]),
        ("1080p60", ["mp4", "mov"]),
        ("720p", ["mp4", "mov"]),
    ]
    without_aac = formats_out(FormatList(info, (video(399, "av1", 1080), formats[6])))
    assert (without_aac.file_types, without_aac.resolutions) == ([], [])


def test_a_translation_is_embedded_and_shown_by_default(tmp_path: Path) -> None:
    server = build_server(Client(transport=FakeYouTube()), Config(download_dir=tmp_path))

    result = output(
        call(
            server,
            "download",
            {"video": VIDEO_ID, "translated_subtitles": [{"language": "tr", "srt": TURKISH}]},
        )
    )

    assert result["embedded_subtitles"] == ["tr"]
    subtitle = read_movie(Path(result["path"])).tracks[2]
    assert (subtitle.extended_language, subtitle.name, subtitle.flags & 1) == (
        "tr",
        "Turkish (AI: assistant)",
        1,
    )


def test_youtube_tracks_and_a_translation_together(tmp_path: Path) -> None:
    server = build_server(Client(transport=FakeYouTube()), Config(download_dir=tmp_path))

    result = output(
        call(
            server,
            "download",
            {
                "video": VIDEO_ID,
                "subtitles": ["en"],
                "translated_subtitles": [{"language": "tr", "srt": TURKISH}],
            },
        )
    )

    assert result["embedded_subtitles"] == ["en", "tr"]
    tracks = read_movie(Path(result["path"])).tracks[2:]
    assert [(track.extended_language, track.flags & 1) for track in tracks] == [
        ("en", 0),
        ("tr", 1),
    ]


def test_a_translation_that_is_not_subtitles_is_refused_before_any_download(
    tmp_path: Path,
) -> None:
    youtube = FakeYouTube()
    server = build_server(Client(transport=youtube), Config(download_dir=tmp_path))

    result = call(
        server,
        "download",
        {"video": VIDEO_ID, "translated_subtitles": [{"language": "tr", "srt": "Merhaba"}]},
    )

    assert "no subtitle cue" in error_text(result)
    assert youtube.media.requests == []


def test_resolution_reaches_the_download(tmp_path: Path) -> None:
    server = build_server(Client(transport=FakeYouTube()), Config(download_dir=tmp_path))

    smaller = call(server, "download", {"video": VIDEO_ID, "resolution": 720})
    fitting = output(call(server, "download", {"video": VIDEO_ID, "resolution": 1080}))

    assert "up to 720p" in error_text(smaller)
    assert fitting["skipped"] is False


def test_overwrite_downloads_a_file_that_is_already_there(tmp_path: Path) -> None:
    youtube = ManyVideos()
    server = build_server(Client(transport=youtube), Config(download_dir=tmp_path))
    output(call(server, "download", {"video": VIDEO, "format": "m4a"}))
    players = len(youtube.players)

    again = output(call(server, "download", {"video": VIDEO, "format": "m4a", "overwrite": True}))

    assert again["skipped"] is False
    assert again["path"] == str(tmp_path / f"{NAME}.m4a")
    assert len(youtube.players) > players


def test_save_subtitles_writes_youtubes_track(tmp_path: Path) -> None:
    server = build_server(Client(transport=FakeYouTube()), Config(download_dir=tmp_path / "subs"))

    result = output(call(server, "save_subtitles", {"video": VIDEO_ID}))

    path = tmp_path / "subs" / f"{RICK} [{VIDEO_ID}].en.srt"
    assert result == {
        "path": str(path),
        "video_id": VIDEO_ID,
        "title": RICK,
        "language_code": "en",
        "language": "English",
        "format": "srt",
        "cues": 3,
    }
    assert "We're no strangers to love" in path.read_text(encoding="utf-8")


def test_save_subtitles_writes_the_assistants_translation(tmp_path: Path) -> None:
    server = build_server(Client(transport=FakeYouTube()), Config(download_dir=tmp_path))

    result = output(
        call(
            server,
            "save_subtitles",
            {
                "video": VIDEO_ID,
                "translated_srt": TURKISH,
                "translated_language": "tr",
                "format": "vtt",
            },
        )
    )

    path = tmp_path / f"{RICK} [{VIDEO_ID}].tr.vtt"
    assert (result["path"], result["language"], result["cues"]) == (str(path), "Turkish", 2)
    assert path.read_text(encoding="utf-8") == (
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nMerhaba\n\n00:00:02.000 --> 00:00:03.500\nDunya\n"
    )


def test_save_subtitles_needs_the_language_of_a_translation(tmp_path: Path) -> None:
    server = build_server(Client(transport=FakeYouTube()), Config(download_dir=tmp_path))

    result = call(server, "save_subtitles", {"video": VIDEO_ID, "translated_srt": TURKISH})

    assert "translated_language" in error_text(result)
    assert list(tmp_path.iterdir()) == []
```

**In `tests/mcp/conftest.py`, replace:**

```python
    else ["test_download.py", "test_live.py", "test_server.py", "test_stdio.py"]
```

**with:**

```python
    else ["test_download.py", "test_flow.py", "test_live.py", "test_server.py", "test_stdio.py"]
```

**In `tests/mcp/test_server.py`, replace:**

```python
TOOLS = ["list_tracks", "get_transcript", "list_videos", "download"]
```

**with:**

```python
TOOLS = [
    "list_tracks",
    "get_transcript",
    "list_formats",
    "list_videos",
    "download",
    "save_subtitles",
]
```

**In `tests/mcp/test_server.py`, replace:**

```python
def test_the_server_offers_four_tools() -> None:
```

**with:**

```python
def test_the_server_offers_six_tools() -> None:
```

**In `tests/mcp/test_server.py`, replace:**

```python

def test_tool_arguments_are_described_and_bounded() -> None:
```

**with:**

```python

def test_the_assistant_is_told_what_to_ask_before_a_download() -> None:
    instructions = mcp_server.INSTRUCTIONS
    for words in (
        "ask which file type",
        "which resolution",
        "whether to embed subtitles",
        "translated_subtitles",
        "save_subtitles",
        "overwrite=true",
        "already answered",
    ):
        assert words in instructions, words


def test_tool_arguments_are_described_and_bounded() -> None:
```

**In `tests/mcp/test_server.py`, replace:**

```python
    assert list(download) == ["video", "format", "quality", "subtitles", "subtitle_mode"]
    assert download["format"]["enum"] == ["mp4", "mov", "m4a", "mp3"]


def test_only_download_changes_anything() -> None:
```

**with:**

```python
    assert list(download) == [
        "video",
        "format",
        "quality",
        "resolution",
        "subtitles",
        "translated_subtitles",
        "subtitle_mode",
        "overwrite",
    ]
    assert download["format"]["enum"] == ["mp4", "mov", "m4a", "mp3"]
    assert download["quality"]["enum"] == ["best", "compat"]
    assert download["quality"]["default"] == "best"
    assert download["resolution"]["anyOf"] == [{"type": "integer", "minimum": 1}, {"type": "null"}]
    save = offered["save_subtitles"].input_schema
    assert save["required"] == ["video"]
    assert list(save["properties"]) == [
        "video",
        "languages",
        "source",
        "translated_srt",
        "translated_language",
        "format",
    ]
    assert save["properties"]["format"]["enum"] == ["srt", "vtt"]


def test_only_download_and_save_subtitles_change_anything() -> None:
```

**In `tests/mcp/test_server.py`, replace:**

```python
        "list_videos": True,
        "download": False,
```

**with:**

```python
        "list_formats": True,
        "list_videos": True,
        "download": False,
        "save_subtitles": False,
```

**In `tests/mcp/test_stdio.py`, replace:**

```python
    assert names == ["list_tracks", "get_transcript", "list_videos", "download"]
```

**with:**

```python
    assert names == [
        "list_tracks",
        "get_transcript",
        "list_formats",
        "list_videos",
        "download",
        "save_subtitles",
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/mcp -q`
Expected: a collection error — `ImportError: cannot import name 'formats_out' from 'utmax.mcp.server'`.

- [ ] **Step 3: The new tools, arguments and instructions**

**In `src/utmax/mcp/server.py`, replace:**

```python
"""The utmax MCP server: YouTube transcripts, playlists and downloads as tools.
```

**with:**

```python
"""The utmax MCP server: YouTube transcripts, playlists, formats, downloads and subtitle files
as tools.
```

**In `src/utmax/mcp/server.py`, replace:**

```python
from utmax.core.ids import parse_video_id
from utmax.errors import UTMaxError
```

**with:**

```python
from utmax.core.filenames import default_filename
from utmax.core.ids import parse_video_id
from utmax.core.streams import file_types
from utmax.errors import InvalidOption, UTMaxError
```

**In `src/utmax/mcp/server.py`, replace:**

```python
    Container,
    FormatName,
```

**with:**

```python
    Container,
    FormatList,
    FormatName,
```

**In `src/utmax/mcp/server.py`, replace:**

```python
    "TrackOut",
    "TracksOut",
    "TranscriptOut",
```

**with:**

```python
    "FormatsOut",
    "ResolutionOut",
    "SavedOut",
    "TrackOut",
    "TracksOut",
    "TranscriptOut",
    "TranslatedSubtitle",
```

**In `src/utmax/mcp/server.py`, replace:**

```python
    "download_file",
    "run",
]
```

**with:**

```python
    "download_file",
    "formats_out",
    "run",
    "save_subtitle_file",
]
```

**In `src/utmax/mcp/server.py`, replace:**

```python
    "videos of a playlist or channel, and download a video or its audio into the server's "
    "download folder. Read long transcripts in parts with max_chars and next_offset. To "
    "translate a transcript, get it as srt or vtt and translate its text lines yourself, keeping "
    "the timing lines as they are."
```

**with:**

```python
    "videos of a playlist or channel, list the formats a video can be downloaded in, download a "
    "video or its audio, and save subtitles as files in the server's download folder. Read long "
    "transcripts in parts with max_chars and next_offset. To translate a transcript, get it as "
    "srt or vtt and translate its text lines yourself, keeping the timing lines as they are. "
    "When the user asks to download a video, call list_formats, then ask which file type they "
    "want, which resolution (among those list_formats gives for that file type), and whether "
    "to embed subtitles: in the original language (list_tracks), translated into a language "
    "they name (translate them yourself and pass them as translated_subtitles), or none; skip "
    "the questions the user already answered, then call download. When the user only wants "
    "subtitles, call save_subtitles; to save a translation, pass your translated text as "
    "translated_srt. A download that finds its file already there returns skipped=true; call "
    "it again with overwrite=true when the user wants another resolution or other subtitles."
```

**In `src/utmax/mcp/server.py`, replace:**

```python
    Field(description="embed: inside the video; sidecar: .srt files next to it; both: the two."),
]


```

**with:**

```python
    Field(description="embed: inside the video; sidecar: .srt files next to it; both: the two."),
]
ResolutionArg = Annotated[
    int | None,
    Field(
        ge=1,
        description=(
            "The largest picture to take, as lines of its short side (1080 means at most "
            "1080p); null: the largest. list_formats shows what the video has."
        ),
    ),
]


class TranslatedSubtitle(BaseModel):
    language: str = Field(description='The language code of the translation, such as "tr".')
    srt: str = Field(description="The translated subtitles as SRT (or WebVTT) text.")


TranslatedArg = Annotated[
    list[TranslatedSubtitle] | None,
    Field(
        description=(
            "Subtitles you translated, to add like subtitles; the first one is shown by default. "
            "Without subtitles, only these are added."
        )
    ),
]
OverwriteArg = Annotated[
    bool,
    Field(description="Download again a file that is already in the download folder."),
]
TranslatedSrtArg = Annotated[
    str | None,
    Field(description="Subtitles you translated, as SRT (or WebVTT) text, to save instead."),
]
TranslatedLanguageArg = Annotated[
    str | None,
    Field(description='The language code of translated_srt, such as "tr".'),
]
SubtitleFileArg = Annotated[
    Literal["srt", "vtt"],
    Field(description="srt: SubRip, for most players; vtt: WebVTT, for browsers."),
]


```

**In `src/utmax/mcp/server.py`, replace:**

```python

class DownloadOut(BaseModel):
```

**with:**

```python

class ResolutionOut(BaseModel):
    resolution: str = Field(description='As YouTube labels it, such as "2160p60 HDR" or "1080p".')
    height: int = Field(description="Lines of the short side; download takes it as resolution.")
    fps: int | None
    hdr: bool
    file_types: list[Container] = Field(description="The video file types with this picture.")


class FormatsOut(BaseModel):
    video: VideoOut
    file_types: list[Container] = Field(description="Every file type the video can become.")
    resolutions: list[ResolutionOut] = Field(description="Pictures of video files, largest first.")


class SavedOut(BaseModel):
    path: str
    video_id: str
    title: str
    language_code: str
    language: str
    format: Literal["srt", "vtt"]
    cues: int = Field(description="How many subtitle cues the file holds.")


class DownloadOut(BaseModel):
```

**In `src/utmax/mcp/server.py`, replace:**

```python
    """The MCP server with utmax's four tools, using ``client`` (by default one built from
```

**with:**

```python
    """The MCP server with utmax's six tools, using ``client`` (by default one built from
```

**In `src/utmax/mcp/server.py`, replace:**

```python
    @tool(reads)
    def list_videos(source: CollectionArg, kind: KindArg = None, limit: LimitArg = 50) -> VideosOut:
```

**with:**

```python
    @tool(reads)
    def list_formats(video: VideoArg) -> FormatsOut:
        """List what a YouTube video can be downloaded as: the file types, and the resolutions
        each video file type offers, largest first."""
        with tool_errors():
            formats = youtube.list_formats(video)
        return formats_out(formats)

    @tool(reads)
    def list_videos(source: CollectionArg, kind: KindArg = None, limit: LimitArg = 50) -> VideosOut:
```

**In `src/utmax/mcp/server.py`, replace:**

```python
        format: ContainerArg = "mp4",
        quality: QualityArg = "best",
        subtitles: SubtitlesArg = None,
        subtitle_mode: SubtitleModeArg = "embed",
        *,
        ctx: Context[Any, Any],
    ) -> DownloadOut:
        """Download a YouTube video (mp4, mov) or its audio (m4a, mp3) into the server's
        download folder, named after its title. A file that is already there is not
        downloaded again."""
```

**with:**

```python
        *,
        format: ContainerArg = "mp4",
        quality: QualityArg = "best",
        resolution: ResolutionArg = None,
        subtitles: SubtitlesArg = None,
        translated_subtitles: TranslatedArg = None,
        subtitle_mode: SubtitleModeArg = "embed",
        overwrite: OverwriteArg = False,
        ctx: Context[Any, Any],
    ) -> DownloadOut:
        """Download a YouTube video (mp4, mov) or its audio (m4a, mp3) into the server's
        download folder, named after its title, with YouTube's subtitles and/or ones you
        translated. A file that is already there is not downloaded again unless overwrite."""
```

**In `src/utmax/mcp/server.py`, replace:**

```python
            subtitles=subtitles,
            subtitle_mode=subtitle_mode,
            report=ctx.report_progress,
        )
```

**with:**

```python
            resolution=resolution,
            subtitles=subtitles,
            translated_subtitles=translated_subtitles,
            subtitle_mode=subtitle_mode,
            overwrite=overwrite,
            report=ctx.report_progress,
        )

    @tool(writes)
    def save_subtitles(
        video: VideoArg,
        *,
        languages: LanguagesArg = None,
        source: TrackSourceArg = "any",
        translated_srt: TranslatedSrtArg = None,
        translated_language: TranslatedLanguageArg = None,
        format: SubtitleFileArg = "srt",
    ) -> SavedOut:
        """Save a YouTube video's subtitles as a file in the server's download folder: one of
        its tracks, or a translation you made (translated_srt and translated_language)."""
        with tool_errors():
            return save_subtitle_file(
                reader,
                youtube,
                settings.download_dir,
                video,
                languages=languages,
                source=source,
                translated_srt=translated_srt,
                translated_language=translated_language,
                format=format,
            )
```

**In `src/utmax/mcp/server.py`, replace:**

```python
    subtitles: list[str] | None = None,
    subtitle_mode: SubtitleMode = "embed",
    report: Callable[[float, float | None, str | None], Coroutine[Any, Any, None]] | None = None,
) -> DownloadOut:
    """Download ``video`` into ``directory`` on a worker thread, unless it is already there.
```

**with:**

```python
    resolution: int | None = None,
    subtitles: list[str] | None = None,
    translated_subtitles: list[TranslatedSubtitle] | None = None,
    subtitle_mode: SubtitleMode = "embed",
    overwrite: bool = False,
    report: Callable[[float, float | None, str | None], Coroutine[Any, Any, None]] | None = None,
) -> DownloadOut:
    """Download ``video`` into ``directory`` on a worker thread, unless it is already there
    (``overwrite`` downloads it again).

    ``translated_subtitles`` join ``subtitles`` (or replace the spoken-language default when
    ``subtitles`` is ``None``), and the first translation is the track shown by default.
```

**In `src/utmax/mcp/server.py`, replace:**

```python
        video_id = parse_video_id(video)
    token = anyio.lowlevel.current_token()
```

**with:**

```python
        video_id = parse_video_id(video)
        translations = [
            Transcript.from_srt(
                item.srt, item.language, video=_bare_video(video_id), translator="assistant"
            )
            for item in translated_subtitles or ()
        ]
    chosen: list[str | Transcript] | None = None if subtitles is None else list(subtitles)
    if translations:
        chosen = [*(chosen or ()), *translations]
    shown = translations[0].language_code if translations else None
    token = anyio.lowlevel.current_token()
```

**In `src/utmax/mcp/server.py`, replace:**

```python
        existing = _existing_download(directory, video_id, format)
```

**with:**

```python
        existing = None if overwrite else _existing_download(directory, video_id, format)
```

**In `src/utmax/mcp/server.py`, replace:**

```python
            subtitles=subtitles,
            subtitle_mode=subtitle_mode,
```

**with:**

```python
            resolution=resolution,
            subtitles=chosen,
            subtitle_mode=subtitle_mode,
            default_subtitle=shown,
```

**In `src/utmax/mcp/server.py`, replace:**

```python


def run() -> None:
    """Serve the tools over stdio (the ``utmax-mcp`` command); logs go to stderr."""
```

**with:**

```python


def formats_out(formats: FormatList) -> FormatsOut:
    """The ``list_formats`` output: the file types and resolutions ``formats`` allow.

    Video file types need AAC audio too, so a video without it offers none.
    """
    order: tuple[Container, ...] = ("mp4", "mov", "m4a", "mp3")
    has_audio = any(fmt.kind == "audio" and file_types(fmt) for fmt in formats)
    pictures: dict[tuple[int, int | None, bool], set[Container]] = {}
    for fmt in formats:
        side = min((n for n in (fmt.width, fmt.height) if n), default=0)
        if has_audio and fmt.kind == "video" and side and file_types(fmt):
            pictures.setdefault((side, fmt.fps, fmt.hdr), set()).update(file_types(fmt))
    resolutions = [
        ResolutionOut(
            resolution=_resolution_label(side, fps, hdr),
            height=side,
            fps=fps,
            hdr=hdr,
            file_types=[kind for kind in order if kind in kinds],
        )
        for (side, fps, hdr), kinds in sorted(
            pictures.items(), key=lambda item: (item[0][0], item[0][1] or 0, not item[0][2])
        )[::-1]
    ]
    held = {kind for resolution in resolutions for kind in resolution.file_types}
    if has_audio:
        held |= {"m4a", "mp3"}
    return FormatsOut(
        video=_video(formats.video),
        file_types=[kind for kind in order if kind in held],
        resolutions=resolutions,
    )


def save_subtitle_file(
    reader: _Reader,
    client: Client,
    directory: Path,
    video: str,
    *,
    languages: list[str] | None = None,
    source: Literal["any", "manual", "generated"] = "any",
    translated_srt: str | None = None,
    translated_language: str | None = None,
    format: Literal["srt", "vtt"] = "srt",
) -> SavedOut:
    """Write a track of ``video``, or ``translated_srt``, to ``directory`` as
    ``"{title} [{video_id}].{language}.{format}"``."""
    if translated_srt is not None:
        if not translated_language:
            raise InvalidOption(
                "A translation needs its language code.",
                suggestion='Pass translated_language, such as "tr", with translated_srt.',
            )
        transcript = Transcript.from_srt(
            translated_srt,
            translated_language,
            video=client.video_info(video),
            translator="assistant",
        )
    else:
        transcript = reader.transcript(
            video,
            languages,
            include_manual=source != "generated",
            include_generated=source != "manual",
        )
    directory.mkdir(parents=True, exist_ok=True)
    name = default_filename(transcript.video, f"{transcript.language_code}.{format}")
    path = transcript.save(directory / name, format=format)
    return SavedOut(
        path=str(path),
        video_id=transcript.video.video_id,
        title=transcript.video.title,
        language_code=transcript.language_code,
        language=transcript.language,
        format=format,
        cues=len(transcript),
    )


def run() -> None:
    """Serve the tools over stdio (the ``utmax-mcp`` command); logs go to stderr."""
```

**In `src/utmax/mcp/server.py`, replace:**

```python
    return min([*named, *([plain] if plain.is_file() else [])], default=None)
```

**with:**

```python
    return min([*named, *([plain] if plain.is_file() else [])], default=None)


def _bare_video(video_id: str) -> VideoInfo:
    """A video known only by its ID: enough for subtitles the download attaches to it."""
    return VideoInfo(video_id, "", "", "", 0.0, False)


def _resolution_label(side: int, fps: int | None, hdr: bool) -> str:
    """``"2160p60 HDR"``, ``"1080p"``: YouTube names the frame rate only above 30."""
    rate = f"{fps}" if fps and fps > 30 else ""
    return f"{side}p{rate}{' HDR' if hdr else ''}"
```

- [ ] **Step 4: Run the gates**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: all clean; **1705 passed, 28 deselected** (11 new tests).

- [ ] **Step 5: Commit**

```bash
git add src/utmax/mcp/server.py tests/mcp/test_flow.py tests/mcp/test_server.py tests/mcp/test_stdio.py tests/mcp/conftest.py
git commit -m "feat: MCP tools for the download conversation: list_formats, translated subtitles, save_subtitles"
```

### Task 6: Live checks, README and the spec

**Files:**
- Modify: `tests/live/test_download_live.py`, `README.md`, `docs/design/2026-09-27-u-transcript-max-design.md`, `docs/design/2026-10-09-high-quality-downloads-design.md`

**Interfaces:**
- Consumes: everything above, through the public API (`utmax.list_formats`, `utmax.download(..., resolution=...)`, `utmax.fetch`).

- [ ] **Step 1: Live checks for VISIONOS, the resolution cap and a dubbed video**

**In `tests/live/test_download_live.py`, replace:**

```python
They use "Me at the zoo" (jNQXAC9IVRw): 19 seconds, 240p H.264, manual English subtitles, and
ANDROID_VR asks for a bot check on it, so the stream-client fallback is exercised too.
```

**with:**

```python
Most use "Me at the zoo" (jNQXAC9IVRw): 19 seconds, 240p, manual English subtitles. Without a
visitorData, VISIONOS and ANDROID_VR asked for a bot check on it (2026-10-09). The dubbed-audio
checks use ZcDFZzsp3_Y, an English video with about twenty automatically dubbed audio tracks.
```

**In `tests/live/test_download_live.py`, replace:**

```python
pytestmark = pytest.mark.live

ZOO = "jNQXAC9IVRw"


def handlers(path: Path) -> list[str]:
```

**with:**

```python
pytestmark = pytest.mark.live

ZOO = "jNQXAC9IVRw"
DUBBED = "ZcDFZzsp3_Y"


def handlers(path: Path) -> list[str]:
```

**In `tests/live/test_download_live.py`, replace:**

```python
    assert result.video_format.codec == "h264"
```

**with:**

```python
    assert result.video_format.codec in ("h264", "av1")
```

**In `tests/live/test_download_live.py`, replace:**

```python
        assert codecs == ["h264", "aac", "mov_text"]
```

**with:**

```python
        assert codecs == [result.video_format.codec, "aac", "mov_text"]


@pytest.mark.parametrize("video", [ZOO, "9bZkp7q19f0", DUBBED])
def test_videos_play_through_visionos(video: str) -> None:
    formats = utmax.list_formats(video)
    assert {fmt.kind for fmt in formats} == {"video", "audio"}


def test_resolution_caps_a_download_and_dubbed_videos_keep_their_original_audio(
    tmp_path: Path,
) -> None:
    result = utmax.download(DUBBED, tmp_path / "small.mp4", resolution=144, subtitles=[])
    assert result.video_format is not None
    assert min(n for n in (result.video_format.width, result.video_format.height) if n) <= 144
    assert (result.audio_format.language, result.audio_format.is_original) == ("en-US", True)
    assert utmax.fetch(DUBBED).language_code == "en"
```

- [ ] **Step 2: README and the main spec**

**In `README.md`, replace:**

```markdown
utmax.download("dQw4w9WgXcQ", "rick.mp4")  # H.264 up to 1080p with English subtitles
```

**with:**

```markdown
utmax.download("dQw4w9WgXcQ", "rick.mp4")  # the best MP4 (AV1 or H.264) with English subtitles
```

**In `README.md`, replace:**

```markdown
`utmax-mcp` gives an AI assistant four tools: `list_tracks`, `get_transcript`, `list_videos`
and `download`. It needs no API key: ask for a translation and the assistant translates the
transcript itself. The commands below start it with `uvx` from
```

**with:**

```markdown
`utmax-mcp` gives an AI assistant six tools: `list_tracks`, `get_transcript`, `list_formats`,
`list_videos`, `download` and `save_subtitles`. It needs no API key. Ask it to download a video
and the assistant asks which file type, which of the video's resolutions and which subtitles
(original or translated) you want; ask for a translation and it translates the subtitles
itself. The commands below start it with `uvx` from
```

**In `docs/design/2026-09-27-u-transcript-max-design.md`, replace:**

```markdown
| Video | `.mp4` / `.mov` with audio + subtitles; default best **H.264 ≤ 1080p**; `quality="max"` → **AV1 ≤ 2160p** (`.mp4` only) |
```

**with:**

```markdown
| Video | `.mp4` / `.mov` with audio + subtitles; `quality="best"` (default since M8) takes the largest picture the file type holds (`.mp4`: AV1 or H.264, up to 8K, HDR AV1 included), `resolution` caps it; `"compat"` → **H.264 ≤ 1080p** |
```

**In `docs/design/2026-09-27-u-transcript-max-design.md`, replace:**

```markdown
| Small calls (mine) | `quality="max"` + `.mov` → `InvalidOption` · MCP download dir default `~/Downloads/utmax` · OpenRouter via openai SDK (official SDK pins `pydantic<2.13`) |
```

**with:**

```markdown
| Small calls (mine) | `.mov` holds H.264 only · MCP download dir default `~/Downloads/utmax` · OpenRouter via openai SDK (official SDK pins `pydantic<2.13`) |
```

**In `docs/design/2026-09-27-u-transcript-max-design.md`, replace:**

```markdown
download(video, path, *, format: Container | None = None, quality: Literal["compat", "max"] = "compat",
         subtitles: Sequence[str | Transcript] | None = None,          # None = spoken-language track; [] = none
         subtitle_mode: Literal["embed", "sidecar", "both"] = "embed", default_subtitle=None,
         connections=4, chunk_size=8 * 2**20, resume=True, overwrite=False, ffmpeg=None,
```

**with:**

```markdown
list_formats(video) -> FormatList                                   # the streams a download can choose from
download(video, path, *, format: Container | None = None, quality: Literal["best", "compat"] = "best",
         resolution: int | None = None,                                 # at most this many lines (short side)
         subtitles: Sequence[str | Transcript] | None = None,          # None = spoken-language track; [] = none
         subtitle_mode: Literal["embed", "sidecar", "both"] = "embed", default_subtitle=None,
         connections=4, chunk_size=2 * 2**20, resume=True, overwrite=False, ffmpeg=None,
```

**In `docs/design/2026-09-27-u-transcript-max-design.md`, replace:**

```markdown
download_many(videos, out_dir, *, format: Container = "mp4", quality="compat", subtitles: Sequence[str] | None = None,
```

**with:**

```markdown
download_many(videos, out_dir, *, format: Container = "mp4", quality="best", resolution=None,
              subtitles: Sequence[str] | None = None,
```

**In `docs/design/2026-09-27-u-transcript-max-design.md`, replace:**

```markdown
utmax.download("dQw4w9WgXcQ", "rick.mp4")                # H.264 ≤1080p + AAC + embedded English track
```

**with:**

```markdown
utmax.download("dQw4w9WgXcQ", "rick.mp4")                # best MP4 (AV1 4K) + AAC + embedded English track
```

**In `docs/design/2026-09-27-u-transcript-max-design.md`, replace:**

```markdown
  height, fps, bitrate, content_length, audio_sample_rate, audio_channels, is_default_audio, is_drc)` ·
```

**with:**

```markdown
  height, fps, bitrate, content_length, audio_sample_rate, audio_channels, is_default_audio, is_drc, last_modified,
  hdr, bit_depth, language, is_original)` (`language`/`is_original`: audio tracks of dubbed videos) ·
  `FormatList(Sequence[Format])`: `video, formats` ·
```

**In `docs/design/2026-09-27-u-transcript-max-design.md`, replace:**

```markdown
| `.mp4` | best H.264 ≤1080p (`max`: AV1/H.264 ≤2160p, 8-bit) + AAC; tx3g tracks when mode includes embed |
| `.mov` | same H.264 + AAC, QuickTime flavor; `quality="max"` → `InvalidOption` |
```

**with:**

```markdown
| `.mp4` | `best`: the largest AV1 or H.264 picture (HDR where it is the only way to a larger one) + AAC; `compat`: H.264 ≤1080p; tx3g tracks when mode includes embed |
| `.mov` | H.264 + AAC, QuickTime flavor |
```

**In `docs/design/2026-09-27-u-transcript-max-design.md`, replace:**

```markdown
| `list_videos` | `source, kind=None (the link's tab, else all), limit=50 (1..5000)` | title, source_id, kind, count, videos[] |
| `download` | `video, format="mp4", quality="compat", subtitles=None, subtitle_mode="embed"` | path, size_bytes, video_id, title, container, embedded_subtitles, sidecars, skipped |
```

**with:**

```markdown
| `list_formats` | `video` | video + file_types + resolutions[] (resolution label, height, fps, hdr, file_types), largest first |
| `list_videos` | `source, kind=None (the link's tab, else all), limit=50 (1..5000)` | title, source_id, kind, count, videos[] |
| `download` | `video, format="mp4", quality="best", resolution=None, subtitles=None, translated_subtitles=None ([{language, srt}]), subtitle_mode="embed", overwrite=False` | path, size_bytes, video_id, title, container, embedded_subtitles, sidecars, skipped |
| `save_subtitles` | `video, languages=None, source="any", translated_srt=None, translated_language=None, format="srt"` | path, video_id, title, language_code, language, format, cues |

Since M8 the instructions describe the conversation: on "download this" the assistant calls `list_formats`, asks
for the file type, a resolution the video has and the subtitles (original, translated by itself, or none) unless
the user already said, then calls `download`; `save_subtitles` saves subtitles alone (see
`2026-10-09-high-quality-downloads-design.md`).
```

**In `docs/design/2026-09-27-u-transcript-max-design.md`, replace:**

```markdown
`captions: ANDROID→IOS→ANDROID_VR`, `streams: ANDROID_VR→ANDROID→IOS`, `browse/resolve: ANDROID_VR→WEB`. Next
```

**with:**

```markdown
`captions: ANDROID→IOS→ANDROID_VR`, `streams: VISIONOS→ANDROID_VR` (since M8; VISIONOS `1.02` sends a
`visitorData` from `visitor_id`, renewed after a bot check or a 403 refresh), `browse/resolve: ANDROID_VR→WEB`. Next
```

**In `docs/design/2026-09-27-u-transcript-max-design.md`, replace:**

```markdown
**Stream selection**: exclude ciphered, DRM, WebM/VP9/Opus, HDR/10-bit, itag 18. `compat`: MP4 `avc1` ≤1080p by
(height, fps, bitrate). `max`: MP4 `avc1` or 8-bit `av01` ≤2160p, AV1 preferred at equal height. Audio: MP4 AAC,
default track, non-DRC, highest bitrate (140 > 139). None eligible → `FormatNotAvailable(reason, available)`.

**Downloader**: size from `content_length` or first 206 `Content-Range`; 8 MiB chunks in an ascending FIFO shared by
```

**with:**

```markdown
**Stream selection** (since M8): exclude ciphered, DRM, live, progressive and unknown codecs; the file type decides
the rest. `best`: the largest short side ≤ `resolution` among the codecs the file holds (`.mp4` AV1/H.264, `.mov`
H.264), then fps, SDR over HDR, AV1 over H.264, bitrate. `compat`: SDR `avc1` ≤1080p. Audio: AAC, the original
track of a dubbed video, then the default track, non-DRC, highest bitrate (140 > 139). None eligible →
`FormatNotAvailable(reason, available)`.

**Downloader**: size from `content_length` or first 206 `Content-Range`; 2 MiB chunks (YouTube slows 8 MiB ranges of
VISIONOS down to ~150 KB/s) in an ascending FIFO shared by
```

**In `docs/design/2026-10-09-high-quality-downloads-design.md`, replace:**

```markdown
  retries. The PO-token probe of the downloader stays as a safety net.
```

**with:**

```markdown
  retries, and a download that refreshes its URLs after a 403 asks as a new visitor (YouTube
  restricted the streams of about one fresh visitor in six). The PO-token probe of the
  downloader stays as a safety net.
- Downloads use 2 MiB ranges: YouTube slowed 8 MiB ranges of VISIONOS to about 150 KB/s after a
  burst, while 4 MiB and smaller ones kept full speed.
```

**In `docs/design/2026-10-09-high-quality-downloads-design.md`, replace:**

```markdown
  bot check), the VISIONOS profile and the stream order; a recorded, redacted VISIONOS player
  response of a dubbed HDR video; selection tables for every target, quality and resolution;
  SRT/VTT parsing; MCP tools in memory (flow, errors, paths inside the download folder).
- Live: the ten-video reach test; a 4K `.mp4` and a `resolution=720` download with ffprobe.
```

**with:**

```markdown
  bot check or a download's 403 refresh, threads sharing one value), the VISIONOS profile and
  the stream order; selection tables for every target, quality and resolution on payloads
  shaped like the 2026-10-09 VISIONOS answers (dubbed audio tracks, HDR AV1); SRT/VTT parsing;
  MCP tools in memory (flow, errors, paths inside the download folder).
- Live: three videos (two met the bot check without a visitorData) list their formats; a
  `resolution=144` download of a dubbed video keeps its original audio; a 4K HDR `.mp4` is
  checked by hand with ffprobe.
```

- [ ] **Step 3: Run the gates and the live checks**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: all clean; **1705 passed, 32 deselected** (four more live tests).

Run (network): `uv run pytest -m live`
Expected on 2026-10-09: 27 passed, 5 skipped (the AI translation checks without API keys). A run from a cloud IP may report YouTube's blocks as skips.

- [ ] **Step 4: Check a 4K HDR download by hand**

Run: `uv run python -c "import utmax; print(utmax.download('LXb3EKWsInQ', 'costa.mp4', subtitles=[]).video_format.label)"` (about 1 GB), then `ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,pix_fmt,color_transfer -of compact costa.mp4`.
Expected: `701 mp4 av1 2160p60 hdr`; ffprobe shows `av1`, 3840x2160, a 10-bit pixel format and `color_transfer=smpte2084`.

- [ ] **Step 5: Commit**

```bash
git add tests/live/test_download_live.py README.md docs/design/2026-09-27-u-transcript-max-design.md docs/design/2026-10-09-high-quality-downloads-design.md
git commit -m "docs: describe M8's access, quality and MCP flow; live checks for VISIONOS, resolution and dubbed audio"
```
