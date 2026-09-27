"""Architecture rules: the core stays pure and ``import utmax`` needs only the standard library."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import utmax

PACKAGE = Path(utmax.__file__).resolve().parent
CORE = PACKAGE / "core"

FORBIDDEN_IN_CORE = (
    "asyncio",
    "concurrent",
    "http.client",
    "http.cookiejar",
    "http.server",
    "socket",
    "ssl",
    "subprocess",
    "threading",
    "urllib.error",
    "urllib.request",
    "utmax.adapters",
    "utmax.client",
    "utmax.compat",
    "utmax.mcp",
    "utmax.services",
)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def is_forbidden(name: str) -> bool:
    return any(name == banned or name.startswith(f"{banned}.") for banned in FORBIDDEN_IN_CORE)


def test_core_never_imports_io_modules_or_outer_layers() -> None:
    offenders = [
        f"{path.relative_to(PACKAGE).as_posix()}: {name}"
        for path in sorted(CORE.rglob("*.py"))
        for name in sorted(imported_modules(path))
        if is_forbidden(name)
    ]
    assert offenders == []


def test_import_utmax_loads_only_the_standard_library() -> None:
    probe = (
        "import sys\n"
        "import utmax\n"
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
