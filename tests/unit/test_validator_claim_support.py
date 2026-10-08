from adaslog.llm.provider import LLMResult
from adaslog.llm.validator import validate_candidates
from adaslog.models import Classification, Evidence


def _ev(eid, category, text="x"):
    return Evidence(
        id=eid, label="EVIDENCE", category=category, event_id=1,
        text=text, why_it_matters="t", line_no=1,
    )


def test_gpu_on_signal_idle_is_unknown_not_candidate():
    """Repro A: SIGNAL_NOT_TRIGGERED + queue-empty evidence must not accept a hardware claim."""
    evidence = [_ev("E1", "text_idle", "队列为空且无当前显示，等待新文言触发")]
    clf = Classification(
        issue_type="SIGNAL_NOT_TRIGGERED", confidence=0.8, evidence_ids=["E1"],
        scores={"SIGNAL_NOT_TRIGGERED": 4}, reason="idle",
    )
    out = validate_candidates(
        LLMResult(
            candidates=[{
                "title": "GPU 硬件永久损坏",
                "status": "CANDIDATE",
                "confidence": "MEDIUM",
                "evidence_ids": ["E1"],
                "reasoning": "队列为空",
                "source": "rule",
                "claim_type": "SYMPTOM",
            }],
            provider="openai",
        ),
        evidence,
        clf,
    )
    assert out[0].status == "UNKNOWN"
    assert out[0].confidence == "LOW"
    assert out[0].reject_kind == "missing_support"
    assert "缺少支持" in (out[0].reason or "")


def test_gpu_on_crash_fatal_is_unknown_not_high():
    """Repro B: CRASH + fatal evidence is a symptom, not proof of hardware damage."""
    evidence = [_ev("E1", "fatal", "FATAL EXCEPTION: main java.lang.NullPointerException")]
    clf = Classification(issue_type="CRASH", confidence=0.95, evidence_ids=["E1"], scores={}, reason="crash")
    out = validate_candidates(
        LLMResult(
            candidates=[{
                "title": "GPU 硬件永久损坏",
                "status": "CANDIDATE",
                "confidence": "HIGH",
                "evidence_ids": ["E1"],
                "reasoning": "Fatal 异常所以是硬件损坏",
            }],
            provider="openai",
        ),
        evidence,
        clf,
    )
    assert out[0].status == "UNKNOWN"
    assert out[0].confidence != "HIGH"
    assert out[0].reject_kind == "missing_support"


def test_rule_crash_symptom_remains_candidate():
    evidence = [_ev("E1", "fatal", "FATAL EXCEPTION: main")]
    clf = Classification(issue_type="CRASH", confidence=0.9, evidence_ids=["E1"], scores={}, reason="c")
    out = validate_candidates(
        LLMResult(
            candidates=[{
                "title": "进程崩溃（Fatal 异常 / native abort）。",
                "status": "CANDIDATE",
                "confidence": "MEDIUM",
                "evidence_ids": ["E1"],
                "reasoning": "日志出现 Fatal 异常。",
            }],
            provider="rule",
        ),
        evidence,
        clf,
    )
    assert out[0].status == "CANDIDATE"
    assert "崩溃" in out[0].title


def test_llm_symptom_restatement_is_candidate_not_high():
    evidence = [_ev("E1", "fatal", "FATAL EXCEPTION: main NullPointerException")]
    clf = Classification(issue_type="CRASH", confidence=0.9, evidence_ids=["E1"], scores={}, reason="c")
    out = validate_candidates(
        LLMResult(
            candidates=[{
                "title": "进程发生 Fatal 异常",
                "status": "CANDIDATE",
                "confidence": "HIGH",
                "evidence_ids": ["E1"],
                "reasoning": "Fatal EXCEPTION 出现在日志中",
            }],
            provider="openai",
        ),
        evidence,
        clf,
    )
    assert out[0].status == "CANDIDATE"
    assert out[0].confidence != "HIGH"


def test_valid_ids_but_wrong_category_missing_support():
    evidence = [_ev("E1", "text_idle", "队列为空")]
    clf = Classification(issue_type="CRASH", confidence=0.9, evidence_ids=["E1"], scores={}, reason="c")
    out = validate_candidates(
        LLMResult(
            candidates=[{
                "title": "进程崩溃（Fatal 异常 / native abort）。",
                "status": "CANDIDATE",
                "confidence": "HIGH",
                "evidence_ids": ["E1"],
            }],
            provider="rule",
        ),
        evidence,
        clf,
    )
    assert out[0].status == "UNKNOWN"
    assert out[0].reject_kind == "missing_support"


def test_contradiction_reason_distinct_from_missing_support():
    from adaslog.models import SignalFieldStatus, SignalSummary

    evidence = [
        _ev("E1", "signal_idle", "Fcw=0"),
        _ev("E2", "signal_transition", "Fcw=2"),
    ]
    clf = Classification(
        issue_type="SIGNAL_NOT_TRIGGERED", confidence=0.8, evidence_ids=["E1", "E2"],
        scores={}, reason="x",
    )
    sig = SignalSummary(
        structs={}, constant_fields=[], changed_fields={}, focus=[],
        field_status=[SignalFieldStatus(
            key="AdasActiveSafetyFcnInfo.FcwAcitveSt", struct="AdasActiveSafetyFcnInfo",
            field="FcwAcitveSt", observation="saw_trigger", values_seen=["0", "2"], mapped=True,
        )],
    )
    out = validate_candidates(
        LLMResult(candidates=[{
            "title": "已映射焦点信号全窗口为空闲值",
            "status": "CANDIDATE",
            "confidence": "MEDIUM",
            "evidence_ids": ["E1", "E2"],
        }], provider="rule"),
        evidence, clf, sig,
    )
    assert out[0].status == "UNKNOWN"
    assert out[0].reject_kind == "contradiction"
    assert "反证" in (out[0].reason or "")
