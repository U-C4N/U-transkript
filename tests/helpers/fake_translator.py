"""A deterministic Translator for engine tests: no network, scripted answers, recorded requests."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from typing import Any

from utmax.adapters.providers.base import Translator

Script = Callable[[dict[str, Any]], str]


def echo(request: dict[str, Any]) -> str:
    """A valid answer: every requested cue upper-cased."""
    items = [{"id": item["id"], "text": item["text"].upper()} for item in request["items"]]
    return json.dumps({"items": items})


class FakeTranslator(Translator):
    """Answers every request with ``script(request)`` and records what it was sent."""

    def __init__(self, script: Script = echo, *, name: str = "fake=echo-1", **engine: int) -> None:
        super().__init__(**engine)
        self.script = script
        self._name = name
        self.requests: list[dict[str, Any]] = []
        self.systems: list[str] = []
        self.schemas: list[Mapping[str, Any]] = []
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._name

    def generate_json(self, system: str, prompt: str, schema: Mapping[str, Any]) -> str:
        request = json.loads(prompt)
        with self._lock:
            self.requests.append(request)
            self.systems.append(system)
            self.schemas.append(schema)
        return self.script(request)

    @property
    def batches(self) -> list[list[int]]:
        """The ids of every request, in the order the requests arrived."""
        return [[item["id"] for item in request["items"]] for request in self.requests]
