"""B3. Model proposes a parse; code validates against the KB and resolves the elevator."""

from agent.mock_model import MockModel
from agent.outage_parser import (
    OutageParse,
    parse_and_validate,
    parse_outage_regex,
    parse_outage_with_model,
    validate_against_kb,
)


def test_regex_baseline_on_documented_sample():
    p = parse_outage_regex("DELN: Platform - Richmond")
    assert p == OutageParse(
        station_abbr="DELN", level_from="platform", level_to=None, platform_label="Richmond"
    )
    assert parse_outage_regex("EMBR: Street - Concourse").level_to == "concourse"
    assert parse_outage_regex("garbage") is None


def test_validation_nulls_unknown_station_and_reports_it():
    v = validate_against_kb(OutageParse(station_abbr="ZZZZ", level_from="platform"), "ZZZZ: Platform - X")
    assert v.station_abbr is None and v.kb_elevator is None and not v.valid
    assert any("not in the KB" in p for p in v.problems)


def test_resolution_examples_from_kb():
    assert parse_and_validate("SANL: Platform - SFO/Millbrae/Daly City").kb_elevator == (
        "PLATFORM 2 ELEVATOR (RICHMOND, SFO/MILLBRAE/DALY CITY DIRECTIONS)"
    )
    assert parse_and_validate("EMBR: Street - Concourse").kb_elevator == "STREET ELEVATOR"
    assert parse_and_validate("COLS: Platform - Fruitvale").kb_elevator == "STATION ELEVATOR"
    ambiguous = parse_and_validate("WDUB: Garage - North/Dublin")
    assert ambiguous.kb_elevator is None and "no unique KB elevator" in ambiguous.problems[0]


def test_model_path_uses_structured_output_and_matches_baseline():
    turn = {
        "type": "tool_use",
        "name": "OutageParse",
        "input": {
            "station_abbr": "DELN",
            "level_from": "platform",
            "level_to": None,
            "platform_label": "Richmond",
        },
    }
    model = MockModel([turn])
    proposal, calls = parse_outage_with_model("DELN: Platform - Richmond", model)
    assert isinstance(proposal, OutageParse) and calls == 1
    assert model.calls[0]["tool_names"] == ["OutageParse"]
    assert (
        validate_against_kb(proposal, "DELN: Platform - Richmond").as_label()
        == parse_and_validate("DELN: Platform - Richmond").as_label()
    )


def test_model_that_never_answers_yields_no_parse():
    model = MockModel(
        [{"type": "text", "text": "I cannot parse this."}, {"type": "text", "text": "still no"}]
    )
    proposal, _ = parse_outage_with_model("DELN: Platform - Richmond", model)
    assert proposal is None
    v = validate_against_kb(proposal, "DELN: Platform - Richmond")
    assert v.problems == ["no parse proposed"] and not v.valid
