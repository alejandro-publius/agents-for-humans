"""The `afh` entrypoint loads `.env` from the working directory, as the README quickstart promises."""

import os

from afh_agent.agent import build_agent
from afh_agent.cli import main
from tests.fake_model import ScriptedModel, text_turn

VAR = "AFH_TEST_FROM_DOTENV"


def test_main_loads_dotenv_from_cwd(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env").write_text(f"{VAR}=from-file\n")
    monkeypatch.chdir(tmp_path)
    os.environ.pop(VAR, None)
    seen = {}

    def fake_build_agent(session_id=None):
        seen["value"] = os.environ.get(VAR)
        return build_agent(model=ScriptedModel([text_turn("all good")]), tools=[])

    monkeypatch.setattr("afh_agent.cli.build_agent", fake_build_agent)
    try:
        assert main(["hello"]) == 0
    finally:
        os.environ.pop(VAR, None)

    assert seen["value"] == "from-file", ".env should be loaded before the agent is built"
    assert "all good" in capsys.readouterr().out


def test_real_environment_wins_over_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(f"{VAR}=from-file\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(VAR, "from-shell")
    monkeypatch.setattr(
        "afh_agent.cli.build_agent",
        lambda session_id=None: build_agent(model=ScriptedModel([text_turn("ok")]), tools=[]),
    )

    assert main(["hello"]) == 0
    assert os.environ[VAR] == "from-shell"
