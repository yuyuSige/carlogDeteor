"""Analysis session binding: params fingerprint, result, and anti-rerun guards."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from adaslog.ui.validation import AnalysisParams, params_fingerprint
from adaslog.ui.workspace import TaskWorkspace


STAGE_LABELS = {
    "load": "读取日志",
    "extract": "提取证据",
    "analyze": "分析问题",
    "report": "生成报告",
    "done": "完成",
}


@dataclass
class StageRecord:
    stage: str
    message: str
    elapsed_s: float


@dataclass
class AnalysisSession:
    task: TaskWorkspace
    params: AnalysisParams
    fingerprint: str
    log_name: str
    log_size: int
    report: Any = None
    rendered: dict[str, str] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)
    stages: list[StageRecord] = field(default_factory=list)
    encoding_used: str | None = None
    error: str | None = None
    error_hint: str | None = None
    started_at: float = field(default_factory=time.perf_counter)
    finished_at: float | None = None
    running: bool = False

    @property
    def duration_s(self) -> float | None:
        if self.finished_at is None:
            return None
        return round(self.finished_at - self.started_at, 3)


def make_fingerprint(params: AnalysisParams, log_name: str, size: int) -> str:
    return params_fingerprint(params, log_name, size)


def result_stale(session: AnalysisSession | None, fingerprint: str) -> bool:
    if session is None or session.report is None:
        return False
    return session.fingerprint != fingerprint
