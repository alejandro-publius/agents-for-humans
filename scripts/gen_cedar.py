"""make agentcore-policy-gen: derive Cedar policies from the KB export."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.cedar_gen import POLICY_DIR, TOOLS_PATH, generate, load_tools, write_policies  # noqa: E402
from le_dispatch.interfaces import load_kb  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", default=None, help="KB export JSON (LE_KB_EXPORT, else the fixture)")
    ap.add_argument("--tools", default=str(TOOLS_PATH))
    ap.add_argument("--out", default=str(POLICY_DIR))
    args = ap.parse_args(argv)
    kb = load_kb(args.kb)
    target, tools = load_tools(args.tools)
    files = generate(kb, target, tools)
    manifest = write_policies(files, kb, target, tools, Path(args.out))
    for name, text in files.items():
        print(f"wrote {Path(args.out) / name} ({len(text)} chars)")
    print(
        f"manifest: {manifest['stations']} stations, {manifest['elevators']} elevators, "
        f"{len(manifest['option_labels'])} labels, tools {manifest['tools']}, kb tag {manifest['kb_frozen_tag']!r}"
    )
    print(f"schema: {manifest['schema']}; local validation: {manifest['local_validation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
