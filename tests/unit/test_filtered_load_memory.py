from adaslog.parser import load_log


def test_time_window_keeps_stack_and_outside_proc_map(tmp_path):
    p = tmp_path / "w.log"
    p.write_text(
        "08-11 16:00:00.000   456   456 I ActivityManager: Start proc 100:com.app.one/1000 for service {x}\n"
        "08-11 16:10:00.000  999  999 I Noise: ignore me\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: java.lang.NullPointerException: x\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: \tat com.chery.ivi.adas.A.foo(A.kt:1)\n"
        "08-11 16:12:00.000  999  999 I Noise: after\n",
        encoding="utf-8",
    )
    parsed = load_log(p, time_range="16:11:00-16:11:30")
    assert parsed.meta["memory_strategy"] == "filter_early"
    assert parsed.meta["processes"].get("100") == "com.app.one"
    assert any(e.extra.get("fatal") or e.extra.get("exception_class") for e in parsed.events)
    assert parsed.events[0].line_no == 3
    assert not any("ignore me" in e.message for e in parsed.events)
    assert not any("after" in e.message for e in parsed.events)


def test_stack_starting_just_outside_window_kept_if_frames_inside(tmp_path):
    p = tmp_path / "edge.log"
    p.write_text(
        "08-11 16:10:59.500  100  100 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:11:00.100  100  100 E AndroidRuntime: java.lang.NullPointerException: x\n"
        "08-11 16:11:00.100  100  100 E AndroidRuntime: \tat com.chery.ivi.adas.A.foo(A.kt:1)\n",
        encoding="utf-8",
    )
    parsed = load_log(p, time_range="16:11:00-16:11:30")
    assert any("FATAL" in e.message or e.extra.get("fatal") or e.extra.get("exception_class") for e in parsed.events)


def test_pid_reuse_uses_last_start_proc(tmp_path):
    p = tmp_path / "reuse.log"
    p.write_text(
        "08-11 16:00:00.000   1  1 I ActivityManager: Start proc 100:com.old/1000 for service {x}\n"
        "08-11 16:10:00.000   1  1 I ActivityManager: Start proc 100:com.new/1000 for service {y}\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: java.lang.NullPointerException: x\n"
        "08-11 16:11:00.000  100  100 E AndroidRuntime: \tat com.chery.ivi.adas.A.foo(A.kt:1)\n",
        encoding="utf-8",
    )
    parsed = load_log(p, time_range="16:11:00-16:11:30")
    assert parsed.meta["processes"]["100"] == "com.new"
    crash = next(e for e in parsed.events if e.pid == 100)
    assert crash.process == "com.new"
