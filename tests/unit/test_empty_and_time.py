from pathlib import Path

import pytest

from adaslog.classifier import classify
from adaslog.core.errors import LogLoadError
from adaslog.core.pipeline import run_analysis
from adaslog.parser import load_log, parse_lines
from adaslog.utils.timeparse import in_clock_range, parse_clock, parse_timestamp


def test_parse_clock_rejects_out_of_range():
    assert parse_clock("24:00:00") is None
    assert parse_clock("12:60:00") is None
    assert parse_clock("12:00:60") is None
    assert parse_clock("23:59:59") is not None


def test_midnight_wrap_includes_both_sides():
    start, end = parse_clock("23:59:00"), parse_clock("00:01:00")
    late = parse_timestamp("08-11 23:59:30.000") % (24 * 3600 * 1000)
    early = parse_timestamp("08-11 00:00:30.000") % (24 * 3600 * 1000)
    mid = parse_timestamp("08-11 16:11:00.000") % (24 * 3600 * 1000)
    assert in_clock_range(late, start, end)
    assert in_clock_range(early, start, end)
    assert not in_clock_range(mid, start, end)


def test_empty_log_is_unknown_not_normal(tmp_path):
    p = tmp_path / "empty.log"
    p.write_text("", encoding="utf-8")
    parsed = load_log(p)
    assert parsed.meta["data_status"] == "empty"
    clf = classify([], parsed.events, data_status=parsed.meta["data_status"])
    assert clf.issue_type == "UNKNOWN"
    assert clf.data_status == "empty"
    result = run_analysis(p, formats=["json"], out_dir=tmp_path / "out", llm_provider="rule", progress=False)
    rep = result["report"]
    assert rep.issue_type == "UNKNOWN"
    assert rep.classification_confidence == "LOW"
    assert rep.root_cause_confidence == "LOW"
    assert "足够数据" in rep.summary or "数据" in rep.summary
    assert all(rc.status == "UNKNOWN" for rc in rep.root_causes)


def test_time_filter_empty_is_not_normal(tmp_path):
    p = tmp_path / "day.log"
    p.write_text(
        "08-11 16:11:20.100  1736  1811 D CommonAdapter: hello\n",
        encoding="utf-8",
    )
    parsed = load_log(p, time_range="10:00:00-10:01:00")
    assert parsed.meta["data_status"] == "filter_empty"
    assert parsed.events == []
    result = run_analysis(
        p, formats=["txt"], out_dir=tmp_path / "out", llm_provider="rule",
        time_range="10:00:00-10:01:00", progress=False,
    )
    assert result["report"].issue_type == "UNKNOWN"
    assert result["report"].classification.data_status == "filter_empty"
    assert result["report"].confidence != "HIGH"


def test_midnight_window_keeps_timestamped_events(tmp_path):
    p = tmp_path / "wrap.log"
    p.write_text(
        "08-11 16:11:00.000  1  1 I Skip: daytime\n"
        "08-11 23:59:30.000  100  100 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 23:59:30.000  100  100 E AndroidRuntime: Process: com.a, PID: 100\n"
        "08-11 23:59:30.000  100  100 E AndroidRuntime: java.lang.NullPointerException: x\n"
        "08-11 23:59:30.000  100  100 E AndroidRuntime: \tat com.chery.ivi.adas.A.foo(A.kt:1)\n"
        "08-11 00:00:20.000  100  100 I Keep: after midnight\n",
        encoding="utf-8",
    )
    parsed = load_log(p, time_range="23:59:00-00:01:00")
    assert parsed.meta["time_wraps_midnight"] is True
    assert parsed.meta["data_status"] == "ok"
    assert len(parsed.events) >= 2
    assert all(e.ts_ms is not None for e in parsed.events)
    messages = " ".join(e.message for e in parsed.events)
    assert "daytime" not in messages
    assert "after midnight" in messages


def test_invalid_time_range_rejected(tmp_path):
    p = tmp_path / "a.log"
    p.write_text("08-11 16:11:00.000  1  1 I T: x\n", encoding="utf-8")
    with pytest.raises(LogLoadError):
        load_log(p, time_range="24:00:00-25:00:00")


def test_untimed_excluded_when_time_range_set(tmp_path):
    p = tmp_path / "mix.log"
    p.write_text(
        "bare line without timestamp\n"
        "08-11 16:11:20.100  1736  1811 D CommonAdapter: hello\n",
        encoding="utf-8",
    )
    parsed = load_log(p, time_range="16:11:00-16:12:00")
    assert parsed.meta["untimed_excluded"] >= 1
    assert parsed.meta["filter_policy"]["untimed_events"] == "excluded_when_time_range_set"
    assert all(e.ts_ms is not None for e in parsed.events)


def test_normal_log_still_normal():
    evs = parse_lines(["service started", "connection established", "request completed"])
    assert classify([], evs).issue_type == "NORMAL"
    assert classify([], evs).data_status == "ok"
