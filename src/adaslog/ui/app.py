"""Streamlit local log analysis workbench.

Bind to 127.0.0.1 by default. Analysis always goes through ``run_analysis``;
this module only handles input, task state, and result display.
"""
from __future__ import annotations

import time
from pathlib import Path

from adaslog.core.errors import LogLoadError, LLMProviderError
from adaslog.core.pipeline import run_analysis
from adaslog.report.labels import confidence as conf_zh
from adaslog.report.labels import issue as issue_zh
from adaslog.ui.session import (
    STAGE_LABELS,
    AnalysisSession,
    StageRecord,
    make_fingerprint,
    result_stale,
)
from adaslog.ui.settings import (
    CONTEXT_LINES_AFTER,
    CONTEXT_LINES_BEFORE,
    MAX_UPLOAD_LABEL,
    format_bytes,
)
from adaslog.ui.validation import validate_params, validate_upload
from adaslog.ui.workspace import cleanup_old_tasks, create_task, read_line_window


def _require_streamlit():
    try:
        import streamlit as st
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "未安装 Streamlit。请执行：pip install 'adaslog[ui]' 或 pip install streamlit"
        ) from exc
    return st


def _init_state(st) -> None:
    st.session_state.setdefault("adas_session", None)
    st.session_state.setdefault("adas_running", False)
    st.session_state.setdefault("adas_selected_evidence", None)
    st.session_state.setdefault("adas_upload_token", None)


def _data_status_banner(report) -> tuple[str, str]:
    ds = getattr(report.classification, "data_status", None) or (report.meta or {}).get("data_status")
    itype = report.issue_type
    if ds in ("empty", "filter_empty") or itype == "UNKNOWN" and ds != "ok":
        return "数据不足", "当前没有足够可分析的带时间戳事件（空文件或过滤后为空）。这不是“正常”。"
    if itype == "NORMAL":
        return "没有发现异常", "窗口内有日志且未匹配到异常规则；这是“未发现异常”，不是“没有数据”。"
    return "检测到问题", f"主问题类型：{issue_zh(itype)}（候选原因待核实，有证据编号不等于根因已成立）。"


def _run_pipeline(session: AnalysisSession, stage_box) -> None:
    t0 = time.perf_counter()
    stages: list[StageRecord] = []

    def on_stage(stage: str, message: str) -> None:
        elapsed = round(time.perf_counter() - t0, 3)
        stages.append(StageRecord(stage=stage, message=message, elapsed_s=elapsed))
        label = STAGE_LABELS.get(stage, stage)
        stage_box.info(f"阶段：{label}（已用时 {elapsed:.2f}s）\n{message}")

    params = session.params
    try:
        result = run_analysis(
            log_path=session.task.log_path,
            source_dir=params.source_dir,
            formats=["md", "json", "txt"],
            out_dir=session.task.out_dir,
            llm_provider="rule",
            focus_signals=params.focus_signals,
            time_range=params.time_range,
            pid=params.pid,
            question=params.question or None,
            progress=False,
            encoding=params.encoding,
            on_stage=on_stage,
        )
        session.report = result["report"]
        session.rendered = result.get("rendered") or {}
        session.outputs = list(result.get("outputs") or [])
        session.encoding_used = (session.report.meta or {}).get("encoding")
        session.error = None
        session.error_hint = None
    except LogLoadError as exc:
        session.error = str(exc)
        session.error_hint = "请检查文件编码、时间窗格式（HH:MM:SS-HH:MM:SS）或 PID 是否正确。"
    except LLMProviderError as exc:
        session.error = f"分析引擎错误：{exc}"
        session.error_hint = "当前默认使用离线规则；若手动指定了远端模型，请检查配置后重试。"
    except OSError as exc:
        session.error = f"文件读写失败：{exc}"
        session.error_hint = "请确认磁盘空间，并清理 tmp/ui_workbench 下的旧任务目录。"
    except Exception as exc:  # noqa: BLE001 — surface to operators
        session.error = f"{type(exc).__name__}: {exc}"
        session.error_hint = "请保留该日志样本与参数，便于本地复现；不要在界面粘贴密钥。"
    session.stages = stages
    session.finished_at = time.perf_counter()
    session.running = False


