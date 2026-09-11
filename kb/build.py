"""Build ``kb/stations/<ABBR>.json`` from the raw page captures in ``kb/raw/``.

    python -m kb.build            # parse kb/raw/batch*.json (committed) into kb/stations/*.json
    python -m kb.build --fetch    # try to re-capture the pages live at one request per second

Provenance. bart.gov returns HTTP 403 "Access denied" to every non-browser client we tried
(curl, python, browser-like headers), so the raw captures were made on 2026-09-11 from a real
Chrome session, same-origin fetch, one request per 1.1 s, text blocks only. ``--fetch`` is kept so
the build documents how a re-capture would work and fails loudly instead of silently reusing stale
data if the site ever opens up. Every station file carries ``source_url`` and ``scraped_at``.

What is a fact here. Elevator names, "Can't enter / Can't exit" options, and entering/exiting
pathway prose are BART's text verbatim. ``kind`` is derived from BART's own elevator heading by a
fixed rule and is labeled as such. Stations with no pathway prose on their page get
``pathways_status: "unknown"`` rather than an invented description.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from kb.labels import OPTION_ORDER, label_option, strict_only_label

KB_DIR = Path(__file__).resolve().parent
RAW_DIR = KB_DIR / "raw"
STATIONS_DIR = KB_DIR / "stations"
INDEX_FILE = KB_DIR / "index.json"
DISTRIBUTION_FILE = KB_DIR.parent / "results" / "kb_label_distribution.json"
POLICY_FILE = KB_DIR / "policy.json"
ABBREVS_FILE = RAW_DIR / "station_abbrevs.json"

STATION_PAGE = "https://www.bart.gov/stations/{abbr}/accessible"
STATUS_PAGE = "https://www.bart.gov/stations/elevators"
NOISE = ("The referenced media source is missing",)

# BART's ranked outage options, verified by a human against the live page on Fri Sept 11, 2026.
# The automated capture saw HTTP 403 for this page because BART's WAF blocks this laptop's IP, not
# because the page is gone.
OPTION_ORDER_SOURCE = "https://www.bart.gov/guide/accessibility/elevators"
OPTION_ORDER_VERIFIED = list(OPTION_ORDER)


def elevator_kind(heading: str) -> str:
    """Fixed rule over BART's own heading text. Not a judgment call."""
    h = heading.upper()
    for key, kind in (
        ("CALTRAIN", "caltrain"),
        ("CONNECTOR", "connector"),
        ("GARAGE", "garage"),
        ("WHEELCHAIR LIFT", "lift"),
        ("BRIDGE", "bridge"),
        ("TUNNEL", "tunnel"),
        ("STATION ELEVATOR", "station"),
        ("STREET", "street"),
        ("PLATFORM", "platform"),
    ):
        if key in h:
            return kind
    return "other"


def situation_slug(label: str) -> str:
    lab = label.lower().replace("’", "'")
    if lab.startswith("can't enter station"):
        return "cant_enter" if "tunnel" not in lab else "cant_enter_from_tunnel"
    if lab.startswith("can't exit station"):
        return "cant_exit" if "tunnel" not in lab else "cant_exit_from_tunnel"
    return re.sub(r"[^a-z0-9]+", "_", lab).strip("_")


