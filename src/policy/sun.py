"""Local sunset for the after-dark flag. Standard sunrise equation (US Naval Observatory
almanac form), accurate to a few minutes, which is all a flag needs. Default location is
Oakland (37.8044, -122.2712); time zone America/Los_Angeles."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

OAKLAND_LAT = 37.8044
OAKLAND_LON = -122.2712
PACIFIC = ZoneInfo("America/Los_Angeles")
ZENITH = 90.833  # official sunset, degrees


def sunset_local(day: date, lat: float = OAKLAND_LAT, lon: float = OAKLAND_LON) -> datetime:
    """Sunset on ``day`` as an aware datetime in America/Los_Angeles."""
    n = day.timetuple().tm_yday
    lng_hour = lon / 15.0
    t = n + ((18.0 - lng_hour) / 24.0)
    m = (0.9856 * t) - 3.289
    lsun = m + (1.916 * math.sin(math.radians(m))) + (0.020 * math.sin(math.radians(2 * m))) + 282.634
    lsun %= 360.0
    ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(lsun)))) % 360.0
    lquadrant = math.floor(lsun / 90.0) * 90.0
    raquadrant = math.floor(ra / 90.0) * 90.0
    ra = (ra + (lquadrant - raquadrant)) / 15.0
    sin_dec = 0.39782 * math.sin(math.radians(lsun))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(math.radians(ZENITH)) - (sin_dec * math.sin(math.radians(lat)))) / (
        cos_dec * math.cos(math.radians(lat))
    )
    cos_h = max(-1.0, min(1.0, cos_h))
    h = math.degrees(math.acos(cos_h)) / 15.0
    t_local = h + ra - (0.06571 * t) - 6.622
    ut = (t_local - lng_hour) % 24.0
    base = datetime(day.year, day.month, day.day, tzinfo=UTC)
    local = (base + timedelta(hours=ut)).astimezone(PACIFIC)
    # Sunset in California falls after 00:00 UTC of the next day, so the UTC arithmetic can land on
    # the previous local date. Pin the result to the requested local date.
    if local.date() < day:
        local += timedelta(days=1)
    elif local.date() > day:
        local -= timedelta(days=1)
    return local


def is_after_dark(when: datetime, lat: float = OAKLAND_LAT, lon: float = OAKLAND_LON) -> bool:
    """True if ``when`` (aware, any tz) is at or after local sunset that day."""
    local = when.astimezone(PACIFIC)
    return local >= sunset_local(local.date(), lat, lon)
