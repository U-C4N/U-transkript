"""The ``utmax-mcp`` command: it explains a missing SDK, reads the environment and serves stdio."""

from __future__ import annotations

import importlib
import io
import os
import runpy
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

import utmax.mcp
from utmax.mcp import main
from utmax.mcp.config import Config


def test_main_explains_how_to_install_the_sdk() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COV_", "COVERAGE_"))}
    env["PYTHONPATH"] = str(Path(utmax.mcp.__file__).resolve().parent.parent.parent)
    result = subprocess.run(
        [sys.executable, "-S", "-c", "from utmax.mcp import main; main()"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert (
        result.stderr.strip() == 'utmax-mcp needs the MCP SDK: pip install "u-transcript-max[mcp]"'
    )


class WithoutSDK(types.ModuleType):
    """``utmax.mcp.server`` as it imports when the MCP SDK is missing."""

    def __getattr__(self, name: str) -> Any:
        raise ModuleNotFoundError("No module named 'mcp'", name="mcp")


def test_main_turns_a_missing_sdk_into_the_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "utmax.mcp.server", WithoutSDK("utmax.mcp.server"))

    with pytest.raises(SystemExit, match=r'pip install "u-transcript-max\[mcp\]"') as caught:
        main()

    assert isinstance(caught.value.__cause__, ModuleNotFoundError)


def test_main_does_not_hide_other_import_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "utmax.mcp.server", None)

    with pytest.raises(ModuleNotFoundError, match=r"utmax\.mcp\.server"):
        main()


def test_python_m_utmax_mcp_runs_main(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(utmax.mcp, "main", lambda: calls.append("main"))

    runpy.run_module("utmax.mcp", run_name="__main__")
    module = importlib.import_module("utmax.mcp.__main__")
    del sys.modules["utmax.mcp.__main__"]

    assert calls == ["main"]
    assert module.main is utmax.mcp.main


def test_main_runs_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    server = pytest.importorskip("utmax.mcp.server")
    calls: list[str] = []
    monkeypatch.setattr(server, "run", lambda: calls.append("run"))

    main()

    assert calls == ["run"]


def test_run_serves_stdio_with_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    server = pytest.importorskip("utmax.mcp.server")
    served: list[Any] = []

    class FakeServer:
        def run(self, transport: str) -> None:
            served.append(transport)

    def fake_build(client: Any, config: Config) -> FakeServer:
        served.append((type(client).__name__, config.download_dir))
        return FakeServer()

    monkeypatch.setattr(server, "build_server", fake_build)
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    monkeypatch.setenv("UTMAX_DOWNLOAD_DIR", str(tmp_path))
    monkeypatch.delenv("UTMAX_PROXY", raising=False)

    server.run()

    assert served == [("Client", tmp_path), "stdio"]


def test_run_writes_utf_8_to_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    server = pytest.importorskip("utmax.mcp.server")
    stderr = io.TextIOWrapper(io.BytesIO(), encoding="cp1254")
    monkeypatch.setattr(
        server,
        "build_server",
        lambda client, config: types.SimpleNamespace(run=lambda transport: None),
    )
    monkeypatch.setattr(sys, "stderr", stderr)

    server.run()

    assert (stderr.encoding, stderr.errors) == ("utf-8", "backslashreplace")


def test_run_refuses_an_unusable_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    server = pytest.importorskip("utmax.mcp.server")
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    monkeypatch.setenv("UTMAX_PROXY", "socks5://proxy.test:1080")

    with pytest.raises(SystemExit, match=r"utmax-mcp: Unsupported proxy URL .* Suggestion: "):
        server.run()