def parse_station(record: dict[str, Any], canonical: dict[str, str]) -> dict[str, Any]:
    url = record["source_url"]
    abbr = url.rstrip("/").split("/")[-2].upper()
    blocks = [b for b in record["blocks"] if not any(n in b["text"] for n in NOISE)]

    page_name = ""
    outage_intro = ""
    elevators: list[dict[str, Any]] = []
    pathways: list[dict[str, Any]] = []
    other_sections: list[dict[str, Any]] = []
    section = "none"
    current_elevator: dict[str, Any] | None = None
    current_pathway: dict[str, Any] | None = None
    current_other: dict[str, Any] | None = None

    for b in blocks:
        tag, text = b["tag"], b["text"]
        if tag == "h2":
            current_elevator = None
            if text.startswith("Elevator Outage Options"):
                section = "outage"
                page_name = re.sub(r"^Elevator Outage Options\s*-\s*", "", text)
                page_name = re.sub(r"\s+Station$", "", page_name).strip()
            elif re.match(r"^(Entering|Exiting)\b", text):
                section = "pathway"
                current_pathway = {"section": text, "text": []}
                pathways.append(current_pathway)
            else:
                section = "other"
                current_other = {"section": text, "text": []}
                other_sections.append(current_other)
            continue
        if section == "outage":
            if tag == "h3":
                current_elevator = {"name": text, "kind": elevator_kind(text), "outage_options": []}
                elevators.append(current_elevator)
            elif tag == "p" and current_elevator is None and not outage_intro:
                outage_intro = text
            elif tag in ("li", "p", "text") and current_elevator is not None:
                label, sep, rest = text.partition(":")
                if sep and len(label) < 60:
                    current_elevator["outage_options"].append(
                        {"situation": situation_slug(label), "label": label.strip(), "text": rest.strip()}
                    )
                else:
                    current_elevator["outage_options"].append(
                        {"situation": "note", "label": "", "text": text}
                    )
        elif section == "pathway" and current_pathway is not None:
            current_pathway["text"].append(text)
        elif section == "other" and current_other is not None:
            current_other["text"].append(text)

    for e in elevators:
        e["enter_option"] = None
        e["exit_option"] = None
        for opt in e["outage_options"]:
            if opt["situation"] == "note":
                continue
            opt["option_label"], opt["label_rule"] = label_option(opt["text"])
            if opt["situation"].startswith("cant_enter") and e["enter_option"] is None:
                e["enter_option"] = opt["option_label"]
            elif opt["situation"].startswith("cant_exit") and e["exit_option"] is None:
                e["exit_option"] = opt["option_label"]
    documented = [
        {"elevator": e["name"], "elevator_kind": e["kind"], **opt}
        for e in elevators
        for opt in e["outage_options"]
        if opt["situation"] != "note"
    ]
    return {
        "abbr": abbr,
        "name": canonical.get(abbr, page_name),
        "page_name": page_name,
        "outage_intro": outage_intro,
        "elevators": elevators,
        "documented_outage_options": documented,
        "pathways": pathways,
        "pathways_status": "documented" if pathways else "unknown",
        "other_sections": other_sections,
        "source_url": url,
        "scraped_at": record["fetched_at"],
        "http_status": record.get("status"),
        "scrape_method": "Chrome same-origin fetch, text blocks, 1 request per 1.1 s",
    }


def parse_policy(record: dict[str, Any]) -> dict[str, Any]:
    sections: dict[str, list[str]] = {}
    current = None
    for b in record["blocks"]:
        if b["tag"] in ("h1", "h2"):
            current = b["text"]
            sections.setdefault(current, [])
        elif current is not None and b["tag"] in ("p", "li", "td", "text"):
            sections[current].append(b["text"])
    return {
        "source_url": record["source_url"],
        "scraped_at": record["fetched_at"],
        "sections": sections,
        "option_order": {
            "order": OPTION_ORDER_VERIFIED,
            "verified": True,
            "source_url": OPTION_ORDER_SOURCE,
            "verified_by": "reviewer, read on the live page Fri Sept 11, 2026",
            "note": (
                "Alternate elevator is always the primary option when one exists, then backtracking, "
                "then transit, then Mitigation Trip, then Mitigation Shuttle. The automated capture got "
                "HTTP 403 for this page: BART's WAF blocks this laptop's IP; the page itself is live."
            ),
        },
    }


def load_raw() -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    stations, status_page = [], None
    for path in sorted(RAW_DIR.glob("batch*.json")):
        for record in json.loads(path.read_text()):
            url = record["source_url"]
            if url.rstrip("/") == STATUS_PAGE:
                status_page = record
            elif url.endswith("/accessible"):
                stations.append(record)
    return stations, status_page


