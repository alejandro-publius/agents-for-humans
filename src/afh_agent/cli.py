"""Command-line entrypoint: `uv run afh "do the thing"` or `uv run afh` for a REPL."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from afh_agent.agent import build_agent


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="afh", description="Run the Agents for Humans agent.")
    parser.add_argument("prompt", nargs="*", help="Task for the agent. Omit for an interactive REPL.")
    parser.add_argument(
        "--session",
        metavar="ID",
        help="Persist conversation state under this id so later runs resume where this one left off.",
    )
    return parser.parse_args(argv)


def run_once(agent, prompt: str) -> str:
    """Run one task to completion and return the agent's final text."""
    result = agent(prompt)
    return str(result)


def repl(agent) -> None:
    print("afh agent ready. Ctrl-D or 'exit' to quit.")
    while True:
        try:
            line = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if line.lower() in {"exit", "quit"}:
            return
        if line:
            print(f"\nagent> {run_once(agent, line)}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    agent = build_agent(session_id=args.session)
    if args.prompt:
        print(run_once(agent, " ".join(args.prompt)))
    else:
        repl(agent)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
