# Hollow media fixtures

Recorded 2026-09-27 from video `dQw4w9WgXcQ` (itags 137, 140, 399, first 2 fragments) with
`uv run python scripts/make_media_fixtures.py`. Each `.hollow.bin` file holds the real
`ftyp`, `moov`, `sidx` and `moof` boxes and every `mdat` header, without payloads;
`tests/helpers/hollow_source.py` replays them with zero-filled payloads. No stream URL
or URL parameter is stored. `manifest.json` lists facts read independently of utmax.
