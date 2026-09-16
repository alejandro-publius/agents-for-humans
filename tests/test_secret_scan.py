"""A7. The regex secret scan detects planted secrets and passes clean files."""

from scripts.secret_scan import scan_files, scan_text

PLANTED = {
    "aws-access-key-id": "AKIA" + "ABCDEFGHIJKLMNOP",
    "anthropic-api-key": "sk-ant-" + "a" * 24,
    "github-token": "ghp_" + "x" * 36,
    "bart-api-key": "MW9S-E7SL-26DU-VV8V",
    "secret-assignment": "BART_API_KEY=" + "Z" * 12,
    "private-key-block": "-----BEGIN RSA PRIVATE KEY-----",
}


def test_every_pattern_catches_its_planted_secret():
    for name, sample in PLANTED.items():
        names = {hit[1] for hit in scan_text(f"x = {sample}\n")}
        assert name in names, f"{name} not detected in {sample!r}"


def test_matches_are_redacted():
    (hit,) = scan_text("AKIA" + "ABCDEFGHIJKLMNOP")
    assert hit[2] == "AKIAAB…OP"


def test_env_example_shape_is_clean():
    assert scan_text("# BART_API_KEY=\nAWS_REGION=us-west-2\nkey=KEY\n") == []


def test_scan_files_reports_relative_path_and_line(tmp_path):
    bad = tmp_path / "config.py"
    bad.write_text("ok = 1\ntoken = 'ghp_" + "q" * 36 + "'\n")
    findings = scan_files([bad], tmp_path)
    assert findings == ["config.py:2: github-token (ghp_qq…qq)"]
