"""Metrics over golden-case results.

- classification accuracy is on the labelled synthetic/golden set only.
- candidate_without_evidence_ids_rate is NOT “root cause correctness”.
- claim_mismatch_rate uses expected forbidden titles / support flags.
- extra extracted evidence without a label is unlabelled, not automatic TP.
Manual times are estimates and labelled as such.
"""
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


def compute_metrics(results_dir: str | Path | None = None, cases_dir: str | Path | None = None) -> dict:
    results_dir = Path(results_dir) if results_dir else PROJECT_ROOT / "tests" / "results"
    path = results_dir / "test_result.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"cases": []}
    cases = data.get("cases") or []
    default_cases = Path(cases_dir) if cases_dir else Path(data.get("cases_dir") or (PROJECT_ROOT / "tests" / "cases"))
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
    if per_type:
        macro = {
            k: round(sum(v[k] for v in per_type.values()) / len(per_type), 3)
            for k in ("precision", "recall", "f1")
        }
    else:
        macro = {"precision": 0, "recall": 0, "f1": 0}

    coverage_n = coverage_d = no_id_n = no_id_d = mismatch_n = mismatch_d = 0
    key_tp = key_fp = key_fn = 0
    unlabelled_extra = 0
    for c in cases:
        case_dir = results_dir / c["case"]
        report_path = next(case_dir.glob("*_analysis.json"), None) if case_dir.exists() else None
        expected_path = Path(c["expected_path"]) if c.get("expected_path") else (
            default_cases / c.get("group", "positive") / c["case"] / "expected.json"
        )
        exp = json.loads(expected_path.read_text(encoding="utf-8")) if expected_path.exists() else {}
        if not report_path:
            continue
        rep = json.loads(report_path.read_text(encoding="utf-8"))
        rcs = rep.get("root_causes") or []
        for rc in rcs:
            no_id_d += 1
            coverage_d += 1
            if rc.get("evidence_ids"):
                coverage_n += 1
            if rc.get("status") == "CANDIDATE" and not rc.get("evidence_ids"):
                no_id_n += 1
            mismatch_d += 1
            title = rc.get("title") or ""
            if rc.get("status") == "CANDIDATE":
                for part in exp.get("forbidden_root_cause_substrings") or []:
                    if part.lower() in title.lower():
                        mismatch_n += 1
                        break
        want = set(exp.get("must_have_evidence_categories") or [])
        got = {e.get("category") for e in (rep.get("key_evidence") or [])}
        forbidden = set(exp.get("forbidden_evidence_categories") or [])
        key_tp += len(want & got)
        key_fn += len(want - got)
        key_fp += len(got & forbidden)
        unlabelled_extra += len(got - want - forbidden)

    neg = [c for c in cases if c.get("group") == "negative"]
    kinds = {}
    for c in cases:
        kinds.setdefault(c.get("sample_kind", "synthetic"), 0)
        kinds[c.get("sample_kind", "synthetic")] += 1
    metrics = {
        "classification": {
            "accuracy": round(correct / len(cases), 3) if cases else 0,
            "macro": macro,
            "per_type": per_type,
            "scope": "labelled golden cases only; not production accuracy",
        },
        "key_log_extraction": {
            **_prf(key_tp, key_fp, key_fn),
            "unlabelled_extra_categories": unlabelled_extra,
            "note": "precision/recall only use must_have vs forbidden labels; extra categories are unlabelled, not counted as correct",
        },
        "evidence_id_coverage": round(coverage_n / coverage_d, 3) if coverage_d else 1.0,
        "candidate_without_evidence_ids_rate": round(no_id_n / no_id_d, 3) if no_id_d else 0.0,
        "claim_mismatch_rate": round(mismatch_n / mismatch_d, 3) if mismatch_d else 0.0,
        "hallucination_rate": round(no_id_n / no_id_d, 3) if no_id_d else 0.0,
        "hallucination_rate_definition": "CANDIDATE with zero evidence ids. This is NOT root-cause correctness.",
        "negative_control_pass_rate": round(sum(1 for c in neg if c["pass"]) / len(neg), 3) if neg else None,
        "sample_kinds": kinds,
        "efficiency": {
            "manual_minutes_note": "engineer estimate, labelled as estimate; not measured production time",
            "cases": [
                {
                    "case": c["case"],
                    "manual_minutes_estimate": c.get("manual_minutes_estimate"),
                    "ai_seconds": c.get("seconds"),
                    "note": c.get("manual_minutes_note", "estimate"),
                    "sample_kind": c.get("sample_kind", "synthetic"),
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
