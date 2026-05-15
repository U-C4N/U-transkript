from __future__ import annotations

from pathlib import Path

_CONFIG_PATHS = [
    Path.home() / ".u-transkriptrc",
    Path.home() / ".config" / "u-transkript" / "config.toml",
]

_SUPPORTED_FORMATS = ("pretty", "json", "text", "srt", "vtt")


def _parse_simple_config(text: str) -> dict[str, str]:
    """Parse `key=value` lines (one per line, `#` introduces a comment)."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _parse_toml(text: str) -> dict[str, str] | None:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return None

    data = tomllib.loads(text)
    flat: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            for k2, v2 in value.items():
                flat[k2] = str(v2)
        else:
            flat[key] = str(value)
    return flat


def load_config() -> dict[str, str]:
    """Load the first config file we can find.

    Supported keys: `language`, `format`. Returns an empty dict if nothing exists.
    """
    for config_path in _CONFIG_PATHS:
        if not config_path.exists():
            continue
        try:
            text = config_path.read_text(encoding="utf-8")
            if config_path.suffix == ".toml":
                parsed = _parse_toml(text)
                if parsed is not None:
                    return parsed
            return _parse_simple_config(text)
        except Exception:
            continue
    return {}


def apply_config_defaults(args: object, config: dict[str, str]) -> None:
    """Apply config defaults to argparse args (CLI flags always win)."""
    if not config:
        return

    if getattr(args, "languages", None) is None and "language" in config:
        args.languages = [config["language"]]  # type: ignore[attr-defined]

    if getattr(args, "format", "pretty") == "pretty" and "format" in config:
        fmt = config["format"]
        if fmt in _SUPPORTED_FORMATS:
            args.format = fmt  # type: ignore[attr-defined]
