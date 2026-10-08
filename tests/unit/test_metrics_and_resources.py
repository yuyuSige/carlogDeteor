import json

from adaslog.core.config import load_config, load_json_resource
from adaslog.testing.metrics import compute_metrics
from adaslog.testing.runner import _eval_case
from adaslog.models import AnalysisReport, Classification, Evidence, RootCauseCandidate


def _report(**kwargs):
    clf = kwargs.pop("classification", Classification(issue_type="CRASH", confidence=0.8, evidence_ids=["E1"], scores={}, reason="x"))
    return AnalysisReport(
        issue_type=kwargs.get("issue_type", "CRASH"),
        severity="HIGH",
        summary="s",
        classification=clf,
        key_evidence=kwargs.get("key_evidence", [Evidence(id="E1", label="EVIDENCE", category="fatal", event_id=1, text="t", why_it_matters="w")]),
        timeline=[],
        causal_chain=[],
        context_windows=[],
        root_causes=kwargs.get("root_causes", [RootCauseCandidate(title="c", status="CANDIDATE", confidence="MEDIUM", evidence_ids=["E1"], reasoning="r")]),
        confidence="MEDIUM",
        related_modules=[],
        related_processes=[],
        related_code=[],
        recommendations=[],
        unknowns=[],
        signal_summary=None,
        meta={},
        incidents=kwargs.get("incidents", []),
    )


def test_runner_checks_forbidden_evidence():
    ok, errors = _eval_case(
        _report(),
        {"issue_type": "CRASH", "forbidden_evidence_categories": ["fatal"]},
    )
    assert not ok and any("forbidden evidence" in e for e in errors)


def test_packaged_rules_load():
    rules = load_json_resource("rules/signal_text.json")
    assert "FcwAcitveSt" in rules["fields"]
    cfg = load_config()
    assert "classifier" in cfg


def test_user_config_utf8_bom(tmp_path):
    p = tmp_path / "u.json"
    p.write_bytes(b'\xef\xbb\xbf{"classifier":{"normal_confidence":0.55}}')
    cfg = load_config(p)
    assert cfg["classifier"]["normal_confidence"] == 0.55


def test_metrics_do_not_treat_id_coverage_as_correctness(tmp_path, cases_dir):
    case_dir = tmp_path / "positive" / "fake_case"
    case_dir.mkdir(parents=True)
    (case_dir / "expected.json").write_text(
        json.dumps({
            "issue_type": "CRASH",
            "must_have_evidence_categories": ["fatal"],
            "forbidden_evidence_categories": ["text_idle"],
            "forbidden_root_cause_substrings": ["GPU"],
            "sample_kind": "synthetic",
        }),
        encoding="utf-8",
    )
    results = tmp_path / "results"
    out = results / "fake_case"
    out.mkdir(parents=True)
    (out / "x_analysis.json").write_text(
        json.dumps({
            "root_causes": [{"status": "CANDIDATE", "title": "GPU 损坏", "evidence_ids": ["E1"]}],
            "key_evidence": [{"category": "fatal"}, {"category": "text_idle"}, {"category": "extra_unlabelled"}],
        }),
        encoding="utf-8",
    )
    (results / "test_result.json").write_text(
        json.dumps({
            "passed": 1, "failed": 0,
            "cases_dir": str(tmp_path),
            "cases": [{
                "case": "fake_case", "group": "positive", "pass": True,
                "expected": "CRASH", "actual": "CRASH",
                "expected_path": str(case_dir / "expected.json"),
                "sample_kind": "synthetic",
            }],
        }),
        encoding="utf-8",
    )
    m = compute_metrics(results_dir=results, cases_dir=tmp_path)
    assert m["hallucination_rate_definition"]
    assert "NOT root-cause" in m["hallucination_rate_definition"]
    assert m["claim_mismatch_rate"] > 0
    assert m["key_log_extraction"]["unlabelled_extra_categories"] >= 1
    assert m["sample_kinds"]["synthetic"] == 1
