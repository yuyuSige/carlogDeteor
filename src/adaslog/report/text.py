from __future__ import annotations

from adaslog.models import AnalysisReport


def render_text(r: AnalysisReport) -> str:
    sep = "=" * 30
    lines = [
        sep,
        "ADAS Log Analysis Report",
        sep,
        "",
        "1. Issue Type",
        r.issue_type,
        "",
        "2. Severity",
        r.severity,
        "",
        "3. Summary",
        r.summary,
        "",
        "4. Key Evidence",
    ]
    if not r.key_evidence:
        lines.append("(none)")
    for e in r.key_evidence:
        lines.append(f"  {e.id} [{e.category}] L{e.line_no} {e.timestamp or ''}")
        lines.append(f"    {e.text}")
    lines += ["", "5. Event Timeline"]
    for t in r.timeline:
        lines.append(f"  {t.timestamp or ''} L{t.line_no} {t.label}")
    lines += ["", "6. Possible Root Causes"]
    if not r.root_causes:
        lines.append("  (none — NORMAL or nothing to hypothesise)")
    for rc in r.root_causes:
        lines.append(f"  {rc.status}: {rc.title}")
        lines.append(f"    Confidence: {rc.confidence}")
        lines.append(f"    Evidence: {', '.join(rc.evidence_ids) or '(none)'}")
        lines.append(f"    Reasoning: {rc.reasoning}")
        if rc.reason:
            lines.append(f"    Reason: {rc.reason}")
        for v in rc.need_verification:
            lines.append(f"    Need verification: {v}")
    lines += ["", "7. Confidence", r.confidence]
    lines += ["", "8. Related Modules", ", ".join(r.related_modules) or "(unknown)"]
    lines += ["", "9. Related Code"]
    if not r.related_code:
        lines.append("  (none)")
    for h in r.related_code:
        lines.append(f"  {h.file}:{h.line} {h.symbol}")
    lines += ["", "10. Recommended Investigation"]
    for rec in r.recommendations:
        lines.append(f"  - {rec.text}")
    if not r.recommendations:
        lines.append("  (none)")
    lines += ["", "11. Unknown / Missing Information"]
    for u in r.unknowns:
        lines.append(f"  - {u}")
    if not r.unknowns:
        lines.append("  (none)")
    return "\n".join(lines) + "\n"
