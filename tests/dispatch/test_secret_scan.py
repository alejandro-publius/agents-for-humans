"""The secret scan in a tree that came without git (a download, an archive)."""

from __future__ import annotations

import importlib.util
import sys

from le_dispatch.interfaces import ROOT


def _load():
    spec = importlib.util.spec_from_file_location(
        "secret_scan_script", ROOT / "scripts" / "dispatch" / "secret_scan.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["secret_scan_script"] = module
    spec.loader.exec_module(module)
    return module


def test_a_tree_without_git_is_scanned_without_its_virtualenv_and_caches(tmp_path, monkeypatch, capsys):
    """A judge who downloads the zip, makes a venv inside it and runs make verify must not fail the scan on
    botocore's STS examples or cryptography's PEM markers; the walk skips .venv*, caches and build folders,
    and still catches a key in a real file."""
    m = _load()
    tree = tmp_path / "download"
    (tree / "le_dispatch").mkdir(parents=True)
    (tree / "le_dispatch" / "x.py").write_text("print('no keys here')\n")
    example = tree / ".venv313" / "lib" / "python3.13" / "site-packages" / "botocore" / "data" / "examples.json"
    example.parent.mkdir(parents=True)
    fake = "".join(["AKIA", "IOSFODNN7EXAMPLE"])  # joined at run time, so neither the source nor its .pyc carries it
    example.write_text('{"AccessKeyId": "' + fake + '"}\n')
    (tree / "build" / "site").mkdir(parents=True)
    (tree / "build" / "site" / "page.html").write_text("".join(["-----BEGIN ", "RSA PRIVATE KEY-----\n"]))
    (tree / "le_dispatch" / "__pycache__").mkdir()
    (tree / "le_dispatch" / "__pycache__" / "x.cpython-311.pyc").write_bytes(fake.encode())  # a folded constant
    monkeypatch.setattr(m, "ROOT", tree)
    assert m.tracked_files() == ["le_dispatch/x.py"]
    assert m.main() == 0 and "clean (1 tracked files)" in capsys.readouterr().out
    (tree / "le_dispatch" / "leak.py").write_text('KEY = "' + fake + '"\n')
    assert m.main() == 1 and "leak.py" in capsys.readouterr().out
