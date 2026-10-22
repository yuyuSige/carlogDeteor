"""Signal findings must coexist with other anomalies as separate incidents."""
from adaslog.core.pipeline import run_analysis


def _signal_line(ts="08-11 16:11:27.391"):
    return (
        f"{ts}  1736  1811 D CommonAdapter: notifyCallback() AdasActiveSafetyFcnInfo, "
        f"msg:AdasActiveSafetyFcnInfo{{FcwAcitveSt=0, AebAcitveSt=0}}\n"
    )


def _jank_line(ts="08-11 16:11:27.400"):
    return (
        f"{ts}  5636  5636 I Choreographer: Skipped 30 frames!  "
        f"The application may be doing too much work on its main thread.\n"
    )


def _fatal(ts, pid, msg="boom"):
    return (
        f"{ts}  {pid}  {pid} E AndroidRuntime: FATAL EXCEPTION: main\n"
        f"{ts}  {pid}  {pid} E AndroidRuntime: Process: com.app.{pid}, PID: {pid}\n"
        f"{ts}  {pid}  {pid} E AndroidRuntime: java.lang.NullPointerException: {msg}\n"
        f"{ts}  {pid}  {pid} E AndroidRuntime: \tat com.chery.ivi.adas.A.foo(A.kt:1)\n"
    )


def test_signal_plus_jank_keeps_both_incidents(tmp_path):
    p = tmp_path / "sig_jank.log"
    p.write_text(_signal_line() + _jank_line(), encoding="utf-8")
    result = run_analysis(
        p,
        formats=["md", "json", "txt"],
        out_dir=tmp_path / "out",
        llm_provider="rule",
        focus_signals=["FcwAcitveSt"],
        progress=False,
    )
    rep = result["report"]
    types = {i.issue_type for i in rep.incidents}
    assert "SIGNAL_NOT_TRIGGERED" in types
    assert "PERFORMANCE" in types
    assert rep.issue_type == "SIGNAL_NOT_TRIGGERED"
    assert any(e.category == "signal_idle" for e in rep.key_evidence)
    assert any(e.category == "key_warning" for e in rep.key_evidence)
    # Top-level root cause must follow the primary signal incident, not jank.
    assert rep.root_causes
    assert "掉帧" not in rep.root_causes[0].title
    assert rep.root_causes[0].status == "CANDIDATE"
    sig_inc = next(i for i in rep.incidents if i.issue_type == "SIGNAL_NOT_TRIGGERED")
    perf_inc = next(i for i in rep.incidents if i.issue_type == "PERFORMANCE")
    assert sig_inc.root_causes and set(sig_inc.root_causes[0].evidence_ids) <= set(sig_inc.evidence_ids)
    assert perf_inc.root_causes and set(perf_inc.root_causes[0].evidence_ids) <= set(perf_inc.evidence_ids)
    # MD / TXT / JSON agree on both issue entries
    stem = p.stem + f"_{rep.run_id}_analysis"
    md = (tmp_path / "out" / f"{stem}.md").read_text(encoding="utf-8")
    tx = (tmp_path / "out" / f"{stem}.txt").read_text(encoding="utf-8")
    js = (tmp_path / "out" / f"{stem}.json").read_text(encoding="utf-8")
    assert "SIGNAL_NOT_TRIGGERED" in md and "PERFORMANCE" in md
    assert "SIGNAL_NOT_TRIGGERED" in tx and "PERFORMANCE" in tx
    assert "SIGNAL_NOT_TRIGGERED" in js and "PERFORMANCE" in js


def test_signal_plus_crash_keeps_both(tmp_path):
    p = tmp_path / "sig_crash.log"
    p.write_text(_signal_line() + _fatal("08-11 16:11:28.000", 5636, "crash-x"), encoding="utf-8")
    result = run_analysis(
        p, formats=["json"], out_dir=tmp_path / "out", llm_provider="rule",
        focus_signals=["FcwAcitveSt"], progress=False,
    )
    rep = result["report"]
    types = {i.issue_type for i in rep.incidents}
    assert "SIGNAL_NOT_TRIGGERED" in types
    assert "CRASH" in types
    # Crash outranks signal at top level.
    assert rep.issue_type == "CRASH"
    crash_inc = next(i for i in rep.incidents if i.issue_type == "CRASH")
    assert rep.root_causes == crash_inc.root_causes or (
        rep.root_causes and rep.root_causes[0].title == crash_inc.root_causes[0].title
    )
    assert any(e.category in ("fatal", "first_exception", "crash") for e in rep.key_evidence)
    assert any(e.category == "signal_idle" for e in rep.key_evidence)


def test_multi_process_different_anomalies_isolated(tmp_path):
    p = tmp_path / "multi.log"
    p.write_text(
        _fatal("08-11 16:11:00.000", 100, "proc-a")
        + _jank_line("08-11 16:11:00.200").replace("5636", "200")
        + _signal_line("08-11 16:11:00.300"),
        encoding="utf-8",
    )
    result = run_analysis(
        p, formats=["json"], out_dir=tmp_path / "out", llm_provider="rule",
        focus_signals=["FcwAcitveSt"], progress=False,
    )
    rep = result["report"]
    types = {i.issue_type for i in rep.incidents}
    assert "CRASH" in types
    assert "SIGNAL_NOT_TRIGGERED" in types or "PERFORMANCE" in types
    for inc in rep.incidents:
        for rc in inc.root_causes:
            assert set(rc.evidence_ids) <= set(inc.evidence_ids)
