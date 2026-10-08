"""Record the public surface of youtube-transcript-api as JSON, for utmax.compat's parity test.

Download the release from PyPI, then run from the repository root::

    uv run python scripts/compat_manifest.py youtube_transcript_api-1.2.4-py3-none-any.whl \\
        tests/fixtures/compat/youtube_transcript_api-1.2.4.json

The source is a wheel or an sdist. Its Python files are read from the archive and parsed with
``ast`` only: nothing is extracted to disk, imported or run.

The manifest lists, for each module of the package, its public names: classes (bases, dataclass
fields, TypedDict keys, class attributes, methods with their parameters, nested classes),
constants with their values, functions with their parameters, names imported from sibling
modules, and ``__all__``.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import tarfile
import zipfile
from email.parser import HeaderParser
from pathlib import Path
from typing import Any

PACKAGE = "youtube_transcript_api"
MODULES = ("__init__", "_api", "_errors", "_settings", "_transcripts", "formatters", "proxies")
_KINDS = {
    "posonlyargs": "positional_only",
    "args": "positional_or_keyword",
    "kwonlyargs": "keyword_only",
}

Scope = dict[str, Any]


def read_archive(path: Path) -> tuple[str, dict[str, str]]:
    """The version and the sources of :data:`MODULES` found in a wheel or an sdist."""
    if path.name.endswith(".whl"):
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            metadata = next(name for name in names if name.endswith(".dist-info/METADATA"))
            version = _version(archive.read(metadata).decode("utf-8"))
            sources = {
                module: archive.read(f"{PACKAGE}/{module}.py").decode("utf-8") for module in MODULES
            }
        return version, sources
    if path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            members = {member.name: member for member in archive.getmembers() if member.isfile()}
            root = next(name for name in members if name.endswith("/PKG-INFO")).split("/")[0]
            version = _version(_read_member(archive, members[f"{root}/PKG-INFO"]))
            sources = {
                module: _read_member(archive, members[f"{root}/{PACKAGE}/{module}.py"])
                for module in MODULES
            }
        return version, sources
    raise SystemExit(f"{path.name}: expected a .whl or .tar.gz file")


def build_manifest(path: Path) -> dict[str, Any]:
    """The manifest of the release in ``path``."""
    version, sources = read_archive(path)
    return {
        "package": PACKAGE,
        "version": version,
        "source": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "modules": {
            module: module_surface(ast.parse(source, filename=f"{module}.py"))
            for module, source in sources.items()
        },
    }


def module_surface(tree: ast.Module) -> dict[str, Any]:
    """The public names of one module, in source order, and its ``__all__``."""
    names: dict[str, Any] = {}
    scope: Scope = {}
    classes: dict[str, Scope] = {}
    exported: list[str] | None = None
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level > 0:
            for alias in node.names:
                name = alias.asname or alias.name
                if _public(name):
                    names[name] = {"kind": "import", "from": node.module or "", "name": alias.name}
        elif isinstance(node, ast.ClassDef):
            surface, class_scope = class_surface(node, classes, scope)
            classes[node.name] = class_scope
            if _public(node.name):
                names[node.name] = surface
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and _public(node.name):
            names[node.name] = {"kind": "function", "parameters": parameters(node.args, scope)}
        elif isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                value = evaluate(node.value, scope, classes)
                if "value" in value:
                    scope[target.id] = value["value"]
                if target.id == "__all__":
                    exported = list(value["value"])
                elif _public(target.id):
                    names[target.id] = {"kind": "constant", **value}
    return {"all": exported, "names": names}


def class_surface(
    node: ast.ClassDef, classes: dict[str, Scope], outer: Scope
) -> tuple[dict[str, Any], Scope]:
    """One class: bases, dataclass fields or TypedDict keys, attributes, methods, nested classes.

    Names in the class body resolve to the class's own constants first, then to ``outer``.
    """
    bases = [_dotted(base) for base in node.bases]
    decorators = {_dotted(_called(decorator)) for decorator in node.decorator_list}
    surface: dict[str, Any] = {"kind": "class", "bases": bases}
    fields = [
        item.target.id
        for item in node.body
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
    ]
    if "dataclass" in decorators:
        surface["dataclass_fields"] = fields
    if "TypedDict" in bases:
        surface["typeddict_keys"] = fields
    scope: Scope = {}
    attributes: dict[str, Any] = {}
    methods: dict[str, Any] = {}
    nested: dict[str, Any] = {}
    for item in node.body:
        if isinstance(item, ast.Assign | ast.AnnAssign) and item.value is not None:
            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    value = evaluate(item.value, {**outer, **scope}, classes)
                    if "value" in value:
                        scope[target.id] = value["value"]
                    if _public(target.id):
                        attributes[target.id] = value
        elif isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
            if _public(item.name) or _dunder(item.name):
                methods[item.name] = method_surface(item, {**outer, **scope})
        elif isinstance(item, ast.ClassDef) and _public(item.name):
            nested[item.name], _ = class_surface(item, classes, {**outer, **scope})
    if attributes:
        surface["attributes"] = attributes
    if methods:
        surface["methods"] = methods
    if nested:
        surface["classes"] = nested
    return surface, scope


def method_surface(node: ast.FunctionDef | ast.AsyncFunctionDef, scope: Scope) -> dict[str, Any]:
    """A method's kind (method, classmethod, staticmethod, property) and parameters."""
    decorators = {_dotted(_called(decorator)) for decorator in node.decorator_list}
    kind = next(
        (name for name in ("property", "classmethod", "staticmethod") if name in decorators),
        "method",
    )
    surface: dict[str, Any] = {"kind": kind}
    if "abstractmethod" in decorators:
        surface["abstract"] = True
    if kind != "property":
        surface["parameters"] = parameters(node.args, scope)
    return surface


