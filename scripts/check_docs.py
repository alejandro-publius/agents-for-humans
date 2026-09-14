"""make check-docs: the submission text keeps its promises.

- the three post drafts have "Agents for Humans" in their titles
- the Devpost text keeps every link field (TODO until the laptop fills it; a filled value passes)
- no document claims the product satisfies a settlement or the ADA
- the Strands benchmark sentence appears at most once per document
- the mock 100 percent number is never presented without "plumbing" or "mock"
  (until a claimable live row in results/policy_agreement.json says 100, which
  the enforced mode does by construction)
- every fixture-run number quoted in the docs matches results/ and is
  labelled as fixture, synthetic or pending; once results/red_team.json is
  claimable (produced from the real exports) the fixture labels must go
- every package path a document names exists, every test a document
  names exists, and the "Strands surface used" table names only real
  Strands symbols (each one imports)
- the test count the README states is the number pytest collects
- every `make <target>` a document names is a Makefile target
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from le_dispatch.claims import CLAIMS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
RESULTS = ROOT / "results"

# the documents this package ships (docs/ names); --only-dispatch restricts the checks to them
SHIPPED_DOCS = (
    "ARCHITECTURE.md",
    "EVIDENCE.md",
    "FAQ.md",
    "HUMAN-CHECKLIST.md",
    "INTEGRATION.md",
    "ONBOARDING-AN-AGENCY.md",
    "README-sections.md",
    "RUNBOOK-dispatch.md",
    "SUBMISSION-CHECKLIST.md",
    "SUNDAY.md",
    "THREAT-MODEL.md",
    "TOUR-TRANSCRIPT.md",
    "UPSTREAM-NOTE.md",
    "architecture-additions.md",
    "devpost.md",
    "narrative.md",
    "video-script.md",
    "diagrams",
    "evidence",
    "posts",
    "reports",
    "screenshots",
    "video",
)
POST_WORDS = 900
LABELLED_DOCS = (
    DOCS / "README-sections.md",
    DOCS / "devpost.md",
    DOCS / "FAQ.md",
    DOCS / "posts" / "02-agents-for-humans-two-stage-gate.md",
)
# the Links section of the Devpost text keeps these fields; each holds TODO until the laptop fills it, and a
# filled value (a URL, an ARN, "in the form") passes too, so make verify stays green while the owner fills them
REQUIRED_LINK_FIELDS = [
    "Repo:",
    "Video:",
    "Live URL:",
    "Evidence site:",
    "AgentCore runtime ARN:",
    "Builder ID",
    "Posts:",
]
# paths under these prefixes belong to the dispatch package, so a document naming one must name a real file
PATH_RE = re.compile(r"`((?:le_dispatch|infra/agentcore|evals)/[A-Za-z0-9_./-]+)`")
# where the Strands symbols the "Strands surface used" table may name import from
STRANDS_MODULES = (
    "strands",
    "strands.hooks",
    "strands.session",
    "strands.models.model",
    "strands.models.bedrock",
    "strands.agent.agent_result",
    "strands.vended_plugins.steering.core.handler",
    "strands.vended_plugins.steering.core.action",
)
# lower-case prefixes in the table stand for these Strands classes
ALIASES = {"event": "BeforeToolCallEvent", "result": "AgentResult", "agent": "Agent"}
# names the table may use that are not Python symbols here or in Strands (span names, payload keys, AgentCore)
NOT_PYTHON = {"execute_tool", "gen_ai.tool.message", "interruptResponse", "sessionSpans", "BedrockAgentCoreApp"}
NOT_PYTHON.add("stream")


def _strands_symbol(name: str) -> object | None:
    import importlib

    for module in STRANDS_MODULES:
        obj = getattr(importlib.import_module(module), name, None)
        if obj is not None:
            return obj
    return None


def _has_attr(owner: object, attr: str) -> bool:
    import inspect

    names = set(dir(owner)) | set(getattr(owner, "__annotations__", {}))
    names |= set(getattr(owner, "__dataclass_fields__", {}))
    if attr in names:
        return True
    init = getattr(owner, "__init__", None)
    return init is not None and attr in inspect.signature(init).parameters


def check_paths_and_symbols(docs: list[Path], problems: list[str]) -> None:
    """Every package path a document names exists; every symbol in the Strands table is real."""
    import inspect

    for p in docs:
        for rel in sorted(set(PATH_RE.findall(p.read_text()))):
            if not (ROOT / rel).exists():
                fail(f"{p.relative_to(ROOT)}: names {rel}, which does not exist", problems)
    readme = (DOCS / "README-sections.md").read_text()
    table = readme.split("**Strands surface used.**", 1)[1].split("**The numbers", 1)[0]
    rows = [row.strip().strip("|").split("|") for row in table.splitlines() if row.strip().startswith("|")]
    rows = [r for r in rows if len(r) == 3 and not set(r[0].strip()) <= set("-: ")][1:]  # drop the header row
    sources = [f.read_text() for f in (ROOT / "le_dispatch").rglob("*.py")]

    def ours(name: str) -> bool:
        return any(re.search(rf"^\s*(class|def|async def) {name}\b", src, re.M) for src in sources)

    for _guarantee, surface, where in rows:
        for token in re.findall(r"`([^`]+)`", surface):
            if token in NOT_PYTHON:
                continue
            call = re.fullmatch(r"(\w+)\((\w+)=\w+\)", token)  # Agent(structured_output_model=Plan)
            dotted = re.fullmatch(r"(\w+)\.(\w+)", token)
            if call:
                owner = _strands_symbol(call.group(1))
                if owner is None or call.group(2) not in inspect.signature(owner.__init__).parameters:
                    fail(f"README-sections.md: the Strands table names {token}, missing in Strands", problems)
            elif dotted:
                cls = ALIASES.get(dotted.group(1), dotted.group(1))
                owner = _strands_symbol(cls)
                if owner is None or not _has_attr(owner, dotted.group(2)):
                    fail(f"README-sections.md: the Strands table names {token}, which {cls} does not have", problems)
            elif re.fullmatch(r"\w+", token) and not ours(token) and _strands_symbol(token) is None:
                fail(f"README-sections.md: the Strands table names {token}, not in Strands or le_dispatch/", problems)
        for rel in re.findall(r"`((?:le_dispatch|infra)/[A-Za-z0-9_./-]+)`", where):
            if not (ROOT / rel).exists():
                fail(f"README-sections.md: the Strands table names {rel}, which does not exist", problems)
        for name in re.findall(r"`(\w+)`", where):
            if not ours(name):
                fail(f"README-sections.md: the Strands table names {name}, not defined in le_dispatch/", problems)


CLAIM_PATTERN = re.compile(r"(satisf\w*|compl(?:y|ies|iant)|meets?|fulfil\w*)\s+(the\s+|any\s+)?(settlement|ADA)", re.I)
ALLOWED_CONTEXT = ("not satisfy", "never state", "never say", "does not claim", "do not claim", "not claim")


def fail(msg: str, problems: list[str]) -> None:
    problems.append(msg)


def collected_tests() -> int | None:
    """How many tests pytest collects (parametrized cases included); None if pytest is unavailable."""
    import subprocess
    import sys

    try:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    counts = re.findall(r"^tests/\S+: (\d+)$", out, re.M)
    return sum(int(c) for c in counts) if counts else None


def make_targets() -> set[str] | None:
    """The targets of the Makefile here plus dispatch.mk (the file the main repo includes); None when
    neither file is here. Without a Makefile (the integrated copy in CI), the main repo's own targets
    (INTEGRATION.md section 1) are taken as given."""
    files = [p for p in (ROOT / "Makefile", ROOT / "dispatch.mk") if p.exists()]
    if not files:
        return None
    targets = {t for p in files for t in re.findall(r"^([a-z][a-z0-9-]*):", p.read_text(), re.M)}
    if not (ROOT / "Makefile").exists():
        targets |= NOT_LISTED_IN_GUIDE
    return targets


def check_make_targets(docs: list[Path], problems: list[str]) -> None:
    """Every `make <target>` a document (or the README) names is a target of the Makefile or dispatch.mk."""
    targets = make_targets()
    if targets is None:
        return
    for p in [*docs, ROOT / "README.md"]:
        if not p.exists():
            continue
        for target in sorted(set(re.findall(r"`make ([a-z][a-z0-9-]*)", p.read_text()))):
            if target not in targets:
                fail(
                    f"{p.relative_to(ROOT)} names `make {target}`, which is not a target of the Makefile or "
                    "dispatch.mk (in the main repo: `-include dispatch.mk`, docs/INTEGRATION.md section 1)",
                    problems,
                )


# the main Makefile's own targets, which the package Makefile keeps (INTEGRATION.md section 1); all else is dispatch.mk
NOT_LISTED_IN_GUIDE = {
    "help",
    "install",
    "test",
    "lint",
    "typecheck",
    "check-docs",
    "secret-scan",
    "fixtures",
    "verify",
    "verify-claims",
    "demo-one",
    "integrate",
    "integrate-check",
}


MAKE_VAR_RE = re.compile(r"`make [a-z][a-z0-9-]*((?: [A-Z_]+=)+)")


def check_make_variables(docs: list[Path], problems: list[str]) -> None:
    """Every variable a document passes to make (`make report REPORT_ARGS=...`) is one the Makefile or
    dispatch.mk assigns, so a documented flag is one a target reads."""
    files = [p for p in (ROOT / "Makefile", ROOT / "dispatch.mk") if p.exists()]
    if not files:
        return
    assigned = {v for p in files for v in re.findall(r"^([A-Z_]+)\s*[?:]?=", p.read_text(), re.M)}
    if not (ROOT / "Makefile").exists():  # the integrated copy: `make integrate` and its variables stay in the package
        assigned |= {"INTO", "INTEGRATE_ARGS"}
    for p in [*docs, ROOT / "README.md"]:
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text().splitlines(), 1):
            for group in MAKE_VAR_RE.findall(line):
                for var in re.findall(r"([A-Z_]+)=", group):
                    if var not in assigned:
                        rel = p.relative_to(ROOT) if str(p).startswith(str(ROOT)) else p
                        fail(f"{rel}:{i}: passes {var}= to make, which no target in dispatch.mk reads", problems)


def check_guide_lists_every_target(problems: list[str]) -> None:
    """Every target the main repo needs is in dispatch.mk (the file make integrate copies and one include line
    picks up), and the package Makefile keeps only the main repo's own; INTEGRATION.md section 1 says so."""
    makefile = ROOT / "Makefile"
    guide = DOCS / "INTEGRATION.md"
    if not makefile.exists() or not guide.exists() or (ROOT / "tests" / "dispatch").exists():
        return
    own = set(re.findall(r"^([a-z][a-z0-9-]*):", makefile.read_text(), re.M))
    for target in sorted(own - NOT_LISTED_IN_GUIDE - {"help"}):
        fail(f"Makefile defines {target}; a target the main repo needs belongs in dispatch.mk", problems)
    if "-include dispatch.mk" not in guide.read_text():
        fail("docs/INTEGRATION.md section 1 must tell the owner to add `-include dispatch.mk`", problems)


IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def check_image_alt_text(problems: list[str], files: list[Path] | None = None) -> None:
    """Every image in the README and the shipped documents has alt text a screen reader can say: a project
    for riders who depend on elevators does not ship a picture with no words."""
    files = files if files is not None else [ROOT / "README.md"] + sorted(DOCS.rglob("*.md"))
    for path in files:
        if not path.exists():  # the integrated layout: the README is the main repo's, or not there
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            for alt, target in IMAGE_RE.findall(line):
                if len(alt.strip()) < 4 or alt.strip().lower().endswith((".png", ".svg", ".jpg")):
                    rel = path.relative_to(ROOT) if str(path).startswith(str(ROOT)) else path
                    fail(f"{rel}:{i}: image {target} has no alt text a screen reader can say", problems)


def check_badge(problems: list[str]) -> None:
    """The committed claims badge says N/N for the N claims the package has; a stale badge is a stale number
    on the README's first screen and in screenshot 07."""
    path = RESULTS / "badges" / "claims.json"
    if not path.exists():
        return
    message = json.loads(path.read_text()).get("message", "")
    if message != f"{len(CLAIMS)}/{len(CLAIMS)}":
        fail(f"results/badges/claims.json says {message}; the package has {len(CLAIMS)} claims (make badge)", problems)


