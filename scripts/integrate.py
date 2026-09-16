"""make integrate INTO=~/agents-for-humans: drop this package into the main repo without overwriting anything.

    python scripts/integrate.py --into ~/agents-for-humans            # plan only: copy / identical / CONFLICT, per file
    python scripts/integrate.py --into ~/agents-for-humans --yes      # copy the non-conflicting files, write a report

Rules, so the laptop session can run it without reading it first:
- every tracked file of this package maps to one path in the main repo
  (table in PLACEMENT); nothing else is touched, and `data/` is never read
- an existing file with identical content is skipped; an existing file
  with different content is a CONFLICT and is left alone (the report lists
  it with both paths so the owner merges by hand); nothing is ever deleted
- the Makefile, pyproject.toml, README.md, LICENSE and .gitignore are not
  copied: the report prints what to add (docs/INTEGRATION.md has the text)
- the tests land in tests/dispatch/ with their own conftest.py, so the
  network guard and the key strip apply to them without touching the
  main conftest
"""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (source prefix, destination prefix); the first match wins; a None destination means "not copied, see notes"
PLACEMENT: list[tuple[str, str | None]] = [
    ("le_dispatch/", "le_dispatch/"),
    ("tests/conftest.py", "tests/dispatch/conftest.py"),
    ("tests/", "tests/dispatch/"),
    ("scripts/", "scripts/"),
    ("fixtures/", "fixtures/"),
    ("infra/agentcore/", "infra/agentcore/"),
    ("evals/", "evals/"),
    ("results/policy_agreement.json", None),  # the main file exists; merge rows with write_scores / merge_entries
    ("results/", "results/"),
    ("docs/", "docs/"),
    (".github/workflows/verify.yml", ".github/workflows/dispatch-verify.yml"),
    (".github/workflows/pages.yml", ".github/workflows/dispatch-pages.yml"),
    ("dispatch.mk", "dispatch.mk"),  # every target the package adds; one `-include dispatch.mk` in the main Makefile
    (".devcontainer/", None),  # the main repo decides its own Codespace
    ("Makefile", None),
    ("pyproject.toml", None),
    ("README.md", None),
    ("LICENSE", None),
    (".gitignore", None),
]
NOTES = {
    "results/policy_agreement.json": "not copied: the main file exists; merge rows with write_scores / merge_entries",
    "Makefile": "not copied: add `-include dispatch.mk` at the end of the main Makefile (INTEGRATION.md section 1)",
    "pyproject.toml": "not copied: add the extras cedar and aws, and pytest pythonpath = ['.'] (INTEGRATION.md 1)",
    "README.md": "not copied: merge docs/README-sections.md into the main README (F9 PR text)",
    "LICENSE": "not copied: the main repo has its own MIT license",
    ".devcontainer/": "not copied: the main repo decides its own Codespace (the package's is one file to copy)",
    ".gitignore": "not copied: add data/public/ and fixtures/archive_fixture.sqlite to the main .gitignore",
}


@dataclass
class Move:
    src: Path  # relative to this package
    dst: Path | None  # relative to the main repo
    action: str  # copy | identical | CONFLICT | replace | note
    note: str = ""


SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "data", "build", "dist", "htmlcov"}
SKIP_DIRS |= {".integrate-check", "node_modules"}  # what make integrate-check leaves when a step fails
SKIP_FILES = {"fixtures/archive_fixture.sqlite", ".coverage"}


def package_layout(root: Path = ROOT) -> bool:
    """True when running from the last-elevator-dispatch package itself, not from an integrated repo."""
    return (root / "tests" / "conftest.py").exists() and not (root / "tests" / "dispatch").exists()


def tracked_files() -> list[Path]:
    """git ls-files when the package came with its .git; otherwise every file under the tree except caches,
    virtualenvs, data/ and the generated sqlite fixture."""
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        files = [Path(line) for line in out.splitlines() if line]
        if files:  # plus what is new and not ignored, so a check before the commit sees the whole change
            new = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True
            ).stdout
            files += [Path(line) for line in new.splitlines() if line and Path(line) not in files]
            return [f for f in files if f.as_posix() not in SKIP_FILES and not set(f.parts) & SKIP_DIRS]
    except (OSError, subprocess.CalledProcessError):
        pass
    files = []
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if not p.is_file() or rel.as_posix() in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS or part.startswith(".venv") or part.endswith(".egg-info") for part in rel.parts):
            continue  # what a pip install -e leaves in a tree that came without its .git (a tarball, an archive)
        files.append(rel)
    return files


