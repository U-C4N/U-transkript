"""Only the optional extras (AI providers, MCP) add dependencies; the core stays dependency-free."""

from __future__ import annotations

from importlib.metadata import entry_points, metadata

EXPECTED_REQUIREMENTS = {
    "anthropic<2,>=1.8; extra == 'ai'",
    "google-genai<3,>=2.25; extra == 'ai'",
    "openai<4,>=3.19; extra == 'ai'",
    "anthropic<2,>=1.8; extra == 'claude'",
    "google-genai<3,>=2.25; extra == 'gemini'",
    "openai<4,>=3.19; extra == 'openai'",
    "openai<4,>=3.19; extra == 'openrouter'",
    "mcp<3,>=2.2; extra == 'mcp'",
    "anyio<5,>=4.11; extra == 'mcp'",
}


def test_the_extras_are_declared() -> None:
    extras = metadata("u-transcript-max").get_all("Provides-Extra") or []
    assert sorted(extras) == ["ai", "claude", "gemini", "mcp", "openai", "openrouter"]


def test_every_requirement_belongs_to_an_extra() -> None:
    requirements = metadata("u-transcript-max").get_all("Requires-Dist") or []
    assert set(requirements) == EXPECTED_REQUIREMENTS


def test_the_mcp_server_is_the_only_command() -> None:
    commands = {
        point.name: point.value
        for point in entry_points(group="console_scripts")
        if point.dist is not None and point.dist.name == "u-transcript-max"
    }
    assert commands == {"utmax-mcp": "utmax.mcp:main"}