CLAIM_COUNT_RE = re.compile(r"\b(?:checks (\d+) claims|(\d+) claims checked|(\d+) `Claim` rows)\b")


def check_claim_count_phrases(problems: list[str], files: list[Path] | None = None) -> None:
    """Every 'checks N claims', 'N claims checked' or 'N `Claim` rows' in the README or a shipped document is
    the number of claims the package has; the count moves with every results file, and the words with it."""
    files = files if files is not None else [ROOT / "README.md"] + sorted(DOCS.rglob("*.md"))
    for path in files:
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            for a, b, c in CLAIM_COUNT_RE.findall(line):
                n = int(a or b or c)
                if n != len(CLAIMS):
                    rel = path.relative_to(ROOT) if str(path).startswith(str(ROOT)) else path
                    fail(f"{rel}:{i}: says {n} claims; the package has {len(CLAIMS)}", problems)


RUN_COUNT_RE = re.compile(r"\b(\d{3,5}) (?:exhaustive |adversarial |persona-case )?(?:runs|times|invocations)\b")
FIRST_PAGE = ("README.md", "docs/README-sections.md", "docs/devpost.md", "docs/FAQ.md", "docs/video-script.md")


def check_run_counts(problems: list[str], files: list[Path] | None = None, allowed: set[int] | None = None) -> None:
    """Every 'N runs', 'N times' or 'N invocations' on the first page (the README, the sections the owner
    merges, the devpost, the FAQ, the script, the posts) is a count a results file carries, so a rerun
    that changes a count names every sentence that still says the old one."""
    if allowed is None:
        allowed = set()
        for name, keys in (
            ("red_team.json", ("runs",)),
            ("red_team_exhaustive.json", ("runs",)),
            ("adaptive_convergence.json", ("runs",)),
            ("wire_convergence.json", ("runs",)),
            ("runtime_sweep.json", ("invocations", "model_runs", "cases")),
            ("runtime_sweep_synthetic.json", ("invocations", "model_runs", "cases")),
        ):
            path = RESULTS / name
            if path.exists():
                doc = json.loads(path.read_text())
                allowed |= {doc[k] for k in keys if isinstance(doc.get(k), int)}
    if files is None:
        files = [ROOT / f for f in FIRST_PAGE] + sorted((DOCS / "posts").glob("*.md"))
    for path in files:
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            for n in RUN_COUNT_RE.findall(line):
                if int(n) not in allowed:
                    rel = path.relative_to(ROOT) if str(path).startswith(str(ROOT)) else path
                    fail(f"{rel}:{i}: a count of {n} runs that no results file carries (stale, or typed)", problems)


