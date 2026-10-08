"""Split anomalies into per-process / per-gap incidents. Time order is precedence, not causation."""
from __future__ import annotations

from dataclasses import dataclass, field

from adaslog.models import Anomaly, Evidence, Incident, LogEvent, RootCauseCandidate

GAP_MS = 60_000
SPAN_SLACK_MS = 2_000


@dataclass
class IncidentDraft:
    anomalies: list[Anomaly]
    pid: int | None
    issue_type: str
    event_ids: set[int] = field(default_factory=set)
    start_ts: str | None = None
    end_ts: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    module: str | None = None


def group_anomalies(anomalies: list[Anomaly], events: list[LogEvent]) -> list[IncidentDraft]:
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

    drafts: list[IncidentDraft] = []
    for key in order:
        ans = groups[key]
        evs = [by_id[a.event_id] for a in ans if a.event_id in by_id]
        event_ids: set[int] = set()
        for a in ans:
            event_ids.add(a.event_id)
            event_ids.update(a.event_ids or [])
        start_ms = next((e.ts_ms for e in evs if e.ts_ms is not None), None)
        end_ms = next((e.ts_ms for e in reversed(evs) if e.ts_ms is not None), None)
        drafts.append(
            IncidentDraft(
                anomalies=ans,
                pid=evs[0].pid if evs else None,
                issue_type=ans[0].category,
                event_ids=event_ids,
                start_ts=evs[0].timestamp if evs else None,
                end_ts=evs[-1].timestamp if evs else None,
                start_ms=start_ms,
                end_ms=end_ms,
                module=next((e.module for e in evs if e.module), None),
            )
        )
    return drafts


def events_for_draft(draft: IncidentDraft, events: list[LogEvent]) -> list[LogEvent]:
    """Events belonging to this incident: its anomaly events plus same-pid neighbours in the span."""
    out: list[LogEvent] = []
    lo = (draft.start_ms - SPAN_SLACK_MS) if draft.start_ms is not None else None
    hi = (draft.end_ms + SPAN_SLACK_MS) if draft.end_ms is not None else None
    for e in events:
        if e.id in draft.event_ids:
            out.append(e)
            continue
        if draft.pid is not None and e.pid == draft.pid:
            if lo is None or e.ts_ms is None or (lo <= e.ts_ms <= hi):
                out.append(e)
    return out


def to_incident(
    draft: IncidentDraft,
    index: int,
    evidence_ids: list[str],
    root_causes: list[RootCauseCandidate],
    unknowns: list[str],
) -> Incident:
    return Incident(
        id=f"I{index}",
        issue_type=draft.issue_type,
        confidence=min(0.97, 0.4 + sum(a.score for a in draft.anomalies) / 20.0),
        pid=draft.pid,
        module=draft.module,
        start_ts=draft.start_ts,
        end_ts=draft.end_ts,
        evidence_ids=evidence_ids,
        summary=(
            f"pid={draft.pid} {draft.issue_type} ×{sum(a.repeat_count for a in draft.anomalies)} "
            f"{draft.start_ts}..{draft.end_ts}（时序仅表示先于）"
        ),
        root_causes=root_causes,
        unknowns=unknowns,
        related_incident_ids=[],
    )


def build_incidents(
    anomalies: list[Anomaly],
    events: list[LogEvent],
    primary_type: str,
    evidence: list[Evidence] | list[str],
    root_causes: list[RootCauseCandidate],
) -> list[Incident]:
    """Backward-compatible wrapper. Prefer per-incident analysis in the pipeline."""
    drafts = group_anomalies(anomalies, events)
    incidents: list[Incident] = []
    for i, draft in enumerate(drafts, start=1):
        if evidence and isinstance(evidence[0], str):
            ev_ids = list(evidence) if draft.issue_type == primary_type else []
        else:
            ev_ids = [e.id for e in evidence if e.event_id in draft.event_ids]
        rcs = [rc for rc in root_causes if set(rc.evidence_ids) <= set(ev_ids)] if ev_ids else []
        if draft.issue_type == primary_type and not rcs and ev_ids:
            # keep only candidates whose ids are a subset; otherwise leave empty (caller should attach)
            rcs = []
        incidents.append(to_incident(draft, i, ev_ids, rcs, [] if ev_ids else ["该故障事件未能关联到独立证据编号。"]))
    if not incidents and primary_type not in ("NORMAL",):
        if evidence and evidence and isinstance(evidence[0], str):
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
