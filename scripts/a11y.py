"""Accessibility audit of the rider app with axe-core (via Playwright + Chromium), offline.

    make a11y        # serves the app locally, audits /, writes results/axe.json, exits 1 on violations

The page is audited with real data (register nothing; the replayed inbox and timeline are present
when data/riders.sqlite exists, and the empty state is audited otherwise).
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "results" / "axe.json"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1).read()
            return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(f"app did not start at {url}")


def main() -> int:
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import sync_playwright

    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        url = f"http://127.0.0.1:{port}/"
        wait_for(url + "api/status")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, wait_until="networkidle")
            page.wait_for_selector("#inbox tr", timeout=5000)
            results = Axe().run(page, options={"resultTypes": ["violations", "passes", "incomplete"]})
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    response = results.response
    violations = response.get("violations", [])
    summary = {
        "url": "/",
        "axe_version": response.get("testEngine", {}).get("version"),
        "violations": len(violations),
        "violation_nodes": sum(len(v["nodes"]) for v in violations),
        "passes": len(response.get("passes", [])),
        "incomplete": len(response.get("incomplete", [])),
        "violation_details": [
            {
                "id": v["id"],
                "impact": v["impact"],
                "help": v["help"],
                "nodes": [n["target"] for n in v["nodes"]],
            }
            for v in violations
        ],
        "incomplete_rules": [v["id"] for v in response.get("incomplete", [])],
        "note": "axe-core via Playwright Chromium against the served page with replayed data; 0 required.",
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"a11y: {summary['violations']} violations ({summary['violation_nodes']} nodes), "
        f"{summary['passes']} rules passed, {summary['incomplete']} incomplete; axe {summary['axe_version']}"
    )
    for v in summary["violation_details"]:
        print(f"  [{v['impact']}] {v['id']}: {v['help']} -> {v['nodes'][:3]}")
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
