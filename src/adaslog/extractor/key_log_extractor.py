"""Pick the log lines that actually matter for diagnosis (not a raw keyword dump)."""
from __future__ import annotations

from adaslog.models import Anomaly, Evidence, LogEvent, SignalSummary

_KIND_TO_CATEGORY = {
    "FATAL_EXCEPTION": "fatal",
    "NATIVE_CRASH": "crash",
    "FORCE_FINISH": "crash",
    "JAVA_EXCEPTION": "first_exception",
    "ANR": "anr",
    "BINDER_DEAD_OBJECT": "binder_failure",
    "BINDER_REMOTE_EXCEPTION": "binder_failure",
    "SERVICE_DISCONNECTED": "service_disconnected",
    "STATE_ILLEGAL_TRANSITION": "state_transition_failure",
    "GRPC_FAILURE": "communication_failure",
    "KANZI_DISCONNECT": "communication_failure",
    "TIMEOUT": "timeout",
    "BUS_FAILURE": "communication_failure",
    "SYSTEM_ERROR": "system_error",
    "JANK": "key_warning",
    "STATE_IGNORED_EVENT": "key_warning",
    "BINDER_DEATH_RECIPIENT": "key_warning",
}

_WHY = {
    "first_error": "时间窗内第一条 ERROR，通常是最早症状。",
    "first_exception": "第一条带堆栈的异常。",
    "fatal": "Fatal 异常，进程即将退出。",
    "crash": "崩溃后的进程死亡或强制结束界面。",
    "binder_failure": "服务之间的 Binder/IPC 失败。",
    "service_disconnected": "远端服务连接断开。",
    "state_transition_failure": "状态机拒绝或从非法转换中恢复。",
    "timeout": "等待超过截止时间。",
    "communication_failure": "跨模块通信失败。",
    "anr": "应用无响应（ANR）。",
    "key_warning": "位于因果链上的关键告警。",
    "signal_idle": "焦点信号保持空闲值 0；Profile 将其映射为 NO_TEXT。",
    "text_idle": "DrivingTextManager 报告队列为空且无当前显示。",
    "text_trigger": "DrivingTextManager 实际入队或显示了文言。",
}


def _add(
    out: list[Evidence],
    ev: LogEvent | None,
    category: str,
    text: str,
    extra_ids: list[int] | None = None,
    repeats: int = 1,
) -> None:
    eid = f"E{len(out) + 1}"
    out.append(
        Evidence(
            id=eid,
            label="EVIDENCE",
            category=category,
            event_id=ev.id if ev else None,
            text=text,
            why_it_matters=_WHY.get(category, "与本次诊断相关。"),
            line_no=ev.line_no if ev else None,
            timestamp=ev.timestamp if ev else None,
            repeat_count=repeats,
            related_event_ids=extra_ids or ([ev.id] if ev else []),
        )
    )


def extract_evidence(
    events: list[LogEvent],
    anomalies: list[Anomaly],
    signal_summary: SignalSummary | None = None,
    max_items: int = 25,
) -> list[Evidence]:
    out: list[Evidence] = []
    used_event_ids: set[int] = set()
    by_id = {e.id: e for e in events}

    first_error = next((e for e in events if e.level in ("E", "F")), None)
    if first_error:
        _add(out, first_error, "first_error", first_error.short(200))
        used_event_ids.add(first_error.id)

    first_exc = next(
        (e for e in events if e.has_stacktrace or e.extra.get("exception_class") or e.extra.get("fatal")),
        None,
    )
    if first_exc and first_exc.id not in used_event_ids:
        cls = first_exc.extra.get("exception_class", "exception")
        _add(out, first_exc, "first_exception", f"{cls}: {first_exc.message[:160]}")
        used_event_ids.add(first_exc.id)

    # Rank anomalies: fatal / crash / binder / state first
    kind_rank = {
        "FATAL_EXCEPTION": 0, "NATIVE_CRASH": 1, "ANR": 2, "BINDER_DEAD_OBJECT": 3,
        "STATE_ILLEGAL_TRANSITION": 4, "SERVICE_DISCONNECTED": 5, "JAVA_EXCEPTION": 6,
    }
    ordered = sorted(anomalies, key=lambda a: (kind_rank.get(a.kind, 20), -a.score, a.event_id))
    for an in ordered:
        if len(out) >= max_items:
            break
        if an.event_id in used_event_ids and an.kind not in (
            "FATAL_EXCEPTION",
            "ANR",
            "STATE_ILLEGAL_TRANSITION",
            "BINDER_DEAD_OBJECT",
            "BINDER_REMOTE_EXCEPTION",
            "SERVICE_DISCONNECTED",
            "JAVA_EXCEPTION",
            "GRPC_FAILURE",
            "TIMEOUT",
            "BUS_FAILURE",
        ):
            continue
        ev = by_id.get(an.event_id)
        if ev is None:
            continue
        cat = _KIND_TO_CATEGORY.get(an.kind, "key_warning")
        extra = f" (x{an.repeat_count})" if an.repeat_count > 1 else ""
        _add(out, ev, cat, f"[{an.kind}] {ev.short(180)}{extra}", an.event_ids, an.repeat_count)
        used_event_ids.add(an.event_id)

    if signal_summary:
        for period in signal_summary.focus:
            if len(out) >= max_items:
                break
            ev = next((e for e in events if e.line_no == period.first_line), None)
            _add(
                out,
                ev,
                "signal_idle" if period.value in ("0", "0.0") else "key_warning",
                (
                    f"{period.struct}.{period.field}={period.value}，"
                    f"{period.start_ts} 至 {period.end_ts}"
                    f"（{period.samples} 次采样，第 {period.first_line}-{period.last_line} 行）"
                ),
            )
        if signal_summary.text_manager_idle_count:
            idle_ev = next(
                (e for e in events if e.tag == "DrivingTextManager" and "队列为空" in e.message),
                None,
            )
            _add(
                out,
                idle_ev,
                "text_idle",
                f"DrivingTextManager 空闲 ×{signal_summary.text_manager_idle_count}"
                f"（队列为空，等待新文言触发）。",
                repeats=signal_summary.text_manager_idle_count,
            )
        if signal_summary.text_manager_trigger_count:
            trig = next(
                (
                    e for e in events
                    if e.tag == "DrivingTextManager"
                    and any(k in e.message for k in ("加入队列", "显示文言", "变化: "))
                ),
                None,
            )
            _add(
                out,
                trig,
                "text_trigger",
                f"DrivingTextManager 入队/显示文言 ×{signal_summary.text_manager_trigger_count}。",
                repeats=signal_summary.text_manager_trigger_count,
            )

    return out[:max_items]
