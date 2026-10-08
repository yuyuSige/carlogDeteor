from __future__ import annotations

from typing import Any

from adaslog.analyzer.root_cause import build_rule_candidates
from adaslog.llm.provider import LLMProvider, LLMResult
from adaslog.models import Classification, CodeHit, Evidence, SignalSummary


class RuleBasedProvider(LLMProvider):
    name = "rule"

    def reason(self, bundle: dict[str, Any]) -> LLMResult:
        classification = bundle["_classification"]
        evidence = bundle["_evidence"]
        signal_summary = bundle.get("_signal_summary")
        code_hits = bundle.get("_code_hits") or []
        assert isinstance(classification, Classification)
        assert isinstance(evidence, list)
        cands = build_rule_candidates(classification, evidence, signal_summary, code_hits)
        return LLMResult(
            candidates=[
                {
                    "title": c.title,
                    "status": c.status,
                    "confidence": c.confidence,
                    "evidence_ids": c.evidence_ids,
                    "reasoning": c.reasoning,
                    "need_verification": c.need_verification,
                    "reason": c.reason,
                    "source": "rule",
                }
                for c in cands
            ],
            unknowns=[],
            provider="rule",
            status="ok",
        )
