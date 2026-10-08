from adaslog.llm.provider import LLMResult
from adaslog.llm.validator import validate_candidates
from adaslog.models import Classification, Evidence, SignalFieldStatus, SignalSummary


def _ev(eid, category, text="x"):
    return Evidence(
        id=eid, label="EVIDENCE", category=category, event_id=1,
        text=text, why_it_matters="t", line_no=1,
    )


def test_gpu_claim_on_queue_empty_is_unknown():
    evidence = [_ev("E1", "text_idle", "队列为空")]
    clf = Classification(
        issue_type="EXCEPTION", confidence=0.9, evidence_ids=["E1"],
        scores={"EXCEPTION": 4}, reason="score high",
    )
    raw = LLMResult(
        candidates=[{
            "title": "GPU 硬件永久损坏",
            "status": "CANDIDATE",
            "confidence": "HIGH",
            "evidence_ids": ["E1"],
            "reasoning": "队列为空所以 GPU 坏了",
        }],
        provider="fake",
    )
    out = validate_candidates(raw, evidence, clf)
    assert out and out[0].status == "UNKNOWN"
    assert out[0].confidence == "LOW"
    assert "硬件" in out[0].reasoning or "证据类型" in out[0].reasoning or "支持" in out[0].reasoning


def test_missing_and_partial_evidence_ids():
    evidence = [_ev("E1", "fatal")]
    clf = Classification(issue_type="CRASH", confidence=0.9, evidence_ids=["E1"], scores={}, reason="c")
    missing = validate_candidates(
        LLMResult(candidates=[{"title": "crash", "status": "CANDIDATE", "confidence": "HIGH", "evidence_ids": ["E99"]}]),
        evidence, clf,
    )
    assert missing[0].status == "UNKNOWN"
    partial = validate_candidates(
        LLMResult(candidates=[{"title": "crash", "status": "CANDIDATE", "confidence": "HIGH", "evidence_ids": ["E1", "E99"]}]),
        evidence, clf,
    )
    assert "E1" in partial[0].evidence_ids
    assert "E99" not in partial[0].evidence_ids


def test_malformed_structure_and_enums():
    evidence = [_ev("E1", "fatal")]
    clf = Classification(issue_type="CRASH", confidence=0.8, evidence_ids=["E1"], scores={}, reason="c")
    out = validate_candidates(
        LLMResult(candidates=["not a dict", {"title": 1, "status": "YES", "confidence": "ULTRA", "evidence_ids": "E1"}]),
        evidence, clf,
    )
    assert all(c.status == "UNKNOWN" or c.confidence in ("HIGH", "MEDIUM", "LOW") for c in out)


def test_contradicting_signal_transition_blocks_idle_claim():
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
        field_status=[SignalFieldStatus(key="AdasActiveSafetyFcnInfo.FcwAcitveSt", struct="AdasActiveSafetyFcnInfo",
                                        field="FcwAcitveSt", observation="saw_trigger", values_seen=["0", "2"], mapped=True)],
    )
    out = validate_candidates(
        LLMResult(candidates=[{
            "title": "焦点信号保持为 0",
            "status": "CANDIDATE",
            "confidence": "HIGH",
            "evidence_ids": ["E1", "E2"],
        }]),
        evidence, clf, sig,
    )
    assert out[0].status == "UNKNOWN"


def test_empty_classification_forces_unknown():
    clf = Classification(issue_type="UNKNOWN", confidence=0.3, evidence_ids=[], scores={}, reason="空日志", data_status="empty")
    out = validate_candidates(LLMResult(candidates=[{"title": "正常", "status": "CANDIDATE", "confidence": "HIGH", "evidence_ids": []}]), [], clf)
    assert out[0].status == "UNKNOWN" and out[0].confidence == "LOW"
