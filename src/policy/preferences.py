"""Rider preferences that change option ranking, behind one store interface.

``Preferences`` is the object the policy engine reads. The store is local JSON by default and
Amazon Bedrock AgentCore Memory when AWS credentials are present (constructed lazily; never
called without credentials). Both stores expose ``get`` / ``set`` / ``all``.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Protocol

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCAL = REPO_ROOT / "data" / "preferences.json"


@dataclass(frozen=True)
class Preferences:
    avoid_buses: bool = False  # transit options are infeasible for this rider
    never_after_dark: bool = False  # after dark, a Mitigation Trip outranks riding or rolling elsewhere
    needs_larger_elevator: bool = False  # alternate-elevator options infeasible until dimensions are in KB
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Preferences:
        data = data or {}
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def needs(self) -> frozenset[str]:
        """Trip needs implied by the preferences (the policy engine already understands these)."""
        out = {"elevator"}
        if self.avoid_buses:
            out.add("no_bus")
        if self.never_after_dark:
            out.add("no_after_dark")
        if self.needs_larger_elevator:
            out.add("larger_elevator")
        return frozenset(out)


class PreferenceStore(Protocol):
    def get(self, rider_id: str) -> Preferences: ...
    def set(self, rider_id: str, prefs: Preferences) -> None: ...
    def all(self) -> dict[str, Preferences]: ...


@dataclass
class LocalJsonPreferenceStore:
    path: Path = DEFAULT_LOCAL
    _cache: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if self.path.exists():
            self._cache = json.loads(self.path.read_text())

    def get(self, rider_id: str) -> Preferences:
        return Preferences.from_dict(self._cache.get(rider_id))

    def set(self, rider_id: str, prefs: Preferences) -> None:
        self._cache[rider_id] = prefs.as_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._cache, indent=2, sort_keys=True) + "\n")

    def all(self) -> dict[str, Preferences]:
        return {rid: Preferences.from_dict(d) for rid, d in self._cache.items()}


class AgentCoreMemoryPreferenceStore:
    """Preferences in Amazon Bedrock AgentCore Memory. Built only when credentials are present.

    Not exercised tonight: no credentials. The shape follows the AgentCore Memory data plane
    (one memory resource, one record per rider under the ``preferences`` namespace) and must be
    verified against the installed ``bedrock-agentcore`` SDK before first use.
    """

    def __init__(self, memory_id: str, region: str) -> None:
        from bedrock_agentcore.memory import MemoryClient  # type: ignore[import-not-found]

        self.memory_id = memory_id
        self.client = MemoryClient(region_name=region)

    def get(self, rider_id: str) -> Preferences:  # pragma: no cover - needs AWS
        records = self.client.retrieve_memories(
            memory_id=self.memory_id, namespace=f"/preferences/{rider_id}", query="rider preferences"
        )
        for record in records:
            try:
                return Preferences.from_dict(json.loads(record["content"]["text"]))
            except (KeyError, ValueError):
                continue
        return Preferences()

    def set(self, rider_id: str, prefs: Preferences) -> None:  # pragma: no cover - needs AWS
        self.client.create_event(
            memory_id=self.memory_id,
            actor_id=rider_id,
            session_id="preferences",
            messages=[(json.dumps(prefs.as_dict()), "USER")],
        )

    def all(self) -> dict[str, Preferences]:  # pragma: no cover - needs AWS
        raise NotImplementedError("listing riders is not supported by the memory store")


def preference_store(path: Path | None = None) -> PreferenceStore:
    """AgentCore Memory when AWS credentials and AGENTCORE_MEMORY_ID are set; local JSON otherwise."""
    creds = os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_BEARER_TOKEN_BEDROCK")
    memory_id = os.getenv("AGENTCORE_MEMORY_ID")
    if os.getenv("AWS_REGION") and creds and memory_id:
        return AgentCoreMemoryPreferenceStore(memory_id, os.environ["AWS_REGION"])
    return LocalJsonPreferenceStore(path or DEFAULT_LOCAL)
