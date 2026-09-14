"""F27: the same scripts and writers run on the real exports; results become claimable only then."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest
from le_dispatch import interfaces
from le_dispatch.interfaces import (
    FIXTURES,
    ROOT,
    claimable,
    data_source,
    load_cases,
    load_kb,
    source_label,
    using_fixtures,
)
from le_dispatch.red_team import run_red_team, write_results


def test_fixtures_are_the_default_and_never_claimable(monkeypatch):
    monkeypatch.delenv(interfaces.KB_EXPORT_ENV, raising=False)
    monkeypatch.delenv(interfaces.CASES_EXPORT_ENV, raising=False)
    assert using_fixtures() and not claimable()
    assert data_source() == {"kb": "fixtures/kb.json", "cases": "fixtures/cases.json", "fixture": True}
    assert source_label() == "fixture KB"
    assert len(load_kb().stations) == 50 and len(load_cases()) == 194


def test_exports_switch_every_loader_and_make_results_claimable(tmp_path, monkeypatch):
    """The laptop sets two environment variables; nothing else changes."""
    kb_export = tmp_path / "kb-labels-v1.json"
    cases_export = tmp_path / "cases-v1.json"
    shutil.copy(FIXTURES / "kb.json", kb_export)
    shutil.copy(FIXTURES / "cases.json", cases_export)
    monkeypatch.setenv(interfaces.KB_EXPORT_ENV, str(kb_export))
    monkeypatch.setenv(interfaces.CASES_EXPORT_ENV, str(cases_export))
    assert not using_fixtures() and claimable()
    assert source_label() == "KB export kb-labels-v1.json"
    assert data_source()["fixture"] is False and data_source()["kb"].endswith("kb-labels-v1.json")
    kb, policy = interfaces.fixture_policy()
    assert len(kb.stations) == 50
    doc = write_results(run_red_team(kb, policy, load_cases(), n_per_attack=1), tmp_path / "rt.json", provenance="x")
    assert doc["provenance"]["claimable"] is True and doc["provenance"]["source"]["fixture"] is False
    assert "real exports" in doc["provenance"]["note"]
    # only one of the two set: still the fixtures for the other, and not claimable
    monkeypatch.delenv(interfaces.CASES_EXPORT_ENV)
    assert not claimable() and data_source()["cases"] == "fixtures/cases.json"


def test_check_docs_flips_its_labels_once_the_red_team_is_claimable(tmp_path):
    """With a claimable red_team.json the docs must drop 'fixture run'; with the fixture one they must keep it."""
    repo = tmp_path / "repo"
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv*", ".integrate-check"))
    ok = subprocess.run([sys.executable, "scripts/check_docs.py"], cwd=repo, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout
    red = repo / "results" / "red_team.json"
    doc = json.loads(red.read_text())
    doc["provenance"]["claimable"] = True
    red.write_text(json.dumps(doc, indent=2) + "\n")
    flipped = subprocess.run([sys.executable, "scripts/check_docs.py"], cwd=repo, capture_output=True, text=True)
    assert flipped.returncode == 1 and "still says 'fixture run'" in flipped.stdout
    import re

    assert flipped.stdout.count("still says 'fixture run'") == 4  # the sections, the devpost, the FAQ, post 2
    for name in (
        "README-sections.md",
        "devpost.md",
        "FAQ.md",
        "posts/02-agents-for-humans-two-stage-gate.md",
        "posts/publish-ready/post-2.md",
    ):
        f = repo / "docs" / name
        text = re.sub(r"fixture\s+run\b", "laptop run", f.read_text())
        f.write_text(re.sub(r"pending\s+the\s+laptop\s+rerun", "rerun done", text))
    updated = subprocess.run([sys.executable, "scripts/check_docs.py"], cwd=repo, capture_output=True, text=True)
    assert updated.returncode == 0, updated.stdout


def test_check_docs_stays_green_once_the_owner_fills_the_devpost_links(tmp_path):
    """Sunday night the owner replaces every TODO in the devpost's Links section with the real URL or ARN;
    make verify (the main repo's CI) must stay green then, and must still refuse a Links field that was
    deleted rather than filled."""
    repo = tmp_path / "repo"
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv*", ".integrate-check"))
    devpost = repo / "docs" / "devpost.md"
    filled = devpost.read_text()
    for old, new in (
        ("- Repo: TODO (public, MIT license)", "- Repo: https://github.com/o/agents-for-humans (public, MIT license)"),
        ("- Video: TODO (under five minutes)", "- Video: https://youtu.be/abc123 (4:35)"),
        ("- Live URL: TODO", "- Live URL: https://last-elevator.example.org"),
        ("- AgentCore runtime ARN: TODO", "- AgentCore runtime ARN: arn:aws:bedrock-agentcore:us-west-2:1:runtime/le"),
        (
            "- Posts: TODO, TODO, TODO",
            "- Posts: https://builder.aws.com/a, https://builder.aws.com/b, https://builder.aws.com/c",
        ),
    ):
        assert old in filled, old
        filled = filled.replace(old, new)
    devpost.write_text(filled)
    ok = subprocess.run([sys.executable, "scripts/check_docs.py"], cwd=repo, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout
    devpost.write_text("\n".join(line for line in filled.splitlines() if not line.startswith("- Video:")) + "\n")
    gone = subprocess.run([sys.executable, "scripts/check_docs.py"], cwd=repo, capture_output=True, text=True)
    assert gone.returncode == 1 and "must keep a '- Video:' line" in gone.stdout


def test_check_docs_lets_the_words_say_a_hundred_once_a_live_row_does(tmp_path):
    """The enforced mode agrees with the policy engine by construction, so the laptop's live row will say
    100 percent; the mock-label rule must step aside then, and only then."""
    repo = tmp_path / "repo"
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv*", ".integrate-check"))
    devpost = repo / "docs" / "devpost.md"
    old = "policy agreement enforced versus no-steering on two models, TODO (live\nrows pending)"
    assert old in devpost.read_text()
    devpost.write_text(devpost.read_text().replace(old, "policy agreement enforced 100 percent on 40 live cases"))
    mock = subprocess.run([sys.executable, "scripts/check_docs.py"], cwd=repo, capture_output=True, text=True)
    assert mock.returncode == 1 and "100 percent figure without the plumbing-proof label" in mock.stdout
    results = repo / "results" / "policy_agreement.json"
    doc = json.loads(results.read_text())
    row = {"provider": "bedrock", "model_id": "m", "mode": "enforced", "cases": 40, "agreement_pct": 100.0}
    doc["entries"].append({**row, "claimable": True})
    results.write_text(json.dumps(doc, indent=2) + "\n")
    live = subprocess.run([sys.executable, "scripts/check_docs.py"], cwd=repo, capture_output=True, text=True)
    assert live.returncode == 0, live.stdout


def test_check_docs_only_dispatch_leaves_the_main_repos_readme_to_its_own_rules(tmp_path):
    """In the main repo the README is the owner's document: --only-dispatch (the flag INTEGRATION.md names for
    the main repo) must not fail on a picture or a count in it, while the full check still does."""
    if not (ROOT / "README.md").exists():
        pytest.skip("the integrated layout has the main repo's README, not the package's")
    repo = tmp_path / "repo"
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv*", ".integrate-check"))
    readme = repo / "README.md"
    readme.write_text(readme.read_text() + "\n![](docs/diagrams/x.png)\n\nThe C block ran 999 runs of its own.\n")
    full = subprocess.run([sys.executable, "scripts/check_docs.py"], cwd=repo, capture_output=True, text=True)
    assert full.returncode == 1 and "no alt text" in full.stdout and "999 runs" in full.stdout
    cmd = [sys.executable, "scripts/check_docs.py", "--only-dispatch"]
    only = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
    assert only.returncode == 0, only.stdout


def test_preflight_reports_the_environment_without_calling_anything(tmp_path, monkeypatch, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("preflight", ROOT / "scripts" / "preflight.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["preflight"] = module
    spec.loader.exec_module(module)

    monkeypatch.delenv(interfaces.KB_EXPORT_ENV, raising=False)
    monkeypatch.delenv(interfaces.CASES_EXPORT_ENV, raising=False)
    rows, code = module.run([], regenerate=False)
    statuses = {what: status for status, what, _ in rows}
    assert code == 0 and statuses["fixtures in use (exports not set)"] == "warn"
    assert statuses["no AWS credentials in the environment or the shared credentials file"] == "warn"
    assert any(what.startswith("strands-agents 1.55.1") and status == "ok" for status, what, _ in rows)

    monkeypatch.setenv(interfaces.KB_EXPORT_ENV, str(FIXTURES / "kb.json"))
    rows, code = module.run([], regenerate=False)
    assert code == 1 and any(status == "FAIL" and "only one" in what for status, what, _ in rows)

    kb_export, cases_export = tmp_path / "kb-labels-v1.json", tmp_path / "cases-v1.json"
    shutil.copy(FIXTURES / "kb.json", kb_export)
    shutil.copy(FIXTURES / "cases.json", cases_export)
    monkeypatch.setenv(interfaces.KB_EXPORT_ENV, str(kb_export))
    monkeypatch.setenv(interfaces.CASES_EXPORT_ENV, str(cases_export))
    assert module.main(["--quick"]) == 0
    out = capsys.readouterr().out
    assert "exports: 50 stations, 97 elevators, 194 cases" in out and "claimable=True" in out
    assert "preflight: ok" in out


def test_credentials_present_sees_the_environment_and_the_shared_file_but_never_a_laptops_keys(tmp_path, monkeypatch):
    """The laptop keeps its keys in ~/.aws/credentials; the apply paths must see them (else --yes would be
    a dry run forever), and the tests must never see them (the conftest points the file variable away)."""
    from le_dispatch.interfaces import credentials_present

    assert credentials_present() is False  # the conftest stripped every variable and pointed the file away
    monkeypatch.setenv("AWS_PROFILE", "laptop")
    assert credentials_present() is True
    monkeypatch.delenv("AWS_PROFILE")
    shared = tmp_path / "credentials"
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(shared))
    assert credentials_present() is False
    shared.write_text("[default]\naws_access_key_id = not-a-real-key\n")
    assert credentials_present() is True
    for module in ("le_dispatch.eval_live", "le_dispatch.agentcore_eval", "le_dispatch.agentcore_policy"):
        import importlib

        assert importlib.import_module(module).credentials_present() is True  # one implementation


def test_check_docs_refuses_an_image_without_alt_text(tmp_path):
    """A picture with no words is a picture a screen reader skips; the docs check names it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_docs_alt", ROOT / "scripts" / "check_docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    good = tmp_path / "good.md"
    good.write_text("![One poll for one rider](diagrams/architecture-poll.png)\n")
    bad = tmp_path / "bad.md"
    bad.write_text("![](x.png)\n![x.png](x.png)\n![ok words here](y.png)\n")
    problems: list[str] = []
    module.check_image_alt_text(problems, [good])
    assert problems == []
    module.check_image_alt_text(problems, [bad])
    assert len(problems) == 2 and all("no alt text" in p for p in problems)