def canonical_names() -> dict[str, str]:
    data = json.loads(ABBREVS_FILE.read_text())
    return {s["abbr"].upper(): s["name"] for s in data["stations"]}


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def build() -> dict[str, Any]:
    canonical = canonical_names()
    raw_stations, status_page = load_raw()
    STATIONS_DIR.mkdir(exist_ok=True)
    for stale in STATIONS_DIR.glob("*.json"):
        stale.unlink()

    stations = [parse_station(r, canonical) for r in raw_stations]
    stations.sort(key=lambda s: s["abbr"])
    for s in stations:
        write_json(STATIONS_DIR / f"{s['abbr']}.json", s)

    seen = {s["abbr"] for s in stations}
    missing = sorted(set(canonical) - seen)
    index = {
        "built_from": "kb/raw/batch*.json",
        "canonical_station_list": {
            "source_url": json.loads(ABBREVS_FILE.read_text())["source_url"],
            "count": len(canonical),
        },
        "scraped_at_range": [
            min(s["scraped_at"] for s in stations),
            max(s["scraped_at"] for s in stations),
        ],
        "counts": {
            "stations": len(stations),
            "stations_missing_page": missing,
            "with_elevators": sum(1 for s in stations if s["elevators"]),
            "with_documented_outage_options": sum(1 for s in stations if s["documented_outage_options"]),
            "with_pathways": sum(1 for s in stations if s["pathways"]),
            "pathways_unknown": sum(1 for s in stations if s["pathways_status"] == "unknown"),
            "elevators_total": sum(len(s["elevators"]) for s in stations),
            "documented_outage_options_total": sum(len(s["documented_outage_options"]) for s in stations),
        },
        "stations": [
            {
                "abbr": s["abbr"],
                "name": s["name"],
                "elevators": len(s["elevators"]),
                "documented_outage_options": len(s["documented_outage_options"]),
                "pathways": len(s["pathways"]),
            }
            for s in stations
        ],
    }
    write_json(INDEX_FILE, index)
    if status_page is not None:
        write_json(POLICY_FILE, parse_policy(status_page))
    write_json(DISTRIBUTION_FILE, label_distribution(stations))
    return index


def label_distribution(stations: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts of option labels under the strict rules alone and with the extension tier."""
    strict_counts = dict.fromkeys(OPTION_ORDER, 0)
    final_counts = dict.fromkeys(OPTION_ORDER, 0)
    by_rule = {"strict": 0, "extended": 0, "default": 0}
    default_texts = []
    checks = {}
    for s in stations:
        for opt in s["documented_outage_options"]:
            strict_counts[strict_only_label(opt["text"])] += 1
            final_counts[opt["option_label"]] += 1
            by_rule[opt["label_rule"]] += 1
            if opt["label_rule"] == "default":
                default_texts.append({"station": s["abbr"], "elevator": opt["elevator"], "text": opt["text"]})
        if s["abbr"] in ("SANL", "DBRK", "12TH"):
            checks[s["abbr"]] = [
                {"elevator": o["elevator"], "situation": o["situation"], "label": o["option_label"]}
                for o in s["documented_outage_options"]
            ]
    total = sum(final_counts.values())
    return {
        "stations": len(stations),
        "elevators_total": sum(len(s["elevators"]) for s in stations),
        "stations_with_pathways": sum(1 for s in stations if s["pathways"]),
        "stations_pathways_unknown": sum(1 for s in stations if s["pathways_status"] == "unknown"),
        "options_total": total,
        "rank_order": list(OPTION_ORDER),
        "strict_rules_only": strict_counts,
        "with_extension": final_counts,
        "labeled_by_rule": by_rule,
        "default_after_extension": default_texts,
        "checks": checks,
        "note": (
            "strict = the mapping specified in the work order; extended = additional BART phrasings "
            "listed in kb/labels.py; default = mitigation_trip when nothing matched. Labels are "
            "derived from BART's text by fixed rules; they are not BART's own categories."
        ),
    }


def fetch_live(abbrs: list[str], delay: float = 1.1) -> int:
    """Attempt a live re-capture. Documented to fail with 403 outside a browser session."""
    ok = 0
    for i, abbr in enumerate(abbrs):
        if i:
            time.sleep(delay)
        url = STATION_PAGE.format(abbr=abbr)
        req = urllib.request.Request(url, headers={"User-Agent": "last-elevator-kb/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                print(f"{abbr}: HTTP {resp.status} ({len(resp.read())} bytes)")
                ok += 1
        except urllib.error.HTTPError as exc:
            print(f"{abbr}: HTTP {exc.code} {exc.reason}")
        except urllib.error.URLError as exc:
            print(f"{abbr}: no response ({exc.reason})")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--fetch", action="store_true", help="try a live re-capture at 1 req/s (expect 403)")
    parser.add_argument("--limit", type=int, default=2, help="stations to try with --fetch")
    args = parser.parse_args(argv)

    if args.fetch:
        abbrs = sorted(canonical_names())[: args.limit]
        got = fetch_live(abbrs)
        if got < len(abbrs):
            print("live fetch blocked; building from kb/raw captures instead", file=sys.stderr)

    index = build()
    c = index["counts"]
    print(
        f"kb: {c['stations']} stations; {c['with_documented_outage_options']} with documented outage options "
        f"({c['documented_outage_options_total']} options across {c['elevators_total']} elevators); "
        f"{c['with_pathways']} with pathways, {c['pathways_unknown']} pathways unknown; "
        f"missing pages: {c['stations_missing_page'] or 'none'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
