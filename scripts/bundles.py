"""make bundles: the package as git bundles the laptop applies with a fetch, keeping every commit hash.

The package is a standalone repository; the main repo (`agents-for-humans`, branch `overnight`) is private
and unreachable from the dispatch session, so the bundles carry this repository's history, in dependency
order: one base bundle (everything through F53) and one bundle per item after it. Applied in INDEX order
with `git fetch <bundle> <branch>:refs/dispatch/<branch>`, each bundle's prerequisite is the previous
bundle's tip, and the last ref is this repository's `main`. The files then land in the main repo through
`make integrate` (which never overwrites and never deletes; docs/INTEGRATION.md), from a tree archived out
of that ref, so the history is in the main repo's object store and the working tree changes come through
the one path that knows the two layouts.

    python scripts/bundles.py                 # build/bundles/*.bundle, one note per bundle, INDEX.md
    python scripts/bundles.py --check         # also: a throwaway repo takes every bundle in INDEX order,
                                              # the archived tree runs make verify, the integrated tree
                                              # runs the dispatch tests, check-docs and verify-claims

Nothing here touches the main repo; the throwaway lives under build/.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "bundles"
MAIN_REPO = "~/agents-for-humans"


@dataclass(frozen=True)
class Item:
    name: str  # the bundle and branch name (dispatch/<name>)
    tip: str  # the last commit of the item
    base: str | None  # the previous item's tip; None for the base bundle
    what: str
    acceptance: str  # the command whose observed output the note carries


ITEMS: list[Item] = [
    Item(
        "base-f1-f53",
        "c131f08",
        None,
        "everything through F53 (the gates, the studies, the wire, AgentCore Runtime, Policy, Evaluations, Memory, "
        "the runtime demo) plus the two post-F53 commits (the Memory store follows pages; post 02 carries all four "
        "SDK findings)",
        "make verify | tail -1",
    ),
    Item(
        "f54",
        "fb7c541",
        "c131f08",
        "a question never blocks (the morning poll supersedes an unanswered night question and sends the plan) and "
        "an answer never fails (a double tap, a changed mind, an answer to a question never asked here: a plain "
        "state, never an error)",
        "python3 -m pytest tests/test_runtime.py -q | tail -1",
    ),
    Item(
        "f55",
        "8c7b0bf",
        "fb7c541",
        "one retry layer on the live path, priced: every live client on le_dispatch/live.py (botocore's own retries "
        "off), Strands' strategy bounded to four attempts; the fifth SDK finding",
        "python3 scripts/preflight.py --quick | grep 'retry layer'",
    ),
    Item(
        "f56",
        "cc624d9",
        "8c7b0bf",
        "the durable copy is best effort, the delivery is not: ResilientMemoryClient, idempotency tokens on every "
        "write, the memory field on every runtime response",
        "python3 -m pytest tests/test_agentcore_memory.py -q | tail -1",
    ),
    Item(
        "f57",
        "d42c81d",
        "cc624d9",
        "a hung stream priced on the wire: one request, not retried, code composes; the tenth wire scenario",
        "python3 scripts/bedrock_wire.py | grep '^hung'",
    ),
    Item(
        "f58",
        "d35dcc5",
        "d42c81d",
        "make runtime-sweep: every case through the runtime entrypoint with three riders each, 194 of 194 on every "
        "count; the service models cached once per process",
        "python3 scripts/runtime_sweep.py --cases 3 --out /tmp/le-sweep-check.json | sed -n 1p",
    ),
    Item(
        "f59",
        "e86fcbe",
        "d35dcc5",
        "a decision belongs to its outage: forgotten in every copy when the elevator is back, the next outage asked "
        "afresh",
        "python3 -m pytest tests/test_runtime.py -q -k belongs_to_its_outage | tail -1",
    ),
    Item(
        "f60",
        "e7f6a48",
        "e86fcbe",
        "the conversation belongs to its outage: the quiet poll deletes the trip's session, the next outage starts "
        "clean",
        "python3 -m pytest tests/test_runtime.py -q -k conversation_belongs | tail -1",
    ),
    Item(
        "f61",
        "f457e7b",
        "e7f6a48",
        "the package as git bundles (this script): the chain in dependency order, one note per bundle, INDEX.md, "
        "and the throwaway check that applies the chain and runs make verify",
        "python3 scripts/bundles.py --out /tmp/le-bundles-check | tail -1",
    ),
    Item(
        "f62",
        "f18a52d",
        "f457e7b",
        "the commands behind the video (make video-assets): the exact command per on-screen moment with the lines "
        "to freeze on and the observed output, docs/video/trace.png and docs/video/eval_table.png",
        "python3 -m pytest tests/test_video_assets.py -q | tail -1",
    ),
    Item(
        "f63",
        "e2c7e39",
        "f18a52d",
        "the numbered submission screenshots that need no laptop (make screenshots), the devpost referring to them "
        "by number, the claims badge regenerated",
        "python3 -m pytest tests/test_screenshots.py -q | tail -1",
    ),
    Item(
        "f64",
        "fcf92d5",
        "e2c7e39",
        "the cold start replayed (make cold-start): the bundles into an empty repository, a fresh venv, the README's "
        "setup block as written, the transcript in docs/reports/cold-start.md; the two trips it found, fixed",
        "python3 -m pytest tests/test_cold_start.py -q | tail -1",
    ),
    Item(
        "f65",
        "9c5544a",
        "fcf92d5",
        "the video's first shot in plain lines (make demo-one-brief), the rubric self-score with the top five gaps, "
        "the two-pollers threat named",
        "python3 scripts/demo_one.py --brief | tail -1",
    ),
    Item(
        "f66",
        "2813e1f",
        "9c5544a",
        "the evidence as a static site a judge can open (make site), a Pages workflow",
        "python3 -m pytest tests/test_site.py -q | tail -1",
    ),
    Item(
        "f67",
        "31cbb69",
        "2813e1f",
        "the hand-off written down: FINAL-INTEGRATION.md next to the bundles, the human checklist with times, the "
        "Devpost fields sheet, the publish-ready posts, the field survey",
        "python3 scripts/check_docs.py | tail -1",
    ),
    Item(
        "f68",
        "29739d9",
        "31cbb69",
        "what riders faced, from the feed (make impact): the outage archive summarised, five claims, the paragraph "
        "in the devpost checked against the file",
        "python3 scripts/impact.py | sed -n 1p",
    ),
    Item(
        "f69",
        "fdc0d01",
        "29739d9",
        "the hosted contract on a judge's laptop (make serve): the runtime app module on the stand-in, a curl line "
        "per state, no key",
        "python3 -m pytest tests/test_runtime.py -q -k stand_in | tail -1",
    ),
    Item(
        "f70",
        "514706a",
        "fdc0d01",
        "the rider's own words: RiderNote, a fixed vocabulary the model may only point at, applied by code as "
        "feasibility; the runtime's note field, the demo and the video beat",
        "python3 -m pytest tests/test_note.py -q | tail -1",
    ),
    Item(
        "f71",
        "bdaac8a",
        "514706a",
        "the first screen checked: the brief opens the tour, demo-live reads the note, alt text on every shipped "
        "image is a check-docs rule",
        "python3 scripts/check_docs.py | tail -1",
    ),
    Item(
        "f72",
        "a851cc4",
        "bdaac8a",
        "the package's tests where the main repo puts them: make integrate-check green in the integrated layout, "
        "pipefail on every masked pipe in the checks",
        "make integrate-check | tail -1",
    ),
    Item(
        "f73",
        "2fab937",
        "a851cc4",
        "the main repo's CI, green before the merge: make integrate-ci runs the placed workflow in the integrated "
        "layout and writes docs/reports/integrated-ci.md; the stale badge caught by a rule; bundles, cold-start and "
        "integrate-check pass without the package history",
        "python3 -m pytest tests/test_integrated_ci.py tests/test_bundles.py tests/test_cold_start.py -q | tail -1",
    ),
    Item(
        "f74",
        "7c8440b",
        "2fab937",
        "the evidence site a screen reader and a keyboard can use: make site-a11y (axe-core over every page, zero "
        "violations as a claim), the two findings fixed; a stale badge and a stale claim count as docs rules",
        "python3 -m pytest tests/test_site_a11y.py tests/test_site.py -q | tail -1",
    ),
    Item(
        "f75",
        "0805a57",
        "7c8440b",
        "the first paragraph (README, sections, devpost) and the voice-over as lines under twelve words, with a "
        "check-docs rule",
        "python3 scripts/check_docs.py | tail -1",
    ),
    Item(
        "f76",
        "f540989",
        "0805a57",
        "post 2 under 900 words; every post under 900 and the publish-ready copies in step, as check-docs rules",
        "python3 -m pytest tests/test_exports.py -q | tail -1",
    ),
    Item(
        "f77",
        "ad263e9",
        "f540989",
        "docs/FAQ.md (the judge's questions, each answer pointing at its proof), the note curl line on make serve, "
        "the checklist wording",
        "python3 -m pytest tests/test_runtime.py -q -k stand_in | tail -1",
    ),
    Item(
        "f78",
        "f70d1e6",
        "ad263e9",
        "dispatch.mk: every package target in one file the main Makefile includes with one line; the note property "
        "test over every case",
        "python3 -m pytest tests/test_integrate.py tests/test_note.py -q | tail -1",
    ),
    Item(
        "f79",
        "2131042",
        "f70d1e6",
        "make first-shot: the brief as a GIF and a still under the README's first paragraph and on the site's "
        "front page",
        "python3 -m pytest tests/test_screenshots.py tests/test_site.py -q | tail -1",
    ),
    Item(
        "f80",
        "795ff78",
        "2131042",
        "the README in the judge's order: the five-minute path and the setup before the index",
        "python3 scripts/check_docs.py | tail -1",
    ),
    Item(
        "f81",
        "47968e3",
        "795ff78",
        "a Codespace that opens on make verify; the self-score revised; the site's first-shot lines wrap",
        "python3 -m pytest tests/test_cold_start.py -q | tail -1",
    ),
    Item(
        "f82",
        "8f18ff2",
        "47968e3",
        "every run count on the first page pinned to results, as a check-docs rule",
        "python3 -m pytest tests/test_exports.py -q | tail -1",
    ),
    Item(
        "f83",
        "267fe61",
        "8f18ff2",
        "make judge said a minute and takes two, fixed everywhere; the still for reduced motion on the site",
        "python3 -m pytest tests/test_site.py -q | tail -1",
    ),
    Item(
        "f84",
        "b3407fc",
        "267fe61",
        "the archive replay wired into make report (--archive, --riders, --tz), rehearsed as the twenty-fifth step",
        "python3 scripts/quiet_report.py --archive fixtures/archive_fixture.sqlite --out /tmp/le-q.json | sed -n 1p",
    ),
    Item(
        "f85",
        "bcc1a05",
        "b3407fc",
        "a make variable a document passes must be one a target reads (check-docs rule); make tour timed and said "
        "plainly",
        "python3 -m pytest tests/test_exports.py -q | tail -1",
    ),
    Item(
        "f86",
        "2f128c6",
        "bcc1a05",
        "the merge sections carry the first shot and the judge's five minutes; the README merge an explicit laptop "
        "step; ruff and mypy bounded",
        "python3 -m pytest tests/test_site.py -q | tail -1",
    ),
    Item(
        "f87",
        "2f08a2a",
        "2f128c6",
        "the midday integrated CI run: a stale coverage file caught and regenerated, the transcript green; the form "
        "sheet and What's next current",
        "python3 -m pytest tests/test_integrated_ci.py -q | tail -1",
    ),
    Item(
        "f88",
        "70ea7d4",
        "2f08a2a",
        "make integrate --take: a named conflict replaced with the package's version, the main copy kept as "
        ".main-repo.bak",
        "python3 -m pytest tests/test_integrate.py -q | tail -1",
    ),
    Item(
        "f89",
        "365b03c",
        "70ea7d4",
        "the hostile note through the whole hosted contract, counted in the runtime sweep: orders change nothing "
        "194/194, a real constraint removes one option and no more 194/194; two claims",
        "python3 -m pytest tests/test_runtime_sweep.py -q | tail -1",
    ),
    Item(
        "f90",
        "6b1134c",
        "365b03c",
        "the note run as a fourth evidence packet with its diagram, on the site; the note row in the Strands tables",
        "python3 -m pytest tests/test_evidence.py -q | tail -1",
    ),
    Item(
        "f91",
        "651b6d0",
        "6b1134c",
        "docs/video/storyboard.md: the script's sections with every voice line and the screen moments under their "
        "time, generated with the video assets",
        "python3 -m pytest tests/test_video_assets.py -q | tail -1",
    ),
    Item(
        "f92",
        "c6908ef",
        "651b6d0",
        "the note in the architecture diagram; the blocked items for day-1.md; the 10:00 integrated CI transcript "
        "green",
        "python3 -m pytest tests/test_integrated_ci.py -q | tail -1",
    ),
    Item(
        "f93",
        "e82814f",
        "c6908ef",
        "the quiet report names its week and riders; the FAQ's try-to-break-it section; What we learned closes with "
        "the note; the index wording",
        "python3 scripts/quiet_report.py --out /tmp/le-q-syn.json | sed -n 5p",
    ),
    Item(
        "f94",
        "4520bdb",
        "e82814f",
        "make runtime-sweep-synthetic: the second agency's 48 cases through the same entrypoint, every counter 48/48, "
        "four claims",
        "python3 -m pytest tests/test_runtime_sweep.py -q | tail -1",
    ),
    Item(
        "f95",
        "305ba0d",
        "4520bdb",
        "the secret scan's git-less walk skips virtualenvs and caches (a downloaded zip with a venv inside failed "
        "it); verify green on 3.13 from the archive; the second agency on the first screen",
        "python3 -m pytest tests/test_secret_scan.py -q | tail -1",
    ),
    Item(
        "f96",
        "ebc2e50",
        "305ba0d",
        "the secret scan's git-listed path skips compiled files and cache folders (the merge-day CI copy listed a "
        ".pyc with the folded example key); the note is read by an agent with no session; the rider's own words in "
        "post 1 and the note packet in post 3; a 59-character tagline; the 13:00 integrated CI transcript green",
        "python3 -m pytest tests/test_secret_scan.py tests/test_note.py -q | tail -1",
    ),
    Item(
        "f97",
        "696a739",
        "ebc2e50",
        "make verify stays green while the owner fills Sunday night's words: the Devpost link fields may be filled, a "
        "claimable live 100 percent row lifts the mock label, a post's filled links line is not a body change, "
        "--only-dispatch leaves the main README to its own rules, the label flip covers the FAQ and post 2, an "
        "off-slice wire convergence run lands beside the pinned file; the guide's claims section",
        "python3 -m pytest tests/test_exports.py -q | tail -1",
    ),
    Item(
        "f98",
        "2f24083",
        "696a739",
        "the main repo's CI after the real results land: the workflow reads the committed exports, the tests always "
        "read the fixtures, a fixture run never overwrites a results file a real run wrote (every writer), POLICY in "
        "the main Makefile; the 14:56 integrated CI transcript green",
        "python3 -m pytest tests/test_impact.py tests/test_quiet.py -q | tail -1",
    ),
    Item(
        "f99",
        "e29b2e1",
        "2f24083",
        "the tour transcript's header follows the run (the fixture label would have outlived the laptop's rerun on "
        "the Tour page); the 16:58 integrated CI transcript",
        "python3 scripts/transcript_header.py | sed -n 1p",
    ),
    Item(
        "f100",
        "ae060fa",
        "e29b2e1",
        "documents only, after the code stop: judge two to three minutes as measured, the rehearsal about seven, the "
        "owner's evening checklist in durations with the order kept",
        "python3 scripts/check_docs.py | tail -1",
    ),
    Item(
        "f101",
        "f98396a",
        "ae060fa",
        "documents only: the merge-day lesson in What we learned, post 3 and the FAQ; the compressed "
        "Monday-morning order in SUNDAY.md and the checklist; the corrected laptop work order",
        "python3 scripts/check_docs.py | tail -1",
    ),
    Item(
        "f102",
        "main",  # the open item: whatever main is when the bundles are built
        "f98396a",
        "the first paragraph leads with the work the rider is stuck doing, corrected against the code and shipped "
        "in all three places; the session's audit in docs/reports/AUDIT.md",
        "python3 scripts/check_docs.py | tail -1",
    ),
]


def git(*args: str, cwd: Path = ROOT, check: bool = True) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and out.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed in {cwd}:\n{out.stderr}")
    return out.stdout.strip()


def full(commit: str) -> str:
    return git("rev-parse", "--verify", f"{commit}^{{commit}}")


def branch_name(item: Item) -> str:
    return f"dispatch/{item.name}"


def build(out: Path) -> list[tuple[Item, Path]]:
    out.mkdir(parents=True, exist_ok=True)
    built: list[tuple[Item, Path]] = []
    for item in ITEMS:
        if item.base is not None and full(item.tip) == full(item.base):
            continue  # the open item with nothing after the previous tip yet: no bundle
        branch = branch_name(item)
        git("branch", "-f", branch, full(item.tip))  # the item's branch at its tip, so the bundle carries a ref
        path = out / f"dispatch-{item.name}.bundle"
        rev = branch if item.base is None else f"{full(item.base)}..{branch}"
        git("bundle", "create", str(path), rev)
        git("bundle", "verify", str(path), check=False)  # the base bundle verifies anywhere; the rest need the chain
        built.append((item, path))
    return built


def last_item() -> Item:
    """The last item with commits (the open item counts only once main has moved past the previous tip)."""
    built = [i for i in ITEMS if i.base is None or full(i.tip) != full(i.base)]
    return built[-1]


def commits_of(item: Item) -> list[str]:
    rev = full(item.tip) if item.base is None else f"{full(item.base)}..{full(item.tip)}"
    lines = git("log", "--format=%h %s", "--reverse", rev).splitlines()
    return lines[-40:] if item.base is None else lines


def note(item: Item, path: Path, acceptance_output: str, verified: str, pr_dir: Path | None = None) -> str:
    branch = branch_name(item)
    ref = f"refs/dispatch/{item.name}"
    fetch = f"git -C {MAIN_REPO} fetch {path.name} {branch}:{ref}"
    lines = [
        f"# Bundle dispatch-{item.name}",
        "",
        f"Branch: `{branch}` (tip `{full(item.tip)[:12]}`"
        + (f", on top of `{full(item.base)[:12]}`)" if item.base else ", from the root)"),
        f"State: {verified}",
        "",
        "## What it is",
        "",
        item.what + ".",
        "",
        "## Commits",
        "",
    ]
    commits = commits_of(item)
    if item.base is None:
        lines.append(
            f"The base carries the whole history through F53 ({git('rev-list', '--count', full(item.tip))} "
            "commits); the last forty:"
        )
        lines.append("")
    lines += [f"- `{c}`" for c in commits]
    lines += [
        "",
        "## Apply on the laptop",
        "",
        "Run from the directory that holds the bundles, after every earlier bundle in INDEX.md:",
        "",
        "```",
        fetch,
        "```",
        "",
        "The fetch brings the commits into the main repo's object store with their hashes and leaves the working",
        "tree alone. The last bundle in the index is followed by the integration (see INDEX.md): the tree is",
        f"archived out of `refs/dispatch/{last_item().name}` and `make integrate` drops it into the main repo "
        "without overwriting anything.",
        "",
        "## Acceptance",
        "",
        "```",
        f"$ {item.acceptance}",
        acceptance_output.rstrip(),
        "```",
        "",
        "## PR description",
        "",
    ]
    pr = pr_text(item, pr_dir)
    if pr:
        lines += [pr.rstrip(), ""]
    else:
        lines += [
            f"The text is in `dispatch-{item.name}-PR.md` next to the tarball of the same name"
            + (
                " (the base bundle: one text per item, `dispatch-f1-PR.md` to `dispatch-f53-PR.md`)."
                if item.base is None
                else "."
            ),
            "",
        ]
    return "\n".join(lines)


def pr_text(item: Item, pr_dir: Path | None) -> str | None:
    """The PR description written with the item's tarball, when the directory that holds them is given."""
    if pr_dir is None or item.base is None:
        return None
    path = pr_dir / f"dispatch-{item.name}-PR.md"
    return path.read_text() if path.exists() else None


