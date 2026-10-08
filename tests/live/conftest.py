"""Treat YouTube blocking this machine's IP as a skip, not a failure (cloud CI runners)."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from utmax import compat
from utmax.errors import RequestBlocked


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, object, object]:
    try:
        return (yield)
    except (RequestBlocked, compat.RequestBlocked) as error:
        pytest.skip(f"YouTube is blocking this IP address: {error}")
