import json
from pathlib import Path

from adaslog.testing.metrics import compute_metrics
from adaslog.testing.runner import run_cases


def _write_report(path: Path, cats, issue="CRASH"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "issue_type": issue,
            "root_causes": [{"status": "CANDIDATE", "title": "t", "evidence_ids": ["E1"]}],
            "key_evidence": [{"category": c} for c in cats],
        }),
        encoding="utf-8",
    )


def test_metrics_uses_recorded_path_not_first_glob(tmp_path):
    results = tmp_path / "results"
    case = results / "crash_case"
    _write_report(case / "old_analysis.json", ["text_idle"])
    _write_report(case / "new_analysis.json", ["fatal"])
    expected = tmp_path / "cases" / "positive" / "crash_case" / "expected.json"
    expected.parent.mkdir(parents=True)
    expected.write_text(json.dumps({
        "issue_type": "CRASH",
        "must_have_evidence_categories": ["fatal"],
        "sample_kind": "synthetic",
    }), encoding="utf-8")
    (results / "test_result.json").write_text(json.dumps({
        "passed": 1, "failed": 0, "cases_dir": str(tmp_path / "cases"),
        "cases": [{
            "case": "crash_case", "group": "positive", "pass": True,
            "expected": "CRASH", "actual": "CRASH",
            "expected_path": str(expected),
            "report_path": "crash_case/new_analysis.json",
            "run_id": "run-new",
            "sample_kind": "synthetic",
        }],
    }), encoding="utf-8")
    m = compute_metrics(results_dir=results, cases_dir=tmp_path / "cases")
    assert m["key_log_extraction"]["recall"] == 1.0
    assert m["used_reports"][0]["run_id"] == "run-new"
    assert "new_analysis.json" in m["used_reports"][0]["report_path"]


def test_metrics_ambiguous_legacy_glob_is_error(tmp_path):
    results = tmp_path / "results"
    case = results / "crash_case"
    _write_report(case / "a_analysis.json", ["fatal"])
    _write_report(case / "b_analysis.json", ["fatal"])
    expected = tmp_path / "pos" / "crash_case" / "expected.json"
    expected.parent.mkdir(parents=True)
    expected.write_text(json.dumps({"issue_type": "CRASH", "must_have_evidence_categories": ["fatal"]}), encoding="utf-8")
    (results / "test_result.json").write_text(json.dumps({
        "cases": [{
            "case": "crash_case", "group": "positive", "expected": "CRASH", "actual": "CRASH",
            "expected_path": str(expected), "pass": True,
        }],
    }), encoding="utf-8")
    m = compute_metrics(results_dir=results)
    assert m["evaluation_errors"]
    assert "ambiguous" in m["evaluation_errors"][0]["error"]


