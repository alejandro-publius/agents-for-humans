"""F61: the package as git bundles, in dependency order (scripts/bundles.py)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest
from le_dispatch.interfaces import ROOT


def _script(need_history: bool = True):
    spec = importlib.util.spec_from_file_location("bundles_script", ROOT / "scripts" / "bundles.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["bundles_script"] = module  # dataclasses with postponed annotations look the module up by name
    spec.loader.exec_module(module)
    if need_history and module.history_here():
        pytest.skip(module.history_here())  # the main repo takes the package by bundle, not by history
    return module


def test_without_the_package_history_the_build_says_so_and_passes(tmp_path, capsys, monkeypatch):
    """In the main repo (or any checkout without the base commit) make bundles and make cold-start have no
    chain to build or replay; they say so and exit 0, so the placed CI workflow stays green there."""
    b = _script(need_history=False)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(b, "ROOT", tmp_path)
    assert b.history_here() and b.ITEMS[0].tip in b.history_here()
    assert b.main(["--out", str(tmp_path / "out")]) == 0
    assert "nothing to build here" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_the_chain_is_in_dependency_order_and_every_tip_is_on_main():
    """Each item's base is the previous item's tip, every tip is an ancestor of main (or main itself), and the
    base bundle starts from the root; so the bundles apply in index order and nothing depends on a later one."""
    b = _script()
    items = b.ITEMS
    assert items[0].base is None and all(i.base is not None for i in items[1:])
    for prev, item in zip(items, items[1:], strict=False):
        assert b.full(item.base) == b.full(prev.tip), (item.name, prev.name)
    head = b.full("main")
    for item in items:
        tip = b.full(item.tip)
        assert subprocess.run(["git", "merge-base", "--is-ancestor", tip, head], cwd=ROOT).returncode == 0, item.name
    assert b.full(b.last_item().tip) == head  # the open item, or the last closed one, is main


def test_the_build_writes_one_bundle_per_item_with_a_note_and_the_index(tmp_path, capsys):
    """Built into a temporary directory: a bundle per item that verifies as a bundle, a note that carries the
    apply command and the acceptance command, and INDEX.md with the apply sequence in order."""
    b = _script()
    assert b.main(["--out", str(tmp_path)]) == 0
    built = [i for i in b.ITEMS if i.base is None or b.full(i.tip) != b.full(i.base)]
    for item in built:
        bundle = tmp_path / f"dispatch-{item.name}.bundle"
        assert bundle.exists() and bundle.stat().st_size > 1000
        heads = subprocess.run(["git", "bundle", "list-heads", str(bundle)], capture_output=True, text=True).stdout
        assert f"refs/heads/dispatch/{item.name}" in heads
        note = (tmp_path / f"dispatch-{item.name}.md").read_text()
        assert f"fetch dispatch-{item.name}.bundle dispatch/{item.name}:refs/dispatch/{item.name}" in note
        assert item.acceptance in note and "## PR description" in note
    index = (tmp_path / "INDEX.md").read_text()
    order = [line.split("`")[1] for line in index.splitlines() if line.startswith("| ") and ".bundle" in line]
    assert order == [f"dispatch-{i.name}.bundle" for i in built]
    assert "integrate INTO=~/agents-for-humans" in index and "Verified in a throwaway repo" in index
    assert "\u2014" not in index  # no em dash anywhere in what the laptop reads
