"""Aggregate anomalies (+ optional signal finding) into one IssueType."""
from __future__ import annotations

from collections import defaultdict

from adaslog.models import Anomaly, Classification, LogEvent, SignalSummary

# Stronger categories win ties. PERFORMANCE is informational and rarely the primary type.
PRIORITY = [
    "CRASH",
    "ANR",
    "BINDER_IPC",
    "STATE_MACHINE",
    "MODULE_COMMUNICATION",
    "EXCEPTION",
    "SYSTEM_ERROR",
    "SIGNAL_NOT_TRIGGERED",
    "BUSINESS_ERROR",
    "PERFORMANCE",
    "UNKNOWN",
    "NORMAL",
]


def _has_stack(events: list[LogEvent], event_ids: list[int]) -> bool:
    by_id = {e.id: e for e in events}
    for eid in event_ids:
        ev = by_id.get(eid)
        if ev and (ev.has_stacktrace or ev.extra.get("exception_class") or ev.extra.get("fatal")):
            return True
    return False


def classify(
    anomalies: list[Anomaly],
    events: list[LogEvent],
    signal_summary: SignalSummary | None = None,
    cfg: dict | None = None,
) -> Classification:
    cfg = cfg or {}
    th = cfg.get("classifier", {})
    min_specific = float(th.get("min_specific_score", 2.0))
    scores: dict[str, float] = defaultdict(float)
    evidence_by_cat: dict[str, list[int]] = defaultdict(list)

    for an in anomalies:
        weight = an.score * (1.0 + 0.05 * min(an.repeat_count - 1, 10))
        scores[an.category] += weight
        evidence_by_cat[an.category].append(an.event_id)

    signal_idle = False
    if signal_summary is not None:
        idle_focus = [p for p in signal_summary.focus if p.value in ("0", "0.0") and p.samples > 0]
        if idle_focus and signal_summary.text_manager_trigger_count == 0 and (
            signal_summary.text_manager_idle_count > 0 or bool(signal_summary.focus)
        ):
            signal_idle = True
            scores["SIGNAL_NOT_TRIGGERED"] += 4.0

    if not scores:
        lone_errors = [e for e in events if e.level in ("E", "F")]
        if lone_errors and not any(e.has_stacktrace or e.extra.get("exception_class") for e in lone_errors):
            return Classification(
                issue_type="UNKNOWN",
                confidence=float(th.get("unknown_confidence", 0.3)),
                evidence_ids=[],
                scores={},
                reason="存在错误级别日志，但没有堆栈、上下文或模块证据。",
            )
        return Classification(
            issue_type="NORMAL",
            confidence=float(th.get("normal_confidence", 0.9)),
            evidence_ids=[],
            scores={},
            reason="未匹配到异常，也没有信号空闲/文言缺失模式。",
        )

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], PRIORITY.index(kv[0]) if kv[0] in PRIORITY else 99))
    top_type, top_score = ranked[0]

    # Vague ERROR without stack / binder / state / comm / crash -> UNKNOWN
    if top_type == "EXCEPTION" and top_score < min_specific + 1.0:
        ev_ids = evidence_by_cat.get("EXCEPTION", [])
        if not _has_stack(events, ev_ids) and not signal_idle:
            return Classification(
                issue_type="UNKNOWN",
                confidence=float(th.get("unknown_confidence", 0.3)),
                evidence_ids=[],
                scores=dict(scores),
                reason="存在类似错误的日志，但没有堆栈、上下文或模块证据。",
            )

    if top_score < min_specific and not signal_idle:
        return Classification(
            issue_type="UNKNOWN",
            confidence=float(th.get("unknown_confidence", 0.3)),
            evidence_ids=[],
            scores=dict(scores),
            reason="异常得分低于阈值，模式匹配不足。",
        )

    # Normalize confidence into 0..1
    conf = min(0.97, 0.45 + top_score / 12.0)
    return Classification(
        issue_type=top_type,
        confidence=round(conf, 3),
        evidence_ids=[],
        scores=dict(scores),
        reason=f"最高分类为 {top_type}（得分={top_score:.2f}）。",
    )
