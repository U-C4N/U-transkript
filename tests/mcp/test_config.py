"""The MCP server's settings come from environment variables."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from utmax.mcp.config import Config, default_download_dir


def test_defaults() -> None:
    config = Config.from_env({})

    assert config == Config()
    assert config.proxy is None
    assert config.download_dir == Path.home() / "Downloads" / "utmax"
    assert default_download_dir() == config.download_dir


def test_every_variable_is_read() -> None:
    config = Config.from_env(
        {"UTMAX_DOWNLOAD_DIR": "~/videos", "UTMAX_PROXY": "http://user:pass@proxy.test:8080"}
    )

    assert config.download_dir == Path.home() / "videos"
    assert config.proxy == "http://user:pass@proxy.test:8080"


def test_empty_variables_keep_the_defaults() -> None:
    assert Config.from_env({"UTMAX_DOWNLOAD_DIR": "  ", "UTMAX_PROXY": ""}) == Config()


def test_the_process_environment_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UTMAX_PROXY", "http://proxy.test:8080")

    assert Config.from_env().proxy == "http://proxy.test:8080"


def test_the_download_folder_is_expanded_and_absolute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("UTMAX_TEST_FOLDER", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    variable = Config.from_env({"UTMAX_DOWNLOAD_DIR": "$UTMAX_TEST_FOLDER/videos"})
    relative = Config.from_env({"UTMAX_DOWNLOAD_DIR": "downloads"})

    assert variable.download_dir == tmp_path / "videos"
    assert relative.download_dir == tmp_path / "downloads"
    assert relative.download_dir.is_absolute()


def test_the_proxy_password_stays_out_of_the_repr() -> None:
    config = Config(proxy="http://alice:s3cret@proxy.test:8080")

    assert "s3cret" not in repr(config)
    assert config == Config(proxy="http://alice:s3cret@proxy.test:8080")


def test_settings_cannot_change() -> None:
    config = Config()

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.proxy = "http://proxy.test:8080"  # type: ignore[misc]
    assert not hasattr(config, "__dict__")
