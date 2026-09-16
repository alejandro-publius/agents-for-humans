"""BART Legacy API client. JSON mode. Live only when ``BART_API_KEY`` is set.

Without a key every call reads ``fixtures/bart/*.json`` (provenance in ``fixtures/bart/README.md``).
With a key, a call makes exactly one HTTPS request with certifi's CA bundle; on any failure it logs
one line and raises ``BartUnavailable``. No retries, no tracebacks, and the key is never logged.

Endpoints (docs: https://api.bart.gov/docs/overview/index.aspx):
    bsa.aspx?cmd=elev      elevator advisories        -> elevators()
    bsa.aspx?cmd=bsa       service advisories         -> advisories()
    etd.aspx?cmd=etd       real-time departures       -> etd(orig)
    sched.aspx?cmd=depart  trip plan by departure     -> depart(orig, dest, ...)
    stn.aspx?cmd=stns      station list               -> stations()
    stn.aspx?cmd=stnaccess station access text        -> station_access(orig)
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import certifi

log = logging.getLogger("bart")

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures" / "bart"
BASE_URL = "https://api.bart.gov/api/"
USER_AGENT = "last-elevator/0.1 (+https://github.com/alejandro-publius/agents-for-humans)"

DEFAULT_FIXTURES = {
    "elev": "elev_sample.json",
    "bsa": "bsa_sample.json",
    "etd": "etd_RICH.json",
    "depart": "depart_ASHB_CIVC.json",
    "stns": "stns.json",
    "stnaccess": "stnaccess_12TH.json",
}


class BartUnavailable(RuntimeError):
    """The live BART API could not be reached or returned something unusable."""


# --- payload helpers ------------------------------------------------------------------------
def _text(value: Any) -> str:
    """BART wraps free text as {"#cdata-section": "..."}; sometimes it is a bare string."""
    if isinstance(value, dict):
        return str(value.get("#cdata-section", "")).strip()
    return "" if value is None else str(value).strip()


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


_PREAMBLE = re.compile(r"^.*?out of service at this time:\s*", re.IGNORECASE | re.DOTALL)
_SPLIT = re.compile(r"\s*[;,]\s*(?=[A-Z0-9]{4}:\s)")
_NO_OUTAGE = re.compile(r"(no elevators?\b.*out of service|all elevators are in service)", re.IGNORECASE)


def outage_fragments(description: str) -> list[str]:
    """Split BART's elevator advisory text into one fragment per elevator.

    'There is 1 elevator out of service at this time: DELN: Platform - Richmond'
        -> ['DELN: Platform - Richmond']
    Multiple outages are separated by ';' or ',' before the next 4-character station code.
    Text with no outage yields []. Fragment *meaning* (levels, platform) is parsed later (B3).
    """
    text = description.strip()
    if not text or _NO_OUTAGE.search(text):
        return []
    m = _PREAMBLE.match(text)
    body = text[m.end() :] if m else text
    if not m and not re.match(r"^[A-Z0-9]{4}:\s", body):
        return []
    return [frag.strip().rstrip(".") for frag in _SPLIT.split(body) if frag.strip()]


@dataclass(frozen=True)
class ElevatorAdvisory:
    id: str
    station: str
    type: str
    description: str
    sms_text: str
    posted: str
    expires: str

    @property
    def fragments(self) -> list[str]:
        return outage_fragments(self.description)


def parse_elevator_advisories(payload: dict[str, Any]) -> list[ElevatorAdvisory]:
    root = payload["root"]
    out = []
    for item in _as_list(root.get("bsa")):
        out.append(
            ElevatorAdvisory(
                id=str(item.get("@id", "")),
                station=_text(item.get("station")),
                type=_text(item.get("type")),
                description=_text(item.get("description")),
                sms_text=_text(item.get("sms_text")),
                posted=_text(item.get("posted")),
                expires=_text(item.get("expires")),
            )
        )
    return out


def parse_stations(payload: dict[str, Any]) -> list[dict[str, str]]:
    stations = _as_list(payload["root"]["stations"]["station"])
    return [{"name": _text(s.get("name")), "abbr": _text(s.get("abbr")).upper()} for s in stations]


@dataclass(frozen=True)
class Trip:
    origin: str
    destination: str
    orig_time: str
    dest_time: str
    orig_date: str
    trip_time_min: int
    legs: int
    train_head_stations: tuple[str, ...]


def parse_depart(payload: dict[str, Any]) -> list[Trip]:
    root = payload["root"]
    trips = _as_list(root["schedule"]["request"]["trip"])
    out = []
    for t in trips:
        legs = _as_list(t.get("leg"))
        out.append(
            Trip(
                origin=str(t.get("@origin", "")).upper(),
                destination=str(t.get("@destination", "")).upper(),
                orig_time=str(t.get("@origTimeMin", "")).strip(),
                dest_time=str(t.get("@destTimeMin", "")).strip(),
                orig_date=str(t.get("@origTimeDate", "")).strip(),
                trip_time_min=int(str(t.get("@tripTime", "0")).strip() or 0),
                legs=len(legs),
                train_head_stations=tuple(str(leg.get("@trainHeadStation", "")) for leg in legs),
            )
        )
    return out


def parse_etd(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten real-time estimates: one row per (destination, estimate)."""
    rows = []
    for station in _as_list(payload["root"].get("station")):
        for etd in _as_list(station.get("etd")):
            for est in _as_list(etd.get("estimate")):
                minutes = str(est.get("minutes", "")).strip()
                rows.append(
                    {
                        "station": _text(station.get("abbr")).upper(),
                        "destination": _text(etd.get("abbreviation")).upper(),
                        "minutes": 0 if minutes.lower() == "leaving" else int(minutes or 0),
                        "platform": str(est.get("platform", "")),
                        "direction": str(est.get("direction", "")),
                    }
                )
    return rows