def parameters(args: ast.arguments, scope: Scope) -> list[dict[str, Any]]:
    """Every parameter in order: name, kind and, when it has one, its default."""
    result: list[dict[str, Any]] = []
    positional = [*args.posonlyargs, *args.args]
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults))
    defaults += args.defaults
    for group in ("posonlyargs", "args"):
        for arg in getattr(args, group):
            default = defaults[positional.index(arg)]
            result.append(_parameter(arg.arg, _KINDS[group], default, scope))
    if args.vararg is not None:
        result.append({"name": args.vararg.arg, "kind": "var_positional"})
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        result.append(_parameter(arg.arg, "keyword_only", default, scope))
    if args.kwarg is not None:
        result.append({"name": args.kwarg.arg, "kind": "var_keyword"})
    return result


def evaluate(node: ast.expr, scope: Scope, classes: dict[str, Scope]) -> dict[str, Any]:
    """Describe a value: ``{"value": ...}`` when it can be computed from the source alone,
    ``{"ref": name}`` for a name, ``{"dict": {...}}`` for a dict literal with other values,
    else ``{"source": text}``."""
    try:
        return {"value": ast.literal_eval(node)}
    except ValueError:
        pass
    if isinstance(node, ast.JoinedStr):
        text = _joined(node, scope, classes)
        if text is not None:
            return {"value": text}
    if isinstance(node, ast.Name):
        return {"value": scope[node.id]} if node.id in scope else {"ref": node.id}
    if isinstance(node, ast.Dict) and all(isinstance(key, ast.Constant) for key in node.keys):
        return {
            "dict": {
                str(key.value): evaluate(value, scope, classes)
                for key, value in zip(node.keys, node.values, strict=True)
                if isinstance(key, ast.Constant)
            }
        }
    return {"source": ast.unparse(node)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="the release: a .whl or .tar.gz file")
    parser.add_argument("output", type=Path, help="where to write the JSON manifest")
    options = parser.parse_args(argv)
    manifest = build_manifest(options.source)
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(text, encoding="utf-8", newline="\n")


def _parameter(name: str, kind: str, default: ast.expr | None, scope: Scope) -> dict[str, Any]:
    parameter: dict[str, Any] = {"name": name, "kind": kind}
    if default is not None:
        parameter["default"] = evaluate(default, scope, {})
    return parameter


def _joined(node: ast.JoinedStr, scope: Scope, classes: dict[str, Scope]) -> str | None:
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
            continue
        if not isinstance(value, ast.FormattedValue) or value.format_spec or value.conversion != -1:
            return None
        inner = value.value
        if isinstance(inner, ast.Name) and isinstance(scope.get(inner.id), str):
            parts.append(scope[inner.id])
        elif (
            isinstance(inner, ast.Attribute)
            and isinstance(inner.value, ast.Name)
            and isinstance(classes.get(inner.value.id, {}).get(inner.attr), str)
        ):
            parts.append(classes[inner.value.id][inner.attr])
        else:
            return None
    return "".join(parts)


def _read_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> str:
    handle = archive.extractfile(member)
    if handle is None:
        raise SystemExit(f"{member.name}: not a regular file")
    with handle:
        return handle.read().decode("utf-8")


def _version(metadata: str) -> str:
    return str(HeaderParser().parsestr(metadata)["Version"])


def _called(node: ast.expr) -> ast.expr:
    return node.func if isinstance(node, ast.Call) else node


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ast.unparse(node)


def _public(name: str) -> bool:
    return not name.startswith("_")


def _dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


if __name__ == "__main__":
    main()
