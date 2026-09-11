"""Model provider selection. Bedrock is the default (what the hackathon judges expect).

Other providers are optional extras so the default install stays small:
    uv sync --extra anthropic    # ANTHROPIC_API_KEY
    uv sync --extra openai       # OPENAI_API_KEY
    uv sync --extra ollama       # local models, no key
"""

from __future__ import annotations

import os
from typing import Any

from afh_agent.config import DEFAULT_BEDROCK_MODEL_ID, Settings, load_settings

DEFAULT_ANTHROPIC_MODEL_ID = "claude-opus-5"
SUPPORTED_PROVIDERS = ("bedrock", "anthropic", "openai", "ollama")


class MissingExtraError(RuntimeError):
    """Raised when a provider is selected but its optional dependency is not installed."""


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set; see .env.example")
    return value


def build_model(settings: Settings | None = None) -> Any:
    """Return a strands Model for the provider named in AFH_MODEL_PROVIDER."""
    s = settings or load_settings()

    if s.provider == "bedrock":
        from strands.models import BedrockModel

        return BedrockModel(model_id=s.model_id or DEFAULT_BEDROCK_MODEL_ID, region_name=s.aws_region)

    if s.provider == "anthropic":
        try:
            from strands.models.anthropic import AnthropicModel
        except ImportError as exc:
            raise MissingExtraError("run: uv sync --extra anthropic") from exc
        return AnthropicModel(
            client_args={"api_key": _require_env("ANTHROPIC_API_KEY")},
            model_id=s.model_id or DEFAULT_ANTHROPIC_MODEL_ID,
            max_tokens=4096,
        )

    if s.provider == "openai":
        try:
            from strands.models.openai import OpenAIModel
        except ImportError as exc:
            raise MissingExtraError("run: uv sync --extra openai") from exc
        if not s.model_id:
            raise RuntimeError("set AFH_MODEL_ID to an OpenAI model id when AFH_MODEL_PROVIDER=openai")
        return OpenAIModel(client_args={"api_key": _require_env("OPENAI_API_KEY")}, model_id=s.model_id)

    if s.provider == "ollama":
        try:
            from strands.models.ollama import OllamaModel
        except ImportError as exc:
            raise MissingExtraError("run: uv sync --extra ollama") from exc
        if not s.model_id:
            raise RuntimeError("set AFH_MODEL_ID to a pulled Ollama model when AFH_MODEL_PROVIDER=ollama")
        return OllamaModel(host=s.ollama_host, model_id=s.model_id)

    raise ValueError(f"unknown AFH_MODEL_PROVIDER={s.provider!r}; expected one of {SUPPORTED_PROVIDERS}")
