"""Parse ``"provider=model-id"`` model specs such as ``"claude=claude-opus-5"``."""

from __future__ import annotations

from dataclasses import dataclass

from utmax.errors import InvalidModelSpec

__all__ = ["PROVIDERS", "ModelSpec", "parse_model_spec"]

PROVIDERS = ("claude", "openai", "gemini", "openrouter")

_EXAMPLES = '"claude=claude-opus-5" or "openai=llama3.1:8b"'


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """A provider plus the model id to ask it for."""

    provider: str
    model: str

    def __str__(self) -> str:
        return f"{self.provider}={self.model}"


def parse_model_spec(spec: object) -> ModelSpec:
    """Split ``spec`` at its first ``=`` into a provider and a model id.

    The provider is case-insensitive and whitespace around both parts is ignored; the model id
    may itself contain ``=``, ``:`` or ``/`` (``"openrouter=meta-llama/llama-4-maverick"``).

    Raises:
        InvalidModelSpec: ``spec`` is not a string, has no ``=``, has an empty part or names an
            unknown provider.
    """
    if not isinstance(spec, str):
        raise InvalidModelSpec(f"The model must be a string such as {_EXAMPLES}, not {spec!r}.")
    provider, separator, model = spec.partition("=")
    provider, model = provider.strip().lower(), model.strip()
    if not separator or not provider or not model:
        raise InvalidModelSpec(
            f'The model {spec!r} is not "provider=model-id"; use for example {_EXAMPLES}.'
        )
    if provider not in PROVIDERS:
        raise InvalidModelSpec(
            f"Unknown provider {provider!r} in {spec!r}; choose one of: {', '.join(PROVIDERS)}."
        )
    return ModelSpec(provider, model)
