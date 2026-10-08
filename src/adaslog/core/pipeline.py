"""End-to-end analysis pipeline."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from adaslog.analyzer.code_analyzer import analyze_code
from adaslog.classifier import classify
from adaslog.context import analyze_signals, build_context
from adaslog.core.config import PROJECT_ROOT, load_config
from adaslog.core.errors import LLMProviderError
from adaslog.detector import detect_anomalies
from adaslog.extractor import extract_evidence
from adaslog.llm.provider import get_provider
from adaslog.llm.validator import validate_candidates
from adaslog.models import (
    AnalysisReport,
    Classification,
    Confidence,
    Recommendation,
)
from adaslog.parser import load_log
from adaslog.report import render_report, write_reports

_SEVERITY = {
    "CRASH": "CRITICAL",
    "ANR": "CRITICAL",
    "BINDER_IPC": "HIGH",
    "STATE_MACHINE": "HIGH",
    "MODULE_COMMUNICATION": "HIGH",
    "EXCEPTION": "HIGH",
    "SYSTEM_ERROR": "HIGH",
    "SIGNAL_NOT_TRIGGERED": "MEDIUM",
    "BUSINESS_ERROR": "MEDIUM",
    "PERFORMANCE": "LOW",
    "UNKNOWN": "LOW",
    "NORMAL": "NONE",
}

_SIGNAL_QUESTION = ("文言", "信号", "signal", "未触发", "没有触发", "没触发", "text tip", "prompt")


def _apply_question(classification: Classification, question: str | None, has_signal: bool) -> Classification:
    if not question or not has_signal:
        return classification
    if not any(k.lower() in question.lower() for k in _SIGNAL_QUESTION):
        return classification
    if classification.issue_type in ("CRASH", "ANR"):
        return classification
    classification.issue_type = "SIGNAL_NOT_TRIGGERED"
    classification.reason = (
        classification.reason + " 用户问题指向文言未弹出；以信号与文言关联为主要假设。"
    )
    classification.confidence = max(classification.confidence, 0.7)
    return classification


def _summary(classification: Classification, evidence, root_causes) -> str:
    if classification.issue_type == "NORMAL":
        return "该时间窗日志正常：无崩溃、Binder、状态机或通信失败，也无文言缺失模式。"
    if classification.issue_type == "UNKNOWN":
        return "存在类似错误的症状，但证据不足以给出具体根因。"
    ev = "、".join(e.id for e in evidence[:5]) or "无"
    rc = root_causes[0].title if root_causes else "无"
    return f"{classification.issue_type}（置信度 {classification.confidence}）。关键证据：{ev}。候选：{rc}"


def _unknowns(classification: Classification, evidence, code_hits, source_dir) -> list[str]:
    out = []
    if classification.issue_type == "UNKNOWN":
        out.append("证据不足，无法给出具体根因（无堆栈 / 模块 / 信号上下文）。")
    if not source_dir:
        out.append("未提供 --source 目录：相关代码为空（可选）。")
    if source_dir and not code_hits:
        out.append("已提供源码目录，但堆栈帧或 TAG 未能映射到文件。")
    if not any(e.category == "first_exception" for e in evidence) and classification.issue_type in ("CRASH", "EXCEPTION"):
        out.append("存在异常类名，但可能缺少应用侧堆栈帧。")
    return out


def run_analysis(
    log_path: str | Path,
    source_dir: str | None = None,
    formats: list[str] | None = None,
    out_dir: str | None = None,
    llm_provider: str | None = None,
    focus_signals: list[str] | None = None,
    time_range: str | None = None,
    pid: int | None = None,
    question: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    cfg = load_config(config_path)
    formats = formats or [cfg.get("report", {}).get("default_format", "md")]
    parsed = load_log(log_path, time_range=time_range, pid=pid)
    events = parsed.events

    anomalies = detect_anomalies(events, collapse=bool(cfg.get("extractor", {}).get("collapse_repeats", True)))
    signal_summary = analyze_signals(events, focus_signals=focus_signals, cfg=cfg)
    classification = classify(anomalies, events, signal_summary, cfg)
    classification = _apply_question(classification, question, bool(signal_summary.focus or signal_summary.text_manager_idle_count))

    max_ev = int(cfg.get("extractor", {}).get("max_key_evidence", 25))
    evidence = extract_evidence(events, anomalies, signal_summary, max_items=max_ev)
    classification.evidence_ids = [e.id for e in evidence[:8]]

    timeline, causal, windows = build_context(events, evidence, cfg)
    code_hits = analyze_code(events, evidence, source_dir, cfg)

    bundle = {
        "issue_type": classification.issue_type,
        "classification_reason": classification.reason,
        "question": question,
        "evidence": [
            {"id": e.id, "category": e.category, "text": e.text, "line_no": e.line_no, "timestamp": e.timestamp}
            for e in evidence
        ],
        "timeline": [{"ts": t.timestamp, "label": t.label, "evidence_id": t.evidence_id} for t in timeline],
        "code_hits": [{"file": h.file, "line": h.line, "symbol": h.symbol} for h in code_hits],
        "signal_focus": [
            {"struct": p.struct, "field": p.field, "value": p.value, "samples": p.samples}
            for p in signal_summary.focus
        ],
        "_classification": classification,
        "_evidence": evidence,
        "_signal_summary": signal_summary,
        "_code_hits": code_hits,
    }

    llm_status = "skipped"
    provider_name = "rule"
    if classification.issue_type == "NORMAL":
        candidates = []
        provider_name = "none"
    else:
        provider = get_provider(llm_provider, cfg)
        provider_name = provider.name
        try:
            llm_result = provider.reason(bundle)
            llm_status = llm_result.status
            candidates = validate_candidates(llm_result, evidence, classification)
        except (LLMProviderError, Exception) as exc:
            # Always fall back to the offline engine so the tool stays usable.
            from adaslog.llm.rule_based import RuleBasedProvider

            llm_result = RuleBasedProvider().reason(bundle)
            llm_status = "fallback"
            provider_name = f"{provider_name}->rule"
            candidates = validate_candidates(llm_result, evidence, classification)
            parsed.meta["llm_error"] = f"{type(exc).__name__}: {exc}"

    recs: list[Recommendation] = []
    for rc in candidates:
        for v in rc.need_verification:
            recs.append(Recommendation(text=v, evidence_ids=rc.evidence_ids, priority=2))
    if classification.issue_type == "SIGNAL_NOT_TRIGGERED":
        recs.insert(
            0,
            Recommendation(
                text="信号为 0 时映射为 NO_TEXT 属于预期：除非发布过非 0 值，否则不要先查 DrivingTextManager 缺陷。",
                evidence_ids=[e.id for e in evidence if e.category in ("signal_idle", "text_idle")],
                priority=1,
            )
        )

    modules = sorted({e.module for e in events if e.module})
    processes = sorted({e.process for e in events if e.process})
    conf_label = (
        "HIGH" if classification.issue_type == "NORMAL"
        else ("LOW" if classification.issue_type == "UNKNOWN" else Confidence.from_score(classification.confidence).value)
    )
    if candidates:
        conf_label = candidates[0].confidence

    report = AnalysisReport(
        issue_type=classification.issue_type,
        severity=_SEVERITY.get(classification.issue_type, "MEDIUM"),
        summary=_summary(classification, evidence, candidates),
        classification=classification,
        key_evidence=evidence,
        timeline=timeline,
        causal_chain=causal,
        context_windows=windows,
        root_causes=candidates,
        confidence=conf_label,
        related_modules=modules[:20],
        related_processes=processes[:12],
        related_code=code_hits,
        recommendations=recs,
        unknowns=_unknowns(classification, evidence, code_hits, source_dir),
        signal_summary=signal_summary,
        meta={
            **parsed.meta,
            "llm_provider": provider_name,
            "llm_status": llm_status,
            "question": question,
            "focus_signals": focus_signals,
            "anomaly_count": len(anomalies),
            "event_count": len(events),
        },
    )

    dest = Path(out_dir) if out_dir else (PROJECT_ROOT / cfg.get("report", {}).get("output_dir", "reports"))
    stem = Path(log_path).stem + "_analysis"
    rendered = {fmt: render_report(report, fmt) for fmt in formats}
    written = write_reports(report, dest, formats, stem=stem)
    return {
        "report": report,
        "outputs": [str(p) for p in written.values()],
        "rendered": rendered,
        "parsed": parsed,
    }
