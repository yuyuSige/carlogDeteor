from adaslog.classifier.incidents import build_incidents
from adaslog.detector import detect_anomalies
from adaslog.parser import parse_lines
from adaslog.parser.stacktrace import aggregate_stacktraces
from adaslog.models import Evidence


def _fatal(ts, pid, tag="AndroidRuntime"):
    return (
        f"{ts}  {pid}  {pid} E {tag}: FATAL EXCEPTION: main\n"
        f"{ts}  {pid}  {pid} E {tag}: Process: com.app.{pid}, PID: {pid}\n"
        f"{ts}  {pid}  {pid} E {tag}: java.lang.NullPointerException: boom\n"
        f"{ts}  {pid}  {pid} E {tag}: \tat com.chery.ivi.adas.A.foo(A.kt:1)\n"
    )


def test_multi_pid_same_exception_are_separate_incidents():
    text = _fatal("08-11 16:11:00.000", 100) + _fatal("08-11 16:11:00.050", 200)
    evs = aggregate_stacktraces(parse_lines(text.splitlines()))
    ans = detect_anomalies(evs)
    evidence = [
        Evidence(id="E1", label="EVIDENCE", category="fatal", event_id=0, text="a", why_it_matters="t"),
        Evidence(id="E2", label="EVIDENCE", category="fatal", event_id=1, text="b", why_it_matters="t"),
    ]
    incs = build_incidents(ans, evs, "CRASH", evidence, [])
    pids = {i.pid for i in incs}
    assert 100 in pids and 200 in pids
    assert len(incs) >= 2


def test_same_pid_far_apart_not_merged():
    text = _fatal("08-11 16:11:00.000", 100) + _fatal("08-11 16:13:30.000", 100)
    evs = aggregate_stacktraces(parse_lines(text.splitlines()))
    ans = detect_anomalies(evs)
    incs = build_incidents(ans, evs, "CRASH", [], [])
    crash = [i for i in incs if i.issue_type == "CRASH"]
    assert len(crash) >= 2


def test_interleaved_stacks_do_not_cross_pid():
    lines = [
        "08-11 16:11:00.000  100  100 E AndroidRuntime: FATAL EXCEPTION: main",
        "08-11 16:11:00.000  200  200 E AndroidRuntime: FATAL EXCEPTION: main",
        "08-11 16:11:00.000  100  100 E AndroidRuntime: java.lang.NullPointerException: a",
        "08-11 16:11:00.000  200  200 E AndroidRuntime: java.lang.IllegalStateException: b",
        "08-11 16:11:00.000  100  100 E AndroidRuntime: \tat com.a.A.foo(A.kt:1)",
        "08-11 16:11:00.000  200  200 E AndroidRuntime: \tat com.b.B.bar(B.kt:2)",
    ]
    evs = aggregate_stacktraces(parse_lines(lines))
    for e in evs:
        blob = e.message + "\n" + "\n".join(e.stacktrace)
        if e.pid == 100:
            assert "B.kt" not in blob and "IllegalStateException" not in blob
        if e.pid == 200:
            assert "A.kt" not in blob and "NullPointerException" not in blob


def test_truncated_stack_keeps_original_line_no():
    lines = [
        "08-11 16:11:00.000  100  100 E AndroidRuntime: FATAL EXCEPTION: main",
        "08-11 16:11:00.000  100  100 E AndroidRuntime: java.lang.NullPointerException: cut",
        "08-11 16:11:00.000  100  100 E AndroidRuntime: \tat com.a.A.foo(A.kt:1)",
        # truncated: no further frames
        "08-11 16:11:01.000  100  100 I Other: still here",
    ]
    evs = aggregate_stacktraces(parse_lines(lines))
    fatal = next(e for e in evs if e.extra.get("fatal") or e.extra.get("exception_class"))
    assert fatal.line_no == 1
    assert fatal.stacktrace
