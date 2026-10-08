from adaslog.core.pipeline import run_analysis
from adaslog.extractor import extract_evidence
from adaslog.parser import parse_lines
from adaslog.parser.stacktrace import aggregate_stacktraces
from adaslog.classifier.incidents import group_anomalies, events_for_draft
from adaslog.detector import detect_anomalies


def _fatal(ts, pid, msg):
    return (
        f"{ts}  {pid}  {pid} E AndroidRuntime: FATAL EXCEPTION: main\n"
        f"{ts}  {pid}  {pid} E AndroidRuntime: Process: com.app.{pid}, PID: {pid}\n"
        f"{ts}  {pid}  {pid} E AndroidRuntime: java.lang.NullPointerException: {msg}\n"
        f"{ts}  {pid}  {pid} E AndroidRuntime: \tat com.chery.ivi.adas.A.foo(A.kt:1)\n"
    )


def test_multi_pid_root_causes_do_not_share_evidence(tmp_path):
    p = tmp_path / "m.log"
    p.write_text(_fatal("08-11 16:11:00.000", 100, "proc-a") + _fatal("08-11 16:11:00.050", 200, "proc-b"), encoding="utf-8")
    result = run_analysis(p, formats=["md", "json", "txt"], out_dir=tmp_path / "out", llm_provider="rule", progress=False)
    rep = result["report"]
    by_pid = {inc.pid: inc for inc in rep.incidents}
    assert 100 in by_pid and 200 in by_pid
    ids100 = set(by_pid[100].evidence_ids)
    ids200 = set(by_pid[200].evidence_ids)
    assert ids100 and ids200
    assert ids100.isdisjoint(ids200)
    for pid, inc in by_pid.items():
        allowed = set(inc.evidence_ids)
        assert inc.root_causes
        for rc in inc.root_causes:
            assert set(rc.evidence_ids) <= allowed
            assert rc.evidence_ids
    md = (tmp_path / "out" / (p.stem + f"_{rep.run_id}_analysis.md")).read_text(encoding="utf-8")
    tx = (tmp_path / "out" / (p.stem + f"_{rep.run_id}_analysis.txt")).read_text(encoding="utf-8")
    js = (tmp_path / "out" / (p.stem + f"_{rep.run_id}_analysis.json")).read_text(encoding="utf-8")
    assert "I1" in md and "I2" in md and "证据" in md
    assert "I1" in tx and "证据" in tx
    assert '"pid": 100' in js and '"pid": 200' in js


def test_same_pid_gap_root_causes_isolated(tmp_path):
    p = tmp_path / "g.log"
    p.write_text(_fatal("08-11 16:11:00.000", 100, "first") + _fatal("08-11 16:13:30.000", 100, "second"), encoding="utf-8")
    result = run_analysis(p, formats=["json"], out_dir=tmp_path / "out", llm_provider="rule", progress=False)
    incs = [i for i in result["report"].incidents if i.issue_type == "CRASH"]
    assert len(incs) >= 2
    assert set(incs[0].evidence_ids).isdisjoint(set(incs[1].evidence_ids))
    for inc in incs:
        for rc in inc.root_causes:
            assert set(rc.evidence_ids) <= set(inc.evidence_ids)


def test_mixed_types_each_get_own_analysis(tmp_path):
    p = tmp_path / "x.log"
    p.write_text(
        _fatal("08-11 16:11:00.000", 100, "crash-a")
        + "08-11 16:11:00.200  200  200 E AvmSdkService: android.os.DeadObjectException\n"
        + "08-11 16:11:00.210  200  200 W AvmWindowManager: onServiceDisconnected: shared surface\n",
        encoding="utf-8",
    )
    result = run_analysis(p, formats=["json"], out_dir=tmp_path / "out", llm_provider="rule", progress=False)
    types = {i.issue_type for i in result["report"].incidents}
    assert "CRASH" in types
    assert "BINDER_IPC" in types or any(i.pid == 200 and i.root_causes for i in result["report"].incidents)
    for inc in result["report"].incidents:
        for rc in inc.root_causes:
            assert set(rc.evidence_ids) <= set(inc.evidence_ids)


def test_later_incident_survives_global_evidence_cap():
    lines = []
    for i in range(40):
        lines.append(f"08-11 16:11:00.{i:03d}  100  100 E Tag{i}: unique error number {i} boom\n")
    lines.append("08-11 16:11:02.000  200  200 E AndroidRuntime: FATAL EXCEPTION: main\n")
    lines.append("08-11 16:11:02.000  200  200 E AndroidRuntime: java.lang.NullPointerException: late\n")
    lines.append("08-11 16:11:02.000  200  200 E AndroidRuntime: \tat com.chery.ivi.adas.A.foo(A.kt:1)\n")
    evs = aggregate_stacktraces(parse_lines("".join(lines).splitlines()))
    ans = detect_anomalies(evs)
    drafts = group_anomalies(ans, evs)
    assert any(d.pid == 200 for d in drafts)
    from adaslog.core.pipeline import _extract_fair
    evidence, per = _extract_fair(evs, drafts, None, max_items=8)
    late = next(ids for d, ids in zip(drafts, per) if d.pid == 200)
    assert late, "pid 200 must still have evidence when max_items is small"
    assert any(e.id in late and e.category in ("fatal", "first_exception", "first_error") for e in evidence)
