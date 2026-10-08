"""End-to-end analysis pipeline."""
from __future__ import annotations

import hashlib
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from adaslog import __version__
from adaslog.analyzer.code_analyzer import analyze_code
from adaslog.classifier import classify
from adaslog.classifier.incidents import build_incidents
from adaslog.context import analyze_signals, build_context
from adaslog.core.config import default_output_dir, load_config
from adaslog.core.errors import LLMProviderError
from adaslog.detector import detect_anomalies
from adaslog.extractor import extract_evidence
from adaslog.llm.provider import get_provider
from adaslog.llm.validator import validate_candidates
from adaslog.models import (
    AnalysisReport,
    Classification,
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

_BUNDLE_CHAR_BUDGET = 8000


def _summary(classification: Classification, evidence, root_causes) -> str:
    if classification.data_status in ("empty", "filter_empty"):
        return "没有足够数据进行分析（空日志或过滤后无带时间戳事件），不能判为正常。"
    if classification.issue_type == "NORMAL":
        return "该时间窗内有日志且未匹配到异常：这是“未发现异常”，不是“没有数据”。"
    if classification.issue_type == "UNKNOWN":
        return classification.reason or "证据不足以给出具体根因。"
    ev = "、".join(e.id for e in evidence[:5]) or "无"
    rc = root_causes[0].title if root_causes else "无"
    st = root_causes[0].status if root_causes else "UNKNOWN"
    return (
        f"{classification.issue_type}（分类置信度 {classification.confidence}）。"
        f"关键证据：{ev}。{st}：{rc}"
    )


def _unknowns(classification: Classification, evidence, code_hits, source_dir, question, signal_summary) -> list[str]:
    out = []
    if classification.data_status in ("empty", "filter_empty"):
        out.append("数据不足：请检查文件是否为空，或时间窗/PID 是否滤掉了全部带时间戳事件。")
    if classification.issue_type == "UNKNOWN" and classification.data_status == "ok":
        out.append("证据不足，无法给出具体根因（无堆栈 / 模块 / 已映射信号空闲）。")
    if not source_dir:
        out.append("未提供 --source 目录：相关代码为空（可选）。")
    if source_dir and not code_hits:
        out.append("已提供源码目录，但堆栈帧或 TAG 未能映射到文件。")
    if any(h.how_found == "ambiguous" for h in code_hits):
        out.append("源码命中存在多 flavor/同名文件歧义，不能默认第一个文件正确。")
    if signal_summary and signal_summary.enqueue_unobserved_is_unknown and signal_summary.text_manager_trigger_count == 0:
        out.append("未见入队日志不能证明未入队。")
    if question:
        out.append(f"用户关注：{question}（用于确定分析重点，不覆盖已检测到的其他故障）。")
    return out


def _public_bundle(bundle: dict) -> dict:
    return {k: v for k, v in bundle.items() if not str(k).startswith("_")}


def _trim(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _run_id(log_path, time_range, focus, question) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw = f"{log_path}|{time_range}|{focus}|{question}|{uuid.uuid4().hex[:8]}"
    short = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{stamp}_{short}"


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
    progress: bool = True,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    timings: dict[str, float] = {}
    cfg = load_config(config_path)
    formats = formats or [cfg.get("report", {}).get("default_format", "md")]

    def _prog(msg: str) -> None:
        if progress:
            print(f"[adaslog] {msg}", file=sys.stderr)

    _prog("loading log")
    parsed = load_log(log_path, time_range=time_range, pid=pid, progress=_prog if progress else None)
    timings["load"] = round(time.perf_counter() - t0, 3)
    events = parsed.events
    data_status = parsed.meta.get("data_status", "ok")

    t1 = time.perf_counter()
    anomalies = detect_anomalies(events, collapse=bool(cfg.get("extractor", {}).get("collapse_repeats", True)))
    signal_summary = analyze_signals(events, focus_signals=focus_signals, cfg=cfg)
    classification = classify(anomalies, events, signal_summary, cfg, data_status=data_status)
    timings["detect_classify"] = round(time.perf_counter() - t1, 3)

    max_ev = int(cfg.get("extractor", {}).get("max_key_evidence", 25))
    evidence = extract_evidence(events, anomalies, signal_summary, max_items=max_ev)
    classification.evidence_ids = [e.id for e in evidence[:8]]

    timeline, causal, windows = build_context(events, evidence, cfg)
    code_hits = analyze_code(events, evidence, source_dir, cfg)

    snippet_budget = _BUNDLE_CHAR_BUDGET
    code_payload = []
    for h in code_hits:
        chunk = _trim(h.snippet, min(1200, snippet_budget))
        snippet_budget -= len(chunk)
        code_payload.append({
            "file": h.file, "line": h.line, "symbol": h.symbol,
            "how_found": h.how_found, "candidates": h.candidates[:6], "snippet": chunk,
        })
        if snippet_budget <= 0:
            break

    ctx_payload = []
    for w in windows[:4]:
        ctx_payload.append({"anchor": w.anchor_evidence_id, "before": w.before[:6], "after": w.after[:6]})

    bundle = {
        "issue_type": classification.issue_type,
        "classification_reason": classification.reason,
        "classification_confidence": classification.confidence,
        "data_status": classification.data_status,
        "question": question,
        "evidence": [
            {"id": e.id, "category": e.category, "text": e.text, "line_no": e.line_no, "timestamp": e.timestamp}
            for e in evidence
        ],
        "timeline": [{"ts": t.timestamp, "label": t.label, "evidence_id": t.evidence_id} for t in timeline],
        "context_windows": ctx_payload,
        "code_hits": code_payload,
        "signal_field_status": [
            {"key": s.key, "observation": s.observation, "values": s.values_seen, "mapped": s.mapped, "note": s.note}
            for s in (signal_summary.field_status or [])
        ],
        "_classification": classification,
        "_evidence": evidence,
        "_signal_summary": signal_summary,
        "_code_hits": code_hits,
    }

    llm_status = "skipped"
    provider_name = "rule"
    llm_unknowns: list[str] = []
    t2 = time.perf_counter()
    if classification.issue_type == "NORMAL":
        candidates = []
        provider_name = "none"
    else:
        provider = get_provider(llm_provider, cfg)
        provider_name = provider.name
        try:
            llm_result = provider.reason(bundle)
            llm_status = llm_result.status
            llm_unknowns = list(llm_result.unknowns or [])
            candidates = validate_candidates(llm_result, evidence, classification, signal_summary)
        except LLMProviderError as exc:
            from adaslog.llm.rule_based import RuleBasedProvider

            llm_result = RuleBasedProvider().reason(bundle)
            llm_status = "fallback"
            provider_name = f"{provider_name}->rule"
            candidates = validate_candidates(llm_result, evidence, classification, signal_summary)
            parsed.meta["llm_error"] = f"{type(exc).__name__}: {exc}"
    timings["reason"] = round(time.perf_counter() - t2, 3)

    recs: list[Recommendation] = []
    for rc in candidates:
        for v in rc.need_verification:
            recs.append(Recommendation(text=v, evidence_ids=rc.evidence_ids, priority=2))
    if classification.issue_type == "SIGNAL_NOT_TRIGGERED":
        recs.insert(
            0,
            Recommendation(
                text="仅当字段有 Profile 映射且全窗口为空闲值时，才按 NO_TEXT 解释；未见入队不能证明未入队。",
                evidence_ids=[e.id for e in evidence if e.category in ("signal_idle", "text_idle")],
                priority=1,
            )
        )

    modules = sorted({e.module for e in events if e.module})
    processes = sorted({e.process for e in events if e.process})
    class_conf = (
        "HIGH" if classification.issue_type == "NORMAL"
        else ("LOW" if classification.issue_type == "UNKNOWN" else
              ("HIGH" if classification.confidence >= 0.75 else "MEDIUM" if classification.confidence >= 0.45 else "LOW"))
    )
    rc_conf = candidates[0].confidence if candidates else class_conf
    if classification.issue_type == "NORMAL":
        rc_conf = "HIGH"

    incidents = build_incidents(anomalies, events, classification.issue_type, evidence, candidates)
    counter = [e.text for e in evidence if e.category in ("signal_transition", "text_trigger")]
    run_id = _run_id(log_path, time_range, focus_signals, question)
    timings["total"] = round(time.perf_counter() - t0, 3)

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
        confidence=class_conf,
        related_modules=modules[:20],
        related_processes=processes[:12],
        related_code=code_hits,
        recommendations=recs,
        unknowns=_unknowns(classification, evidence, code_hits, source_dir, question, signal_summary) + llm_unknowns,
        signal_summary=signal_summary,
        meta={
            **parsed.meta,
            "llm_provider": provider_name,
            "llm_status": llm_status,
            "question": question,
            "focus_signals": focus_signals,
            "anomaly_count": len(anomalies),
            "event_count": len(events),
            "run_id": run_id,
            "tool_version": __version__,
            "timings_s": timings,
            "input_summary": {
                "log": str(log_path),
                "time_range": time_range,
                "pid": pid,
                "focus_signals": focus_signals,
                "size_bytes": parsed.meta.get("size_bytes"),
                "encoding": parsed.meta.get("encoding"),
            },
        },
        incidents=incidents,
        classification_confidence=class_conf,
        root_cause_confidence=rc_conf,
        run_id=run_id,
        counter_evidence=counter,
    )

    dest = Path(out_dir) if out_dir else default_output_dir()
    stem = Path(log_path).stem + f"_{run_id}_analysis"
    rendered = {fmt: render_report(report, fmt) for fmt in formats}
    written = write_reports(report, dest, formats, stem=stem)
    _prog(f"done issue_type={report.issue_type} run_id={run_id}")
    return {
        "report": report,
        "outputs": [str(p) for p in written.values()],
        "rendered": rendered,
        "parsed": parsed,
    }
