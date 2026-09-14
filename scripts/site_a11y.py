"""make site-a11y: axe-core over every page of the evidence site; results/site_a11y.json; exit 1 on a violation.

    python scripts/site_a11y.py                 # builds the site into build/site first, then audits every page
    python scripts/site_a11y.py --site <dir>    # an already built site

A project for riders who depend on elevators does not publish an evidence site a screen reader or a
keyboard cannot use. Every page the site builds is opened in Chromium and run through axe-core (the
`axe-playwright-python` package carries the script; `pip install -e '.[a11y]' && playwright install
chromium`); the results file records every rule that fired, on which page, with how many nodes, and the
claim `site.a11y.violations == 0` keeps it at zero. Without Playwright or Chromium the audit says so and
exits 0, leaving the committed results file as the last audit; CI installs both.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RESULTS = ROOT / "results" / "site_a11y.json"
SITE = ROOT / "build" / "site"


def build_site(out: Path) -> int:
    import importlib.util

    spec = importlib.util.spec_from_file_location("site_script", ROOT / "scripts" / "site.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["site_script"] = module
    spec.loader.exec_module(module)
    return len(module.build(out))


def audit(site: Path) -> tuple[dict, int]:
    """Every page under `site` through axe-core: (the results document, the number of checks that passed).
    The passes stay out of the document: they move with the content, and the file is diffed in CI."""
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import sync_playwright

    pages = sorted(site.rglob("*.html"))
    by_rule: dict[str, dict] = {}
    by_page: dict[str, int] = {}
    passes = 0
    axe = Axe()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        # the audit is offline: the README's badge image and any other remote URL are refused, not fetched
        page.route("**/*", lambda route: route.continue_() if route.request.url.startswith("file:") else route.abort())
        for path in pages:
            page.goto(path.resolve().as_uri())
            response = axe.run(page, options={"resultTypes": ["violations", "passes"]}).response
            rel = path.relative_to(site).as_posix()
            passes += len(response.get("passes", []))
            by_page[rel] = 0
            for item in response["violations"]:
                rule = by_rule.setdefault(
                    item["id"], {"impact": item["impact"], "help": item["help"], "nodes": 0, "pages": []}
                )
                rule["nodes"] += len(item["nodes"])
                if rel not in rule["pages"]:
                    rule["pages"].append(rel)
                by_page[rel] += len(item["nodes"])
        engine = page.evaluate("axe.version")
        browser.close()
    return {
        "provenance": {
            "run": "axe-core over every page of the evidence site (scripts/site_a11y.py); the site is built from "
            "the documents in the repository, so this is the accessibility of what a judge reads",
            "engine": f"axe-core {engine}",
            "claimable": True,
            "note": "Nothing here is about the rider app, whose audit is the main repo's (screenshot 08).",
        },
        "pages": len(pages),
        "violations": sum(r["nodes"] for r in by_rule.values()),
        "rules_failed": len(by_rule),
        "by_rule": dict(sorted(by_rule.items())),
        "pages_with_violations": {k: v for k, v in sorted(by_page.items()) if v},
    }, passes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=None, help="an already built site (default: build it into build/site)")
    ap.add_argument("--out", default=str(RESULTS))
    args = ap.parse_args(argv)
    try:
        import axe_playwright_python  # noqa: F401
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("site-a11y: playwright or axe-playwright-python not installed; pip install -e '.[a11y]'; skipped")
        return 0
    try:
        with sync_playwright() as pw:
            pw.chromium.launch(args=["--no-sandbox"]).close()
    except Exception as exc:  # no browser binary: say so, keep the last audit
        print(f"site-a11y: Chromium not available ({type(exc).__name__}); playwright install chromium; skipped")
        return 0
    site = Path(args.site) if args.site else SITE
    if not args.site:
        print(f"site-a11y: built {build_site(site)} pages under {site.relative_to(ROOT)}")
    doc, passes = audit(site)
    Path(args.out).write_text(json.dumps(doc, indent=2) + "\n")
    print(
        f"site-a11y: {doc['pages']} pages, {passes} checks passed, {doc['violations']} violations "
        f"({doc['rules_failed']} rules); {doc['provenance']['engine']}"
    )
    for rule, r in doc["by_rule"].items():
        print(f"  {rule:<30} {r['impact']:<9} {r['nodes']:>4} nodes on {len(r['pages'])} pages: {r['help']}")
    print(f"wrote {args.out}")
    return 1 if doc["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
