"""Golden-case runner. Writes tests/results/test_result.md|json."""
from __future__ import annotations

import json
import time
from pathlib import Path

from adaslog.core.config import PROJECT_ROOT
from adaslog.core.pipeline import run_analysis


def _case_dirs(cases_dir: Path) -> list[Path]:
    out = []
    for group in ("positive", "negative"):
        root = cases_dir / group
        if not root.exists():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "input.log").exists() and (child / "expected.json").exists():
                out.append(child)
    return out


def _eval_case(report, expected: dict) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if report.issue_type != expected["issue_type"]:
        errors.append(f"issue_type expected {expected['issue_type']} got {report.issue_type}")
    for cat in expected.get("must_have_evidence_categories") or []:
        if not any(e.category == cat for e in report.key_evidence):
            errors.append(f"missing evidence category {cat}")
    if expected.get("forbid_root_cause"):
        if any(rc.status == "CANDIDATE" and rc.title.upper() != "UNKNOWN" for rc in report.root_causes):
            errors.append("root cause candidate was produced but is forbidden")
    status = expected.get("root_cause_status")
    if status:
        if not report.root_causes:
            errors.append(f"expected root_cause_status {status} but none produced")
        elif report.root_causes[0].status != status:
            errors.append(f"root_cause_status expected {status} got {report.root_causes[0].status}")
    reason = expected.get("must_contain_reason")
    if reason:
        blob = " ".join(
            [(rc.reason or "") + " " + rc.reasoning for rc in report.root_causes]
            + [report.classification.reason, report.summary]
        )
        if reason.lower() not in blob.lower():
            errors.append(f"missing reason text: {reason}")
    for cat in expected.get("forbidden_evidence_categories") or []:
        if any(e.category == cat for e in report.key_evidence):
            errors.append(f"forbidden evidence category present: {cat}")
    for title_part in expected.get("forbidden_root_cause_substrings") or []:
        for rc in report.root_causes:
            if rc.status == "CANDIDATE" and title_part.lower() in (rc.title or "").lower():
                errors.append(f"forbidden root-cause text: {title_part}")
    if expected.get("data_status"):
        actual_ds = getattr(report.classification, "data_status", None) or (report.meta or {}).get("data_status")
        if actual_ds != expected["data_status"]:
            errors.append(f"data_status expected {expected['data_status']} got {actual_ds}")
    if expected.get("max_root_confidence"):
        rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        for rc in report.root_causes:
            if rc.status == "CANDIDATE" and rank.get(rc.confidence, 0) > rank.get(expected["max_root_confidence"], 2):
                errors.append(f"root confidence {rc.confidence} exceeds {expected['max_root_confidence']}")
    if expected.get("min_incidents") is not None:
        n = len(report.incidents or [])
        if n < int(expected["min_incidents"]):
            errors.append(f"incidents expected >= {expected['min_incidents']} got {n}")
    return not errors, errors


def run_cases(
    cases_dir: str | Path | None = None,
    results_dir: str | Path | None = None,
    source_dir: str | None = None,
) -> dict:
    cases_dir = Path(cases_dir) if cases_dir else PROJECT_ROOT / "tests" / "cases"
    results_dir = Path(results_dir) if results_dir else PROJECT_ROOT / "tests" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for case in _case_dirs(cases_dir):
        expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
        t0 = time.perf_counter()
        try:
            result = run_analysis(
                log_path=case / "input.log",
                source_dir=expected.get("source_dir") or source_dir,
                formats=["json"],
                out_dir=results_dir / case.name,
                llm_provider="rule",
                focus_signals=expected.get("focus_signals"),
                time_range=expected.get("time_range"),
                pid=expected.get("pid"),
                question=expected.get("question"),
                progress=False,
            )
            report = result["report"]
            ok, errors = _eval_case(report, expected)
            actual = {
                "issue_type": report.issue_type,
                "confidence": report.confidence,
                "evidence": [{"id": e.id, "category": e.category, "line_no": e.line_no} for e in report.key_evidence],
                "root_causes": [{"status": c.status, "title": c.title, "evidence_ids": c.evidence_ids} for c in report.root_causes],
            }
        except Exception as exc:
            ok, errors = False, [f"{type(exc).__name__}: {exc}"]
            actual = {}
            report = None
        elapsed = round(time.perf_counter() - t0, 3)
        rows.append({
            "case": case.name,
            "group": case.parent.name,
            "expected_path": str(case / "expected.json"),
            "sample_kind": expected.get("sample_kind", "synthetic"),
            "expected": expected.get("issue_type"),
            "actual": actual.get("issue_type") if actual else None,
            "pass": ok,
            "errors": errors,
            "evidence": actual.get("evidence"),
            "seconds": elapsed,
            "manual_minutes_estimate": expected.get("manual_minutes_estimate"),
            "manual_minutes_note": expected.get("manual_minutes_note", "estimate"),
        })

    passed = sum(1 for r in rows if r["pass"])
    summary = {
        "total": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "cases": rows,
        "results_md": str(results_dir / "test_result.md"),
        "results_json": str(results_dir / "test_result.json"),
        "cases_dir": str(cases_dir),
    }
    (results_dir / "test_result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# Test results", "", f"Passed {passed}/{len(rows)}", "", "| Case | Expected | Actual | Pass/Fail | Seconds | Evidence | Error |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        ev = ", ".join(e["category"] for e in (r.get("evidence") or [])[:5])
        err = "; ".join(r["errors"]) if r["errors"] else ""
        md.append(f"| {r['case']} | {r['expected']} | {r['actual']} | {'PASS' if r['pass'] else 'FAIL'} | {r['seconds']} | {ev} | {err} |")
    (results_dir / "test_result.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return summary
