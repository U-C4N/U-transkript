"""A tiny validator for the JSON Schema subset used by the translation protocol files."""

from __future__ import annotations

from typing import Any

_TYPES: dict[str, tuple[type, ...]] = {
    "array": (list,),
    "integer": (int,),
    "null": (type(None),),
    "object": (dict,),
    "string": (str,),
}


def schema_errors(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Why ``value`` does not match ``schema`` (type, properties, required, items, strictness)."""
    expected = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
    if not any(
        isinstance(value, _TYPES[name]) and not isinstance(value, bool) for name in expected
    ):
        return [f"{path}: expected {'/'.join(expected)}, got {type(value).__name__}"]
    errors: list[str] = []
    if isinstance(value, dict):
        properties: dict[str, Any] = schema.get("properties", {})
        errors += [
            f"{path}: missing {key!r}" for key in schema.get("required", []) if key not in value
        ]
        if schema.get("additionalProperties") is False:
            errors += [f"{path}: unexpected {key!r}" for key in value if key not in properties]
        for key, item in value.items():
            if key in properties:
                errors += schema_errors(item, properties[key], f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            errors += schema_errors(item, schema["items"], f"{path}[{index}]")
    return errors


def object_nodes(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Every object-typed node of ``schema``, depth first."""
    nodes = [schema] if schema.get("type") == "object" else []
    for child in schema.get("properties", {}).values():
        nodes += object_nodes(child)
    if isinstance(schema.get("items"), dict):
        nodes += object_nodes(schema["items"])
    return nodes
