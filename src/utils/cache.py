from __future__ import annotations

import json
import hashlib
import time
from pathlib import Path


class TranscriptCache:
    """Disk-based cache for transcript data with TTL expiration."""

    def __init__(self, cache_dir: str | None = None, ttl: int = 86400) -> None:
        self.cache_dir = Path(cache_dir or Path.home() / ".cache" / "u-transkript")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl  # Time to live in seconds (default 24h)

    def _cache_key(self, video_id: str, language: str = "default") -> str:
        key = f"{video_id}_{language}"
        return hashlib.md5(key.encode()).hexdigest()

    def get(self, video_id: str, language: str = "default") -> list | None:
        """Retrieve a cached transcript, or None if missing/expired."""
        cache_file = self.cache_dir / f"{self._cache_key(video_id, language)}.json"
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if time.time() - data["timestamp"] > self.ttl:
                cache_file.unlink()
                return None
            return data["transcript"]
        except (json.JSONDecodeError, KeyError):
            cache_file.unlink(missing_ok=True)
            return None

    def set(self, video_id: str, transcript: list, language: str = "default") -> None:
        """Store a transcript in the cache."""
        cache_file = self.cache_dir / f"{self._cache_key(video_id, language)}.json"
        data = {
            "timestamp": time.time(),
            "video_id": video_id,
            "language": language,
            "transcript": transcript,
        }
        cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def clear(self) -> None:
        """Remove all cached transcripts."""
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
