from __future__ import annotations

from adaslog.detector.rules_engine import collapse_repeats, load_rule_packs, match_event
from adaslog.models import Anomaly, LogEvent


def detect_anomalies(events: list[LogEvent], collapse: bool = True) -> list[Anomaly]:
    rules = load_rule_packs()
    hits: list[Anomaly] = []
    for ev in events:
        hits.extend(match_event(ev, rules))
    if collapse:
        return collapse_repeats(hits, events)
    for i, an in enumerate(hits, start=1):
        an.id = f"A{i}"
    return hits