def check_voice_lines(problems: list[str], script: Path | None = None) -> None:
    """Every voice line in the video script (a line starting with 'VO:') is under twelve words: one breath,
    one fact, readable at pace and short enough for a caption."""
    script = script if script is not None else DOCS / "video-script.md"
    if not script.exists():
        return
    for i, line in enumerate(script.read_text().splitlines(), 1):
        if line.startswith("VO:") and len(line[3:].split()) >= 12:
            rel = script.relative_to(ROOT) if str(script).startswith(str(ROOT)) else script
            fail(f"{rel}:{i}: a voice line of {len(line[3:].split())} words; keep every VO line under twelve", problems)


def check_coverage_phrase(problems: list[str]) -> None:
    """The README quotes the coverage percent from results/coverage.json, never a stale one."""
    path = RESULTS / "coverage.json"
    if not path.exists():
        return
    percent = json.loads(path.read_text())["percent"]
    readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
    if "percent of the package's lines" in readme and f"{percent} percent of the package's lines" not in readme:
        fail(f"README.md: the coverage figure is not the one in results/coverage.json ({percent} percent)", problems)


def check_test_count(problems: list[str]) -> None:
    """The README's "N offline tests" must be the number pytest collects."""
    readme = ROOT / "README.md"
    if not readme.exists():
        return
    stated = {int(n) for n in re.findall(r"\b(\d+) offline tests\b", readme.read_text())}
    if not stated:
        return
    actual = collected_tests()
    if actual is None:
        return
    for n in sorted(stated):
        if n != actual:
            fail(f"README.md says {n} offline tests; pytest collects {actual}", problems)


