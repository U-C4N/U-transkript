from __future__ import annotations

import sys

try:
    from colorama import Fore, Style, init
    init(autoreset=True)
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False


def success(msg: str) -> None:
    """Print a green success message to stdout."""
    if HAS_COLOR:
        print(f"{Fore.GREEN}{msg}{Style.RESET_ALL}")
    else:
        print(msg)


def error(msg: str) -> None:
    """Print a red error message to stderr."""
    if HAS_COLOR:
        print(f"{Fore.RED}Error: {msg}{Style.RESET_ALL}", file=sys.stderr)
    else:
        print(f"Error: {msg}", file=sys.stderr)


def warning(msg: str) -> None:
    """Print a yellow warning message to stderr."""
    if HAS_COLOR:
        print(f"{Fore.YELLOW}Warning: {msg}{Style.RESET_ALL}", file=sys.stderr)
    else:
        print(f"Warning: {msg}", file=sys.stderr)


def info(msg: str) -> None:
    """Print a cyan informational message to stdout."""
    if HAS_COLOR:
        print(f"{Fore.CYAN}{msg}{Style.RESET_ALL}")
    else:
        print(msg)
