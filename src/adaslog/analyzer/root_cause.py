"""Deterministic (offline) root-cause candidates. Evidence ids only."""
from __future__ import annotations

from adaslog.models import (
    Classification,
    CodeHit,
    Evidence,
    RootCauseCandidate,
    SignalSummary,
)


def build_rule_candidates(
    classification: Classification,
    evidence: list[Evidence],
    signal_summary: SignalSummary | None,
    code_hits: list[CodeHit],
) -> list[RootCauseCandidate]:
    ev_ids = [e.id for e in evidence]
    itype = classification.issue_type

    if itype == "NORMAL":
        return []

    if itype == "UNKNOWN" or not ev_ids:
        return [
            RootCauseCandidate(
                title="UNKNOWN",
                status="UNKNOWN",
                confidence="LOW",
                evidence_ids=ev_ids[:3],
                reasoning="证据不足。",
                reason="证据不足。",
                need_verification=[
                    "请提供更长的时间窗、异常堆栈，或复现该症状的模块日志。"
                ],
                source="rule",
            )
        ]

    conf = "HIGH" if classification.confidence >= 0.75 else "MEDIUM" if classification.confidence >= 0.45 else "LOW"

    if itype == "SIGNAL_NOT_TRIGGERED":
        idle = [e for e in evidence if e.category in ("signal_idle", "text_idle")]
        ids = [e.id for e in idle] or ev_ids[:4]
        fields = []
        if signal_summary:
            fields = [f"{p.struct}.{p.field}={p.value}" for p in signal_summary.focus if p.value in ("0", "0.0")]
        title = "焦点信号保持为 0，对应驾驶文言未入队（Profile 将空闲/0 映射为 NO_TEXT）。"
        return [
            RootCauseCandidate(
                title=title,
                status="CANDIDATE",
                confidence="HIGH" if fields and any(e.category == "text_idle" for e in evidence) else conf,
                evidence_ids=ids,
                reasoning=(
                    "E02 driving_text_tip 的 Handler 仅在 Profile.map*(value) 返回文言 ID 时调用 addTextToQueue。"
                    "值为 0 时映射为 NO_TEXT。观测到的空闲字段："
                    + ("、".join(fields) if fields else "（见证据）")
                    + f"。DrivingTextManager 触发次数={getattr(signal_summary, 'text_manager_trigger_count', 0)}，"
                    f"空闲次数={getattr(signal_summary, 'text_manager_idle_count', 0)}。"
                ),
                need_verification=[
                    "确认该时间窗内焦点信号是否本应出现非 0 值。",
                    "若信号本应非 0，请排查 VDS / SOME-IP 发布端，而不是文言管理器。",
                ],
                source="rule",
            )
        ]

    title_map = {
        "CRASH": "进程崩溃（Fatal 异常 / native abort）。",
        "EXCEPTION": "诊断路径上出现已捕获或已打印的异常。",
        "BINDER_IPC": "Binder/IPC 事务失败或远端服务已死亡。",
        "STATE_MACHINE": "状态机发生未定义或非法转换。",
        "MODULE_COMMUNICATION": "跨模块通信失败（Kanzi / gRPC / 总线 / 超时）。",
        "SYSTEM_ERROR": "伴随症状出现了 Android 系统级错误。",
        "ANR": "应用无响应（主线程阻塞）。",
        "PERFORMANCE": "出现掉帧或慢操作。",
        "BUSINESS_ERROR": "未崩溃的业务级错误。",
    }
    verify_map = {
        "CRASH": ["用 --source 打开第一个应用堆栈帧，检查空指针或非法状态。"],
        "BINDER_IPC": ["检查远端服务进程是否死亡，以及失败的 AIDL 接口。"],
        "STATE_MACHINE": ["按 (状态, 事件) 对照 StateMachine 转换表回放。"],
        "MODULE_COMMUNICATION": ["确认对端进程当时存活，且失败前连接已建立。"],
        "SIGNAL_NOT_TRIGGERED": ["检查发布端是否曾经发出过非 0 值。"],
    }
    extra = ""
    if code_hits:
        h = code_hits[0]
        extra = f" 首个代码命中：{h.file}:{h.line} {h.symbol}。"
        ev_ids = list(dict.fromkeys(ev_ids + h.evidence_ids))
    return [
        RootCauseCandidate(
            title=title_map.get(itype, itype),
            status="CANDIDATE",
            confidence=conf,
            evidence_ids=ev_ids[:8],
            reasoning=classification.reason + extra,
            need_verification=verify_map.get(itype, ["在首条错误附近采集更长日志。"]),
            source="rule",
        )
    ]
