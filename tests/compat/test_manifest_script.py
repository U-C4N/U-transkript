"""scripts/compat_manifest.py reads a release's surface from its archive with ``ast`` alone."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "compat_manifest.py"
SOURCES = {
    "__init__": 'from ._api import Api\n\n__all__ = ["Api"]\n',
    "_api": (
        "import json\n"
        "from typing import Optional\n"
        "from .proxies import Config\n\n"
        "LIMIT = 3\n"
        "_PRIVATE = 1\n\n\n"
        "class Api:\n"
        '    NAME = "api"\n'
        '    GREETING = f"{NAME}!"\n\n'
        "    def __init__(self, config=None, *args, timeout: float = LIMIT, **kwargs):\n"
        "        raise RuntimeError('never run')\n\n"
        "    @property\n"
        "    def ready(self):\n"
        "        return True\n\n"
        "    @classmethod\n"
        '    def legacy(cls, video_id, languages=("en",)):\n'
        "        pass\n\n"
        "    @staticmethod\n"
        "    def build(client, data):\n"
        "        pass\n\n"
        "    def _hidden(self):\n"
        "        pass\n\n"
        "    def __len__(self):\n"
        "        return 0\n\n"
        "    class Error(Exception):\n"
        "        pass\n"
    ),
    "_errors": (
        "class Base(Exception):\n"
        '    MESSAGE = "x"\n\n\n'
        "class Child(Base):\n"
        '    MESSAGE = f"{Base.MESSAGE}y"\n'
        "    OTHER = f'{undefined_name}'\n"
    ),
    "_settings": 'URL = "https://example.test/{id}"\n',
    "_transcripts": (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\n"
        "class Snip:\n"
        "    text: str\n"
        "    start: float = 0.0\n"
    ),
    "formatters": ('TYPES = {"json": dict}\n\n\ndef helper(a, /, b, *, c=None):\n    pass\n'),
    "proxies": (
        "from abc import ABC, abstractmethod\n"
        "from typing import TypedDict\n\n\n"
        "class D(TypedDict):\n"
        "    http: str\n\n\n"
        "class Config(ABC):\n"
        "    @abstractmethod\n"
        "    def to_dict(self):\n"
        "        pass\n"
    ),
}
METADATA = "Metadata-Version: 2.1\nName: youtube-transcript-api\nVersion: 9.9\n"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("compat_manifest", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_wheel(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("youtube_transcript_api-9.9.dist-info/METADATA", METADATA)
        for module, source in SOURCES.items():
            archive.writestr(f"youtube_transcript_api/{module}.py", source)
    return path


def make_sdist(path: Path) -> Path:
    with tarfile.open(path, "w:gz") as archive:
        files = {"PKG-INFO": METADATA} | {
            f"youtube_transcript_api/{module}.py": source for module, source in SOURCES.items()
        }
        for name, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(f"youtube_transcript_api-9.9/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


def run(script: ModuleType, source: Path, tmp_path: Path) -> dict[str, Any]:
    output = tmp_path / "out" / "manifest.json"
    script.main([str(source), str(output)])
    text = output.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    return json.loads(text)


def test_the_manifest_records_the_release(script: ModuleType, tmp_path: Path) -> None:
    wheel = make_wheel(tmp_path / "fake.whl")

    manifest = run(script, wheel, tmp_path)

    assert manifest["package"] == "youtube_transcript_api"
    assert manifest["version"] == "9.9"
    assert manifest["source"] == "fake.whl"
    assert manifest["sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert manifest["modules"]["__init__"] == {
        "all": ["Api"],
        "names": {"Api": {"kind": "import", "from": "_api", "name": "Api"}},
    }


def test_public_names_classes_and_signatures(script: ModuleType, tmp_path: Path) -> None:
    names = run(script, make_wheel(tmp_path / "fake.whl"), tmp_path)["modules"]["_api"]["names"]

    assert list(names) == ["Config", "LIMIT", "Api"]
    assert names["Config"] == {"kind": "import", "from": "proxies", "name": "Config"}
    assert names["LIMIT"] == {"kind": "constant", "value": 3}
    api = names["Api"]
    assert api["bases"] == []
    assert api["attributes"] == {"NAME": {"value": "api"}, "GREETING": {"value": "api!"}}
    assert list(api["methods"]) == ["__init__", "ready", "legacy", "build", "__len__"]
    assert api["methods"]["__init__"]["parameters"] == [
        {"name": "self", "kind": "positional_or_keyword"},
        {"name": "config", "kind": "positional_or_keyword", "default": {"value": None}},
        {"name": "args", "kind": "var_positional"},
        {"name": "timeout", "kind": "keyword_only", "default": {"value": 3}},
        {"name": "kwargs", "kind": "var_keyword"},
    ]
    assert api["methods"]["ready"] == {"kind": "property"}
    assert api["methods"]["legacy"]["kind"] == "classmethod"
    assert api["methods"]["legacy"]["parameters"][-1]["default"] == {"value": ["en"]}
    assert api["methods"]["build"]["kind"] == "staticmethod"
    assert api["classes"] == {"Error": {"kind": "class", "bases": ["Exception"]}}


def test_values_dataclasses_typeddicts_and_abstract_methods(
    script: ModuleType, tmp_path: Path
) -> None:
    modules = run(script, make_wheel(tmp_path / "fake.whl"), tmp_path)["modules"]

    child = modules["_errors"]["names"]["Child"]
    assert child["attributes"] == {
        "MESSAGE": {"value": "xy"},
        "OTHER": {"source": "f'{undefined_name}'"},
    }
    assert modules["_settings"]["names"]["URL"]["value"] == "https://example.test/{id}"
    assert modules["_transcripts"]["names"]["Snip"]["dataclass_fields"] == ["text", "start"]
    formatters = modules["formatters"]["names"]
    assert formatters["TYPES"] == {"kind": "constant", "dict": {"json": {"ref": "dict"}}}
    assert [p["kind"] for p in formatters["helper"]["parameters"]] == [
        "positional_only",
        "positional_or_keyword",
        "keyword_only",
    ]
    proxies = modules["proxies"]["names"]
    assert proxies["D"] == {"kind": "class", "bases": ["TypedDict"], "typeddict_keys": ["http"]}
    assert proxies["Config"]["methods"]["to_dict"]["abstract"] is True


def test_sdists_give_the_same_surface(script: ModuleType, tmp_path: Path) -> None:
    from_wheel = run(script, make_wheel(tmp_path / "fake.whl"), tmp_path)
    from_sdist = run(script, make_sdist(tmp_path / "fake.tar.gz"), tmp_path)

    assert from_sdist["version"] == "9.9"
    assert from_sdist["modules"] == from_wheel["modules"]


def test_other_files_are_refused(script: ModuleType, tmp_path: Path) -> None:
    other = tmp_path / "fake.zip"
    other.write_bytes(b"")

    with pytest.raises(SystemExit, match=r"expected a \.whl or \.tar\.gz file"):
        script.main([str(other), str(tmp_path / "out.json")])
