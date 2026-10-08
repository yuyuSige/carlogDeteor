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
from adaslog.classifier.incidents import (
    IncidentDraft,
    events_for_draft,
    group_anomalies,
    to_incident,
)
from adaslog.context import analyze_signals, build_context
from adaslog.core.config import default_output_dir, load_config
from adaslog.core.errors import LLMProviderError
from adaslog.detector import detect_anomalies
from adaslog.extractor import extract_evidence
from adaslog.llm.provider import get_provider
from adaslog.llm.rule_based import RuleBasedProvider
from adaslog.llm.schema import as_unknown_list
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


def _summary(classification: Classification, evidence, root_causes, incidents=None) -> str:
    if classification.data_status in ("empty", "filter_empty"):
        return "没有足够数据进行分析（空日志或过滤后无带时间戳事件），不能判为正常。"
    if classification.issue_type == "NORMAL":
        return "该时间窗内有日志且未匹配到异常：这是“未发现异常”，不是“没有数据”。"
    if classification.issue_type == "UNKNOWN":
        return classification.reason or "证据不足以给出具体根因。"
    ev = "、".join(e.id for e in evidence[:5]) or "无"
    rc = root_causes[0].title if root_causes else "无"
    st = root_causes[0].status if root_causes else "UNKNOWN"
    text = (
        f"{classification.issue_type}（分类置信度 {classification.confidence}）。"
        f"关键证据：{ev}。{st}：{rc}"
    )
    if incidents and len(incidents) > 1:
        bits = [f"{inc.id} pid={inc.pid} {inc.issue_type}" for inc in incidents]
        text += " 问题列表：" + "；".join(bits) + "。顶层为主问题摘要，各故障根因见问题列表。"
    return text


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


