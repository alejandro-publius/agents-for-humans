"""Input interfaces between this package and the agents-for-humans repo.

Everything this package needs from the main repo comes through one of the
shapes below. Each shape has a JSON form (so a fixture can stand in for the
real thing) and a Python form (so the laptop session can wire the real
`kb/` package and policy engine directly). Nothing here reads the real
repo; see docs/INTEGRATION.md for the wiring.

KB JSON (fixtures/kb.json)
    {
      "source": "free text: where the codes came from",
      "frozen_tag": "kb-labels-v1",
      "stations": ["12TH", "16TH", ...],          # station abbreviations
      "elevators": ["12TH-E1", ...],               # elevator ids as used by the policy engine
      "option_labels": ["alternate_elevator", "backtracking", "transit",
                        "mitigation_trip", "mitigation_shuttle"],  # BART's published order
      "station_names": {"12TH": "12th St. Oakland City Center", ...}  # optional: what a rider hears
    }

Cases JSON (fixtures/cases.json), the 194 frozen options
    {
      "source": "...", "frozen_tag": "kb-labels-v1",
      "cases": [
        {"case_id": "C001", "station": "12TH", "elevator": "12TH-E1",
         "label": "alternate_elevator", "option_text": "...", "added_minutes": 4,
         "source_url": "https://www.bart.gov/stations/12th/accessible"}
      ]
    }

Policy callable
    policy(trip: Trip) -> PolicyDecision
    The real policy engine is pure code (no model). FixturePolicy below
    implements the same contract from the cases JSON so every test and
    dry-run works offline.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

BART_OPTION_ORDER: tuple[str, ...] = (
    "alternate_elevator",
    "backtracking",
    "transit",
    "mitigation_trip",
    "mitigation_shuttle",
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"

# The laptop points every script and writer at the real exports with two environment variables; unset, the
# package reads its fixtures and every results file says so (claimable: false).
KB_EXPORT_ENV = "LE_KB_EXPORT"
CASES_EXPORT_ENV = "LE_CASES_EXPORT"


def kb_path() -> Path:
    return Path(os.environ.get(KB_EXPORT_ENV) or FIXTURES / "kb.json")


def cases_path() -> Path:
    return Path(os.environ.get(CASES_EXPORT_ENV) or FIXTURES / "cases.json")


def _is_fixture(path: Path, name: str) -> bool:
    return path.resolve() == (FIXTURES / name).resolve()


def using_fixtures() -> bool:
    """Both inputs are the package fixtures."""
    return _is_fixture(kb_path(), "kb.json") and _is_fixture(cases_path(), "cases.json")


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def data_source() -> dict[str, Any]:
    """What the run read; written into every results file's provenance."""
    return {"kb": _display(kb_path()), "cases": _display(cases_path()), "fixture": using_fixtures()}


def claimable() -> bool:
    """A results file is claimable only when both inputs are real exports; a mixed run is neither."""
    return not _is_fixture(kb_path(), "kb.json") and not _is_fixture(cases_path(), "cases.json")


LIVE_CREDENTIAL_ENV = (
    "AWS_ACCESS_KEY_ID",
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
)


def credentials_present() -> bool:
    """Would boto3 find credentials? The environment first; else the shared credentials file, which on a
    laptop is where they usually are (AWS_SHARED_CREDENTIALS_FILE, or ~/.aws/credentials). Never touches
    the network or the credential chain itself; the tests point the file variable at a path that does not
    exist, so no test ever sees a laptop's credentials."""
    if any(os.environ.get(k) for k in LIVE_CREDENTIAL_ENV):
        return True
    shared = os.environ.get("AWS_SHARED_CREDENTIALS_FILE")
    path = Path(shared).expanduser() if shared else Path.home() / ".aws" / "credentials"
    return path.is_file()


def runtime_session_id(*parts: str, prefix: str = "le") -> str:
    """A stable AgentCore Runtime session id for the same rider (and trip): the parts, then a digest, so the
    id is at least 33 characters (the API's minimum for runtimeSessionId) and the same on every poll."""
    import hashlib

    key = "-".join(p.strip() for p in parts if p and p.strip()) or "session"
    digest = hashlib.sha256(key.encode()).hexdigest()[:32]
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in key)[:40]
    return f"{prefix}-{safe}-{digest}"


