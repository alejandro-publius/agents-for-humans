"""Load KEY=value lines from a dotenv-style file into the environment, never overriding what is set.

Used only when a command is given an explicit ``--env-file``; tests never pass one, so no test can
read a live key by accident. Values are not logged.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path, names: tuple[str, ...] | None = None) -> list[str]:
    """Set variables from ``path``. Returns the names that were set (not their values)."""
    if not path.exists():
        return []
    loaded: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if names is not None and key not in names:
            continue
        if value and not os.getenv(key):
            os.environ[key] = value
            loaded.append(key)
    return loaded