def _extract_fair(events, drafts: list[IncidentDraft], signal_summary, max_items: int):
    if not drafts:
        return extract_evidence(events, [], signal_summary, max_items=max_items), []
    n = len(drafts)
    budget = max(4, max_items // n)
    evidence = []
    per: list[list] = []
    for draft in drafts:
        local_events = events_for_draft(draft, events) or events
        sig = signal_summary if draft.issue_type == "SIGNAL_NOT_TRIGGERED" else None
        part = extract_evidence(local_events, draft.anomalies, sig, max_items=budget)
        ids = []
        for e in part:
            e.id = f"E{len(evidence) + 1}"
            evidence.append(e)
            ids.append(e.id)
        per.append(ids)
    return evidence, per


def _reason_one(provider, bundle, evidence, classification, signal_summary):
    try:
        llm_result = provider.reason(bundle)
        unknowns = as_unknown_list(llm_result.unknowns)
        cands = validate_candidates(llm_result, evidence, classification, signal_summary)
        return cands, unknowns, llm_result.status, llm_result.provider, None
    except LLMProviderError as exc:
        fallback = RuleBasedProvider().reason(bundle)
        cands = validate_candidates(fallback, evidence, classification, signal_summary)
        return cands, [], "fallback", f"{getattr(provider, 'name', 'llm')}->rule", f"{type(exc).__name__}: {exc}"


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
    encoding: str | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    timings: dict[str, float] = {}
    cfg = load_config(config_path)
    formats = formats or [cfg.get("report", {}).get("default_format", "md")]

    def _prog(msg: str) -> None:
        if progress:
            print(f"[adaslog] {msg}", file=sys.stderr)

    _prog("loading log")
    parsed = load_log(
        log_path, time_range=time_range, pid=pid,
        progress=_prog if progress else None, encoding=encoding,
    )
    timings["load"] = round(time.perf_counter() - t0, 3)
    events = parsed.events
    data_status = parsed.meta.get("data_status", "ok")

    t1 = time.perf_counter()
    anomalies = detect_anomalies(events, collapse=bool(cfg.get("extractor", {}).get("collapse_repeats", True)))
    signal_summary = analyze_signals(events, focus_signals=focus_signals, cfg=cfg)
    classification = classify(anomalies, events, signal_summary, cfg, data_status=data_status)
    timings["detect_classify"] = round(time.perf_counter() - t1, 3)

    max_ev = int(cfg.get("extractor", {}).get("max_key_evidence", 25))
    drafts = group_anomalies(anomalies, events)
    if not drafts and classification.issue_type not in ("NORMAL",):
        ts = [e.timestamp for e in events if e.timestamp]
        drafts = [
            IncidentDraft(
                anomalies=[],
                pid=events[0].pid if events else None,
                issue_type=classification.issue_type,
                event_ids={e.id for e in events},
                start_ts=ts[0] if ts else None,
                end_ts=ts[-1] if ts else None,
            )
        ]
    if drafts:
        evidence, evidence_by_draft = _extract_fair(events, drafts, signal_summary, max_ev)
    else:
        evidence = extract_evidence(events, anomalies, signal_summary, max_items=max_ev)
        evidence_by_draft = []
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
    incidents = []
    candidates = []
    if classification.issue_type == "NORMAL":
        provider_name = "none"
    else:
        provider = get_provider(llm_provider, cfg)
        provider_name = provider.name
        ev_by_id = {e.id: e for e in evidence}
        for i, draft in enumerate(drafts):
            local_ids = evidence_by_draft[i] if i < len(evidence_by_draft) else [e.id for e in evidence]
            local_ev = [ev_by_id[eid] for eid in local_ids if eid in ev_by_id]
            local_events = events_for_draft(draft, events) or events
            local_sig = signal_summary if draft.issue_type == "SIGNAL_NOT_TRIGGERED" else None
            local_clf = classify(draft.anomalies, local_events, local_sig, cfg, data_status="ok")
            if draft.anomalies and local_clf.issue_type in ("NORMAL", "UNKNOWN") and draft.issue_type not in ("NORMAL", "UNKNOWN"):
                local_clf = Classification(
                    issue_type=draft.issue_type,
                    confidence=0.55,
                    evidence_ids=[e.id for e in local_ev],
                    scores=dict(local_clf.scores or {}),
                    reason=f"按进程/时间段划分的故障类型 {draft.issue_type}。",
                    data_status="ok",
                )
            elif not draft.anomalies:
                local_clf = classification
            local_hits = [
                h for h in code_hits
                if set(h.evidence_ids) & {e.id for e in local_ev}
            ]
            local_bundle = {
                **{k: v for k, v in bundle.items() if not str(k).startswith("_")},
                "issue_type": local_clf.issue_type,
                "evidence": [
                    {"id": e.id, "category": e.category, "text": e.text, "line_no": e.line_no, "timestamp": e.timestamp}
                    for e in local_ev
                ],
                "_classification": local_clf,
                "_evidence": local_ev,
                "_signal_summary": local_sig,
                "_code_hits": local_hits,
            }
            cands, unks, status, pname, err = _reason_one(
                provider, local_bundle, local_ev, local_clf, local_sig,
            )
            allowed = {e.id for e in local_ev}
            for rc in cands:
                rc.evidence_ids = [x for x in rc.evidence_ids if x in allowed]
            llm_unknowns.extend(unks)
            llm_status = status
            provider_name = pname
            if err:
                parsed.meta["llm_error"] = err
            inc_unknowns = []
            if not local_ev:
                inc_unknowns.append("该故障没有独立证据（可能被全局截断，或分组内无关键日志）。")
            incidents.append(to_incident(draft, i + 1, [e.id for e in local_ev], cands, inc_unknowns))
        primary = next((inc for inc in incidents if inc.issue_type == classification.issue_type), None)
        candidates = (primary.root_causes if primary else None) or (incidents[0].root_causes if incidents else [])
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

    counter = [e.text for e in evidence if e.category in ("signal_transition", "text_trigger")]
    run_id = _run_id(log_path, time_range, focus_signals, question)
    timings["total"] = round(time.perf_counter() - t0, 3)

    report = AnalysisReport(
        issue_type=classification.issue_type,
        severity=_SEVERITY.get(classification.issue_type, "MEDIUM"),
        summary=_summary(classification, evidence, candidates, incidents),
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