def written_by_a_real_run(path: Path) -> bool:
    """Does the results file at `path` carry a real run: claimable (both exports real), or a replay of the
    archive's week rather than the synthetic one? Read from its provenance; a missing or unreadable file is
    not."""
    try:
        prov = json.loads(Path(path).read_text()).get("provenance", {})
    except (OSError, ValueError):
        return False
    return bool(prov.get("claimable")) or prov.get("week", "synthetic") != "synthetic"


def keep_the_real_file(path: Path, *, this_run_is_real: bool) -> bool:
    """A run on the fixtures never overwrites a results file a real run wrote: the laptop's real numbers
    survive a `make <target>` typed without the exports or the archive, and the main repo's CI, which has
    neither the archive nor the credentials, leaves them as committed and its determinism diff stays clean.
    True means the caller writes nothing and says so."""
    return not this_run_is_real and written_by_a_real_run(path)


def write_results_json(path: Path, doc: Mapping[str, Any]) -> bool:
    """Write a results document, unless a real run wrote the file and this one is not real (then say so and
    write nothing). Real is the document's own provenance.claimable, or a replay of the archive's week."""
    prov = doc.get("provenance", {}) if isinstance(doc, Mapping) else {}
    real = bool(prov.get("claimable")) or prov.get("week", "synthetic") != "synthetic"
    if keep_the_real_file(Path(path), this_run_is_real=real):
        print(f"left {path} as committed: a real run wrote it and this run read the fixtures")
        return False
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, indent=2) + "\n")
    return True


def source_label() -> str:
    return "fixture KB" if _is_fixture(kb_path(), "kb.json") else f"KB export {kb_path().name}"


@dataclass(frozen=True)
class KBSet:
    """The frozen knowledge base, reduced to the sets the gates need."""

    stations: frozenset[str]
    elevators: frozenset[str]
    option_labels: tuple[str, ...] = BART_OPTION_ORDER
    source: str = ""
    frozen_tag: str = ""
    # optional: station code to the name a rider hears ("DELN" to "El Cerrito del Norte"); a screen reader
    # spells a code letter by letter, so every sentence and card uses the name when the KB has one
    station_names: Mapping[str, str] = field(default_factory=dict)

    def has_station(self, code: Any) -> bool:
        return isinstance(code, str) and code in self.stations

    def name_of(self, code: str | None) -> str:
        """The rider-facing name of a station, or its code when the KB has no name for it."""
        if not code:
            return ""
        return self.station_names.get(code, code)

    def has_elevator(self, elevator_id: Any) -> bool:
        return isinstance(elevator_id, str) and elevator_id in self.elevators

    def has_label(self, label: Any) -> bool:
        return isinstance(label, str) and label in self.option_labels

    def rank(self, label: str) -> int:
        """Position in BART's published order; unknown labels sort last."""
        try:
            return self.option_labels.index(label)
        except ValueError:
            return len(self.option_labels)


def load_kb(path: str | Path | None = None) -> KBSet:
    data = json.loads(Path(path if path is not None else kb_path()).read_text())
    return KBSet(
        stations=frozenset(data["stations"]),
        elevators=frozenset(data["elevators"]),
        option_labels=tuple(data.get("option_labels", BART_OPTION_ORDER)),
        source=data.get("source", ""),
        frozen_tag=data.get("frozen_tag", ""),
        station_names=dict(data.get("station_names", {})),
    )


@dataclass(frozen=True)
class Case:
    case_id: str
    station: str
    elevator: str
    label: str
    option_text: str = ""
    added_minutes: int | None = None
    source_url: str = ""


def load_cases(path: str | Path | None = None) -> list[Case]:
    data = json.loads(Path(path if path is not None else cases_path()).read_text())
    return [Case(**{k: v for k, v in c.items() if k in Case.__dataclass_fields__}) for c in data["cases"]]