def destination(rel: Path) -> tuple[Path | None, str]:
    s = rel.as_posix()
    for prefix, dst in PLACEMENT:
        if s == prefix or (prefix.endswith("/") and s.startswith(prefix)):
            if dst is None:
                return None, NOTES.get(s, NOTES.get(prefix, "not copied"))
            if prefix.endswith("/"):
                return Path(dst) / s[len(prefix) :], ""
            return Path(dst), ""
    raise ValueError(f"no placement rule for {s}")


def plan(into: Path, files: list[Path] | None = None, take: set[str] | None = None) -> list[Move]:
    """`take` names package files (as `src` paths) whose conflicting main-repo copy is to be replaced; the
    main file is kept beside it as `<name>.main-repo.bak` so nothing is lost. Everything else that
    conflicts stays untouched and is listed."""
    take = take or set()
    moves: list[Move] = []
    for rel in files if files is not None else tracked_files():
        dst, note = destination(rel)
        if dst is None:
            moves.append(Move(rel, None, "note", note))
            continue
        target = into / dst
        if not target.exists():
            moves.append(Move(rel, dst, "copy"))
        elif filecmp.cmp(ROOT / rel, target, shallow=False):
            moves.append(Move(rel, dst, "identical"))
        elif rel.as_posix() in take:
            moves.append(Move(rel, dst, "replace", "the main copy is kept as .main-repo.bak"))
        else:
            moves.append(Move(rel, dst, "CONFLICT", "exists with different content; merge by hand, or --take it"))
    return moves


def apply(into: Path, moves: list[Move]) -> int:
    copied = 0
    for m in moves:
        if m.action in ("copy", "replace") and m.dst is not None:
            target = into / m.dst
            target.parent.mkdir(parents=True, exist_ok=True)
            if m.action == "replace":
                backup = target.with_name(target.name + ".main-repo.bak")
                if not backup.exists():  # never overwrite an earlier backup either
                    shutil.copy2(target, backup)
            shutil.copy2(ROOT / m.src, target)
            copied += 1
    return copied


def render(into: Path, moves: list[Move]) -> str:
    counts = {k: sum(1 for m in moves if m.action == k) for k in ("copy", "identical", "CONFLICT", "note", "replace")}
    lines = [
        f"integration plan into {into}: {counts['copy']} to copy, {counts['identical']} identical, "
        f"{counts['CONFLICT']} conflicts, {counts['replace']} to replace (--take), {counts['note']} not copied"
    ]
    for m in moves:
        if m.action == "CONFLICT":
            lines.append(f"  CONFLICT  {m.src}  ->  {m.dst}  ({m.note})")
    for m in moves:
        if m.action == "replace":
            lines.append(f"  replace   {m.src}  ->  {m.dst}  ({m.note})")
    for m in moves:
        if m.action == "note":
            lines.append(f"  note      {m.src}: {m.note}")
    for m in moves:
        if m.action == "copy":
            lines.append(f"  copy      {m.src}  ->  {m.dst}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--into", required=True, help="path of the agents-for-humans checkout (never data/)")
    ap.add_argument("--yes", action="store_true", help="copy the non-conflicting files (default: plan only)")
    ap.add_argument(
        "--take",
        action="append",
        default=[],
        metavar="PACKAGE_PATH",
        help="a package file whose conflicting main-repo copy is replaced (the main copy kept as .main-repo.bak); "
        "repeatable, e.g. --take docs/devpost.md --take docs/video-script.md",
    )
    ap.add_argument(
        "--report", default=None, help="write the plan as JSON here (default: <into>/docs/dispatch-integration.json)"
    )
    args = ap.parse_args(argv)
    if not package_layout():
        print(f"run this from the last-elevator-dispatch package ({ROOT} is an integrated repo, not the package)")
        return 3
    into = Path(args.into).expanduser().resolve()
    if not into.is_dir():
        print(f"{into} is not a directory")
        return 2
    moves = plan(into, take=set(args.take))
    print(render(into, moves))
    if not args.yes:
        print("plan only; rerun with --yes to copy the files marked copy or replace (conflicts stay untouched)")
        return 0
    copied = apply(into, moves)
    report = Path(args.report) if args.report else into / "docs" / "dispatch-integration.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "copied": copied,
                "conflicts": [str(m.src) for m in moves if m.action == "CONFLICT"],
                "replaced": [str(m.src) for m in moves if m.action == "replace"],
                "not_copied": {str(m.src): m.note for m in moves if m.action == "note"},
                "moves": [{"src": str(m.src), "dst": str(m.dst) if m.dst else None, "action": m.action} for m in moves],
            },
            indent=2,
        )
        + "\n"
    )
    print(f"copied {copied} files; report at {report}")
    conflicts = [m for m in moves if m.action == "CONFLICT"]
    if conflicts:
        print(f"{len(conflicts)} conflict(s) left for the owner; nothing was overwritten")
    return 0


if __name__ == "__main__":
    sys.exit(main())
