"""utmax.mcp is an interface: it uses utmax's public API, and only it needs the MCP SDK."""

from __future__ import annotations

import os
import subprocess
import sys

from tests.test_architecture import PACKAGE, imported_modules

SDK = ("anyio", "mcp", "mcp_types", "pydantic")


def test_the_server_uses_utmax_through_its_public_api() -> None:
    offenders = [
        f"{path.name}: {name}"
        for path in sorted((PACKAGE / "mcp").rglob("*.py"))
        for name in sorted(imported_modules(path))
        if name.startswith(("utmax.adapters", "utmax.services", "utmax.compat"))
    ]
    assert offenders == []


def test_nothing_outside_utmax_mcp_imports_the_sdk() -> None:
    offenders = [
        f"{path.relative_to(PACKAGE).as_posix()}: {name}"
        for path in sorted(PACKAGE.rglob("*.py"))
        if "mcp" not in path.relative_to(PACKAGE).parts
        for name in sorted(imported_modules(path))
        if name.partition(".")[0] in SDK
    ]
    assert offenders == []


def test_importing_utmax_mcp_loads_only_the_standard_library() -> None:
    probe = (
        "import sys\n"
        "import utmax.mcp\n"
        "names = {name.partition('.')[0] for name in sys.modules}\n"
        "extra = sorted(n for n in names if not n.startswith('_') and n != 'utmax'"
        " and n not in sys.stdlib_module_names)\n"
        "print(','.join(extra))\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COV_", "COVERAGE_"))}
    env["PYTHONPATH"] = str(PACKAGE.parent)
    result = subprocess.run(
        [sys.executable, "-S", "-c", probe], capture_output=True, text=True, env=env, check=True
    )
    assert result.stdout.strip() == ""
