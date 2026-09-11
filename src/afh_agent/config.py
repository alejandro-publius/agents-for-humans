"""Environment-driven settings. Read at call time so tests can override via monkeypatch."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_BEDROCK_MODEL_ID = "global.anthropic.claude-sonnet-4-6"
DEFAULT_REGION = "us-west-2"


@dataclass(frozen=True)
class Settings:
    provider: str
    model_id: str | None
    aws_region: str
    session_dir: str
    ollama_host: str


def load_settings() -> Settings:
    """Build Settings from the environment (see .env.example for the variables)."""
    return Settings(
        provider=os.getenv("AFH_MODEL_PROVIDER", "bedrock").lower(),
        model_id=os.getenv("AFH_MODEL_ID") or None,
        aws_region=os.getenv("AWS_REGION", DEFAULT_REGION),
        session_dir=os.getenv("AFH_SESSION_DIR", ".sessions"),
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
    )
