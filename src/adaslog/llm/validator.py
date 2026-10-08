"""Drop or downgrade any claim that does not cite existing evidence ids."""
from __future__ import annotations

from adaslog.llm.provider import LLMResult
from adaslog.models import Classification, Evidence, RootCauseCandidate


def validate_candidates(
    result: LLMResult,
    evidence: list[Evidence],
    classification: Classification,
) -> list[RootCauseCandidate]:
    known = {e.id for e in evidence}
    if classification.issue_type == "NORMAL":
        return []

    out: list[RootCauseCandidate] = []
    for raw in result.candidates:
        ids = [i for i in (raw.get("evidence_ids") or []) if i in known]
        status = raw.get("status") or "CANDIDATE"
        title = (raw.get("title") or "").strip() or "UNKNOWN"
        if classification.issue_type == "UNKNOWN" or title.upper() == "UNKNOWN":
            out.append(
                RootCauseCandidate(
                    title="UNKNOWN",
                    status="UNKNOWN",
                    confidence="LOW",
                    evidence_ids=ids,
                    reasoning=raw.get("reasoning") or raw.get("reason") or "Insufficient evidence.",
                    reason="Insufficient evidence.",
                    need_verification=list(raw.get("need_verification") or []),
                    source=raw.get("source") or result.provider,
                )
            )
            continue
        if not ids:
            # hallucination guard: no cited evidence -> UNKNOWN
            out.append(
                RootCauseCandidate(
                    title="UNKNOWN",
                    status="UNKNOWN",
                    confidence="LOW",
                    evidence_ids=[],
                    reasoning="Claim dropped: no valid evidence ids.",
                    reason="Insufficient evidence.",
                    need_verification=["Re-run with a longer log or --source."],
                    source=raw.get("source") or result.provider,
                )
            )
            continue
        out.append(
            RootCauseCandidate(
                title=title,
                status=status,
                confidence=raw.get("confidence") or "MEDIUM",
                evidence_ids=ids,
                reasoning=raw.get("reasoning") or "",
                reason=raw.get("reason"),
                need_verification=list(raw.get("need_verification") or []),
                source=raw.get("source") or result.provider,
            )
        )
    if not out and classification.issue_type != "NORMAL":
        out.append(
            RootCauseCandidate(
                title="UNKNOWN",
                status="UNKNOWN",
                confidence="LOW",
                evidence_ids=[],
                reasoning="Insufficient evidence.",
                reason="Insufficient evidence.",
                source=result.provider,
            )
        )
    return out
