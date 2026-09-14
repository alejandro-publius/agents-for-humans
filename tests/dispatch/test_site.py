"""The evidence site (scripts/site.py): one page per shipped document, pictures for the diagrams, no broken link."""

from __future__ import annotations

import importlib.util
import re
import sys

import pytest
from le_dispatch.interfaces import ROOT


def test_the_site_builds_with_every_document_and_no_broken_link(tmp_path):
    pytest.importorskip("markdown")
    spec = importlib.util.spec_from_file_location("site_script", ROOT / "scripts" / "site.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["site_script"] = module
    spec.loader.exec_module(module)
    written = module.build(tmp_path)
    assert (tmp_path / "index.html").exists() and len(written) >= 25
    for _source, href in module.pages():
        assert (tmp_path / href).exists(), href
    index = (tmp_path / "index.html").read_text()
    assert "claims verified by CI" in index and 'class="gallery"' in index
    assert "The first shot" in index and 'media="(prefers-reduced-motion: reduce)"' in index  # the still, on request
    readme = ROOT / "README.md"
    if readme.exists() and "## In one screen" in readme.read_text():
        assert "In one screen" in index
    else:  # the main repo: the opening of the sections the owner merges
        assert "Models propose, code decides" in index
    # a region that scrolls sideways is reachable from the keyboard (axe: scrollable-region-focusable)
    assert '<pre tabindex="0">' in (tmp_path / "TOUR-TRANSCRIPT.html").read_text()
    evidence = (tmp_path / "EVIDENCE.html").read_text()
    assert '<div class="scroll" tabindex="0"><table>' in evidence and "</table></div>" in evidence
    architecture = (tmp_path / "ARCHITECTURE.html").read_text()
    assert "```mermaid" not in architecture and 'src="diagrams/architecture-poll.png"' in architecture
    packet = (tmp_path / "evidence" / "DELN-E1-daytime.html").read_text()
    assert 'src="../diagrams/evidence-DELN-E1-daytime.png"' in packet
    assert 'href="../EVIDENCE.html"' in packet  # the nav from a nested page
    # every internal link and image resolves
    for page in tmp_path.rglob("*.html"):
        text = page.read_text()
        for target in re.findall(r'(?:href|src|srcset)="([^"#]+)"', text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            assert (page.parent / target).exists(), (page.relative_to(tmp_path), target)
        assert "\u2014" not in text, page.name
