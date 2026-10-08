from __future__ import annotations

from adaslog.models import AnalysisReport
from adaslog.report import labels as L


def render_text(r: AnalysisReport) -> str:
    sep = "=" * 30
    lines = [
        sep,
        "ADAS 日志分析报告",
        sep,
        "",
        "1. 问题类型",
        L.issue(r.issue_type),
        "",
        "2. 严重程度",
        L.severity(r.severity),
        "",
        "3. 摘要",
        r.summary,
        "",
        "4. 关键证据",
    ]
    if not r.key_evidence:
        lines.append("  （无）")
    for e in r.key_evidence:
        loc = f"第{e.line_no}行" if e.line_no else ""
        extra = f" ×{e.repeat_count}" if e.repeat_count > 1 else ""
        lines.append(f"  {e.id} [{L.category(e.category)}] {loc} {e.timestamp or ''}{extra}")
        lines.append(f"    {e.text}")
    lines += ["", "5. 事件时间线"]
    if not r.timeline:
        lines.append("  （无）")
    for t in r.timeline:
        lines.append(f"  {t.timestamp or ''} 第{t.line_no}行 {t.label}")
    lines += ["", "6. 可能根因"]
    if not r.root_causes:
        lines.append("  （无——正常日志，或无需假设）")
    for rc in r.root_causes:
        lines.append(f"  {L.status(rc.status)}：{rc.title}")
        lines.append(f"    置信度：{L.confidence(rc.confidence)}")
        lines.append(f"    证据：{', '.join(rc.evidence_ids) or '（无）'}")
        lines.append(f"    推理：{rc.reasoning}")
        if rc.reason:
            lines.append(f"    原因：{rc.reason}")
        for v in rc.need_verification:
            lines.append(f"    待核实：{v}")
    lines += ["", "7. 置信度", f"分类 {L.confidence(r.classification_confidence or r.confidence)} / 根因 {L.confidence(r.root_cause_confidence or r.confidence)}"]
    lines += ["", "8. 相关模块", ", ".join(r.related_modules) or "（未知）"]
    lines += ["", "9. 相关代码"]
    if not r.related_code:
        lines.append("  （无）")
    for h in r.related_code:
        lines.append(f"  {h.file}:{h.line} {h.symbol}")
    lines += ["", "10. 排查建议"]
    for rec in r.recommendations:
        lines.append(f"  - {rec.text}")
    if not r.recommendations:
        lines.append("  （无）")
    lines += ["", "11. 未知 / 缺失信息"]
    for u in r.unknowns:
        lines.append(f"  - {u}")
    if not r.unknowns:
        lines.append("  （无）")
    if r.incidents:
        lines += ["", "问题列表"]
        for inc in r.incidents:
            lines.append(f"  {inc.id} {L.issue(inc.issue_type)} pid={inc.pid} {inc.summary}")
            lines.append(f"    证据：{', '.join(inc.evidence_ids) or '（无）'}")
            for rc in inc.root_causes:
                lines.append(f"    {L.status(rc.status)}：{rc.title} 引用 {', '.join(rc.evidence_ids) or '无'}")
    if r.counter_evidence:
        lines += ["", "反证 / 变化过程"]
        for c in r.counter_evidence:
            lines.append(f"  - {c}")
    lines += ["", f"任务编号：{r.run_id or r.meta.get('run_id', '')}"]
    lines += [f"工具版本：{r.meta.get('tool_version', '')}"]
    filt = r.meta.get("filter_policy")
    if filt:
        lines.append(f"过滤策略：{filt}；覆盖 {r.meta.get('time_start')}～{r.meta.get('time_end')}；data_status={r.meta.get('data_status')}")
    lines.append("第4节为已观察事实；第6节为候选原因，不是已确认根因。时序仅表示先于。")
    return "\n".join(lines) + "\n"