def test_metrics_missing_report_is_error(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    expected = tmp_path / "e.json"
    expected.write_text("{}", encoding="utf-8")
    (results / "test_result.json").write_text(json.dumps({
        "cases": [{
            "case": "gone", "group": "positive", "expected": "CRASH", "actual": "CRASH",
            "expected_path": str(expected),
            "report_path": "gone/missing_analysis.json",
            "pass": False,
        }],
    }), encoding="utf-8")
    m = compute_metrics(results_dir=results)
    assert m["evaluation_errors"][0]["error"] == "report_missing"


def test_explicit_null_report_path_not_legacy_fallback(tmp_path):
    """report_path=null means this run has no report — do not pick an older JSON."""
    results = tmp_path / "results"
    case = results / "crash_case"
    _write_report(case / "old_success_analysis.json", ["fatal"])
    expected = tmp_path / "cases" / "positive" / "crash_case" / "expected.json"
    expected.parent.mkdir(parents=True)
    expected.write_text(json.dumps({
        "issue_type": "CRASH",
        "must_have_evidence_categories": ["fatal"],
        "sample_kind": "synthetic",
    }), encoding="utf-8")
    (results / "test_result.json").write_text(json.dumps({
        "passed": 0, "failed": 1, "cases_dir": str(tmp_path / "cases"),
        "cases": [{
            "case": "crash_case", "group": "positive", "pass": False,
            "expected": "CRASH", "actual": None,
            "expected_path": str(expected),
            "report_path": None,
            "run_id": None,
            "sample_kind": "synthetic",
            "errors": ["RuntimeError: boom"],
        }],
    }), encoding="utf-8")
    m = compute_metrics(results_dir=results, cases_dir=tmp_path / "cases")
    assert m["evaluation_errors"]
    assert m["evaluation_errors"][0]["error"] == "report_unavailable"
    assert not m["used_reports"]


def test_success_then_failed_rerun_does_not_reuse_old_report(tmp_path):
    """After a green run, a failed re-run with report_path=null must be unevaluable."""
    results = tmp_path / "results"
    case = results / "crash_case"
    _write_report(case / "first_ok_analysis.json", ["fatal"])
    expected = tmp_path / "e.json"
    expected.write_text(json.dumps({
        "issue_type": "CRASH",
        "must_have_evidence_categories": ["fatal"],
    }), encoding="utf-8")
    # Simulate second run overwriting the listing only.
    (results / "test_result.json").write_text(json.dumps({
        "cases": [{
            "case": "crash_case", "group": "positive",
            "expected": "CRASH", "actual": None, "pass": False,
            "expected_path": str(expected),
            "report_path": None,
            "run_id": None,
            "errors": ["LogLoadError: missing"],
        }],
    }), encoding="utf-8")
    m = compute_metrics(results_dir=results)
    assert m["evaluation_errors"][0]["error"] == "report_unavailable"
    assert m["used_reports"] == []


def test_corrupt_report_is_unevaluable(tmp_path):
    results = tmp_path / "results"
    case = results / "crash_case"
    case.mkdir(parents=True)
    bad = case / "broken_analysis.json"
    bad.write_text("{not-json", encoding="utf-8")
    expected = tmp_path / "e.json"
    expected.write_text("{}", encoding="utf-8")
    (results / "test_result.json").write_text(json.dumps({
        "cases": [{
            "case": "crash_case", "group": "positive",
            "expected": "CRASH", "actual": "CRASH", "pass": True,
            "expected_path": str(expected),
            "report_path": "crash_case/broken_analysis.json",
        }],
    }), encoding="utf-8")
    m = compute_metrics(results_dir=results)
    assert m["evaluation_errors"]
    assert m["evaluation_errors"][0]["error"].startswith("report_unreadable")


def test_runner_records_report_path_and_rerun(tmp_path, cases_dir):
    out1 = tmp_path / "r1"
    s1 = run_cases(cases_dir=cases_dir / "positive" if False else cases_dir, results_dir=out1)
    # use a tiny custom cases dir with one case copied conceptually: run twice into same dir
    mini = tmp_path / "cases" / "positive" / "normal_case_01"
    src = cases_dir / "negative" / "normal_case_01"
    if not src.exists():
        src = cases_dir / "positive" / "crash_case_01"
        mini = tmp_path / "cases" / "positive" / "crash_case_01"
    mini.mkdir(parents=True)
    (mini / "input.log").write_bytes((src / "input.log").read_bytes())
    (mini / "expected.json").write_text((src / "expected.json").read_text(encoding="utf-8"), encoding="utf-8")
    dest = tmp_path / "both"
    run_cases(cases_dir=tmp_path / "cases", results_dir=dest)
    run_cases(cases_dir=tmp_path / "cases", results_dir=dest)
    listing = json.loads((dest / "test_result.json").read_text(encoding="utf-8"))
    rel = listing["cases"][0]["report_path"]
    assert rel
    assert listing["cases"][0]["run_id"]
    m = compute_metrics(results_dir=dest, cases_dir=tmp_path / "cases")
    assert not m["evaluation_errors"]
    assert Path(m["used_reports"][0]["report_path"]).name == Path(rel).name
