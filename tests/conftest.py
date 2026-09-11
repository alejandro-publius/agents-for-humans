"""Test configuration. Every test runs with the network blocked; nothing here needs credentials."""

from __future__ import annotations

import socket
from dataclasses import dataclass, field

import pytest


@dataclass
class NetworkGuard:
    """Records every attempt to reach the network and refuses it."""

    attempts: list[str] = field(default_factory=list)

    def refuse(self, where: str):
        def _blocked(*args, **kwargs):
            self.attempts.append(where)
            raise RuntimeError(f"network disabled in tests: {where} called with {args[:2]}")

        return _blocked


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
