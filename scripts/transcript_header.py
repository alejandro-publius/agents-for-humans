"""The two header lines of docs/TOUR-TRANSCRIPT.md (make transcript): what the run read, and whether it counts.

    python scripts/transcript_header.py

On the fixtures the header says so and says nothing here is a result yet; on the real exports it names
the export and says the scripted model still stands in for the live one, so the transcript's counts are
the gates' and never a model's. `make transcript` prints these lines ahead of the tour, so the header
moves with the run instead of staying a fixture label after the laptop's rerun.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.interfaces import claimable, source_label  # noqa: E402


def header() -> list[str]:
    if claimable():
        return [
            f"What `make tour` and `make ablation` print at this commit, on the {source_label()} and the scripted "
            "model.",
            "Run on the real exports (claimable); the scripted model stands in for the live one, so every count "
            "here is the gates' and never a model's.",
        ]
    return [
        "What `make tour` and `make ablation` print at this commit, on the fixture KB and the scripted model.",
        "Fixture run: nothing here is a result until the laptop reruns it on the real KB and policy engine.",
    ]


def main() -> int:
    print("\n".join(header()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
