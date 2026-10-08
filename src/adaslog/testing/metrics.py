"""Metrics over golden-case results. Manual times are estimates and labelled as such."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from adaslog.core.config import PROJECT_ROOT


def _prf(tp: int, fp: int, fn: int) -> dict:
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3)}


def compute_metrics(results_dir: str | Path | None = None) -> dict:
    results_dir = Path(results_dir) if results_dir else PROJECT_ROOT / "tests" / "results"
    path = results_dir / "test_result.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"cases": []}
    cases = data.get("cases") or []
    labels = sorted({c.get("expected") for c in cases if c.get("expected")} | {c.get("actual") for c in cases if c.get("actual")})
    tp = defaultdict(int)
    fp = defaultdict(int)
    fn = defaultdict(int)
    correct = 0
    for c in cases:
        exp, act = c.get("expected"), c.get("actual")
        if exp == act:
            correct += 1
            tp[exp] += 1
        else:
            if act:
                fp[act] += 1
            if exp:
                fn[exp] += 1
    per_type = {lab: _prf(tp[lab], fp[lab], fn[lab]) for lab in labels}
    # macro
    if per_type:
        macro = {
            k: round(sum(v[k] for v in per_type.values()) / len(per_type), 3)
            for k in ("precision", "recall", "f1")
        }
    else:
        macro = {"precision": 0, "recall": 0, "f1": 0}

    # Evidence coverage / hallucination from last per-case reports if present
    coverage_n = coverage_d = hall_n = hall_d = 0
    key_tp = key_fp = key_fn = 0
    for c in cases:
        case_dir = results_dir / c["case"]
        report_path = next(case_dir.glob("*_analysis.json"), None) if case_dir.exists() else None
        if not report_path:
            continue
        rep = json.loads(report_path.read_text(encoding="utf-8"))
        rcs = rep.get("root_causes") or []
        for rc in rcs:
            hall_d += 1
            coverage_d += 1
            if rc.get("evidence_ids"):
                coverage_n += 1
            if rc.get("status") == "CANDIDATE" and not rc.get("evidence_ids"):
                hall_n += 1
        expected_path = PROJECT_ROOT / "tests" / "cases" / c.get("group", "positive") / c["case"] / "expected.json"
        if expected_path.exists():
            exp = json.loads(expected_path.read_text(encoding="utf-8"))
            want = set(exp.get("must_have_evidence_categories") or [])
            got = {e.get("category") for e in (rep.get("key_evidence") or [])}
            key_tp += len(want & got)
            key_fn += len(want - got)
            # extra categories are not counted as fp unless listed as forbidden
            forbidden = set(exp.get("forbidden_evidence_categories") or [])
            key_fp += len(got & forbidden)

    neg = [c for c in cases if c.get("group") == "negative"]
    metrics = {
        "classification": {
            "accuracy": round(correct / len(cases), 3) if cases else 0,
            "macro": macro,
            "per_type": per_type,
        },
        "key_log_extraction": _prf(key_tp, key_fp, key_fn),
        "evidence_coverage": round(coverage_n / coverage_d, 3) if coverage_d else 1.0,
        "hallucination_rate": round(hall_n / hall_d, 3) if hall_d else 0.0,
        "negative_control_pass_rate": round(sum(1 for c in neg if c["pass"]) / len(neg), 3) if neg else None,
        "efficiency": {
            "manual_minutes_note": "engineer estimate, labelled as estimate",
            "cases": [
                {
                    "case": c["case"],
                    "manual_minutes_estimate": c.get("manual_minutes_estimate"),
                    "ai_seconds": c.get("seconds"),
                    "note": c.get("manual_minutes_note", "estimate"),
                }
                for c in cases
            ],
        },
        "n_cases": len(cases),
        "passed": data.get("passed"),
        "failed": data.get("failed"),
    }
    (results_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics
