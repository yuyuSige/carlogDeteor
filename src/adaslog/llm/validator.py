"""Validate LLM/rule candidates: structure, evidence binding, claim support, contradictions."""
from __future__ import annotations

import re

from adaslog.llm.provider import LLMResult
from adaslog.models import Classification, Evidence, RootCauseCandidate, SignalSummary

_STATUS = {"CANDIDATE", "UNKNOWN"}
_CONF = {"HIGH", "MEDIUM", "LOW"}

# Evidence categories that can support a *symptom restatement* of an issue type.
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

# Closed symptom lexicon bound to issue types (allowlist, not a denylist of brands/parts).
_SYMPTOM_LEXICON = {
    "CRASH": {
        "进程", "崩溃", "异常", "退出", "主线程", "fatal", "crash", "abort", "exception",
        "native", "nullpointer", "force", "finishing", "died", "process", "runtime",
        "androidruntime", "throwable",
    },
    "EXCEPTION": {
        "异常", "捕获", "打印", "诊断", "路径", "exception", "error", "throwable", "nullpointer",
    },
    "BINDER_IPC": {
        "binder", "ipc", "aidl", "deadobject", "remoteexception", "事务", "失败", "远端",
        "服务", "死亡", "断开", "disconnected", "dead", "object",
    },
    "STATE_MACHINE": {
        "状态机", "状态", "转换", "非法", "未定义", "事件", "statemachine", "transition", "illegal",
    },
    "MODULE_COMMUNICATION": {
        "通信", "模块", "超时", "总线", "连接", "kanzi", "grpc", "timeout", "disconnect",
    },
    "SIGNAL_NOT_TRIGGERED": {
        "信号", "空闲", "文言", "队列", "映射", "触发", "焦点", "窗口", "采样", "字段",
        "idle", "no_text", "profile", "fcwacitvest", "aebacitvest", "notext",
    },
    "ANR": {"无响应", "阻塞", "主线程", "anr", "input", "dispatch"},
    "SYSTEM_ERROR": {"系统", "错误", "system", "error"},
    "PERFORMANCE": {"掉帧", "卡顿", "慢", "jank", "performance"},
    "BUSINESS_ERROR": {"业务", "错误", "business"},
}

_FUNCTION_LEXICON = {
    "的", "了", "在", "是", "与", "和", "或", "及", "并", "也", "还", "就", "都", "要", "会",
    "可以", "有", "无", "此", "该", "本", "其", "对应", "按", "从", "对", "把", "被", "等",
    "因", "导致", "出现", "发生", "可能", "候选", "根因", "非", "已", "确认", "原因",
    "时间", "内", "日志", "证据", "值", "行", "第", "至", "于", "后", "前", "中", "上",
    "具体", "相关", "所示", "看到", "显示", "报告", "分析", "说明", "不是", "不能", "没有",
    "a", "an", "the", "to", "of", "in", "on", "for", "by", "with", "from", "as", "or",
    "and", "not", "no", "is", "was", "be", "been",
}

_TOKEN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")

# Trusted providers whose titles come from our offline rule catalog, not model JSON.
_RULE_PROVIDERS = {"rule", "none"}


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
        # Ignored for trust: model-reported source / claim_type are not evidence.
        "source_claimed": raw.get("source"),
        "claim_type_claimed": raw.get("claim_type") or raw.get("claim_kind"),
    }


def _unknown(result: LLMResult, ids: list[str], reasoning: str, reject_kind: str) -> RootCauseCandidate:
    reason = {
        "contradiction": "存在反证。",
        "missing_support": "缺少支持。",
        "insufficient_data": "证据不足。",
        "stated_unknown": "证据不足。",
    }.get(reject_kind, "缺少支持。")
    return RootCauseCandidate(
        title="UNKNOWN",
        status="UNKNOWN",
        confidence="LOW",
        evidence_ids=ids,
        reasoning=reasoning,
        reason=reason,
        need_verification=["请补充能直接支持该具体原因的观测，而不是仅重复症状。"]
        if reject_kind == "missing_support"
        else ["请处理与结论矛盾的反证。"]
        if reject_kind == "contradiction"
        else ["请补充与结论类型匹配的证据。"],
        source=result.provider,
        reject_kind=reject_kind,
    )


def _tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN.finditer(text or "")}


def _expand_lexicon(words: set[str]) -> set[str]:
    """Allow both whole words and their CJK characters (tokenizer yields one CJK char)."""
    out = {w.lower() for w in words}
    for w in list(out):
        for ch in w:
            if "\u4e00" <= ch <= "\u9fff":
                out.add(ch)
    return out


_SYMPTOM_LEXICON = {k: _expand_lexicon(v) for k, v in _SYMPTOM_LEXICON.items()}
_FUNCTION_LEXICON = _expand_lexicon(_FUNCTION_LEXICON)


def _is_trusted_rule(result: LLMResult) -> bool:
    name = (result.provider or "").lower()
    return name in _RULE_PROVIDERS or name.endswith("->rule")


def _claim_is_symptom_restatement(title: str, reasoning: str, cited: list[Evidence], itype: str) -> bool:
    """Title/reasoning tokens must be covered by cited evidence text + closed symptom lexicon.

    Extra entities (hardware, unrelated modules, invented defects) remain as leftovers
    and are treated as unverifiable specific causes. This is an allowlist, not a brand denylist.
    """
    allowed = set(_FUNCTION_LEXICON)
    allowed |= {_t.lower() for _t in _SYMPTOM_LEXICON.get(itype, set())}
    for e in cited:
        allowed |= _tokens(e.text)
        allowed |= _tokens(e.category)
        allowed |= _tokens(e.id)
    leftovers = (_tokens(title) | _tokens(reasoning)) - allowed
    return not leftovers


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
        return [_unknown(result, [], classification.reason or "证据不足。", "insufficient_data")]

    out: list[RootCauseCandidate] = []
    raws = result.candidates if isinstance(result.candidates, list) else []
    trusted_rule = _is_trusted_rule(result)
    for raw in raws:
        item = _sanitize_raw(raw)
        if item is None:
            out.append(_unknown(result, [], "模型返回结构非法。", "malformed"))
            continue
        valid_ids = [i for i in item["evidence_ids"] if i in known]
        dropped = [i for i in item["evidence_ids"] if i not in known]
        cited = [known[i] for i in valid_ids]
        cats = {e.category for e in cited}
        itype = classification.issue_type
        allowed = _SUPPORTS.get(itype, set())
        counters = _COUNTER.get(itype, set())

        if item["status"] == "UNKNOWN" or item["title"].upper() == "UNKNOWN":
            out.append(_unknown(result, valid_ids, item["reasoning"] or "证据不足。", "stated_unknown"))
            continue
        if not valid_ids:
            out.append(_unknown(result, [], "没有有效的证据编号。", "missing_support"))
            continue
        if dropped:
            item["need_verification"].append(f"已忽略不存在的证据编号：{dropped}")
        if cats & counters:
            out.append(_unknown(result, valid_ids, "证据中存在与结论矛盾的反证（如信号已出现触发值）。", "contradiction"))
            continue
        if allowed and not (cats & allowed):
            out.append(_unknown(result, valid_ids, "所引证据类型不能支持该结论（缺少支持）。", "missing_support"))
            continue
        if itype == "SIGNAL_NOT_TRIGGERED" and signal_summary is not None:
            if any(s.observation == "saw_trigger" for s in signal_summary.field_status):
                out.append(_unknown(result, valid_ids, "信号已出现触发值，拒绝“保持空闲”类结论。", "contradiction"))
                continue

        if not trusted_rule:
            # Ignore model-reported source/claim_type. Only evidence-bound restatement is CANDIDATE.
            if not _claim_is_symptom_restatement(item["title"], item["reasoning"], cited, itype):
                out.append(
                    _unknown(
                        result,
                        valid_ids,
                        "自由文本提出了所引证据未支持的具体原因；仅能确认症状，不能确认该根因。",
                        "missing_support",
                    )
                )
                continue

        conf = item["confidence"]
        if not trusted_rule:
            if conf == "HIGH":
                conf = "MEDIUM"
        else:
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
                source="rule" if trusted_rule else (result.provider or "llm"),
                reject_kind="",
            )
        )
    if not out:
        out.append(_unknown(result, [], "证据不足。", "missing_support"))
    return out
