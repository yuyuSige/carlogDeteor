"""Aggregate anomalies (+ optional signal finding) into one IssueType."""
from __future__ import annotations

from collections import defaultdict

from adaslog.models import Anomaly, Classification, LogEvent, SignalSummary

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


def _signal_idle_mapped(signal_summary: SignalSummary | None) -> bool:
    if signal_summary is None or not signal_summary.field_status:
        return False
    if any(s.observation == "saw_trigger" for s in signal_summary.field_status):
        return False
    return any(
        s.mapped and s.observation == "idle_entire_window"
        for s in signal_summary.field_status
    )


def classify(
    anomalies: list[Anomaly],
    events: list[LogEvent],
    signal_summary: SignalSummary | None = None,
    cfg: dict | None = None,
    data_status: str = "ok",
) -> Classification:
    cfg = cfg or {}
    th = cfg.get("classifier", {})
    min_specific = float(th.get("min_specific_score", 2.0))
    unknown_c = float(th.get("unknown_confidence", 0.3))

    if data_status in ("empty", "filter_empty") or not events:
        reason = (
            "过滤后没有有效事件，无法区分“正常”与“无数据”。"
            if data_status == "filter_empty"
            else "日志没有可分析的事件（空文件或无可解析行）。"
        )
        return Classification(
            issue_type="UNKNOWN",
            confidence=unknown_c,
            evidence_ids=[],
            scores={},
            reason=reason,
            data_status=data_status if data_status != "ok" else "empty",
        )

    scores: dict[str, float] = defaultdict(float)
    evidence_by_cat: dict[str, list[int]] = defaultdict(list)

    for an in anomalies:
        weight = an.score * (1.0 + 0.05 * min(an.repeat_count - 1, 10))
        scores[an.category] += weight
        evidence_by_cat[an.category].append(an.event_id)

    signal_idle = _signal_idle_mapped(signal_summary)
    if signal_idle:
        scores["SIGNAL_NOT_TRIGGERED"] += 4.0

    if signal_summary and signal_summary.field_status and not scores:
        obs = {s.observation for s in signal_summary.field_status}
        if obs <= {"not_sampled"}:
            return Classification(
                issue_type="UNKNOWN",
                confidence=unknown_c,
                evidence_ids=[],
                scores={},
                reason="指定了焦点信号，但窗口内没有采到该字段。",
                data_status="ok",
            )
        if obs <= {"unknown_mapping", "not_sampled"}:
            return Classification(
                issue_type="UNKNOWN",
                confidence=unknown_c,
                evidence_ids=[],
                scores={},
                reason="焦点字段没有 Profile 映射，不能把 0 解释为 NO_TEXT。",
                data_status="ok",
            )

    if not scores:
        lone_errors = [e for e in events if e.level in ("E", "F")]
        if lone_errors and not any(e.has_stacktrace or e.extra.get("exception_class") for e in lone_errors):
            return Classification(
                issue_type="UNKNOWN",
                confidence=unknown_c,
                evidence_ids=[],
                scores={},
                reason="存在错误级别日志，但没有堆栈、上下文或模块证据。",
                data_status="ok",
            )
        return Classification(
            issue_type="NORMAL",
            confidence=float(th.get("normal_confidence", 0.9)),
            evidence_ids=[],
            scores={},
            reason="窗口内有日志且未匹配到异常，也没有已映射字段的全窗口空闲。",
            data_status="ok",
        )

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], PRIORITY.index(kv[0]) if kv[0] in PRIORITY else 99))
    top_type, top_score = ranked[0]

    if top_type == "EXCEPTION" and top_score < min_specific + 1.0:
        ev_ids = evidence_by_cat.get("EXCEPTION", [])
        if not _has_stack(events, ev_ids) and not signal_idle:
            return Classification(
                issue_type="UNKNOWN",
                confidence=unknown_c,
                evidence_ids=[],
                scores=dict(scores),
                reason="存在类似错误的日志，但没有堆栈、上下文或模块证据。",
            )

    if top_score < min_specific and not signal_idle:
        return Classification(
            issue_type="UNKNOWN",
            confidence=unknown_c,
            evidence_ids=[],
            scores=dict(scores),
            reason="异常得分低于阈值，模式匹配不足。",
        )

    conf = min(0.97, 0.45 + top_score / 12.0)
    return Classification(
        issue_type=top_type,
        confidence=round(conf, 3),
        evidence_ids=[],
        scores=dict(scores),
        reason=f"最高分类为 {top_type}（得分={top_score:.2f}）。分类置信度不等于根因置信度。",
        data_status="ok",
    )
