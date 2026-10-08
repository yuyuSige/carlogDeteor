from adaslog.classifier import classify
from adaslog.context.signals import analyze_signals
from adaslog.core.pipeline import run_analysis
from adaslog.detector import detect_anomalies
from adaslog.parser import load_log


def test_signal_zero_rule(tmp_path):
    p = tmp_path / "s.log"
    p.write_text(
        "08-11 16:11:20.100  1736  1811 D CommonAdapter: "
        "notifyCallback() AdasActiveSafetyFcnInfo, msg:AdasActiveSafetyFcnInfo{FcwAcitveSt=0, AebAcitveSt=0}\n"
        "08-11 16:11:21.011  5636  5636 D DrivingTextManager: 队列为空且无当前显示，等待新文言触发\n",
        encoding="utf-8",
    )
    parsed = load_log(p)
    sig = analyze_signals(parsed.events, focus_signals=["FcwAcitveSt"])
    assert sig.text_manager_idle_count == 1
    assert sig.text_manager_trigger_count == 0
    assert any(p.field == "FcwAcitveSt" and p.value == "0" for p in sig.focus)
    clf = classify(detect_anomalies(parsed.events), parsed.events, sig, {})
    assert clf.issue_type == "SIGNAL_NOT_TRIGGERED"


def test_normal_and_unknown_controls(fixtures_dir):
    from adaslog.parser import parse_lines

    evs = parse_lines(["service started", "connection established", "request completed"])
    assert classify([], evs).issue_type == "NORMAL"
    evs2 = parse_lines(["ERROR something happened"])
    assert classify([], evs2).issue_type == "UNKNOWN"


def test_analyze_crash_fixture(fixtures_dir, tmp_path):
    result = run_analysis(fixtures_dir / "crash_snippet.log", formats=["txt"], out_dir=tmp_path, llm_provider="rule")
    assert result["report"].issue_type == "CRASH"
    assert result["report"].root_causes[0].evidence_ids