def index(out: Path, states: dict[str, str], check_summary: str, items: list[Item]) -> str:
    last = items[-1]
    lines = [
        "# Bundle index (apply in this order)",
        "",
        "The dispatch package is a standalone repository (`last-elevator-dispatch`); `overnight` in",
        "`agents-for-humans` is private and unreachable from the dispatch session, so each bundle carries this",
        "repository's history rather than commits on top of `overnight`. The order below is the dependency",
        "order: every bundle's prerequisite is the tip of the one above it, and the last ref is the package's",
        "`main`. Nothing here depends on a later entry.",
        "",
        "| # | Bundle | Branch | Tip | What | State |",
        "|---|---|---|---|---|---|",
    ]
    for i, item in enumerate(items, 1):
        lines.append(
            f"| {i} | `dispatch-{item.name}.bundle` | `{branch_name(item)}` | `{full(item.tip)[:12]}` | "
            f"{item.what.split(':')[0].split(' (')[0]} | {states[item.name]} |"
        )
    lines += [
        "",
        "## Apply, in order",
        "",
        "From the directory that holds the bundles (the laptop's copy of this session's Outputs):",
        "",
        "```",
    ]
    for item in items:
        lines.append(
            f"git -C {MAIN_REPO} fetch dispatch-{item.name}.bundle {branch_name(item)}:refs/dispatch/{item.name}"
        )
    lines += [
        "```",
        "",
        "Every fetch keeps the commit hashes and touches no working file. Then the integration, once, from the",
        "last ref (`make integrate` never overwrites and never deletes; a differing file is a CONFLICT line for",
        'the owner, or INTEGRATE_ARGS="--yes --take <package path>" for a document the package has taken further;',
        "docs/INTEGRATION.md has the one `-include dispatch.mk` line, the extras and the .gitignore lines to add by",
        "hand):",
        "",
        "```",
        "rm -rf /tmp/le-dispatch && mkdir -p /tmp/le-dispatch",
        f"git -C {MAIN_REPO} archive refs/dispatch/{last.name} | tar -x -C /tmp/le-dispatch",
        f"make -C /tmp/le-dispatch integrate INTO={MAIN_REPO}                  # plan: copy / identical / CONFLICT",
        f"make -C /tmp/le-dispatch integrate INTO={MAIN_REPO} INTEGRATE_ARGS=--yes  # copies the non-conflicting files",
        f"git -C {MAIN_REPO} checkout -b dispatch/f-block overnight && git -C {MAIN_REPO} add -A",
        f'git -C {MAIN_REPO} commit -m "feat(dispatch): Block F, integrated from refs/dispatch/{last.name}"',
        f"make -C {MAIN_REPO} verify",
        "```",
        "",
        "## Verified in a throwaway repo",
        "",
        check_summary,
        "",
    ]
    return "\n".join(lines)


