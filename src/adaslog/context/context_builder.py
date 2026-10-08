"""Windows around key evidence + a simple causal chain."""
from __future__ import annotations

from adaslog.models import CausalLink, ContextWindow, Evidence, LogEvent, TimelineEntry
from adaslog.utils.timeparse import parse_timestamp


def _nearby(events: list[LogEvent], anchor: LogEvent, lines: int, seconds: float) -> tuple[list[LogEvent], list[LogEvent]]:
    before, after = [], []
    a_ms = anchor.ts_ms or (parse_timestamp(anchor.timestamp) if anchor.timestamp else None)
    for ev in events:
        if ev.id == anchor.id:
            continue
        if ev.line_no < anchor.line_no:
            if anchor.line_no - ev.line_no <= lines:
                if a_ms is None or ev.ts_ms is None or (a_ms - ev.ts_ms) <= seconds * 1000:
                    before.append(ev)
        elif ev.line_no > anchor.line_no:
            if ev.line_no - anchor.line_no <= lines:
                if a_ms is None or ev.ts_ms is None or (ev.ts_ms - a_ms) <= seconds * 1000:
                    after.append(ev)
    return before[-lines:], after[:lines]


_CHAIN_ORDER = [
    "connection established",
    "service started",
    "binder transaction failed",
    "DeadObjectException",
    "onServiceDisconnected",
    "onServiceDisConnected",
    "service disconnected",
    "retry failed",
    "未定义的状态转换",
    "队列为空",
]


def build_context(
    events: list[LogEvent],
    evidence: list[Evidence],
    cfg: dict | None = None,
) -> tuple[list[TimelineEntry], list[CausalLink], list[ContextWindow]]:
    cfg = (cfg or {}).get("context", {})
    window_lines = int(cfg.get("window_lines", 12))
    window_seconds = float(cfg.get("window_seconds", 3.0))
    max_anchors = int(cfg.get("max_anchors", 8))

    by_id = {e.id: e for e in events}
    timeline: list[TimelineEntry] = []
    for evd in evidence:
        ev = by_id.get(evd.event_id) if evd.event_id is not None else None
        timeline.append(
            TimelineEntry(
                timestamp=evd.timestamp or (ev.timestamp if ev else None),
                line_no=evd.line_no or (ev.line_no if ev else 0),
                event_id=evd.event_id if evd.event_id is not None else -1,
                label=f"{evd.category}: {(evd.text[:120])}",
                evidence_id=evd.id,
            )
        )
    timeline.sort(key=lambda t: (t.timestamp or "", t.line_no))

    links: list[CausalLink] = []
    for a, b in zip(timeline, timeline[1:]):
        if a.evidence_id and b.evidence_id:
            links.append(CausalLink(a.evidence_id, b.evidence_id, "precedes"))

    windows: list[ContextWindow] = []
    for evd in evidence[:max_anchors]:
        if evd.event_id is None:
            continue
        ev = by_id.get(evd.event_id)
        if ev is None:
            continue
        before, after = _nearby(events, ev, window_lines, window_seconds)
        windows.append(
            ContextWindow(
                anchor_evidence_id=evd.id,
                anchor_event_id=ev.id,
                before=[x.short(140) for x in before],
                after=[x.short(140) for x in after],
            )
        )
    return timeline, links, windows
