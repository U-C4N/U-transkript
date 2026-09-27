"""Smoke tests for the installed package."""

from __future__ import annotations

import logging
import re

import utmax


def test_version_is_a_pep440_release_or_dev_version() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+(\.dev\d+)?", utmax.__version__)


def test_library_logger_has_a_null_handler() -> None:
    handlers = logging.getLogger("utmax").handlers
    assert any(isinstance(handler, logging.NullHandler) for handler in handlers)
