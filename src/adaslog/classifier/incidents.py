"""Split anomalies into per-process / per-gap incidents. Time order is precedence, not causation."""
from __future__ import annotations

from adaslog.models import Anomaly, Evidence, Incident, LogEvent, RootCauseCandidate

GAP_MS = 60_000


def build_incidents(
    anomalies: list[Anomaly],
    events: list[LogEvent],
    primary_type: str,
    evidence: list[Evidence] | list[str],
    root_causes: list[RootCauseCandidate],
) -> list[Incident]:
    by_id = {e.id: e for e in events}
    groups: dict[tuple, list[Anomaly]] = {}
    order: list[tuple] = []
    last_key: dict[tuple, tuple] = {}
    for an in anomalies:
        ev = by_id.get(an.event_id)
        pid = ev.pid if ev else None
        ts = ev.ts_ms if ev else None
        base = (pid, an.category)
        key = last_key.get(base, base)
        if key not in groups:
            groups[key] = []
            order.append(key)
        bucket = groups[key]
        if bucket:
            prev = by_id.get(bucket[-1].event_id)
            prev_ts = prev.ts_ms if prev else None
            if ts is not None and prev_ts is not None and abs(ts - prev_ts) > GAP_MS:
                key = (pid, an.category, an.event_id)
                groups[key] = []
                order.append(key)
        groups[key].append(an)
        last_key[base] = key

    incidents: list[Incident] = []
    for i, key in enumerate(order, start=1):
        ans = groups[key]
        evs = [by_id[a.event_id] for a in ans if a.event_id in by_id]
        start = evs[0].timestamp if evs else None
        end = evs[-1].timestamp if evs else None
        pid = evs[0].pid if evs else None
        module = next((e.module for e in evs if e.module), None)
        itype = ans[0].category
        event_ids = set()
        for a in ans:
            event_ids.add(a.event_id)
            event_ids.update(a.event_ids or [])
        if evidence and isinstance(evidence[0], str):
            ev_ids = list(evidence) if itype == primary_type else []
        else:
            ev_ids = [e.id for e in evidence if e.event_id in event_ids]
        incidents.append(
            Incident(
                id=f"I{i}",
                issue_type=itype,
                confidence=min(0.97, 0.4 + sum(a.score for a in ans) / 20.0),
                pid=pid,
                module=module,
                start_ts=start,
                end_ts=end,
                evidence_ids=ev_ids,
                summary=f"pid={pid} {itype} ×{sum(a.repeat_count for a in ans)} {start}..{end}（时序仅表示先于）",
                root_causes=root_causes if itype == primary_type else [],
                unknowns=[] if ev_ids else ["该故障事件未能关联到独立证据编号。"],
            )
        )
    if not incidents and primary_type not in ("NORMAL",):
        if evidence and isinstance(evidence[0], str):
            ev_ids = list(evidence)
        else:
            ev_ids = [e.id for e in evidence]
        incidents.append(
            Incident(
                id="I1",
                issue_type=primary_type,
                confidence=0.3,
                pid=None,
                module=None,
                start_ts=None,
                end_ts=None,
                evidence_ids=ev_ids,
                summary=primary_type,
                root_causes=root_causes,
            )
        )
    return incidents
