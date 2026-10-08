"""Load a log file into structured LogEvents (loader -> line parser -> stack merge -> tags)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from adaslog.core.errors import LogLoadError
from adaslog.models import LogEvent
from adaslog.parser.logcat import parse_lines
from adaslog.parser.stacktrace import aggregate_stacktraces
from adaslog.parser.tag_normalizer import TagNormalizer
from adaslog.utils.io import load_text
from adaslog.utils.timeparse import ms_of_day, parse_clock


@dataclass
class ParsedLog:
    path: str
    events: list[LogEvent]
    meta: dict[str, Any] = field(default_factory=dict)
    normalizer: Optional[TagNormalizer] = None

    def by_id(self, event_id: int) -> LogEvent:
        return self.events[event_id]


def _in_time_range(ev: LogEvent, start_ms: int | None, end_ms: int | None) -> bool:
    if ev.ts_ms is None:
        return True
    t = ms_of_day(ev.ts_ms)
    if start_ms is not None and t < start_ms:
        return False
    if end_ms is not None and t > end_ms:
        return False
    return True


def load_log(
    path: str | Path,
    time_range: str | None = None,
    pid: int | None = None,
    normalizer: TagNormalizer | None = None,
) -> ParsedLog:
    p = Path(path)
    if not p.exists():
        raise LogLoadError(f"log file not found: {p}")
    if p.suffix.lower() not in (".log", ".txt", "") and p.suffix.lower() not in (".logcat",):
        # still try, but record a warning
        pass
    loaded = load_text(p)
    lines = loaded.text.split("\n")
    events = parse_lines(lines)
    events = aggregate_stacktraces(events)
    normalizer = normalizer or TagNormalizer()
    normalizer.apply(events)

    meta: dict[str, Any] = {
        "file": str(p),
        "size_bytes": p.stat().st_size,
        "encoding": loaded.encoding,
        "mojibake_repaired": loaded.mojibake_repaired,
        "repaired_lines": loaded.repaired_lines,
        "total_lines": len(lines),
        "events_total": len(events),
        "processes": {str(k): v for k, v in sorted(normalizer.pid_to_process.items())},
    }

    start_ms = end_ms = None
    if time_range:
        parts = time_range.replace("~", "-").split("-")
        if len(parts) != 2:
            raise LogLoadError("time range must look like HH:MM:SS-HH:MM:SS")
        start_ms, end_ms = parse_clock(parts[0]), parse_clock(parts[1])
        if start_ms is None or end_ms is None:
            raise LogLoadError("time range must look like HH:MM:SS-HH:MM:SS")
    if time_range or pid is not None:
        filtered = [
            e for e in events
            if _in_time_range(e, start_ms, end_ms) and (pid is None or e.pid == pid or e.pid is None)
        ]
        for k, e in enumerate(filtered):
            e.id = k
        meta["filter"] = {"time_range": time_range, "pid": pid, "events_after_filter": len(filtered)}
        events = filtered

    ts = [e.timestamp for e in events if e.timestamp]
    meta["time_start"] = ts[0] if ts else None
    meta["time_end"] = ts[-1] if ts else None
    return ParsedLog(str(p), events, meta, normalizer)
