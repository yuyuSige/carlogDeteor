"""Workbench helpers: validation, safe paths, fingerprint / stale-result guards."""
from pathlib import Path

import pytest

from adaslog.ui.session import AnalysisSession, make_fingerprint, result_stale
from adaslog.ui.settings import MAX_UPLOAD_BYTES
from adaslog.ui.validation import AnalysisParams, validate_params, validate_upload
from adaslog.ui.workspace import create_task, read_line_window, safe_filename


def test_reject_path_traversal_filename():
    assert safe_filename("../../etc/passwd") == "passwd.log" or "passwd" in safe_filename("../../etc/passwd")
    assert "/" not in safe_filename("a/b/c.log")
    assert "\\" not in safe_filename("a\\b\\c.log")
    assert Path(safe_filename("/tmp/x.log")).name == safe_filename("/tmp/x.log")


def test_upload_size_and_type_checks():
    assert validate_upload(None, None)
    assert any("上传" in e for e in validate_upload(None, 0))
    assert any("类型" in e for e in validate_upload("x.bin", 10))
    assert not validate_upload("ok.log", 100)
    errs = validate_upload("big.log", MAX_UPLOAD_BYTES + 1)
    assert any("过大" in e or "上限" in e for e in errs)


def test_time_range_and_pid_validation():
    bad = validate_params("", "25:00:00-26:00:00", "", "", "自动识别", "")
    assert not bad.ok
    bad2 = validate_params("", "16:11:00-16:12:00", "abc", "", "自动识别", "")
    assert not bad2.ok and any("PID" in e for e in bad2.errors)
    ok = validate_params("文言没触发", "23:59:00-00:01:00", "5636", "FcwAcitveSt", "gbk", "")
    assert ok.ok
    assert ok.params.time_range == "23:59:00-00:01:00"
    assert ok.params.pid == 5636
    assert ok.params.focus_signals == ["FcwAcitveSt"]
    assert ok.params.encoding == "gbk"


def test_create_task_isolates_upload(tmp_path, monkeypatch):
    root = tmp_path / "tmp" / "ui_workbench"
    root.mkdir(parents=True)
    monkeypatch.setattr("adaslog.ui.workspace.temp_root", lambda: root)
    task = create_task("../../evil.log", b"hello\n")
    assert task.log_path.parent == task.root
    assert task.log_path.read_bytes() == b"hello\n"
    assert ".." not in task.log_path.name
    assert task.root.parent == root


def test_fingerprint_stale_guards_rerun():
    p1 = AnalysisParams(question="a", time_range="16:11:00-16:12:00")
    p2 = AnalysisParams(question="b", time_range="16:11:00-16:12:00")
    fp1 = make_fingerprint(p1, "x.log", 10)
    fp2 = make_fingerprint(p2, "x.log", 10)
    assert fp1 != fp2
    from adaslog.ui.workspace import TaskWorkspace

    sess = AnalysisSession(
        task=TaskWorkspace("t", Path("."), Path("x.log"), Path(".")),
        params=p1,
        fingerprint=fp1,
        log_name="x.log",
        log_size=10,
        report=object(),
    )
    assert result_stale(sess, fp2) is True
    assert result_stale(sess, fp1) is False


def test_read_line_window_on_demand(tmp_path):
    p = tmp_path / "a.log"
    p.write_text("\n".join(f"line-{i}" for i in range(1, 21)) + "\n", encoding="utf-8")
    rows = read_line_window(p, 10, before=2, after=2)
    assert [ln for ln, _ in rows] == [8, 9, 10, 11, 12]
    assert rows[2][1] == "line-10"


def test_pipeline_progress_callback_compatible(tmp_path):
    """Optional on_stage must not break CLI-style progress=False callers."""
    from adaslog.core.pipeline import run_analysis

    p = tmp_path / "c.log"
    p.write_text(
        "08-11 16:11:00.000  100  100 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: java.lang.NullPointerException: boom\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: \tat com.a.A.foo(A.kt:1)\n",
        encoding="utf-8",
    )
    seen: list[str] = []
    result = run_analysis(
        p, formats=["json"], out_dir=tmp_path / "out", llm_provider="rule",
        progress=False, on_stage=lambda stage, msg: seen.append(stage),
    )
    assert result["report"].issue_type == "CRASH"
    assert "load" in seen and "extract" in seen and "analyze" in seen and "report" in seen


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("streamlit") is None,
    reason="streamlit optional; install adaslog[ui] for AppTest",
)
def test_streamlit_apptest_upload_analyze_download_and_guards(tmp_path, monkeypatch):
    """Streamlit AppTest closed loop (not a headed browser, but real widget interaction)."""
    from streamlit.testing.v1 import AppTest

    root = tmp_path / "tmp" / "ui_workbench"
    root.mkdir(parents=True)
    monkeypatch.setattr("adaslog.ui.workspace.temp_root", lambda: root)
    monkeypatch.setattr("adaslog.ui.app.cleanup_old_tasks", lambda keep_latest=30: 0)
    app_path = Path(__file__).resolve().parents[2] / "src" / "adaslog" / "ui" / "app.py"

    crash = (
        "08-11 16:11:00.000  100  100 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: java.lang.NullPointerException: boom\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: \tat com.a.A.foo(A.kt:1)\n"
    ).encode("utf-8")

    at = AppTest.from_file(str(app_path), default_timeout=60)
    at.run()
    assert not at.exception
    assert any("工作台" in (el.value or "") for el in at.title)

    # Empty upload rejected
    at.file_uploader[0].set_value([("empty.log", b"", "text/plain")]).run()
    at.button[0].click().run()
    assert any("空" in (e.value or "") for e in at.error)

    # Bad time window
    at.file_uploader[0].set_value([("c.log", crash, "text/plain")]).run()
    at.text_input[0].set_value("25:99:00-26:00:00").run()
    at.button[0].click().run()
    assert any("时间窗" in (e.value or "") for e in at.error)

    # Successful crash analysis + downloads bound to session
    at.text_input[0].set_value("").run()
    at.file_uploader[0].set_value([("crash.log", crash, "text/plain")]).run()
    at.button[0].click().run()
    assert not at.exception
    sess = at.session_state["adas_session"]
    assert sess is not None and sess.report is not None
    assert sess.report.issue_type == "CRASH"
    assert set(sess.rendered) >= {"md", "json", "txt"}
    assert {b.label for b in at.download_button} >= {"下载 MD", "下载 JSON", "下载 TXT"}
    assert any(t.label == "证据查看" for t in at.tabs)

    # Param change must warn that results belong to the previous task
    at.text_area[0].set_value("参数已改").run()
    assert any("上一次任务" in (w.value or "") for w in at.warning)