def _render_overview(st, session: AnalysisSession) -> None:
    rep = session.report
    meta = rep.meta or {}
    title, detail = _data_status_banner(rep)
    st.subheader("分析概况")
    st.markdown(f"**状态：{title}**  \n{detail}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("文件", session.log_name)
    c2.metric("大小", format_bytes(session.log_size))
    c3.metric("事件数", meta.get("event_count") or meta.get("events_kept") or len(getattr(rep, "key_evidence", [])))
    c4.metric("耗时", f"{session.duration_s or meta.get('timings_s', {}).get('total', '-')} s")
    st.caption(
        f"实际覆盖时间：{meta.get('time_start') or '—'} ~ {meta.get('time_end') or '—'}　"
        f"采用编码：{session.encoding_used or meta.get('encoding') or '—'}　"
        f"run_id：{rep.run_id}"
    )
    st.write(
        f"分类置信度：**{conf_zh(rep.classification_confidence or rep.confidence)}**　"
        f"根因置信度：**{conf_zh(rep.root_cause_confidence or 'LOW')}**（二者独立，不可互换）"
    )
    notes = []
    if meta.get("encoding_fallback"):
        notes.append(f"编码自动回退为 {meta['encoding_fallback']}。")
    if meta.get("incomplete_eof"):
        notes.append("文件末尾存在截断字符（incomplete_eof）。")
    if meta.get("filter"):
        notes.append(
            f"已应用过滤：time_range={meta['filter'].get('time_range')} pid={meta['filter'].get('pid')}。"
        )
    if meta.get("untimed_excluded"):
        notes.append(f"因时间窗排除无时间戳行：{meta['untimed_excluded']}。")
    if notes:
        st.warning("限制说明：" + " ".join(notes))
    if session.stages:
        with st.expander("阶段与耗时", expanded=False):
            for s in session.stages:
                st.text(f"{s.elapsed_s:>7.2f}s  {STAGE_LABELS.get(s.stage, s.stage)} — {s.message}")


def _render_incidents(st, session: AnalysisSession) -> None:
    rep = session.report
    st.subheader("问题列表")
    incidents = list(rep.incidents or [])
    if not incidents:
        st.info("没有拆分出的问题条目（可能为 NORMAL / 数据不足）。")
        return
    for inc in incidents:
        label = f"{inc.id} · {issue_zh(inc.issue_type)} · pid={inc.pid} · {inc.start_ts or '—'} ~ {inc.end_ts or '—'}"
        with st.expander(label, expanded=False):
            st.write(inc.summary or "")
            st.markdown("**候选原因（待验证，非已确认根因）**")
            if not inc.root_causes:
                st.caption("无独立候选。")
            for rc in inc.root_causes:
                st.markdown(
                    f"- `{rc.status}` / {conf_zh(rc.confidence)}：**{rc.title}**  "
                    f"证据 {', '.join(rc.evidence_ids) or '无'}"
                )
                if rc.reasoning:
                    st.caption(rc.reasoning)
                if rc.need_verification:
                    st.markdown("待核实：" + "；".join(rc.need_verification))
            ev_ids = inc.evidence_ids or []
            if ev_ids:
                st.markdown("**本问题证据编号：** " + ", ".join(ev_ids))
            if inc.unknowns:
                st.markdown("**未知项：** " + "；".join(inc.unknowns))


def _render_evidence(st, session: AnalysisSession) -> None:
    rep = session.report
    st.subheader("证据查看")
    evidence = list(rep.key_evidence or [])
    if not evidence:
        st.info("无关键证据。")
        return
    options = {f"{e.id} · L{e.line_no} · {e.category} · {(e.timestamp or '')}": e for e in evidence}
    choice = st.selectbox("选择证据", list(options.keys()), key="adas_evidence_select")
    ev = options[choice]
    st.code(ev.text, language=None)
    st.caption(f"为何重要：{ev.why_it_matters}　原始行号：{ev.line_no}　时间：{ev.timestamp or '—'}")
    if ev.line_no:
        enc = session.encoding_used or "utf-8"
        if enc.startswith("utf-16"):
            # LineStream used utf-16; on-demand text reopen may need the same.
            pass
        rows = read_line_window(
            session.task.log_path,
            int(ev.line_no),
            before=CONTEXT_LINES_BEFORE,
            after=CONTEXT_LINES_AFTER,
            encoding="utf-8" if not (enc or "").startswith("utf-16") else enc,
        )
        st.markdown("**原始日志上下文（按需读取，非截断摘要冒充全文）**")
        lines_out = []
        for ln, text in rows:
            mark = ">>> " if ln == ev.line_no else "    "
            lines_out.append(f"{mark}{ln:>6}| {text}")
        # Plain text — never st.markdown the log body (avoid HTML execution).
        st.text("\n".join(lines_out) if lines_out else "（无法读取上下文）")


def _render_next_steps(st, session: AnalysisSession) -> None:
    rep = session.report
    st.subheader("下一步排查")
    st.caption("以下均为建议与待核实事项；候选原因标注为待验证，不是已确认根因。")
    recs = list(rep.recommendations or [])
    if recs:
        for r in recs:
            st.markdown(f"- {r.text}")
    else:
        st.info("暂无额外建议。")
    if rep.unknowns:
        st.markdown("**待补充 / 未知**")
        for u in rep.unknowns:
            st.markdown(f"- {u}")
    for inc in rep.incidents or []:
        for rc in inc.root_causes or []:
            if rc.status == "CANDIDATE":
                st.markdown(f"- （待验证）{inc.id}: {rc.title}")


def _render_downloads(st, session: AnalysisSession) -> None:
    rep = session.report
    st.subheader("报告导出")
    run_id = rep.run_id or "run"
    stem = f"{Path(session.log_name).stem}_{run_id}_analysis"
    for fmt, mime in (("md", "text/markdown"), ("json", "application/json"), ("txt", "text/plain")):
        body = session.rendered.get(fmt)
        if not body:
            continue
        st.download_button(
            label=f"下载 {fmt.upper()}",
            data=body.encode("utf-8"),
            file_name=f"{stem}.{fmt}",
            mime=mime,
            key=f"dl_{fmt}_{run_id}",
        )
    st.caption("下载内容与当前任务结果一致，文件名含 run_id，避免互相覆盖。")


def main() -> None:
    st = _require_streamlit()
    st.set_page_config(page_title="ADAS 日志分析工作台", layout="wide")
    _init_state(st)
    cleanup_old_tasks(keep_latest=30)

    st.title("ADAS 日志分析工作台")
    st.caption(
        f"本地单机工具（默认 127.0.0.1）。离线规则分析，不读取密钥。"
        f"上传上限 {MAX_UPLOAD_LABEL}；临时目录 tmp/ui_workbench/<task_id>。"
    )

    uploaded = st.file_uploader(
        "上传日志（.log / .txt / .logcat）",
        type=["log", "txt", "logcat"],
        accept_multiple_files=False,
    )
    if uploaded is not None:
        st.write(f"文件：**{uploaded.name}**　大小：{format_bytes(uploaded.size)}")

    question = st.text_area("问题描述", placeholder="例如：FCW 文言没有触发", height=80)
    time_range = st.text_input(
        "可选时间窗（HH:MM:SS-HH:MM:SS）",
        placeholder="16:11:00-16:12:00；跨午夜示例 23:59:00-00:01:00",
    )
    st.caption("跨午夜时间窗：当开始时刻晚于结束时刻时按时钟环绕处理（如 23:59:00-00:01:00）。")

    with st.expander("高级选项", expanded=False):
        pid_text = st.text_input("PID（可选）", "")
        focus_signal = st.text_input("焦点信号（逗号分隔，可选）", placeholder="FcwAcitveSt,AebAcitveSt")
        encoding = st.selectbox(
            "编码",
            ["自动识别", "utf-8", "gbk", "utf-16-le", "utf-16-be"],
            index=0,
        )
        source_dir = st.text_input("只读源码目录（可选）", "")

    current_fp = None
    size = uploaded.size if uploaded is not None else 0
    name = uploaded.name if uploaded is not None else ""
    vparams = validate_params(question, time_range, pid_text, focus_signal, encoding, source_dir)
    if vparams.ok and uploaded is not None:
        current_fp = make_fingerprint(vparams.params, name, size)

    session: AnalysisSession | None = st.session_state.get("adas_session")
    if result_stale(session, current_fp or ""):
        st.warning("输入参数或文件已变化：下方结果仍属于上一次任务，请重新点击「开始分析」。")

    start = st.button("开始分析", type="primary", disabled=st.session_state.get("adas_running", False))

    if start:
        errors = validate_upload(name if uploaded else None, size if uploaded else None)
        if not vparams.ok:
            errors.extend(vparams.errors)
        if errors:
            for err in errors:
                st.error(err)
        else:
            st.session_state["adas_running"] = True
            data = uploaded.getvalue()
            task = create_task(name, data)
            session = AnalysisSession(
                task=task,
                params=vparams.params,
                fingerprint=current_fp or make_fingerprint(vparams.params, name, size),
                log_name=name,
                log_size=size,
                running=True,
            )
            stage_box = st.empty()
            with st.spinner("正在分析…"):
                _run_pipeline(session, stage_box)
            st.session_state["adas_session"] = session
            st.session_state["adas_running"] = False
            st.session_state["adas_selected_evidence"] = None

    session = st.session_state.get("adas_session")
    if session is None:
        st.info("上传日志并填写问题后，点击「开始分析」。切换页签或下载不会自动重跑。")
        return

    if session.error:
        st.error(session.error)
        if session.error_hint:
            st.info(session.error_hint)
        return

    if session.report is None:
        st.info("尚无分析结果。")
        return

    tab_overview, tab_issues, tab_evidence, tab_next, tab_dl = st.tabs(
        ["分析概况", "问题列表", "证据查看", "下一步排查", "报告导出"]
    )
    with tab_overview:
        _render_overview(st, session)
    with tab_issues:
        _render_incidents(st, session)
    with tab_evidence:
        _render_evidence(st, session)
    with tab_next:
        _render_next_steps(st, session)
    with tab_dl:
        _render_downloads(st, session)


if __name__ == "__main__":
    main()
