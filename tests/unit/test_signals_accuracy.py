from adaslog.classifier import classify
from adaslog.context.signals import analyze_signals
from adaslog.detector import detect_anomalies
from adaslog.parser import load_log


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_fcw_zero_to_two_is_trigger_not_idle(tmp_path):
    p = _write(
        tmp_path,
        "t.log",
        "08-11 16:11:20.100  1736  1811 D CommonAdapter: "
        "notifyCallback() AdasActiveSafetyFcnInfo, msg:AdasActiveSafetyFcnInfo{FcwAcitveSt=0, AebAcitveSt=0}\n"
        "08-11 16:11:21.100  1736  1811 D CommonAdapter: "
        "notifyCallback() AdasActiveSafetyFcnInfo, msg:AdasActiveSafetyFcnInfo{FcwAcitveSt=2, AebAcitveSt=0}\n"
        "08-11 16:11:21.200  5636  5636 D DrivingTextManager: 队列为空且无当前显示，等待新文言触发\n",
    )
    parsed = load_log(p)
    sig = analyze_signals(parsed.events, focus_signals=["FcwAcitveSt"])
    fcw = next(s for s in sig.field_status if s.field == "FcwAcitveSt")
    assert fcw.observation == "saw_trigger"
    assert "2" in fcw.values_seen
    assert any(period.value == "2" for period in sig.focus)
    clf = classify(detect_anomalies(parsed.events), parsed.events, sig, {})
    assert clf.issue_type != "SIGNAL_NOT_TRIGGERED"


def test_focus_aeb_does_not_include_fcw(tmp_path):
    p = _write(
        tmp_path,
        "f.log",
        "08-11 16:11:20.100  1736  1811 D CommonAdapter: "
        "notifyCallback() AdasActiveSafetyFcnInfo, msg:AdasActiveSafetyFcnInfo{FcwAcitveSt=0, AebAcitveSt=0}\n",
    )
    parsed = load_log(p)
    sig = analyze_signals(parsed.events, focus_signals=["AebAcitveSt"])
    assert all(s.field == "AebAcitveSt" for s in sig.field_status)
    assert all(p.field == "AebAcitveSt" for p in sig.focus)


def test_struct_field_focus_is_strict(tmp_path):
    p = _write(
        tmp_path,
        "s.log",
        "08-11 16:11:20.100  1736  1811 D CommonAdapter: "
        "notifyCallback() OtherInfo, msg:OtherInfo{FcwAcitveSt=0}\n"
        "08-11 16:11:20.200  1736  1811 D CommonAdapter: "
        "notifyCallback() AdasActiveSafetyFcnInfo, msg:AdasActiveSafetyFcnInfo{FcwAcitveSt=0}\n",
    )
    parsed = load_log(p)
    sig = analyze_signals(parsed.events, focus_signals=["AdasActiveSafetyFcnInfo.FcwAcitveSt"])
    assert all(s.struct == "AdasActiveSafetyFcnInfo" for s in sig.field_status if s.observation != "not_sampled")


def test_unknown_field_zero_is_not_no_text(tmp_path):
    p = _write(
        tmp_path,
        "u.log",
        "08-11 16:11:20.100  1736  1811 D CommonAdapter: "
        "notifyCallback() FooBar, msg:FooBar{ParkingQuitInd=0}\n"
        "08-11 16:11:21.011  5636  5636 D DrivingTextManager: 队列为空且无当前显示，等待新文言触发\n",
    )
    parsed = load_log(p)
    sig = analyze_signals(parsed.events, focus_signals=["ParkingQuitInd"])
    st = sig.field_status[0]
    assert st.observation == "unknown_mapping"
    assert st.mapped is False
    clf = classify(detect_anomalies(parsed.events), parsed.events, sig, {})
    assert clf.issue_type != "SIGNAL_NOT_TRIGGERED"


def test_unmapped_nonzero_not_treated_as_trigger(tmp_path):
    p = _write(
        tmp_path,
        "m.log",
        "08-11 16:11:20.100  1736  1811 D CommonAdapter: "
        "notifyCallback() AdasActiveSafetyFcnInfo, msg:AdasActiveSafetyFcnInfo{FcwAcitveSt=1}\n",
    )
    parsed = load_log(p)
    sig = analyze_signals(parsed.events, focus_signals=["FcwAcitveSt"])
    st = next(s for s in sig.field_status if s.field == "FcwAcitveSt")
    assert st.observation == "saw_unmapped_value"
    assert st.mapped is True


def test_focus_not_sampled_is_unknown(tmp_path):
    p = _write(
        tmp_path,
        "n.log",
        "08-11 16:11:20.100  1736  1811 D CommonAdapter: hello without structs\n",
    )
    parsed = load_log(p)
    sig = analyze_signals(parsed.events, focus_signals=["AebAcitveSt"])
    assert sig.field_status and sig.field_status[0].observation == "not_sampled"
    clf = classify([], parsed.events, sig, {})
    assert clf.issue_type == "UNKNOWN"


def test_question_does_not_override_crash(tmp_path):
    from adaslog.core.pipeline import run_analysis

    p = _write(
        tmp_path,
        "c.log",
        "08-11 16:09:14.790  4577  4577 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:09:14.790  4577  4577 E AndroidRuntime: Process: com.chery.ivi.adas, PID: 4577\n"
        "08-11 16:09:14.790  4577  4577 E AndroidRuntime: java.lang.NullPointerException: x\n"
        "08-11 16:09:14.790  4577  4577 E AndroidRuntime: \tat com.chery.ivi.adas.A.foo(A.kt:1)\n",
    )
    result = run_analysis(
        p, formats=["json"], out_dir=tmp_path / "out", llm_provider="rule",
        question="文言没有触发", progress=False,
    )
    assert result["report"].issue_type == "CRASH"
    assert any("用户关注" in u for u in result["report"].unknowns)