def run(cmd: str, cwd: Path, timeout: int = 1800) -> tuple[int, str]:
    """A shell line with pipefail, so `... | tail -1` keeps the failing command's exit code."""
    out = subprocess.run(
        ["bash", "-o", "pipefail", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout
    )
    return out.returncode, (out.stdout + out.stderr)


def check(out: Path, built: list[tuple[Item, Path]]) -> tuple[dict[str, str], str, dict[str, str]]:
    """A throwaway repo takes every bundle in order; the archived tree of the last ref runs make verify; the
    integrated tree runs the dispatch tests, check-docs and verify-claims (what make integrate-check does)."""
    throwaway = out / "throwaway"
    shutil.rmtree(throwaway, ignore_errors=True)
    main_repo = throwaway / "main-repo"
    main_repo.mkdir(parents=True)
    git("init", "-q", cwd=main_repo)
    states: dict[str, str] = {}
    acceptance: dict[str, str] = {}
    for item, path in built:
        git("fetch", "-q", str(path), f"{branch_name(item)}:refs/dispatch/{item.name}", cwd=main_repo)
        got = git("rev-parse", f"refs/dispatch/{item.name}", cwd=main_repo)
        assert got == full(item.tip), (item.name, got)
        states[item.name] = f"verified: applies on the previous, tip `{got[:12]}`"
    last = built[-1][0]
    tree = throwaway / "le-dispatch"
    tree.mkdir()
    archive = subprocess.run(
        ["git", "archive", f"refs/dispatch/{last.name}"], cwd=main_repo, capture_output=True, check=True
    )
    subprocess.run(["tar", "-x", "-C", str(tree)], input=archive.stdout, check=True)
    code, text = run("make verify", tree)
    verify_line = text.strip().splitlines()[-1] if text.strip() else ""
    if code != 0:
        raise SystemExit(f"make verify failed in the archived tree:\n{text[-3000:]}")
    for item, _ in built:  # every item's acceptance command, on the archived tree at the last ref
        c, t = run(item.acceptance, tree, timeout=900)
        acceptance[item.name] = t.strip() if c == 0 else f"exit {c}\n{t.strip()[-800:]}"
    (main_repo / "results").mkdir()
    shutil.copy(tree / "results" / "policy_agreement.json", main_repo / "results" / "policy_agreement.json")
    code, text = run(f"python3 scripts/integrate.py --into {main_repo} --yes | tail -1", tree)
    if code != 0:
        raise SystemExit(f"integrate failed:\n{text[-2000:]}")
    integrate_line = text.strip().splitlines()[-1]
    code, text = run(
        "PYTHONPATH=. python3 -m pytest tests/dispatch -q -p no:cacheprovider | tail -1 "
        "&& python3 scripts/check_docs.py | tail -1 "
        "&& python3 scripts/verify_claims.py | tail -1",
        main_repo,
    )
    if code != 0:
        raise SystemExit(f"the integrated tree failed:\n{text[-3000:]}")
    integrated_lines = text.strip().splitlines()[-3:]
    summary = "\n".join(
        [
            f"- an empty repository took the {len(built)} bundles in index order; `refs/dispatch/{last.name}` is "
            f"`{full(last.tip)[:12]}`, the package's `main`",
            f"- the tree archived from that ref: `make verify` printed `{verify_line}`",
            f"- `make integrate` into the throwaway: `{integrate_line}`",
            "- the integrated tree (tests/dispatch, check-docs, verify-claims): "
            + "; ".join(f"`{line}`" for line in integrated_lines),
        ]
    )
    shutil.rmtree(throwaway, ignore_errors=True)
    return states, summary, acceptance


def history_here() -> str | None:
    """Why the bundles cannot be built from this checkout, or None: the chain starts at the base commit, which
    only the dispatch package's own history has (the main repo takes the package by bundle, not by history)."""
    if (ROOT / "tests" / "dispatch").exists():
        return "this is the integrated layout (tests/dispatch/); the bundles are built in the package"
    base = ITEMS[0].tip
    probe = subprocess.run(["git", "rev-parse", "--verify", "-q", f"{base}^{{commit}}"], cwd=ROOT, capture_output=True)
    if probe.returncode != 0:
        return f"the base commit {base} is not in this repository's history; the bundles are built in the package"
    main = subprocess.run(["git", "rev-parse", "--verify", "-q", "main^{commit}"], cwd=ROOT, capture_output=True)
    if main.returncode != 0:
        return "no main branch here (the refs came in by bundle); the bundles are built in the package"
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--check", action="store_true", help="apply the chain in a throwaway repo and verify")
    ap.add_argument("--pr-dir", default=None, help="the directory holding dispatch-<item>-PR.md, embedded in the notes")
    args = ap.parse_args(argv)
    why = history_here()
    if why:
        print(f"bundles: nothing to build here: {why}")
        return 0
    out = Path(args.out)
    pr_dir = Path(args.pr_dir) if args.pr_dir else None
    built = build(out)
    states = {item.name: "built" for item, _ in built}
    summary = "Not run (`python scripts/bundles.py --check`)."
    acceptance = {item.name: "(run with --check)" for item, _ in built}
    if args.check:
        states, summary, acceptance = check(out, built)
    for item, path in built:
        (out / f"dispatch-{item.name}.md").write_text(
            note(item, path, acceptance[item.name], states[item.name], pr_dir)
        )
    (out / "INDEX.md").write_text(index(out, states, summary, [item for item, _ in built]))
    final = ROOT / "docs" / "reports" / "FINAL-INTEGRATION.md"
    if final.exists():  # the laptop's end-to-end sequence travels with the bundles
        shutil.copy(final, out / "FINAL-INTEGRATION.md")
    for item, path in built:
        print(f"{path.name:<32} {states[item.name]}")
    print(f"wrote {out / 'INDEX.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
