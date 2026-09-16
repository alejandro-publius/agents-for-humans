"""E6. The standalone example runs offline and both mechanisms fire."""

import runpy
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "compliance_steering.py"


def test_standalone_example_runs_offline(no_network, capsys):
    module = runpy.run_path(str(EXAMPLE), run_name="not_main")
    assert module["main"]() == 0
    out = capsys.readouterr().out
    assert "hook cancelled unknown assets : ['PUMP-9']" in out
    assert "steering guided wrong options : ['escalate']" in out
    assert out.strip().endswith("demo OK")
    assert no_network.attempts == []


def test_example_imports_only_strands_and_stdlib():
    text = EXAMPLE.read_text()
    imports = [line for line in text.splitlines() if line.startswith(("import ", "from "))]
    third_party = [line for line in imports if not line.startswith(("from strands", "from __future__"))]
    assert all(line.split()[1].split(".")[0] in {"json", "collections", "typing"} for line in third_party), (
        third_party
    )
