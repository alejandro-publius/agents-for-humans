"""Test configuration. Every test runs with the network blocked; nothing here needs credentials."""

from __future__ import annotations

import socket
from dataclasses import dataclass, field

import pytest


class NetworkBlocked(ConnectionError):
    """Raised for any outbound attempt. An OSError subclass, so code that handles real network
    failures (URLError, OSError) handles the block the same way and never sees a surprise type."""


@dataclass
class NetworkGuard:
    """Records every attempt to reach the network and refuses it."""

    attempts: list[str] = field(default_factory=list)

    def refuse(self, where: str):
        def _blocked(*args, **kwargs):
            self.attempts.append(where)
            raise NetworkBlocked(f"network disabled in tests: {where} called with {args[:2]}")

        return _blocked


LIVE_KEY_NAMES = (
    "BART_API_KEY",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_PROFILE",
    "AGENTCORE_MEMORY_ID",
    "EVAL_MODEL_ID",
)


@pytest.fixture(autouse=True)
def no_live_keys(monkeypatch) -> None:
    """Tests never see a live key, even when the developer's shell has one exported."""
    for name in LIVE_KEY_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_network(monkeypatch) -> NetworkGuard:
    """Block outbound connections and DNS for the duration of each test.

    ``socket.socketpair`` is left alone on purpose: asyncio's event loop uses it for its
    self-pipe, and it never leaves the process.
    """
    guard = NetworkGuard()
    monkeypatch.setattr(socket.socket, "connect", guard.refuse("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", guard.refuse("socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", guard.refuse("socket.create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", guard.refuse("socket.getaddrinfo"))
    return guard