@dataclass(frozen=True)
class Trip:
    """A rider's saved trip plus what the poller currently sees."""

    rider_id: str
    origin: str
    destination: str
    outages: tuple[str, ...] = ()  # elevator ids currently out
    via: tuple[str, ...] = ()  # transfer stations on the saved route, if any
    when: str = ""  # ISO 8601 local time the plan is for; "" means now
    after_dark: bool = False
    last_train: bool = False

    @property
    def case_key(self) -> str:
        """Stable key for 'this rider, this trip, this outage set'."""
        return f"{self.rider_id}|{self.origin}>{self.destination}|{','.join(sorted(self.outages))}"


@dataclass
class RankedOption:
    label: str
    feasible: bool
    reason: str = ""
    added_minutes: int | None = None
    source_url: str = ""


@dataclass
class PolicyDecision:
    """What the policy engine (pure code) decided for one trip."""

    affected: bool
    kind: str | None = None  # cannot_enter | cannot_exit | transfer | None
    station: str | None = None
    elevator: str | None = None
    top_option: str | None = None
    ranked: list[RankedOption] = field(default_factory=list)
    flags: dict[str, bool] = field(default_factory=dict)  # after_dark, last_train
    source_url: str = ""
    station_name: str = ""  # the name a rider hears, when the KB has one; the code otherwise (see spoken_station)
    note_constraints: tuple[str, ...] = ()  # what the rider's note ruled out today (le_dispatch/note.py)
    note_set_aside: bool = False  # the note ruled out every option: BART's order won, and the card says so

    @property
    def spoken_station(self) -> str:
        """What the rider hears for the station: the name when the policy engine supplied one, else the code."""
        return self.station_name or self.station or ""

    def minutes_for(self, label: str | None) -> int | None:
        for opt in self.ranked:
            if opt.label == label:
                return opt.added_minutes
        return None

    def rejected(self) -> list[RankedOption]:
        return [o for o in self.ranked if o.label != self.top_option]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PolicyCallable = Callable[[Trip], PolicyDecision]


class FixturePolicy:
    """Policy engine stand-in built from the cases JSON.

    Contract (same as the real engine): given a trip, decide affectedness from
    the outage set, pick the station and elevator that matter, rank the KB's
    options for that elevator in BART's published order, and mark the first
    feasible one as top. Minutes come from the case rows, never from a model.
    """

    def __init__(self, cases: list[Case], kb: KBSet):
        self.kb = kb
        self.by_elevator: dict[str, list[Case]] = {}
        for c in cases:
            self.by_elevator.setdefault(c.elevator, []).append(c)

    def __call__(self, trip: Trip) -> PolicyDecision:
        flags = {"after_dark": trip.after_dark, "last_train": trip.last_train}
        for elevator in trip.outages:
            station = elevator.split("-")[0]
            if station == trip.origin:
                kind = "cannot_enter"
            elif station == trip.destination:
                kind = "cannot_exit"
            elif station in trip.via:
                kind = "transfer"
            else:
                continue  # an outage elsewhere on the system does not touch this trip
            options = sorted(self.by_elevator.get(elevator, []), key=lambda c: self.kb.rank(c.label))
            ranked = [
                RankedOption(
                    label=c.label,
                    feasible=True,
                    reason=c.option_text or f"{c.label} per BART's station page",
                    added_minutes=c.added_minutes,
                    source_url=c.source_url,
                )
                for c in options
            ]
            top = ranked[0].label if ranked else None
            return PolicyDecision(
                affected=True,
                kind=kind,
                station=station,
                elevator=elevator,
                top_option=top,
                ranked=ranked,
                flags=flags,
                source_url=ranked[0].source_url if ranked else "",
                station_name=self.kb.station_names.get(station, ""),
            )
        return PolicyDecision(affected=False, flags=flags)


def fixture_policy(kb_path: str | Path | None = None, cases_path: str | Path | None = None):
    """The KB and the case-backed policy: the fixtures, or the real exports when LE_KB_EXPORT and
    LE_CASES_EXPORT are set (the name stays for the callers; the data need not be a fixture)."""
    kb = load_kb(kb_path)
    return kb, FixturePolicy(load_cases(cases_path), kb)
