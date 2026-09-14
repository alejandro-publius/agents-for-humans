"""The custom evaluator as a Lambda package: built, imported from the zip alone in an isolated interpreter, run
on real Strands spans with the reference input in the Evaluate API's shape."""

from __future__ import annotations

import importlib.util
import zipfile

from le_dispatch.interfaces import ROOT


def test_the_zip_is_self_contained_and_passes_on_real_spans(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("evaluator_zip_script", ROOT / "scripts" / "evaluator_zip.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    out = tmp_path / "option_equality.zip"
    assert script.main(["--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "verified: imported from the zip alone" in printed and "'label': 'PASS'" in printed
    assert "option_equality.lambda_handler" in printed
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["option_equality.py"]
        source = zf.read("option_equality.py").decode()
    assert "import boto3" not in source and "from le_dispatch" not in source and "from ." not in source
    first = out.read_bytes()
    assert script.main(["--out", str(out)]) == 0
    assert out.read_bytes() == first  # a stable archive
