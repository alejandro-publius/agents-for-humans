"""F22: the integration script never overwrites, never deletes, never reads data/."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from le_dispatch.interfaces import ROOT  # the repo root in either layout (tests/ or tests/dispatch/)


def _load():
    spec = importlib.util.spec_from_file_location("integrate", ROOT / "scripts" / "integrate.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["integrate"] = module  # dataclasses resolve string annotations through sys.modules
    spec.loader.exec_module(module)
    if not module.package_layout():
        pytest.skip("the integration script runs from the package layout only (this is an integrated repo)")
    return module


def test_integrated_repo_is_refused(tmp_path, capsys):
    """From an integrated repo the script refuses to run rather than copy files onto themselves."""
    spec = importlib.util.spec_from_file_location("integrate", ROOT / "scripts" / "integrate.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["integrate"] = module
    spec.loader.exec_module(module)
    fake = tmp_path / "integrated"
    (fake / "tests" / "dispatch").mkdir(parents=True)
    (fake / "tests" / "conftest.py").write_text("")
    assert module.package_layout(fake) is False
    if not module.package_layout():
        assert module.main(["--into", str(tmp_path)]) == 3
        assert "integrated repo" in capsys.readouterr().out


def test_every_tracked_file_has_exactly_one_destination():
    integrate = _load()
    files = integrate.tracked_files()
    assert len(files) > 100
    seen: dict[Path, Path] = {}
    for rel in files:
        dst, note = integrate.destination(rel)
        if dst is None:
            assert note.startswith("not copied"), rel
            continue
        assert dst not in seen, f"{rel} and {seen[dst]} both land on {dst}"
        seen[dst] = rel
        assert not str(dst).startswith("data/"), rel
    assert integrate.destination(Path("tests/conftest.py"))[0] == Path("tests/dispatch/conftest.py")
    assert integrate.destination(Path("tests/test_gates.py"))[0] == Path("tests/dispatch/test_gates.py")
    assert integrate.destination(Path("results/policy_agreement.json"))[0] is None
    assert integrate.destination(Path("dispatch.mk"))[0] == Path("dispatch.mk")  # one include line in the main Makefile
    assert "dispatch.mk" in integrate.destination(Path("Makefile"))[1]
    assert integrate.destination(Path(".github/workflows/verify.yml"))[0] == Path(
        ".github/workflows/dispatch-verify.yml"
    )


def test_a_tree_without_git_is_walked_without_what_the_checks_leave(tmp_path, monkeypatch):
    """An archived tree (git archive, a tarball) has no .git: the walk must skip what make verify, pip
    install -e and a failed make integrate-check leave behind, or integrate refuses its own leftovers."""
    integrate = _load()
    tree = tmp_path / "tree"
    keep = tree / "le_dispatch" / "x.py"
    keep.parent.mkdir(parents=True)
    keep.write_text("")
    for rel in (
        ".integrate-check/results/policy_agreement.json",
        "build/bundles/x.bundle",
        "le_dispatch.egg-info/PKG-INFO",
        ".venv/lib/site.py",
        ".mypy_cache/x",
        ".ruff_cache/x",
        "__pycache__/x.pyc",
    ):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_text("")
    monkeypatch.setattr(integrate, "ROOT", tree)
    assert integrate.tracked_files() == [Path("le_dispatch/x.py")]


def test_plan_and_apply_never_overwrite_or_delete(tmp_path):
    integrate = _load()
    main = tmp_path / "agents-for-humans"
    (main / "scripts").mkdir(parents=True)
    (main / "results").mkdir()
    (main / "data" / "archive").mkdir(parents=True)
    (main / "data" / "archive" / "outages.sqlite").write_bytes(b"do not touch")
    (main / "scripts" / "verify_claims.py").write_text("# the main repo's own claims table\n")  # conflict
    (main / "results" / "policy_agreement.json").write_text('{"entries": []}\n')  # never copied
    identical = main / "le_dispatch" / "budget.py"
    identical.parent.mkdir(parents=True)
    identical.write_bytes((ROOT / "le_dispatch" / "budget.py").read_bytes())  # identical: skipped

    moves = integrate.plan(main)
    by_src = {str(m.src): m for m in moves}
    assert by_src["scripts/dispatch/verify_claims.py"].action == "CONFLICT"
    assert by_src["le_dispatch/budget.py"].action == "identical"
    assert by_src["results/policy_agreement.json"].action == "note"
    assert by_src["Makefile"].action == "note" and by_src["README.md"].action == "note"
    assert by_src["le_dispatch/gates.py"].action == "copy"
    text = integrate.render(main, moves)
    assert "CONFLICT  scripts/dispatch/verify_claims.py" in text and "1 conflicts" in text

    copied = integrate.apply(main, moves)
    assert copied == sum(1 for m in moves if m.action == "copy")
    assert (main / "scripts" / "verify_claims.py").read_text() == "# the main repo's own claims table\n"
    assert (main / "results" / "policy_agreement.json").read_text() == '{"entries": []}\n'
    assert (main / "data" / "archive" / "outages.sqlite").read_bytes() == b"do not touch"
    assert (main / "tests" / "dispatch" / "conftest.py").exists()
    assert (main / "tests" / "dispatch" / "test_gates.py").exists()
    assert (main / ".github" / "workflows" / "dispatch-verify.yml").exists()
    assert not (main / "Makefile").exists() and not (main / "README.md").exists()
    # a second plan is all identical or conflict or note: nothing left to copy
    again = integrate.plan(main)
    assert all(m.action in ("identical", "CONFLICT", "note") for m in again)

    # --take replaces one named conflict and keeps the main copy beside it; nothing else changes
    taken = integrate.plan(main, take={"scripts/dispatch/verify_claims.py"})
    by_src = {str(m.src): m for m in taken}
    assert by_src["scripts/dispatch/verify_claims.py"].action == "replace"
    assert "replace   scripts/dispatch/verify_claims.py" in integrate.render(
        main, taken
    ) and "1 to replace" in integrate.render(main, taken)
    assert integrate.apply(main, taken) == 1
    assert (main / "scripts" / "verify_claims.py").read_bytes() == (
        ROOT / "scripts" / "dispatch" / "verify_claims.py"
    ).read_bytes()
    backup = main / "scripts" / "verify_claims.py.main-repo.bak"
    assert backup.read_text() == "# the main repo's own claims table\n"
    integrate.apply(main, integrate.plan(main, take={"scripts/dispatch/verify_claims.py"}))  # again: the backup stands
    assert backup.read_text() == "# the main repo's own claims table\n"


def test_cli_plan_is_dry_by_default_and_yes_writes_a_report(tmp_path, capsys):
    integrate = _load()
    main = tmp_path / "main"
    main.mkdir()
    assert integrate.main(["--into", str(main)]) == 0
    assert "plan only" in capsys.readouterr().out
    assert not (main / "le_dispatch").exists()
    assert integrate.main(["--into", str(main), "--yes"]) == 0
    report = json.loads((main / "docs" / "dispatch-integration.json").read_text())
    assert report["copied"] > 100 and report["conflicts"] == []
    assert "Makefile" in report["not_copied"]
    assert integrate.main(["--into", str(main / "missing")]) == 2


def test_check_docs_shipped_list_matches_the_docs_directory():
    """--only-dispatch must cover exactly the documents this package ships, so the main repo can run the
    docs checks on them without being failed by its own documents."""
    import re

    src = (ROOT / "scripts" / "check_docs.py").read_text()
    shipped = set(re.findall(r'^    "([^"]+)",$', src.split("SHIPPED_DOCS = (")[1].split(")")[0], re.M))
    on_disk = {p.name for p in (ROOT / "docs").iterdir() if p.name != "dispatch-integration.json"}
    assert shipped == on_disk, shipped ^ on_disk
