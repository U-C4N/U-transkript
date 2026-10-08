"""The MCP server's settings come from environment variables."""

from __future__ import annotations

from pathlib import Path

import pytest

from utmax.mcp.config import Config, default_download_dir


def test_defaults() -> None:
    config = Config.from_env({})

    assert config == Config()
    assert (config.model, config.base_url, config.proxy) == (None, None, None)
    assert config.download_dir == Path.home() / "Downloads" / "utmax"
    assert default_download_dir() == config.download_dir


def test_every_variable_is_read() -> None:
    config = Config.from_env(
        {
            "UTMAX_MODEL": " claude=claude-opus-5 ",
            "UTMAX_BASE_URL": "http://localhost:11434/v1",
            "UTMAX_DOWNLOAD_DIR": "~/videos",
            "UTMAX_PROXY": "http://user:pass@proxy.test:8080",
        }
    )

    assert config.model == "claude=claude-opus-5"
    assert config.base_url == "http://localhost:11434/v1"
    assert config.download_dir == Path("~/videos").expanduser()
    assert config.proxy == "http://user:pass@proxy.test:8080"


def test_empty_variables_keep_the_defaults() -> None:
    names = ("UTMAX_MODEL", "UTMAX_BASE_URL", "UTMAX_DOWNLOAD_DIR", "UTMAX_PROXY")

    assert Config.from_env(dict.fromkeys(names, "  ")) == Config()


def test_the_process_environment_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UTMAX_MODEL", "gemini=gemini-3-pro")

    assert Config.from_env().model == "gemini=gemini-3-pro"


@pytest.mark.parametrize(
    ("model", "options"),
    [
        ("openai=llama3.1:8b", {"base_url": "http://localhost:11434/v1"}),
        (" OpenAI = gpt-5 ", {"base_url": "http://localhost:11434/v1"}),
        ("claude=claude-opus-5", {}),
        ("openrouter=openai/gpt-5", {}),
    ],
)
def test_base_url_only_goes_to_openai_models(model: str, options: dict[str, str]) -> None:
    config = Config(base_url="http://localhost:11434/v1")

    assert config.translator_options(model) == options
    assert Config().translator_options(model) == {}
