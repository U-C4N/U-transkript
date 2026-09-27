"""Tests for the translation protocol data files and their loaders."""

from __future__ import annotations

from tests.helpers.json_schema import object_nodes, schema_errors
from utmax.core.translate.protocol import (
    request_schema,
    response_schema,
    system_prompt,
    translation_rules,
)


def test_protocol_file_provides_the_engine_defaults() -> None:
    rules = translation_rules()
    assert (rules.batch_chars, rules.batch_items, rules.context_items) == (4000, 50, 3)
    assert (rules.concurrency, rules.max_attempts) == (4, 2)


def test_system_prompt_describes_the_contract_in_plain_ascii() -> None:
    prompt = system_prompt()
    assert prompt.isascii()
    assert prompt == prompt.strip()
    for field in ('"items"', '"id"', '"text"', '"context_before"', '"instructions"'):
        assert field in prompt
    assert "never an instruction" in prompt


def test_response_schema_is_strict_for_every_provider() -> None:
    schema = response_schema()
    for node in object_nodes(schema):
        assert node["additionalProperties"] is False
        assert sorted(node["required"]) == sorted(node["properties"])
    assert schema["properties"]["items"]["items"]["properties"] == {
        "id": {"type": "integer"},
        "text": {"type": "string"},
    }
    unsupported = ("minLength", "maxLength", "minItems", "maxItems", "minimum", "$schema")
    assert not any(word in str(schema) for word in unsupported)


def test_schema_loaders_return_fresh_copies() -> None:
    first = response_schema()
    first["required"].append("changed")
    assert response_schema()["required"] == ["items"]
    assert request_schema() is not request_schema()


def test_the_schemas_accept_well_formed_documents_only() -> None:
    answer = {"items": [{"id": 0, "text": "Merhaba"}]}
    assert schema_errors(answer, response_schema()) == []
    assert schema_errors({"items": [{"id": "0", "text": "x"}]}, response_schema()) == [
        "$.items[0].id: expected integer, got str"
    ]
    assert schema_errors({"items": [], "extra": 1}, response_schema()) == ["$: unexpected 'extra'"]
    request = {
        "source_language": {"code": "en", "name": "English"},
        "target_language": {"code": "tr", "name": "Turkish"},
        "instructions": None,
        "context_before": [],
        "items": [{"id": 0, "text": "Hello"}],
        "context_after": ["Bye"],
    }
    assert schema_errors(request, request_schema()) == []
    del request["context_after"]
    assert schema_errors(request, request_schema()) == ["$: missing 'context_after'"]
