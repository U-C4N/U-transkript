# YouTube fixtures

Recorded 2026-09-28 from video `dQw4w9WgXcQ` with
`uv run python scripts/record_fixtures.py`. URL parameters ei, expire, ip, key, lsig, sig, signature are replaced with `REDACTED`.
`streams_android_vr.json` keeps only the stream fields utmax reads; its URLs are
placeholders that keep the itag and the client name.
`browse_*.json` hold the first videos of Rick Astley's long-form uploads
(`UULFuAXFkgsw1L7xaCfnd5JJOw`: ANDROID_VR pages 1 and 2, the WEB first and last pages) and
of his Shorts (`UUSHuAXFkgsw1L7xaCfnd5JJOw`, WEB), trimmed to the fields utmax reads;
`resolve_*.json` hold the ANDROID_VR `navigation/resolve_url` answers for
`@RickAstleyYT` and for a handle that does not exist.
