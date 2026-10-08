"""Load JSON rule packs and match them against LogEvents."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from adaslog.core.config import load_json_resource
from adaslog.core.errors import RuleLoadError
from adaslog.models import Anomaly, LogEvent

PACK_FILES = [
    "android_common.json",
    "binder_ipc.json",
    "state_machine.json",
    "communication.json",
]


def load_rule_packs(rules_dir: Path | None = None) -> list[dict]:
    rules: list[dict] = []
    for name in PACK_FILES:
        if rules_dir is not None:
            path = Path(rules_dir) / name
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuleLoadError(f"{path}: {exc}") from exc
        else:
            try:
                data = load_json_resource(f"rules/{name}")
            except FileNotFoundError:
                continue
        for rule in data.get("rules", []):
            rule["_pack"] = name
            rules.append(rule)
    return rules


def _haystack(ev: LogEvent) -> str:
    parts = [ev.message]
    if ev.stacktrace:
        parts.extend(ev.stacktrace[:20])
    if ev.extra.get("exception_class"):
        parts.append(str(ev.extra["exception_class"]))
    return "\n".join(parts)


def match_event(ev: LogEvent, rules: Iterable[dict]) -> list[Anomaly]:
    text = _haystack(ev)
    text_l = text.lower()
    hits: list[Anomaly] = []
    for rule in rules:
        levels = rule.get("levels")
        if levels and ev.level and ev.level not in levels:
            continue
        tags = rule.get("tags")
        if tags and (ev.tag or "") not in tags and (ev.raw_tag or "") not in tags:
            continue
        any_need = rule.get("any") or []
        all_need = rule.get("all") or []
        matched = None
        if any_need:
            for needle in any_need:
                if needle.lower() in text_l or needle in text:
                    matched = needle
                    break
            if matched is None:
                continue
        if all_need and not all((n.lower() in text_l or n in text) for n in all_need):
            continue
        if not any_need and not all_need:
            continue
        hits.append(
            Anomaly(
                id="",
                kind=rule.get("kind", rule["id"]),
                category=rule.get("category", "UNKNOWN"),
                severity=rule.get("severity", "MEDIUM"),
                event_id=ev.id,
                rule_id=rule["id"],
                matched_text=(matched or all_need[0])[:160],
                score=float(rule.get("score", 1.0)),
                description=rule.get("description", ""),
                event_ids=[ev.id],
            )
        )
    return hits


def collapse_repeats(anomalies: list[Anomaly], events: list[LogEvent]) -> list[Anomaly]:
    """Collapse identical (rule_id, matched_text, tag) bursts into one anomaly with repeat_count."""
    by_key: dict[tuple, Anomaly] = {}
    order: list[tuple] = []
    ev_by_id = {e.id: e for e in events}
    for an in anomalies:
        ev = ev_by_id.get(an.event_id)
        tag = ev.tag if ev else ""
        pid = ev.pid if ev else None
        bucket = (ev.ts_ms // 30_000) if ev and ev.ts_ms is not None else None
        key = (an.rule_id, an.matched_text, tag, pid, bucket)
        if key not in by_key:
            by_key[key] = an
            order.append(key)
        else:
            existing = by_key[key]
            existing.repeat_count += 1
            if an.event_id not in existing.event_ids:
                existing.event_ids.append(an.event_id)
    out = [by_key[k] for k in order]
    for i, an in enumerate(out, start=1):
        an.id = f"A{i}"
    return out
