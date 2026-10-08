"""Core data structures shared by every pipeline stage.

Labels (Evidence First):
  FACT            - directly observed in the log / code
  EVIDENCE        - a FACT selected because it matters for the diagnosis
  HYPOTHESIS      - a root cause candidate, must reference evidence ids
  RECOMMENDATION  - what to check / do next
  UNKNOWN         - explicitly missing information
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class IssueType(str, Enum):
    CRASH = "CRASH"
    EXCEPTION = "EXCEPTION"
    BINDER_IPC = "BINDER_IPC"
    STATE_MACHINE = "STATE_MACHINE"
    MODULE_COMMUNICATION = "MODULE_COMMUNICATION"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    BUSINESS_ERROR = "BUSINESS_ERROR"
    NORMAL = "NORMAL"
    UNKNOWN = "UNKNOWN"
    # Extended types (allowed by spec: "允许扩展分类")
    ANR = "ANR"
    PERFORMANCE = "PERFORMANCE"
    SIGNAL_NOT_TRIGGERED = "SIGNAL_NOT_TRIGGERED"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

    @staticmethod
    def from_score(score: float) -> "Confidence":
        if score >= 0.75:
            return Confidence.HIGH
        if score >= 0.45:
            return Confidence.MEDIUM
        return Confidence.LOW


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


LEVEL_ORDER = {"V": 0, "D": 1, "I": 2, "W": 3, "E": 4, "F": 5, "S": 6}


@dataclass
class LogEvent:
    id: int
    line_no: int
    raw: str
    timestamp: Optional[str] = None      # as written in the log
    ts_ms: Optional[int] = None          # milliseconds since 1970 (year may be synthetic)
    level: Optional[str] = None          # V D I W E F
    pid: Optional[int] = None
    tid: Optional[int] = None
    raw_tag: Optional[str] = None
    tag: Optional[str] = None            # normalised tag (prefix stripped, truncation resolved)
    process: Optional[str] = None        # resolved process name if known
    module: Optional[str] = None
    message: str = ""
    stacktrace: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def level_rank(self) -> int:
        return LEVEL_ORDER.get(self.level or "", -1)

    @property
    def has_stacktrace(self) -> bool:
        return bool(self.stacktrace)

    def short(self, width: int = 160) -> str:
        head = f"[L{self.line_no}] "
        if self.timestamp:
            head += f"{self.timestamp} "
        if self.level:
            head += f"{self.level}/"
        if self.tag:
            head += f"{self.tag}"
        if self.pid is not None:
            head += f"({self.pid})"
        msg = self.message.replace("\n", " ")
        text = f"{head}: {msg}"
        return text if len(text) <= width else text[: width - 3] + "..."


@dataclass
class Anomaly:
    id: str
    kind: str                 # e.g. FATAL_EXCEPTION, BINDER_DEAD_OBJECT, STATE_ILLEGAL_TRANSITION
    category: str             # maps to IssueType name
    severity: str             # Severity value
    event_id: int
    rule_id: str
    matched_text: str
    score: float
    description: str = ""
    repeat_count: int = 1
    event_ids: list[int] = field(default_factory=list)  # all collapsed events


@dataclass
class Evidence:
    id: str                   # E1, E2 ...
    label: str                # FACT / EVIDENCE
    category: str             # first_error, first_exception, fatal, binder_failure, ...
    event_id: Optional[int]
    text: str
    why_it_matters: str
    line_no: Optional[int] = None
    timestamp: Optional[str] = None
    repeat_count: int = 1
    related_event_ids: list[int] = field(default_factory=list)


@dataclass
class Classification:
    issue_type: str
    confidence: float
    evidence_ids: list[str]
    scores: dict[str, float]
    reason: str
    data_status: str = "ok"  # ok | empty | filter_empty


@dataclass
class TimelineEntry:
    timestamp: Optional[str]
    line_no: int
    event_id: int
    label: str                # short description
    evidence_id: Optional[str] = None


@dataclass
class CausalLink:
    from_evidence: str
    to_evidence: str
    relation: str             # "precedes", "triggers", "repeats"


@dataclass
class ContextWindow:
    anchor_evidence_id: str
    anchor_event_id: int
    before: list[str]
    after: list[str]


@dataclass
class SignalPeriod:
    struct: str
    field: str
    value: str
    start_ts: Optional[str]
    end_ts: Optional[str]
    samples: int
    first_line: int
    last_line: int
    pid: Optional[int] = None


@dataclass
class SignalFieldStatus:
    """Per-field observation. observation is a closed set of labels, not a root cause."""
    key: str
    struct: str
    field: str
    observation: str
    # idle_entire_window | saw_trigger | saw_unmapped_value | not_sampled | unknown_mapping
    values_seen: list[str] = field(default_factory=list)
    mapped: bool = False
    idle_value: Optional[str] = None
    trigger_values: list[str] = field(default_factory=list)
    periods: list[SignalPeriod] = field(default_factory=list)
    note: str = ""


@dataclass
class SignalSummary:
    structs: dict[str, int]                       # struct name -> sample count
    constant_fields: list[SignalPeriod]           # fields that never changed in the window
    changed_fields: dict[str, list[tuple]]        # "Struct.field" -> [(ts, value) transitions]
    focus: list[SignalPeriod]                     # ALL periods for focused fields (including non-zero)
    text_manager_idle_count: int = 0
    text_manager_trigger_count: int = 0
    text_manager_tag: Optional[str] = None
    window: Optional[str] = None
    field_status: list[SignalFieldStatus] = field(default_factory=list)
    text_correlation: str = "none"  # idle_seen | trigger_seen | none
    # Seeing idle logs does not prove a prompt was never queued.
    enqueue_unobserved_is_unknown: bool = True


@dataclass
class Incident:
    id: str
    issue_type: str
    confidence: float
    pid: Optional[int]
    module: Optional[str]
    start_ts: Optional[str]
    end_ts: Optional[str]
    evidence_ids: list[str] = field(default_factory=list)
    summary: str = ""
    root_causes: list[RootCauseCandidate] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)


@dataclass
class CodeHit:
    file: str
    line: Optional[int]
    symbol: str               # class.method or class
    snippet: str
    risk_patterns: list[str]
    evidence_ids: list[str]
    how_found: str            # "stack_frame" | "tag_class" | "log_message"
    candidates: list[str] = field(default_factory=list)  # alternative files when ambiguous


@dataclass
class RootCauseCandidate:
    title: str
    status: str               # CANDIDATE | UNKNOWN
    confidence: str           # HIGH | MEDIUM | LOW
    evidence_ids: list[str]
    reasoning: str
    need_verification: list[str] = field(default_factory=list)
    reason: Optional[str] = None   # for UNKNOWN: e.g. "Insufficient evidence."
    source: str = "rule"           # rule | llm


@dataclass
class Recommendation:
    text: str
    evidence_ids: list[str] = field(default_factory=list)
    priority: int = 2


@dataclass
class AnalysisReport:
    issue_type: str
    severity: str
    summary: str
    classification: Classification
    key_evidence: list[Evidence]
    timeline: list[TimelineEntry]
    causal_chain: list[CausalLink]
    context_windows: list[ContextWindow]
    root_causes: list[RootCauseCandidate]
    confidence: str
    related_modules: list[str]
    related_processes: list[str]
    related_code: list[CodeHit]
    recommendations: list[Recommendation]
    unknowns: list[str]
    signal_summary: Optional[SignalSummary]
    meta: dict[str, Any]
    incidents: list[Incident] = field(default_factory=list)
    classification_confidence: str = ""
    root_cause_confidence: str = ""
    run_id: str = ""
    counter_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
