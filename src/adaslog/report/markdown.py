from __future__ import annotations

from adaslog.models import AnalysisReport
from adaslog.report import labels as L


def render_markdown(r: AnalysisReport) -> str:
    lines = [
        "# ADAS 日志分析报告",
        "",
        f"- **问题类型：** {L.issue(r.issue_type)}",
        f"- **严重程度：** {L.severity(r.severity)}",
        f"- **分类置信度：** {L.confidence(r.classification_confidence or r.confidence)}（分类得分={r.classification.confidence}）",
        f"- **根因置信度：** {L.confidence(r.root_cause_confidence or r.confidence)}（候选≠已确认根因）",
        f"- **推理引擎：** {r.meta.get('llm_status', 'n/a')} / {r.meta.get('llm_provider', 'rule')}",
        f"- **任务编号：** {r.run_id or r.meta.get('run_id', '')}",
        f"- **工具版本：** {r.meta.get('tool_version', '')}",
        "",
        "## 1. 问题类型",
        "",
        L.issue(r.issue_type),
        "",
        f"判定说明：{r.classification.reason}",
        "",
        "## 2. 严重程度",
        "",
        L.severity(r.severity),
        "",
        "## 3. 摘要",
        "",
        r.summary,
        "",
        "## 4. 关键证据",
        "",
    ]
    if not r.key_evidence:
        lines.append("_无。_")
    for e in r.key_evidence:
        loc = f"第{e.line_no}行" if e.line_no else ""
        ts = e.timestamp or ""
        extra = f" ×{e.repeat_count}" if e.repeat_count > 1 else ""
        lines.append(f"- **{e.id}** [{L.category(e.category)}] {ts} {loc}{extra}")
        lines.append(f"  - {e.text}")
        lines.append(f"  - 为何关键：{e.why_it_matters}")
    lines += ["", "## 5. 事件时间线", ""]
    if not r.timeline:
        lines.append("_无。_")
    for t in r.timeline:
        lines.append(f"- {t.timestamp or ''} 第{t.line_no}行（{t.evidence_id}）：{t.label}")
    if r.causal_chain:
        lines += ["", "时序（仅表示先于，不表示因果）："]
        for c in r.causal_chain:
            lines.append(f"- {c.from_evidence} --{L.relation(c.relation)}--> {c.to_evidence}")
    lines += ["", "## 6. 可能根因", ""]
    if not r.root_causes:
        lines.append("无根因段落（日志为正常，或无需假设）。")
    for rc in r.root_causes:
        lines.append(f"### {L.status(rc.status)}：{rc.title}")
        lines.append("")
        lines.append(f"- 置信度：{L.confidence(rc.confidence)}")
        lines.append(f"- 证据：{', '.join(rc.evidence_ids) or '（无）'}")
        lines.append(f"- 推理：{rc.reasoning}")
        if rc.reason:
            lines.append(f"- 原因：{rc.reason}")
        if rc.need_verification:
            lines.append("- 待核实：")
            for v in rc.need_verification:
                lines.append(f"  - {v}")
        lines.append("")
    lines += [
        "## 7. 置信度",
        "",
        f"分类 {L.confidence(r.classification_confidence or r.confidence)} / 根因 {L.confidence(r.root_cause_confidence or r.confidence)}",
        "",
    ]
    lines += ["## 8. 相关模块", ""]
    lines.append(", ".join(r.related_modules) or "_未知_")
    if r.related_processes:
        lines += ["", "进程：" + ", ".join(r.related_processes)]
    lines += ["", "## 9. 相关代码", ""]
    if not r.related_code:
        lines.append("_未提供 --source，或堆栈/TAG 未能映射到源文件（可选）。_")
    for h in r.related_code:
        lines.append(f"### `{h.file}`:{h.line or '?'} `{h.symbol}`（{L.how_found(h.how_found)}）")
        if h.candidates:
            lines.append(f"其他 flavor/源集候选：{', '.join(h.candidates[:4])}")
        if h.risk_patterns:
            lines.append(f"风险模式：{', '.join(h.risk_patterns)}")
        lines.append("```")
        lines.append(h.snippet)
        lines.append("```")
    lines += ["", "## 10. 排查建议", ""]
    if not r.recommendations:
        lines.append("_无。_")
    for rec in r.recommendations:
        ev = f"（证据 {', '.join(rec.evidence_ids)}）" if rec.evidence_ids else ""
        lines.append(f"- {rec.text}{ev}")
    lines += ["", "## 11. 未知 / 缺失信息", ""]
    if not r.unknowns:
        lines.append("_无。_")
    for u in r.unknowns:
        lines.append(f"- {u}")
    if r.signal_summary:
        s = r.signal_summary
        lines += ["", "## 信号摘要", ""]
        lines.append(f"时间窗：{s.window or '无'}")
        lines.append(f"结构体采样：{s.structs}")
        lines.append(
            f"DrivingTextManager 空闲={s.text_manager_idle_count} 触发={s.text_manager_trigger_count}"
        )
        if s.focus:
            lines.append("焦点信号时段：")
            for p in s.focus:
                lines.append(
                    f"- {p.struct}.{p.field}={p.value} {p.start_ts}～{p.end_ts} 采样{p.samples}次 第{p.first_line}-{p.last_line}行"
                )
    if r.incidents:
        lines += ["", "## 问题列表（多故障）", ""]
        for inc in r.incidents:
            lines.append(f"- **{inc.id}** {L.issue(inc.issue_type)} pid={inc.pid} {inc.start_ts}～{inc.end_ts} {inc.summary}")
    if r.counter_evidence:
        lines += ["", "## 反证 / 变化过程", ""]
        for c in r.counter_evidence:
            lines.append(f"- {c}")
    q = r.meta.get("question")
    if q:
        lines += ["", f"分析问题：{q}"]
    filt = r.meta.get("filter_policy")
    if filt:
        lines += ["", f"过滤策略：{filt}；覆盖 {r.meta.get('time_start')}～{r.meta.get('time_end')}；data_status={r.meta.get('data_status')}"]
    lines += ["", "---", "说明：第 4 节为已观察事实/证据；第 6 节为候选原因（Hypothesis），不是已确认根因。", f"元数据：`{r.meta}`"]
    return "\n".join(lines) + "\n"
