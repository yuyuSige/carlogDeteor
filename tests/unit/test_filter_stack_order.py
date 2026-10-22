"""Time/PID filter must preserve stacks, boundaries, and original line order."""
from adaslog.parser import load_log


def test_bare_continuation_inherits_time_window(tmp_path):
    """Fatal with unprefixed exception/at lines must keep A.kt:42 under a time window."""
    p = tmp_path / "bare.log"
    p.write_text(
        "08-11 16:11:27.391  5636  5636 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "java.lang.NullPointerException: boom\n"
        "\tat com.chery.ivi.adas.A.foo(A.kt:42)\n"
        "08-11 16:11:28.000  5636  5636 I Other: after\n",
        encoding="utf-8",
    )
    full = load_log(p)
    fatal_full = next(e for e in full.events if e.extra.get("fatal") or "FATAL" in e.message)
    assert any("A.kt:42" in s for s in fatal_full.stacktrace)

    filtered = load_log(p, time_range="16:11:00-16:12:00")
    fatal = next(
        e for e in filtered.events
        if e.extra.get("fatal") or e.extra.get("exception_class") or "FATAL" in e.message
    )
    blob = fatal.message + "\n" + "\n".join(fatal.stacktrace)
    assert "A.kt:42" in blob
    assert fatal.stacktrace, "time filter must not drop bare stack frames"


def test_independent_exception_not_pulled_into_later_window(tmp_path):
    """Same pid/tid/tag at 16:00 and 16:11: filtering 16:11 must not keep the old fault."""
    p = tmp_path / "gap.log"
    p.write_text(
        "08-11 16:00:00.000  100  100 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:00:00.000  100  100 E AndroidRuntime: java.lang.NullPointerException: old\n"
        "08-11 16:00:00.000  100  100 E AndroidRuntime: \tat com.old.O.foo(O.kt:1)\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: java.lang.IllegalStateException: new\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: \tat com.newpkg.N.bar(N.kt:2)\n",
        encoding="utf-8",
    )
    parsed = load_log(p, time_range="16:11:00-16:12:00")
    blobs = [e.message + "\n" + "\n".join(e.stacktrace) for e in parsed.events]
    assert blobs
    assert all("O.kt" not in b and "NullPointerException: old" not in b for b in blobs)
    assert any("N.kt:2" in b for b in blobs)


def test_filtered_output_keeps_original_line_order(tmp_path):
    """Interleaved other-process lines must not reverse stack event order."""
    p = tmp_path / "inter.log"
    p.write_text(
        "08-11 16:11:00.000  100  100 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:11:00.010  200  200 I Other: unrelated\n"
        "08-11 16:11:00.020  100  100 E AndroidRuntime: java.lang.NullPointerException: a\n"
        "08-11 16:11:00.030  100  100 E AndroidRuntime: \tat com.a.A.foo(A.kt:1)\n",
        encoding="utf-8",
    )
    parsed = load_log(p, time_range="16:11:00-16:12:00")
    line_nos = [e.line_no for e in parsed.events]
    assert line_nos == sorted(line_nos)
    timed = [e.timestamp for e in parsed.events if e.timestamp]
    if len(timed) >= 2:
        # meta coverage follows event order
        assert parsed.meta["time_start"] == timed[0]
        assert parsed.meta["time_end"] == timed[-1]


def test_interleaved_stacks_do_not_cross_process_under_filter(tmp_path):
    p = tmp_path / "cross.log"
    p.write_text(
        "08-11 16:11:00.000  100  100 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:11:00.000  200  200 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: java.lang.NullPointerException: a\n"
        "08-11 16:11:00.000  200  200 E AndroidRuntime: java.lang.IllegalStateException: b\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: \tat com.a.A.foo(A.kt:1)\n"
        "08-11 16:11:00.000  200  200 E AndroidRuntime: \tat com.b.B.bar(B.kt:2)\n",
        encoding="utf-8",
    )
    parsed = load_log(p, time_range="16:11:00-16:12:00")
    for e in parsed.events:
        blob = e.message + "\n" + "\n".join(e.stacktrace)
        if e.pid == 100:
            assert "B.kt" not in blob and "IllegalStateException" not in blob
        if e.pid == 200:
            assert "A.kt" not in blob and "NullPointerException" not in blob


def test_midnight_wrap_keeps_both_sides(tmp_path):
    p = tmp_path / "mid.log"
    p.write_text(
        "08-11 23:59:30.000  100  100 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 23:59:30.000  100  100 E AndroidRuntime: java.lang.NullPointerException: late\n"
        "08-11 23:59:30.000  100  100 E AndroidRuntime: \tat com.a.A.foo(A.kt:1)\n"
        "08-12 00:00:30.000  100  100 I Other: early morning\n",
        encoding="utf-8",
    )
    parsed = load_log(p, time_range="23:59:00-00:01:00")
    assert parsed.meta["time_wraps_midnight"] is True
    assert any(e.extra.get("fatal") or e.extra.get("exception_class") for e in parsed.events)
    assert any("early morning" in e.message for e in parsed.events)


def test_pid_filter_keeps_matching_stack(tmp_path):
    p = tmp_path / "pid.log"
    p.write_text(
        "08-11 16:11:00.000  100  100 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: java.lang.NullPointerException: a\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: \tat com.a.A.foo(A.kt:1)\n"
        "08-11 16:11:00.000  200  200 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:11:00.000  200  200 E AndroidRuntime: java.lang.IllegalStateException: b\n"
        "08-11 16:11:00.000  200  200 E AndroidRuntime: \tat com.b.B.bar(B.kt:2)\n",
        encoding="utf-8",
    )
    parsed = load_log(p, pid=100)
    assert all(e.pid == 100 for e in parsed.events if e.pid is not None)
    assert any("A.kt:1" in "\n".join(e.stacktrace) for e in parsed.events)


def test_pid_reuse_uses_identity_at_event_time(tmp_path):
    """Later Start proc must not overwrite the process name of earlier events."""
    p = tmp_path / "reuse.log"
    p.write_text(
        "08-11 16:00:00.000   1  1 I ActivityManager: Start proc 100:com.old/1000 for service {x}\n"
        "08-11 16:05:00.000  100  100 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:05:00.000  100  100 E AndroidRuntime: java.lang.NullPointerException: old-era\n"
        "08-11 16:05:00.000  100  100 E AndroidRuntime: \tat com.old.O.foo(O.kt:1)\n"
        "08-11 16:10:00.000   1  1 I ActivityManager: Start proc 100:com.new/1000 for service {y}\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: java.lang.NullPointerException: new-era\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: \tat com.newpkg.N.bar(N.kt:2)\n",
        encoding="utf-8",
    )
    parsed = load_log(p)
    old = next(e for e in parsed.events if "old-era" in (e.message + "\n" + "\n".join(e.stacktrace)))
    new = next(e for e in parsed.events if "new-era" in (e.message + "\n" + "\n".join(e.stacktrace)))
    assert old.process == "com.old"
    assert new.process == "com.new"
    # Meta still exposes last-known mapping for the pid.
    assert parsed.meta["processes"]["100"] == "com.new"