def test_check_docs_refuses_a_stale_claim_count_and_a_stale_badge(tmp_path):
    """'checks N claims', 'N claims checked' and 'N `Claim` rows' must be the package's count; so must the badge."""
    import importlib.util

    from le_dispatch.claims import CLAIMS

    spec = importlib.util.spec_from_file_location("check_docs_counts", ROOT / "scripts" / "check_docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    good = tmp_path / "good.md"
    n = len(CLAIMS)
    good.write_text(f"`make verify` checks {n} claims; {n} claims checked against results; holds {n} `Claim` rows\n")
    bad = tmp_path / "bad.md"
    bad.write_text(f"`make verify` checks {n - 5} claims and 3 claims checked twice; holds 43 `Claim` rows\n")
    problems: list[str] = []
    module.check_claim_count_phrases(problems, [good])
    assert problems == []
    module.check_claim_count_phrases(problems, [bad])
    assert len(problems) == 3 and all(f"the package has {n}" in p for p in problems)
    problems = []
    module.check_badge(problems)  # the committed badge is current
    assert problems == []


def test_check_docs_keeps_every_voice_line_under_twelve_words(tmp_path):
    """The video script's VO lines are one breath each; a long one is named with its count."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_docs_vo", ROOT / "scripts" / "check_docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    problems: list[str] = []
    module.check_voice_lines(problems)  # the shipped script
    assert problems == []
    script = tmp_path / "script.md"
    script.write_text("VO: Models propose. Code decides.\nVO: " + " ".join(["word"] * 12) + "\nnot a VO line at all\n")
    module.check_voice_lines(problems, script)
    assert len(problems) == 1 and "12 words" in problems[0]


def test_check_docs_keeps_every_post_under_nine_hundred_words_and_the_publish_copies_in_step():
    """Each builder.aws post body is under 900 words, and its publish-ready copy carries the same body."""
    posts = sorted((ROOT / "docs" / "posts").glob("*.md"))
    assert len(posts) == 3
    for p in posts:
        title, _, body = p.read_text().split("\n", 2)
        assert len(body.split()) < 900, p.name
        ready = ROOT / "docs" / "posts" / "publish-ready" / f"post-{p.name[1]}.md"
        assert body.strip() in ready.read_text(), p.name
        assert f"Words: {len(body.strip().split())}" in ready.read_text(), p.name


def test_check_docs_lets_the_owner_fill_the_links_on_a_posts_last_line(tmp_path):
    """The publish-ready copy's last line takes the repo and video URLs on Sunday night; filling them must
    not break the parity rule, and a changed body still must."""
    repo = tmp_path / "repo"
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv*", ".integrate-check"))
    ready = repo / "docs" / "posts" / "publish-ready" / "post-1.md"
    assert "Repo: TODO. Video: TODO." in ready.read_text()
    ready.write_text(
        ready.read_text().replace("Repo: TODO. Video: TODO.", "Repo: https://x.test/r. Video: https://x.test/v.")
    )
    filled = subprocess.run([sys.executable, "scripts/check_docs.py"], cwd=repo, capture_output=True, text=True)
    assert filled.returncode == 0, filled.stdout
    ready.write_text(ready.read_text().replace("A BART rider who depends on", "A rider who depends on"))
    changed = subprocess.run([sys.executable, "scripts/check_docs.py"], cwd=repo, capture_output=True, text=True)
    assert changed.returncode == 1 and "post-1.md does not carry this body" in changed.stdout


def test_check_docs_pins_every_run_count_on_the_first_page_to_results(tmp_path):
    """'N runs', 'N times', 'N invocations' on the first page must be counts a results file carries."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_docs_runs", ROOT / "scripts" / "check_docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    problems: list[str] = []
    module.check_run_counts(problems)  # the shipped first page
    assert problems == []
    doc = tmp_path / "page.md"
    doc.write_text("attacked 2716 times; 140 adversarial runs; 1940 invocations; and 3000 runs nobody measured\n")
    module.check_run_counts(problems, [doc], allowed={2716, 140, 1940})
    assert len(problems) == 1 and "3000 runs" in problems[0]


def test_check_docs_refuses_a_make_variable_no_target_reads(tmp_path):
    """`make report REPORT_ARGS=...` in a document must name a variable dispatch.mk assigns."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_docs_vars", ROOT / "scripts" / "check_docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    problems: list[str] = []
    good = tmp_path / "good.md"
    good.write_text('run `make report REPORT_ARGS="--archive x"` and `make impact IMPACT_ARGS=--archive`\n')
    bad = tmp_path / "bad.md"
    bad.write_text("run `make report ARCHIVE=x --query-file y`\n")
    module.check_make_variables([good], problems)
    assert problems == []
    module.check_make_variables([bad], problems)
    assert len(problems) == 1 and "ARCHIVE=" in problems[0]


def test_a_fixture_run_never_overwrites_a_results_file_a_real_run_wrote(tmp_path, capsys):
    """Every results writer goes through write_results_json: once the laptop's real run (claimable) is
    committed, a rerun on the fixtures (a target typed without the exports, or CI without them) writes
    nothing and says so; a real run always writes; a file without provenance is always written."""
    from le_dispatch.interfaces import write_results_json, written_by_a_real_run

    out = tmp_path / "results" / "x.json"
    assert written_by_a_real_run(out) is False  # missing
    assert write_results_json(out, {"provenance": {"claimable": False}, "n": 1}) is True
    assert write_results_json(out, {"provenance": {"claimable": True}, "n": 2}) is True
    assert written_by_a_real_run(out) is True
    assert write_results_json(out, {"provenance": {"claimable": False}, "n": 3}) is False
    assert json.loads(out.read_text())["n"] == 2 and "left" in capsys.readouterr().out
    assert write_results_json(out, {"provenance": {"claimable": True}, "n": 4}) is True
    plain = tmp_path / "plain.json"
    assert write_results_json(plain, {"n": 1}) is True and write_results_json(plain, {"n": 2}) is True


def test_the_transcript_header_follows_the_run(tmp_path, monkeypatch, capsys):
    """docs/TOUR-TRANSCRIPT.md opens with what the run read: the fixture label on the fixtures, the export's
    name and the stand-in note on the real exports, so the label does not outlive the laptop's rerun."""
    import importlib.util

    from le_dispatch import interfaces

    spec = importlib.util.spec_from_file_location("transcript_header", ROOT / "scripts" / "transcript_header.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = module.header()
    assert fixture[0].endswith("on the fixture KB and the scripted model.") and fixture[1].startswith("Fixture run:")
    for name in ("kb.json", "cases.json"):
        (tmp_path / name).write_text((interfaces.FIXTURES / name).read_text())
    monkeypatch.setenv(interfaces.KB_EXPORT_ENV, str(tmp_path / "kb.json"))
    monkeypatch.setenv(interfaces.CASES_EXPORT_ENV, str(tmp_path / "cases.json"))
    real = module.header()
    assert "KB export kb.json" in real[0] and real[1].startswith("Run on the real exports (claimable)")
    assert module.main() == 0 and capsys.readouterr().out.strip().splitlines() == real
