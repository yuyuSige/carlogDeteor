"""Validate LLM/rule candidates: structure, evidence ids, evidence types, contradictions."""
from __future__ import annotations

from adaslog.llm.provider import LLMResult
from adaslog.models import Classification, Evidence, RootCauseCandidate, SignalSummary

_STATUS = {"CANDIDATE", "UNKNOWN"}
_CONF = {"HIGH", "MEDIUM", "LOW"}

# Evidence categories that can support a given issue type. Free-text claims
# whose citations fall outside this matrix are treated as unverifiable.
_SUPPORTS = {
    "CRASH": {"fatal", "crash", "first_exception", "first_error"},
    "EXCEPTION": {"first_exception", "first_error"},
    "BINDER_IPC": {"binder_failure", "service_disconnected", "first_exception", "first_error"},
    "STATE_MACHINE": {"state_transition_failure", "key_warning"},
    "MODULE_COMMUNICATION": {"communication_failure", "timeout", "first_error", "first_exception"},
    "ANR": {"anr", "first_error"},
    "SYSTEM_ERROR": {"system_error", "crash", "first_error"},
    "SIGNAL_NOT_TRIGGERED": {"signal_idle", "text_idle", "signal_transition"},
    "PERFORMANCE": {"key_warning"},
    "BUSINESS_ERROR": {"key_warning", "first_error"},
}

_COUNTER = {
    "SIGNAL_NOT_TRIGGERED": {"signal_transition", "text_trigger"},
}


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _sanitize_raw(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    status = str(raw.get("status") or "CANDIDATE").upper()
    if status not in _STATUS:
        status = "UNKNOWN"
    conf = str(raw.get("confidence") or "LOW").upper()
    if conf not in _CONF:
        conf = "LOW"
    ids = [str(i) for i in _as_list(raw.get("evidence_ids")) if i]
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        title = "UNKNOWN"
    reasoning = raw.get("reasoning") if isinstance(raw.get("reasoning"), str) else ""
    reason = raw.get("reason") if isinstance(raw.get("reason"), str) else None
    need = [str(x) for x in _as_list(raw.get("need_verification")) if isinstance(x, (str, int))]
    return {
        "title": title.strip(),
        "status": status,
        "confidence": conf,
        "evidence_ids": ids,
        "reasoning": reasoning,
        "reason": reason,
        "need_verification": need,
        "source": raw.get("source"),
    }


def _unknown(result: LLMResult, ids: list[str], reasoning: str) -> RootCauseCandidate:
    return RootCauseCandidate(
        title="UNKNOWN",
        status="UNKNOWN",
        confidence="LOW",
        evidence_ids=ids,
        reasoning=reasoning,
        reason="证据不足。",
        need_verification=["请补充与结论类型匹配的证据。"],
        source=result.provider,
    )


def validate_candidates(
    result: LLMResult,
    evidence: list[Evidence],
    classification: Classification,
    signal_summary: SignalSummary | None = None,
) -> list[RootCauseCandidate]:
    known = {e.id: e for e in evidence}
    if classification.issue_type == "NORMAL":
        return []
    if classification.issue_type == "UNKNOWN" or classification.data_status in ("empty", "filter_empty"):
        return [_unknown(result, [], classification.reason or "证据不足。")]

    out: list[RootCauseCandidate] = []
    raws = result.candidates if isinstance(result.candidates, list) else []
    for raw in raws:
        item = _sanitize_raw(raw)
        if item is None:
            out.append(_unknown(result, [], "模型返回结构非法。"))
            continue
        valid_ids = [i for i in item["evidence_ids"] if i in known]
        dropped = [i for i in item["evidence_ids"] if i not in known]
        cats = {known[i].category for i in valid_ids}
        itype = classification.issue_type
        allowed = _SUPPORTS.get(itype, set())
        counters = _COUNTER.get(itype, set())

        if item["status"] == "UNKNOWN" or item["title"].upper() == "UNKNOWN":
            out.append(_unknown(result, valid_ids, item["reasoning"] or "证据不足。"))
            continue
        if not valid_ids:
            out.append(_unknown(result, [], "没有有效的证据编号。"))
            continue
        if dropped:
            item["need_verification"].append(f"已忽略不存在的证据编号：{dropped}")
        if cats & counters:
            out.append(_unknown(result, valid_ids, "证据中存在与结论矛盾的反证（如信号已出现触发值）。"))
            continue
        if allowed and not (cats & allowed):
            out.append(_unknown(result, valid_ids, "所引证据类型不能支持该结论（例如空队列日志不能支持硬件损坏）。"))
            continue
        if itype == "SIGNAL_NOT_TRIGGERED" and signal_summary is not None:
            if any(s.observation == "saw_trigger" for s in signal_summary.field_status):
                out.append(_unknown(result, valid_ids, "信号已出现触发值，拒绝“保持空闲”类结论。"))
                continue
        # Cap HIGH unless crash with fatal/stack-type evidence.
        conf = item["confidence"]
        if conf == "HIGH" and itype != "CRASH":
            conf = "MEDIUM"
        if conf == "HIGH" and "fatal" not in cats and "first_exception" not in cats:
            conf = "MEDIUM"
        out.append(
            RootCauseCandidate(
                title=item["title"],
                status="CANDIDATE",
                confidence=conf,
                evidence_ids=valid_ids,
                reasoning=item["reasoning"],
                reason=item["reason"],
                need_verification=item["need_verification"],
                source=item.get("source") or result.provider,
            )
        )
    if not out:
        out.append(_unknown(result, [], "证据不足。"))
    return out