# --- client --------------------------------------------------------------------------------
class BartClient:
    """Fixtures by default; live only with an API key (env ``BART_API_KEY`` or ``api_key=``)."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        fixtures_dir: Path = FIXTURES_DIR,
        timeout: float = 20.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("BART_API_KEY") or None
        self.fixtures_dir = Path(fixtures_dir)
        self.timeout = timeout
        self._ssl = ssl.create_default_context(cafile=certifi.where())

    @property
    def live(self) -> bool:
        return bool(self.api_key)

    @property
    def mode(self) -> str:
        return "live" if self.live else "fixtures"

    def _load_fixture(
        self, key: str, fixture: Path | None, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        if fixture:
            path = Path(fixture)
        elif key == "depart" and params:
            # One fixture per station pair, so no trip ever gets another pair's head stations or times.
            path = self.fixtures_dir / f"depart_{params['orig']}_{params['dest']}.json"
            if not path.exists():
                pair = f"{params['orig']}->{params['dest']}"
                raise BartUnavailable(f"no schedule fixture for {pair} ({path.name})")
        else:
            path = self.fixtures_dir / DEFAULT_FIXTURES[key]
        return json.loads(path.read_text())

    def _request(
        self, endpoint: str, params: dict[str, str], key: str, fixture: Path | None
    ) -> dict[str, Any]:
        if not self.live:
            return self._load_fixture(key, fixture, params)
        query = urllib.parse.urlencode({**params, "key": self.api_key, "json": "y"})
        req = urllib.request.Request(f"{BASE_URL}{endpoint}?{query}", headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            detail = f"{type(exc).__name__}: {str(exc)[:160]}".replace(self.api_key or "\0", "***")
            msg = f"BART {endpoint} cmd={params.get('cmd')} unavailable ({detail})"
            log.warning(msg)
            raise BartUnavailable(msg) from None

    # --- endpoints ------------------------------------------------------------------------
    def elevators(self, *, fixture: Path | None = None) -> dict[str, Any]:
        return self._request("bsa.aspx", {"cmd": "elev"}, "elev", fixture)

    def advisories(self, *, fixture: Path | None = None) -> dict[str, Any]:
        return self._request("bsa.aspx", {"cmd": "bsa"}, "bsa", fixture)

    def etd(self, orig: str, *, fixture: Path | None = None) -> dict[str, Any]:
        return self._request("etd.aspx", {"cmd": "etd", "orig": orig.upper()}, "etd", fixture)

    def depart(
        self,
        orig: str,
        dest: str,
        *,
        date: str = "now",
        time: str = "now",
        before: int = 2,
        after: int = 2,
        fixture: Path | None = None,
    ) -> dict[str, Any]:
        params = {
            "cmd": "depart",
            "orig": orig.upper(),
            "dest": dest.upper(),
            "date": date,
            "time": time,
            "b": str(before),
            "a": str(after),
            "l": "1",
        }
        return self._request("sched.aspx", params, "depart", fixture)

    def stations(self, *, fixture: Path | None = None) -> dict[str, Any]:
        return self._request("stn.aspx", {"cmd": "stns"}, "stns", fixture)

    def station_access(self, orig: str, *, fixture: Path | None = None) -> dict[str, Any]:
        params = {"cmd": "stnaccess", "orig": orig.upper(), "l": "1"}
        return self._request("stn.aspx", params, "stnaccess", fixture)

    # --- convenience --------------------------------------------------------------------
    def elevator_advisories(self, *, fixture: Path | None = None) -> list[ElevatorAdvisory]:
        return parse_elevator_advisories(self.elevators(fixture=fixture))

    def trips(self, orig: str, dest: str, **kwargs: Any) -> list[Trip]:
        return parse_depart(self.depart(orig, dest, **kwargs))