def live_agreement_is_a_hundred() -> bool:
    """True once results/policy_agreement.json carries a claimable live row at 100 percent agreement: the
    enforced mode agrees with the policy engine by construction, so the laptop's live run will say 100, and
    the words may then say it too. Until then a 100 percent figure is the mock's and must carry its label."""
    path = RESULTS / "policy_agreement.json"
    if not path.exists():
        return False
    data = json.loads(path.read_text())
    entries = data["entries"] if isinstance(data, dict) and "entries" in data else data
    return any(
        e.get("claimable") is True and e.get("provider") not in ("mock", "stand-in") and e.get("agreement_pct") == 100
        for e in entries
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--only-dispatch",
        action="store_true",
        help="check only the documents this package ships (for the main repo, whose own README and docs have their "
        "own rules; the sentences the owner merges into its README are checked at their source, README-sections)",
    )
    args = ap.parse_args(argv)
    problems: list[str] = []
    docs = sorted(p for p in DOCS.rglob("*.md"))
    if args.only_dispatch:
        shipped = set(SHIPPED_DOCS)
        docs = [p for p in docs if p.relative_to(DOCS).as_posix() in shipped or p.relative_to(DOCS).parts[0] in shipped]

    posts = sorted((DOCS / "posts").glob("*.md"))
    if len(posts) != 3:
        fail(f"expected 3 post drafts, found {len(posts)}", problems)
    for p in posts:
        title = p.read_text().splitlines()[0]
        if not title.startswith("# ") or "Agents for Humans" not in title:
            fail(f"{p.name}: title must start with '# ' and contain 'Agents for Humans'", problems)
        words = len(p.read_text().split()) - len(title.split())
        if words >= POST_WORDS:  # a builder.aws post a judge reads to the end
            fail(f"{p.name}: {words} words; keep every post under {POST_WORDS}", problems)
        ready = DOCS / "posts" / "publish-ready" / f"post-{p.name[1]}.md"
        # the last line holds the repo and video links, TODO until the owner fills them in either copy
        body = re.sub(r"\n+Repo: .*\Z", "", p.read_text().split("\n", 2)[2].strip())
        if ready.exists() and body not in ready.read_text():
            fail(f"{p.name}: docs/posts/publish-ready/{ready.name} does not carry this body", problems)

    devpost = (DOCS / "devpost.md").read_text()
    for field in REQUIRED_LINK_FIELDS:
        match = re.search(rf"^- {re.escape(field)}\s*(\S.*)?$", devpost, re.M)
        if match is None:
            fail(f"devpost.md: the Links section must keep a '- {field}' line (TODO until filled)", problems)
        elif not (match.group(1) or "").strip():
            fail(f"devpost.md: '- {field}' has no value; TODO until the laptop fills it", problems)

    live_hundred = live_agreement_is_a_hundred()
    for p in docs:
        text = p.read_text()
        for i, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if CLAIM_PATTERN.search(line) and not any(a in low for a in ALLOWED_CONTEXT):
                fail(f"{p.relative_to(ROOT)}:{i}: reads like a settlement or ADA compliance claim", problems)
            hundred = re.search(r"\b100(\.0)?\s*(%|percent)", line)
            if hundred and not live_hundred and not any(w in low for w in ("plumbing", "mock", "with it")):
                fail(f"{p.relative_to(ROOT)}:{i}: a 100 percent figure without the plumbing-proof label", problems)
        if text.count("82.5") > 1:
            fail(f"{p.relative_to(ROOT)}: the Strands benchmark sentence appears more than once", problems)

    red = json.loads((RESULTS / "red_team.json").read_text())
    quiet = json.loads((RESULTS / "quiet.json").read_text())
    ds = json.loads((RESULTS / "agentcore_dataset.json").read_text())
    conv = json.loads((RESULTS / "adaptive_convergence.json").read_text())
    week = json.loads((RESULTS / "outage_week.json").read_text())
    reached = red["reached_rider"]
    expected_phrases = {
        f"{week['outages']} elevator outages at {week['stations']} stations": (
            DOCS / "README-sections.md",
            DOCS / "devpost.md",
        ),
        f"{red['runs']} adversarial runs": (DOCS / "README-sections.md", DOCS / "devpost.md"),
        quiet["opening_line"]: (DOCS / "README-sections.md", DOCS / "devpost.md", DOCS / "video-script.md"),
        f"{ds['scenarios']}-case": (DOCS / "README-sections.md", DOCS / "devpost.md"),
        f"plus {len(CLAIMS)} in the dispatch package": (DOCS / "README-sections.md", DOCS / "devpost.md"),
        f"all {conv['runs']} persona-case runs within {conv['max_calls']} model calls": (
            DOCS / "README-sections.md",
            DOCS / "devpost.md",
        ),
    }

    def flat(path: Path) -> str:
        return " ".join(path.read_text().split())

    for phrase, files in expected_phrases.items():
        for f in files:
            if phrase not in flat(f):
                fail(f"{f.relative_to(ROOT)}: expected the results-derived phrase {phrase!r}", problems)
    zeros = f"{reached['hallucinated_stations']}, {reached['wrong_options']}, {reached['minutes_not_from_policy']}"
    red_claimable = bool(red.get("provenance", {}).get("claimable"))
    for f in (DOCS / "README-sections.md", DOCS / "devpost.md"):
        text = flat(f)
        if zeros not in text:
            fail(f"{f.relative_to(ROOT)}: red-team counts {zeros!r} not quoted from results", problems)
        if "synthetic" not in text:  # the quiet week stays synthetic until the archive replay
            fail(f"{f.relative_to(ROOT)}: synthetic-week numbers must be labelled ('synthetic' missing)", problems)
    # every document that cites the red team's numbers carries the label until the real exports are run, and
    # drops it then: the sections the owner merges, the devpost, the FAQ (the judge's five minutes) and post 2
    for f in LABELLED_DOCS:
        text = flat(f)
        labelled = re.search(r"fixture run\b", text) is not None  # "fixture runs" describes the mechanism
        if not red_claimable and not labelled:
            fail(f"{f.relative_to(ROOT)}: fixture-run numbers must be labelled ('fixture run' missing)", problems)
        if red_claimable and (labelled or "pending the laptop rerun" in text):
            fail(
                f"{f.relative_to(ROOT)}: results/red_team.json is claimable (real exports) but the text still says "
                "'fixture run' or 'pending the laptop rerun'; update the labels",
                problems,
            )

    # every test named in any document (the evidence matrix, the threat model, the notes) exists
    tests_dir = ROOT / "tests"
    test_names = set()
    for f in tests_dir.rglob("test_*.py"):  # tests/ here, tests/dispatch/ in the main repo
        test_names.update(re.findall(r"^def (test_\w+)\(", f.read_text(), re.M))
    for p in docs:
        for name in sorted(set(re.findall(r"`(test_\w+)`", p.read_text()))):
            if name not in test_names:
                fail(f"{p.relative_to(ROOT)} names {name}, which does not exist in tests/", problems)
    for packet in ("DELN-E1-daytime", "DELN-E1-after-dark-yes", "DELN-E1-after-dark-no"):
        if not (DOCS / "evidence" / f"{packet}.md").exists():
            fail(f"docs/evidence/{packet}.md missing; run make evidence", problems)

    check_paths_and_symbols(docs, problems)
    check_make_targets(docs, problems)
    check_make_variables(docs, problems)
    check_test_count(problems)
    check_coverage_phrase(problems)
    check_badge(problems)
    # the README is the main repo's own document in the integrated layout; --only-dispatch leaves it to the
    # main repo's rules, and the sentences the owner merges into it are checked at their source, README-sections
    readme = [] if args.only_dispatch else [ROOT / "README.md"]
    first_page = [ROOT / f for f in FIRST_PAGE if not (args.only_dispatch and f == "README.md")]
    check_claim_count_phrases(problems, readme + docs)
    check_voice_lines(problems)
    check_run_counts(problems, first_page + posts)
    check_image_alt_text(problems, readme + docs)
    check_guide_lists_every_target(problems)

    if problems:
        print("check-docs: FAILED")
        print("\n".join(f"  - {p}" for p in problems))
        return 1
    print(f"check-docs: ok ({len(docs)} documents, {len(posts)} posts, {len(CLAIMS)} claims referenced)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
