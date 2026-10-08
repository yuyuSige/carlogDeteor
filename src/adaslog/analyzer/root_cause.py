"""Deterministic (offline) root-cause candidates. Evidence ids only."""
from __future__ import annotations

from adaslog.models import (
    Classification,
    CodeHit,
    Evidence,
    RootCauseCandidate,
    SignalSummary,
)


def build_rule_candidates(
    classification: Classification,
    evidence: list[Evidence],
    signal_summary: SignalSummary | None,
    code_hits: list[CodeHit],
) -> list[RootCauseCandidate]:
    ev_ids = [e.id for e in evidence]
    itype = classification.issue_type

    if itype == "NORMAL":
        return []

    if itype == "UNKNOWN" or not ev_ids:
        return [
            RootCauseCandidate(
                title="UNKNOWN",
                status="UNKNOWN",
                confidence="LOW",
                evidence_ids=ev_ids[:3],
                reasoning="Insufficient evidence.",
                reason="Insufficient evidence.",
                need_verification=[
                    "Provide a longer window, a stack trace, or the module that reproduced the symptom."
                ],
                source="rule",
            )
        ]

    conf = "HIGH" if classification.confidence >= 0.75 else "MEDIUM" if classification.confidence >= 0.45 else "LOW"

    if itype == "SIGNAL_NOT_TRIGGERED":
        idle = [e for e in evidence if e.category in ("signal_idle", "text_idle")]
        ids = [e.id for e in idle] or ev_ids[:4]
        fields = []
        if signal_summary:
            fields = [f"{p.struct}.{p.field}={p.value}" for p in signal_summary.focus if p.value in ("0", "0.0")]
        title = (
            "Focus signal stayed at 0 so the corresponding driving-text prompt was not queued "
            "(Profile maps idle/0 to NO_TEXT)."
        )
        return [
            RootCauseCandidate(
                title=title,
                status="CANDIDATE",
                confidence="HIGH" if fields and any(e.category == "text_idle" for e in evidence) else conf,
                evidence_ids=ids,
                reasoning=(
                    "E02 driving_text_tip handlers only call addTextToQueue when Profile.map*(value) "
                    "returns a text id. Value 0 maps to NO_TEXT. Observed idle fields: "
                    + (", ".join(fields) if fields else "(see evidence)")
                    + f". DrivingTextManager trigger count={getattr(signal_summary, 'text_manager_trigger_count', 0)}, "
                    f"idle count={getattr(signal_summary, 'text_manager_idle_count', 0)}."
                ),
                need_verification=[
                    "Confirm the expected non-zero value for the focus signal in that time window.",
                    "If the signal should have been non-zero, inspect VDS / SOME-IP publisher (not the text manager).",
                ],
                source="rule",
            )
        ]

    title_map = {
        "CRASH": "Process crashed (fatal exception / native abort).",
        "EXCEPTION": "A handled or logged exception occurred on the diagnosis path.",
        "BINDER_IPC": "Binder/IPC transaction failed or the remote service died.",
        "STATE_MACHINE": "State machine hit an undefined or illegal transition.",
        "MODULE_COMMUNICATION": "Cross-module communication failed (Kanzi / gRPC / bus / timeout).",
        "SYSTEM_ERROR": "Android system-level error accompanied the symptom.",
        "ANR": "Application Not Responding (main thread blocked).",
        "PERFORMANCE": "Frame jank / slow operation reported.",
        "BUSINESS_ERROR": "Business-level error without a crash.",
    }
    verify_map = {
        "CRASH": ["Open the first app frame in --source and check the null / illegal state."],
        "BINDER_IPC": ["Check the remote service process death and the AIDL interface that failed."],
        "STATE_MACHINE": ["Replay the (state, event) pair against StateMachine transition table."],
        "MODULE_COMMUNICATION": ["Confirm the peer process was alive and the connection was established before the failure."],
        "SIGNAL_NOT_TRIGGERED": ["Check whether the publisher ever sent a non-zero value."],
    }
    extra = ""
    if code_hits:
        h = code_hits[0]
        extra = f" First code hit: {h.file}:{h.line} {h.symbol}."
        ev_ids = list(dict.fromkeys(ev_ids + h.evidence_ids))
    return [
        RootCauseCandidate(
            title=title_map.get(itype, itype),
            status="CANDIDATE",
            confidence=conf,
            evidence_ids=ev_ids[:8],
            reasoning=classification.reason + extra,
            need_verification=verify_map.get(itype, ["Collect a longer log around the first error."]),
            source="rule",
        )
    ]
