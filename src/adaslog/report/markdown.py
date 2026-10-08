from __future__ import annotations

from adaslog.models import AnalysisReport


def render_markdown(r: AnalysisReport) -> str:
    lines = [
        "# ADAS Log Analysis Report",
        "",
        f"- **Issue Type:** {r.issue_type}",
        f"- **Severity:** {r.severity}",
        f"- **Confidence:** {r.confidence} (score={r.classification.confidence})",
        f"- **LLM:** {r.meta.get('llm_status', 'n/a')} / {r.meta.get('llm_provider', 'rule')}",
        "",
        "## 1. Issue Type",
        "",
        r.issue_type,
        "",
        f"Reason: {r.classification.reason}",
        "",
        "## 2. Severity",
        "",
        r.severity,
        "",
        "## 3. Summary",
        "",
        r.summary,
        "",
        "## 4. Key Evidence",
        "",
    ]
    if not r.key_evidence:
        lines.append("_None._")
    for e in r.key_evidence:
        loc = f"L{e.line_no}" if e.line_no else ""
        ts = e.timestamp or ""
        extra = f" x{e.repeat_count}" if e.repeat_count > 1 else ""
        lines.append(f"- **{e.id}** [{e.category}] {ts} {loc}{extra}")
        lines.append(f"  - {e.text}")
        lines.append(f"  - Why: {e.why_it_matters}")
    lines += ["", "## 5. Event Timeline", ""]
    if not r.timeline:
        lines.append("_None._")
    for t in r.timeline:
        lines.append(f"- {t.timestamp or ''} L{t.line_no} ({t.evidence_id}): {t.label}")
    if r.causal_chain:
        lines += ["", "Causal chain:"]
        for c in r.causal_chain:
            lines.append(f"- {c.from_evidence} --{c.relation}--> {c.to_evidence}")
    lines += ["", "## 6. Possible Root Causes", ""]
    if not r.root_causes:
        lines.append("No root-cause section (NORMAL or nothing to hypothesise).")
    for rc in r.root_causes:
        lines.append(f"### {rc.status}: {rc.title}")
        lines.append("")
        lines.append(f"- Confidence: {rc.confidence}")
        lines.append(f"- Evidence: {', '.join(rc.evidence_ids) or '(none)'}")
        lines.append(f"- Reasoning: {rc.reasoning}")
        if rc.reason:
            lines.append(f"- Reason: {rc.reason}")
        if rc.need_verification:
            lines.append("- Need verification:")
            for v in rc.need_verification:
                lines.append(f"  - {v}")
        lines.append("")
    lines += ["## 7. Confidence", "", r.confidence, ""]
    lines += ["## 8. Related Modules", ""]
    lines.append(", ".join(r.related_modules) or "_unknown_")
    if r.related_processes:
        lines += ["", "Processes: " + ", ".join(r.related_processes)]
    lines += ["", "## 9. Related Code", ""]
    if not r.related_code:
        lines.append("_No --source provided, or no frame/tag mapped to a file. Planned/optional._")
    for h in r.related_code:
        lines.append(f"### `{h.file}`:{h.line or '?'} `{h.symbol}` ({h.how_found})")
        if h.candidates:
            lines.append(f"Other flavor/source-set candidates: {', '.join(h.candidates[:4])}")
        if h.risk_patterns:
            lines.append(f"Risk patterns: {', '.join(h.risk_patterns)}")
        lines.append("```")
        lines.append(h.snippet)
        lines.append("```")
    lines += ["", "## 10. Recommended Investigation", ""]
    if not r.recommendations:
        lines.append("_None._")
    for rec in r.recommendations:
        ev = f" (evidence {', '.join(rec.evidence_ids)})" if rec.evidence_ids else ""
        lines.append(f"- {rec.text}{ev}")
    lines += ["", "## 11. Unknown / Missing Information", ""]
    if not r.unknowns:
        lines.append("_None recorded._")
    for u in r.unknowns:
        lines.append(f"- {u}")
    if r.signal_summary:
        s = r.signal_summary
        lines += ["", "## Signal summary", ""]
        lines.append(f"Window: {s.window or 'n/a'}")
        lines.append(f"Structs sampled: {s.structs}")
        lines.append(
            f"DrivingTextManager idle={s.text_manager_idle_count} trigger={s.text_manager_trigger_count}"
        )
        if s.focus:
            lines.append("Focus periods:")
            for p in s.focus:
                lines.append(
                    f"- {p.struct}.{p.field}={p.value} {p.start_ts}..{p.end_ts} n={p.samples} L{p.first_line}-{p.last_line}"
                )
    lines += ["", "---", f"meta: `{r.meta}`"]
    return "\n".join(lines) + "\n"
