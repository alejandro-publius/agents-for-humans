"""Does the real policy engine agree with the frozen cases it is supposed to embody?

The cases export (194 rows, two labelers) is the ground truth the gates, the
red team, the Cedar policy and the AgentCore evaluation dataset are built
from. On the laptop the real policy engine replaces `FixturePolicy`; if the
two disagree on a case (the top option, the minutes, the source URL), every
number downstream is measuring the wrong thing. This module runs both over
every case and writes the disagreements, so the drift is visible before any
result is cited.

    make policy-check POLICY=main_repo.policy_adapter:real_policy

The adapter is any `policy(trip) -> PolicyDecision` (INTEGRATION.md
section 3). Offline, the check runs the case-backed policy against itself
(and, in the tests, against a deliberately perturbed one).
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Any

from .interfaces import Case, KBSet, PolicyCallable, Trip, claimable, data_source, write_results_json

RESULTS_PATH = Path(__file__).resolve().parent.parent / "results" / "policy_engine_agreement.json"


def load_policy(spec: str) -> PolicyCallable:
    """`package.module:attribute`; the attribute is the callable, or a zero-argument factory returning it."""
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise ValueError("POLICY must look like package.module:callable")
    obj = getattr(importlib.import_module(module_name), attr)
    if not callable(obj):
        raise ValueError(f"{spec} is not callable")
    try:  # a zero-argument factory (for example `lambda: (kb, policy)[1]`) is called; a policy is returned as is
        parameters = inspect.signature(obj).parameters
    except (TypeError, ValueError):
        return obj
    if not parameters:
        made = obj()
        if callable(made):
            return made
        raise ValueError(f"{spec}() did not return a policy callable")
    return obj


def case_trip(case: Case, i: int) -> Trip:
    dest = "EMBR" if case.station != "EMBR" else "MONT"
    return Trip(rider_id=f"check-{i:03d}", origin=case.station, destination=dest, outages=(case.elevator,))


def compare(cases: list[Case], kb: KBSet, reference: PolicyCallable, candidate: PolicyCallable) -> dict[str, Any]:
    """Every case through both policies. A case agrees when affectedness, the station, the elevator, the
    top option and its minutes match; the source URL is reported but does not fail the case."""
    rows: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    for i, case in enumerate(cases):
        trip = case_trip(case, i)
        a, b = reference(trip), candidate(trip)
        fields = {
            "affected": (a.affected, b.affected),
            "station": (a.station, b.station),
            "elevator": (a.elevator, b.elevator),
            "top_option": (a.top_option, b.top_option),
            "minutes": (a.minutes_for(a.top_option), b.minutes_for(b.top_option)),
        }
        differing = {k: {"reference": v[0], "candidate": v[1]} for k, v in fields.items() if v[0] != v[1]}
        url_differs = a.source_url != b.source_url
        row = {"case_id": case.case_id, "station": case.station, "elevator": case.elevator, "agree": not differing}
        if differing:
            row["differs"] = differing
            disagreements.append(row)
        if url_differs:
            row["source_url"] = {"reference": a.source_url, "candidate": b.source_url}
        rows.append(row)
    agree = sum(1 for r in rows if r["agree"])
    return {
        "provenance": {
            "run": "the real policy engine against the case-backed policy over every frozen case",
            "claimable": claimable(),
            "source": data_source(),
            "note": "Agreement below 100 percent means a number downstream measures the wrong thing; fix the "
            "drift (the engine or the labels) before citing any result.",
        },
        "cases": len(rows),
        "agree": agree,
        "disagree": len(rows) - agree,
        "agreement_pct": round(100.0 * agree / len(rows), 1) if rows else None,
        "source_url_differs": sum(1 for r in rows if "source_url" in r),
        "disagreements": disagreements,
    }


def write_results(doc: dict[str, Any], path: Path = RESULTS_PATH) -> dict[str, Any]:
    write_results_json(path, doc)
    return doc


def render(doc: dict[str, Any]) -> str:
    run = doc.get("provenance", {}).get("run", "")
    label = " of the plumbing proof" if "plumbing" in run else ""  # the case-backed policy against itself
    lines = [
        f"policy engine agreement: {doc['agree']}/{doc['cases']} cases ({doc['agreement_pct']}%{label}), "
        f"{doc['disagree']} disagreement(s), source URL differs on {doc['source_url_differs']}"
    ]
    for d in doc["disagreements"][:20]:
        parts = ", ".join(f"{k}: {v['reference']!r} vs {v['candidate']!r}" for k, v in d["differs"].items())
        lines.append(f"  {d['case_id']} {d['station']} {d['elevator']}: {parts}")
    if len(doc["disagreements"]) > 20:
        lines.append(f"  ... {len(doc['disagreements']) - 20} more in the results file")
    return "\n".join(lines)
