"""Deterministic (offline) root-cause candidates. Evidence ids only."""
from __future__ import annotations

from adaslog.models import (
    Classification,
    CodeHit,
    Evidence,
    RootCauseCandidate,
    SignalSummary,
)


def _root_conf(classification: Classification, evidence: list[Evidence], extra_ok: bool) -> str:
    """Root-cause confidence is independent of the classifier score."""
    cats = {e.category for e in evidence}
    if classification.issue_type == "CRASH" and ("fatal" in cats or "first_exception" in cats):
        return "HIGH" if extra_ok else "MEDIUM"
    if classification.issue_type == "SIGNAL_NOT_TRIGGERED" and extra_ok:
        return "MEDIUM"
    if classification.issue_type in ("BINDER_IPC", "STATE_MACHINE", "MODULE_COMMUNICATION", "EXCEPTION"):
        return "MEDIUM"
    return "LOW"


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

    if itype == "UNKNOWN" or classification.data_status in ("empty", "filter_empty"):
        return [
            RootCauseCandidate(
                title="UNKNOWN",
                status="UNKNOWN",
                confidence="LOW",
                evidence_ids=ev_ids[:3],
                reasoning=classification.reason or "证据不足。",
                reason="证据不足。",
                need_verification=["请提供包含时间戳的有效日志窗口。"]
                if classification.data_status in ("empty", "filter_empty")
                else ["请提供更长的时间窗、异常堆栈，或复现该症状的模块日志。"],
                source="rule",
            )
        ]

    if itype == "SIGNAL_NOT_TRIGGERED":
        statuses = list(getattr(signal_summary, "field_status", None) or [])
        if any(s.observation == "saw_trigger" for s in statuses):
            triggered = [s.key for s in statuses if s.observation == "saw_trigger"]
            return [
                RootCauseCandidate(
                    title="UNKNOWN",
                    status="UNKNOWN",
                    confidence="LOW",
                    evidence_ids=ev_ids[:4],
                    reasoning="焦点信号出现过映射表中的触发值（" + "、".join(triggered) + "），不能称为全程保持空闲。",
                    reason="证据与“保持为 0”矛盾。",
                    need_verification=["核对触发值出现的时刻是否对应文言。"],
                    source="rule",
                )
            ]
        mapped_idle = [s for s in statuses if s.mapped and s.observation == "idle_entire_window"]
        if not mapped_idle:
            return [
                RootCauseCandidate(
                    title="UNKNOWN",
                    status="UNKNOWN",
                    confidence="LOW",
                    evidence_ids=ev_ids[:3],
                    reasoning="没有已映射字段的全窗口空闲观测；未知字段不能套用 0→NO_TEXT。未见入队日志不能证明未入队。",
                    reason="证据不足。",
                    need_verification=["指定带 Profile 映射的焦点信号，或提供触发值采样。"],
                    source="rule",
                )
            ]
        idle_ev = [e for e in evidence if e.category in ("signal_idle", "text_idle")]
        ids = [e.id for e in idle_ev] or ev_ids[:4]
        fields = [f"{s.key}={s.idle_value}" for s in mapped_idle]
        text_note = "未见入队日志，不能单独证明未入队。"
        return [
            RootCauseCandidate(
                title="已映射焦点信号全窗口为空闲值，按 Profile 不应产生对应文言（候选，非已确认根因）。",
                status="CANDIDATE",
                confidence=_root_conf(classification, evidence, extra_ok=True),
                evidence_ids=ids,
                reasoning=(
                    "仅对 signal_text.json 中有 trigger_values 的字段使用 NO_TEXT 映射。"
                    "空闲字段：" + "、".join(fields)
                    + f"。文言 idle={getattr(signal_summary, 'text_manager_idle_count', 0)}，"
                    f"可见入队={getattr(signal_summary, 'text_manager_trigger_count', 0)}。"
                    + text_note
                ),
                need_verification=[
                    "确认该时间窗内是否本应出现 trigger_values 中的值。",
                    "若本应非空闲，排查发布端；文言模块未见入队不能当作未入队的充分证明。",
                ],
                source="rule",
            )
        ]

    extra = ""
    extra_ok = False
    if code_hits:
        unambiguous = [h for h in code_hits if h.how_found != "ambiguous"]
        h = unambiguous[0] if unambiguous else code_hits[0]
        extra = f" 代码命中：{h.file}:{h.line} {h.symbol}（{h.how_found}）。"
        if h.how_found == "ambiguous":
            extra += " 存在多个 flavor/源集候选，不能把第一个文件当作唯一命中。"
        extra_ok = h.how_found == "stack_frame" and not h.candidates
        ev_ids = list(dict.fromkeys(ev_ids + h.evidence_ids))
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
        "CRASH": ["用 --source 打开堆栈帧；若有多个 flavor 文件，需人工消歧。"],
        "BINDER_IPC": ["检查远端服务进程是否死亡，以及失败的 AIDL 接口。"],
        "STATE_MACHINE": ["按 (状态, 事件) 对照 StateMachine 转换表回放。"],
        "MODULE_COMMUNICATION": ["确认对端进程当时存活，且失败前连接已建立。"],
    }
    return [
        RootCauseCandidate(
            title=title_map.get(itype, itype),
            status="CANDIDATE",
            confidence=_root_conf(classification, evidence, extra_ok),
            evidence_ids=ev_ids[:8],
            reasoning=classification.reason + extra,
            need_verification=verify_map.get(itype, ["在首条错误附近采集更长日志。"]),
            source="rule",
        )
    ]
