"""B1. Every station file is provenance-stamped and parsed from BART's own text."""

import json
import re
from pathlib import Path

from kb import build as kb_build

STATIONS = sorted(kb_build.STATIONS_DIR.glob("*.json"))
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_fifty_station_files_exist():
    assert len(STATIONS) == 50, [p.stem for p in STATIONS]


def test_every_file_has_source_url_and_timestamp():
    for path in STATIONS:
        s = _load(path)
        assert s["source_url"] == f"https://www.bart.gov/stations/{path.stem}/accessible"
        assert ISO.match(s["scraped_at"]), (path.stem, s["scraped_at"])
        assert s["abbr"] == path.stem and s["name"], path.stem


def test_del_norte_is_parsed_by_abbreviation_not_by_barts_mislabeled_link():
    """The status page links 'El Cerrito del Norte' to DUBL. We fetch by abbreviation, so DELN is DELN."""
    deln = _load(kb_build.STATIONS_DIR / "DELN.json")
    assert deln["name"] == "El Cerrito del Norte"
    assert "El Cerrito del Norte" in deln["page_name"]
    dubl = _load(kb_build.STATIONS_DIR / "DUBL.json")
    assert dubl["name"] == "Dublin/Pleasanton" and "Dublin" in dubl["page_name"]


def test_outage_options_are_verbatim_bart_text_with_situations():
    for path in STATIONS:
        s = _load(path)
        assert s["elevators"], f"{path.stem} has no elevators parsed"
        for opt in s["documented_outage_options"]:
            assert opt["situation"] and opt["text"], (path.stem, opt)
            assert opt["elevator"] in {e["name"] for e in s["elevators"]}
    deln = _load(kb_build.STATIONS_DIR / "DELN.json")
    first = deln["documented_outage_options"][0]
    assert first["elevator"] == "PLATFORM 1 ELEVATOR (RICHMOND DIRECTION)"
    assert first["situation"] == "cant_enter"
    assert first["text"].startswith("Take the Platform 2 elevator on the opposite platform")


def test_unknown_pathways_are_marked_not_invented():
    statuses = {s["pathways_status"] for s in map(_load, STATIONS)}
    assert statuses <= {"documented", "unknown"}
    for path in STATIONS:
        s = _load(path)
        assert (s["pathways_status"] == "documented") == bool(s["pathways"]), path.stem


def test_index_counts_match_files():
    index = json.loads(kb_build.INDEX_FILE.read_text())
    assert index["counts"]["stations"] == len(STATIONS)
    assert index["counts"]["stations_missing_page"] == []
    assert index["counts"]["with_documented_outage_options"] == sum(
        1 for s in map(_load, STATIONS) if s["documented_outage_options"]
    )


def test_policy_order_is_marked_unverified():
    policy = json.loads(kb_build.POLICY_FILE.read_text())
    assert policy["option_order"]["verified"] is False
    assert "Using Elevators" in policy["sections"]


def test_elevator_kind_rule():
    assert kb_build.elevator_kind("PLATFORM 1 ELEVATOR (RICHMOND DIRECTION)") == "platform"
    assert kb_build.elevator_kind("STREET ELEVATOR (14TH STREET/OGAWA PLAZA)") == "street"
    assert kb_build.elevator_kind("STATION ELEVATOR") == "station"
    assert kb_build.elevator_kind("GARAGE ELEVATOR 2 (NORTH/DUBLIN SIDE)") == "garage"
    assert kb_build.elevator_kind("WHEELCHAIR LIFT FROM STATION TO PARKING LOT") == "lift"
    assert kb_build.elevator_kind("CALTRAIN ELEVATOR - WEST PLAZA TO CONCOURSE") == "caltrain"


def test_option_labels_match_the_three_known_pages():
    def labels(abbr):
        s = _load(kb_build.STATIONS_DIR / f"{abbr}.json")
        return [(o["elevator"], o["situation"], o["option_label"]) for o in s["documented_outage_options"]]

    assert {lab for _, _, lab in labels("SANL")} == {"backtracking"} and len(labels("SANL")) == 4
    assert {lab for _, _, lab in labels("DBRK")} == {"transit"} and len(labels("DBRK")) == 4
    twelfth = labels("12TH")
    assert all(lab == "alternate_elevator" for el, _, lab in twelfth if el.startswith("STREET"))
    assert all(lab == "transit" for el, _, lab in twelfth if el == "PLATFORM ELEVATOR")


def test_every_elevator_has_enter_and_exit_labels_or_null():
    from kb.labels import OPTION_ORDER

    for path in STATIONS:
        for e in _load(path)["elevators"]:
            for key in ("enter_option", "exit_option"):
                assert e[key] is None or e[key] in OPTION_ORDER, (path.stem, e["name"], key)


def test_label_distribution_file_is_written_and_consistent():
    dist = json.loads(kb_build.DISTRIBUTION_FILE.read_text())
    assert dist["options_total"] == sum(dist["with_extension"].values()) == 194
    assert sum(dist["labeled_by_rule"].values()) == 194
    assert dist["strict_rules_only"]["mitigation_trip"] >= dist["with_extension"]["mitigation_trip"]
    assert len(dist["default_after_extension"]) == dist["with_extension"]["mitigation_trip"]
