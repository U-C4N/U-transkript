"""Every public name of youtube-transcript-api 1.2.4 exists in utmax.compat, as the same kind
of object, with the same signature, bases, attributes and values.

The manifest is recorded from the released wheel by ``scripts/compat_manifest.py``.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
import typing
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

MANIFEST_PATH = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "compat"
    / "youtube_transcript_api-1.2.4.json"
)
MANIFEST: dict[str, Any] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
_DECORATORS = {"property": property, "classmethod": classmethod, "staticmethod": staticmethod}


def compat_module(name: str) -> ModuleType:
    return importlib.import_module(
        "utmax.compat" if name in {"", "__init__"} else f"utmax.compat.{name}"
    )


def jsonable(value: Any) -> Any:
    if isinstance(value, tuple | list):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    return value


def value_problems(where: str, actual: Any, expected: dict[str, Any]) -> list[str]:
    if "value" in expected:
        return [] if jsonable(actual) == expected["value"] else [f"{where} has another value"]
    if "ref" in expected:
        name = getattr(actual, "__name__", None)
        return [] if name == expected["ref"] else [f"{where} is not {expected['ref']}"]
    if "dict" in expected:
        if not isinstance(actual, dict) or list(actual) != list(expected["dict"]):
            return [f"{where} has other keys"]
        return [
            problem
            for key, item in expected["dict"].items()
            for problem in value_problems(f"{where}[{key!r}]", actual[key], item)
        ]
    return []


def parameter_problems(where: str, function: Any, expected: list[dict[str, Any]]) -> list[str]:
    parameters = list(inspect.signature(function).parameters.values())
    names = [parameter.name for parameter in parameters]
    if names != [parameter["name"] for parameter in expected]:
        return [f"{where} takes {names}"]
    problems = []
    for actual, wanted in zip(parameters, expected, strict=True):
        if actual.kind.name.lower() != wanted["kind"]:
            problems.append(f"{where}({actual.name}) is {actual.kind.name.lower()}")
        has_default = actual.default is not inspect.Parameter.empty
        if has_default != ("default" in wanted):
            problems.append(f"{where}({actual.name}) default presence differs")
        elif has_default:
            problems += value_problems(
                f"{where}({actual.name}=)", actual.default, wanted["default"]
            )
    return problems


def class_problems(where: str, cls: Any, expected: dict[str, Any]) -> list[str]:
    if not isinstance(cls, type):
        return [f"{where} is not a class"]
    problems: list[str] = []
    bases = expected["bases"]
    if bases == ["TypedDict"]:
        if not typing.is_typeddict(cls):
            problems.append(f"{where} is not a TypedDict")
    elif [base.__name__ for base in cls.__bases__ if base is not object] != bases:
        problems.append(f"{where} has bases {[base.__name__ for base in cls.__bases__]}")
    if "dataclass_fields" in expected:
        fields = [field.name for field in dataclasses.fields(cls)]
        if fields != expected["dataclass_fields"]:
            problems.append(f"{where} has dataclass fields {fields}")
    if "typeddict_keys" in expected and list(cls.__annotations__) != expected["typeddict_keys"]:
        problems.append(f"{where} has keys {list(cls.__annotations__)}")
    own = vars(cls)
    for name, value in expected.get("attributes", {}).items():
        if name not in own:
            problems.append(f"{where}.{name} is missing")
        else:
            problems += value_problems(f"{where}.{name}", own[name], value)
    for name, method in expected.get("methods", {}).items():
        if name not in own:
            problems.append(f"{where}.{name}() is missing")
            continue
        raw = own[name]
        decorator = _DECORATORS.get(method["kind"])
        if decorator is not None and not isinstance(raw, decorator):
            problems.append(f"{where}.{name} is not a {method['kind']}")
            continue
        if decorator is None and not inspect.isfunction(raw):
            problems.append(f"{where}.{name} is not a method")
            continue
        if method.get("abstract") and not getattr(raw, "__isabstractmethod__", False):
            problems.append(f"{where}.{name} is not abstract")
        if "parameters" in method:
            function = raw.__func__ if isinstance(raw, classmethod | staticmethod) else raw
            problems += parameter_problems(f"{where}.{name}", function, method["parameters"])
    for name, nested in expected.get("classes", {}).items():
        problems += class_problems(f"{where}.{name}", own.get(name), nested)
    return problems


def module_problems(name: str) -> list[str]:
    module = compat_module(name)
    surface = MANIFEST["modules"][name]
    problems = []
    if surface["all"] is not None:
        missing = sorted(set(surface["all"]) - set(getattr(module, "__all__", ())))
        if missing:
            problems.append(f"{name}.__all__ lacks {missing}")
    for attribute, entry in surface["names"].items():
        where = f"{name}.{attribute}"
        if not hasattr(module, attribute):
            problems.append(f"{where} is missing")
            continue
        value = getattr(module, attribute)
        if entry["kind"] == "import":
            source = getattr(compat_module(entry["from"]), entry["name"], None)
            if value is not source:
                problems.append(f"{where} is not {entry['from']}.{entry['name']}")
        elif entry["kind"] == "constant":
            problems += value_problems(where, value, entry)
        elif entry["kind"] == "function":
            problems += parameter_problems(where, value, entry["parameters"])
        else:
            problems += class_problems(where, value, entry)
    return problems


def test_the_manifest_describes_youtube_transcript_api_1_2_4() -> None:
    modules = MANIFEST["modules"]

    assert (MANIFEST["package"], MANIFEST["version"]) == ("youtube_transcript_api", "1.2.4")
    assert sorted(modules) == [
        "__init__",
        "_api",
        "_errors",
        "_settings",
        "_transcripts",
        "formatters",
        "proxies",
    ]
    assert len(modules["__init__"]["all"]) == 24
    assert sum(len(module["names"]) for module in modules.values()) == 92


@pytest.mark.parametrize("module", sorted(MANIFEST["modules"]))
def test_utmax_compat_matches_the_manifest(module: str) -> None:
    assert module_problems(module) == []


def test_the_parity_check_notices_differences(monkeypatch: pytest.MonkeyPatch) -> None:
    proxies = compat_module("proxies")
    monkeypatch.setattr(proxies.WebshareProxyConfig, "DEFAULT_PORT", 8080)
    monkeypatch.delattr(proxies, "InvalidProxyConfig")

    assert module_problems("proxies") == [
        "proxies.InvalidProxyConfig is missing",
        "proxies.WebshareProxyConfig.DEFAULT_PORT has another value",
    ]
