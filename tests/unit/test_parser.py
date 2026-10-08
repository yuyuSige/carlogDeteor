from adaslog.parser import load_log, parse_lines, aggregate_stacktraces, TagNormalizer
from adaslog.parser.logcat import parse_line
from adaslog.utils.io import repair_mojibake_line, decode_bytes
from adaslog.utils.timeparse import parse_timestamp, parse_clock


def test_threadtime_line():
    d = parse_line("08-11 16:11:27.391  5636  5636 D DrivingTextManager: 队列为空")
    assert d["pid"] == "5636" and d["tid"] == "5636" and d["lvl"] == "D"
    assert d["tag"] == "DrivingTextManager" and d["msg"] == "队列为空"


def test_threadtime_empty_tag_kernel():
    d = parse_line("01-01 08:00:02.524     0     0 I         : [    0.000000] Booting Linux")
    assert d["lvl"] == "I" and d["tag"].strip() == "" and d["msg"].startswith("[")


def test_time_and_brief_and_custom_formats():
    assert parse_line("08-11 16:11:27.391 E/CarService( 1234): boom")["pid"] == "1234"
    assert parse_line("E/CarService( 1234): boom")["tag"] == "CarService"
    d = parse_line("2026-09-29 10:31:22.123 E/CarService: java.lang.NullPointerException")
    assert d["lvl"] == "E" and d["tag"] == "CarService"


def test_generic_and_bare_lines():
    d = parse_line("2026-09-29 10:31:22.123 ERROR something happened")
    assert d["lvl"] == "E" and d["msg"] == "something happened"
    assert parse_line("ERROR something happened")["lvl"] == "E"
    evs = parse_lines(["service started", "connection established"])
    assert len(evs) == 2 and evs[0].level is None


def test_timestamp_parsing():
    assert parse_timestamp("08-11 16:11:27.391") is not None
    assert parse_timestamp("2026-09-29 10:31:22.123") is not None
    assert parse_clock("16:11:27") == ((16 * 60 + 11) * 60 + 27) * 1000


def test_stacktrace_aggregation(fixtures_dir):
    text = (fixtures_dir / "crash_snippet.log").read_text(encoding="utf-8")
    evs = aggregate_stacktraces(parse_lines(text.splitlines()))
    fatal = [e for e in evs if e.extra.get("fatal")]
    assert len(fatal) == 1
    e = fatal[0]
    assert e.extra["exception_class"] == "java.lang.NullPointerException"
    assert e.extra["process"] == "com.chery.ivi.adas"
    assert e.extra["app_frame"]["file"] == "AvmViewPresenter.kt" and e.extra["app_frame"]["line"] == 214
    assert any("Caused by" in s for s in e.stacktrace)
    # the frames were merged: no standalone "at ..." events remain
    assert not any(ev.message.strip().startswith("at ") for ev in evs)


def test_tag_normalizer_prefix_and_truncation():
    n = TagNormalizer()
    assert n.normalize_tag("IVI_ADAS_APP_StateMachi") == "StateMachine"
    assert n.normalize_tag("IVI_ADAS_APP_AvmViewPre") == "AvmViewPresenter"
    assert n.normalize_tag("IVI_ADAS_APP_Event") == "Event"
    assert n.normalize_tag("DrivingTextManager") == "DrivingTextManager"
    assert n.module_for_tag("StateMachine") == "statemachine"
    assert n.module_for_tag("DrivingTextManager") == "driving_text_tip"


def test_process_resolution(fixtures_dir):
    parsed = load_log(fixtures_dir / "crash_snippet.log")
    procs = parsed.meta["processes"]
    assert procs["5636"] == "com.chery.ivi.adas" and procs["4577"] == "com.chery.ivi.adas"
    sm = [e for e in parsed.events if e.tag == "StateMachine"]
    assert sm and sm[0].process == "com.chery.ivi.adas" and sm[0].module == "statemachine"


def test_mojibake_repair():
    fixed, changed = repair_mojibake_line("D DrivingTextManager: 闃熷垪涓虹┖涓旀棤褰撳墠鏄剧ず锛岀瓑寰呮柊鏂囪█瑙﹀彂")
    assert changed and "队列为空且无当前显示" in fixed
    same, changed2 = repair_mojibake_line("plain ascii line")
    assert not changed2 and same == "plain ascii line"


def test_decode_utf16():
    raw = "\ufeffabc 中文".encode("utf-16-le")
    text, enc = decode_bytes(raw)
    assert enc == "utf-16-le" and text == "abc 中文"
