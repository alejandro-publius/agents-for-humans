"""Trip matcher and policy engine. Pure code, no model. Decides whether an outage affects a
rider's trip, which condition applies, and ranks options in BART's published order."""

from policy.engine import Decision, Outage, RankedOption, Trip, assess, assess_condition
from policy.preferences import LocalJsonPreferenceStore, Preferences, preference_store
from policy.sun import is_after_dark, sunset_local

__all__ = [
    "LocalJsonPreferenceStore",
    "Preferences",
    "preference_store",
    "Decision",
    "Outage",
    "RankedOption",
    "Trip",
    "assess",
    "assess_condition",
    "is_after_dark",
    "sunset_local",
]
