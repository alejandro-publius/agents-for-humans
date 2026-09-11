from afh_agent.tools import DOMAIN_TOOLS, days_until


def test_days_until_counts_forward():
    assert days_until("2026-09-14", today_iso="2026-09-10") == 4


def test_days_until_negative_when_overdue():
    assert days_until("2026-09-01", today_iso="2026-09-10") == -9


def test_tool_spec_is_generated_from_docstring():
    spec = days_until.tool_spec
    assert spec["name"] == "days_until"
    assert "date_iso" in spec["inputSchema"]["json"]["properties"]
    assert "due soon" in spec["description"]


def test_domain_tools_are_registered():
    assert days_until in DOMAIN_TOOLS
