"""F74: the evidence site through axe-core (scripts/site_a11y.py, results/site_a11y.json)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys

import pytest
from le_dispatch.interfaces import ROOT


def _script():
    spec = importlib.util.spec_from_file_location("site_a11y_script", ROOT / "scripts" / "site_a11y.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["site_a11y_script"] = module
    spec.loader.exec_module(module)
    return module


def test_the_committed_audit_covers_the_site_and_names_every_rule_that_fired():
    """The results file is the last audit: every page, the engine version, the rules that fired with their
    pages; the claim keeps violations at zero and the file says where any would be."""
    doc = json.loads((ROOT / "results" / "site_a11y.json").read_text())
    assert doc["provenance"]["engine"].startswith("axe-core ") and doc["provenance"]["claimable"] is True
    assert doc["pages"] >= 30 and "checks_passed" not in doc  # the pass count moves with the content
    assert doc["violations"] == sum(r["nodes"] for r in doc["by_rule"].values())
    assert set(doc["pages_with_violations"]) <= {p for r in doc["by_rule"].values() for p in r["pages"]}


def test_a_few_pages_of_the_built_site_pass_axe(tmp_path):
    """Three pages (the front page, a page with code blocks and tables, an evidence packet) built here and
    run through axe-core in Chromium: no violation. The full audit is make site-a11y."""
    pytest.importorskip("markdown")
    pytest.importorskip("axe_playwright_python")
    pw = pytest.importorskip("playwright.sync_api")
    m = _script()
    try:
        with pw.sync_playwright() as p:
            p.chromium.launch(args=["--no-sandbox"]).close()
    except Exception as exc:  # no browser binary here
        pytest.skip(f"Chromium not available: {type(exc).__name__}")
    site = tmp_path / "site"
    assert m.build_site(site) >= 25
    subset = tmp_path / "subset"
    for rel in ("index.html", "EVIDENCE.html", "evidence/DELN-E1-daytime.html"):
        (subset / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(site / rel, subset / rel)
    for folder in ("diagrams", "screenshots"):
        shutil.copytree(site / folder, subset / folder)
    doc, passes = m.audit(subset)
    assert doc["pages"] == 3 and doc["violations"] == 0 and passes > 3, doc["by_rule"]
