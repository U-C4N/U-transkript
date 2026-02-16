from __future__ import annotations

import os
from pathlib import Path

# Default config file locations (checked in order)
_CONFIG_PATHS = [
    Path.home() / ".u-transkriptrc",
    Path.home() / ".config" / "u-transkript" / "config.toml",
]


def _parse_simple_config(text: str) -> dict[str, str]:
    """Parse a simple key=value config file (one per line, # comments)."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def load_config() -> dict[str, str]:
    """Load configuration from the first config file found.

    Supported keys: language, format, model, api_key, proxy, cache_ttl.
    Returns an empty dict if no config file exists.
    """
    for config_path in _CONFIG_PATHS:
        if config_path.exists():
            try:
                text = config_path.read_text(encoding="utf-8")
                # Try TOML first if available
                if config_path.suffix == ".toml":
                    try:
                        import tomllib  # Python 3.11+
                    except ImportError:
                        try:
                            import tomli as tomllib  # type: ignore[no-redef]
                        except ImportError:
                            tomllib = None  # type: ignore[assignment]
                    if tomllib is not None:
                        data = tomllib.loads(text)
                        # Flatten one level: [defaults] section
                        flat: dict[str, str] = {}
                        for k, v in data.items():
                            if isinstance(v, dict):
                                for k2, v2 in v.items():
                                    flat[k2] = str(v2)
                            else:
                                flat[k] = str(v)
                        return flat
                # Fallback: simple key=value
                return _parse_simple_config(text)
            except Exception:
                continue
    return {}


def apply_config_defaults(args: object, config: dict[str, str]) -> None:
    """Apply config file defaults to argparse args (only where args are unset)."""
    if not config:
        return

    # language -> languages (if not set via CLI)
    if getattr(args, "languages", None) is None and "language" in config:
        args.languages = [config["language"]]  # type: ignore[attr-defined]

    # format (if still default 'pretty')
    if getattr(args, "format", "pretty") == "pretty" and "format" in config:
        fmt = config["format"]
        if fmt in ("pretty", "json", "text", "srt", "vtt"):
            args.format = fmt  # type: ignore[attr-defined]

    # proxy
    if getattr(args, "proxy", None) is None and "proxy" in config:
        args.proxy = config["proxy"]  # type: ignore[attr-defined]
