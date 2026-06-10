"""Build and (optionally) publish u-transkript distributions.

This script must NOT be named build.py: a root build.py shadows the PyPA
`build` package for `python -m build` (and `import build`) run from the
repo root, making the subprocess below recurse into this script forever.

Usage:
    python release.py              # clean, build sdist+wheel, run twine check
    python release.py --test       # build + upload to TestPyPI
    python release.py --upload     # build + upload to PyPI
"""

from __future__ import annotations

import argparse
import glob
import shutil
import subprocess
import sys
from pathlib import Path

REQUIRED_TOOLS = ("build", "twine")
BUILD_ARTIFACTS = ("build", "dist", "u_transkript.egg-info")


def _run(command: list[str], description: str) -> bool:
    print(f">> {description}")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"!! {description} failed")
        if result.stderr:
            print(result.stderr.strip())
        return False
    print(f"   {description} OK")
    return True


def check_requirements() -> bool:
    missing = [tool for tool in REQUIRED_TOOLS if not _module_available(tool)]
    if missing:
        print("Missing build dependencies: " + ", ".join(missing))
        print("Install with: pip install " + " ".join(missing))
        return False
    return True


def _module_available(module_name: str) -> bool:
    try:
        __import__(module_name)
    except ImportError:
        return False
    return True


def clean_build() -> None:
    for path in BUILD_ARTIFACTS:
        target = Path(path)
        if target.exists():
            shutil.rmtree(target)
            print(f"   removed {target}")


def build_package() -> bool:
    return _run([sys.executable, "-m", "build"], "Building sdist + wheel")


def check_package() -> bool:
    dist_files = sorted(glob.glob("dist/*"))
    if not dist_files:
        print("!! no files found in dist/")
        return False
    return _run([sys.executable, "-m", "twine", "check", *dist_files], "Validating dist/")


def _upload(repository: str | None) -> bool:
    dist_files = sorted(glob.glob("dist/*"))
    if not dist_files:
        print("!! no files found in dist/")
        return False
    command = [sys.executable, "-m", "twine", "upload"]
    if repository:
        command += ["--repository", repository]
    command += dist_files
    return _run(command, f"Uploading to {repository or 'PyPI'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--test", action="store_true", help="Publish to TestPyPI after building."
    )
    target.add_argument(
        "--upload", action="store_true", help="Publish to PyPI after building."
    )
    args = parser.parse_args(argv)

    if not check_requirements():
        return 1

    clean_build()

    if not build_package():
        return 1

    if not check_package():
        return 1

    if args.test:
        return 0 if _upload("testpypi") else 1
    if args.upload:
        return 0 if _upload(None) else 1

    print("\nBuild complete. Files:")
    for artifact in sorted(Path("dist").iterdir()):
        print(f"  - {artifact}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
