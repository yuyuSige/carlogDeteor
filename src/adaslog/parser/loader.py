"""Load a log file into structured LogEvents (stream decode -> parse -> filter -> stack merge)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from adaslog.core.errors import LogLoadError
from adaslog.models import LogEvent
from adaslog.parser.logcat import parse_lines
from adaslog.parser.stacktrace import aggregate_stacktraces
from adaslog.parser.tag_normalizer import TagNormalizer, RX_PROC_DIED, RX_START_PROC
from adaslog.utils.io import LineStream
from adaslog.utils.timeparse import in_clock_range, ms_of_day, parse_clock

_PROCESS_HINT = ("Start proc ", "Process ", " has died")


@dataclass
class ParsedLog:
    path: str
    events: list[LogEvent]
    meta: dict[str, Any] = field(default_factory=dict)
    normalizer: Optional[TagNormalizer] = None

    def by_id(self, event_id: int) -> LogEvent:
        return self.events[event_id]


def parse_time_range(time_range: str | None) -> tuple[int | None, int | None, bool]:
    """Return (start_ms, end_ms, wraps_midnight)."""
    if not time_range:
        return None, None, False
    parts = time_range.replace("~", "-").split("-")
    if len(parts) != 2:
        raise LogLoadError("时间窗格式必须为 HH:MM:SS-HH:MM:SS")
    start_ms, end_ms = parse_clock(parts[0].strip()), parse_clock(parts[1].strip())
    if start_ms is None or end_ms is None:
        raise LogLoadError("时间窗非法：时须为 0-23，分/秒须为 0-59，格式 HH:MM:SS-HH:MM:SS")
    return start_ms, end_ms, start_ms > end_ms


def _in_time_range(ev: LogEvent, start_ms: int | None, end_ms: int | None) -> bool:
    if start_ms is None:
        return True
    if ev.ts_ms is None:
        return False
    return in_clock_range(ms_of_day(ev.ts_ms), start_ms, end_ms)


def _is_process_map(ev: LogEvent) -> bool:
    msg = ev.message or ""
    return bool(RX_START_PROC.search(msg) or RX_PROC_DIED.search(msg))


def load_log(
    path: str | Path,
    time_range: str | None = None,
    pid: int | None = None,
    normalizer: TagNormalizer | None = None,
    progress=None,
) -> ParsedLog:
    p = Path(path)
    if not p.exists():
        raise LogLoadError(f"log file not found: {p}")
    start_ms, end_ms, wraps = parse_time_range(time_range)

    stream = LineStream(p)
    events = parse_lines(stream)
    if progress:
        progress(f"decoded {stream.total_lines} lines, parsed {len(events)} events")
    events = aggregate_stacktraces(events)
    normalizer = normalizer or TagNormalizer()
    # Learn pid→process from the full stream (including lines later dropped by time/pid filter).
    normalizer.learn_processes(events)

    untimed_excluded = 0
    unpid_excluded = 0
    kept: list[LogEvent] = []
    for e in events:
        if time_range:
            if e.ts_ms is None:
                untimed_excluded += 1
                continue
            if not _in_time_range(e, start_ms, end_ms):
                continue
        if pid is not None:
            if e.pid is None:
                unpid_excluded += 1
                continue
            if e.pid != pid:
                continue
        kept.append(e)

    for k, e in enumerate(kept):
        e.id = k
    # Re-apply tags/modules on the kept set using the already-learned pid map.
    for ev in kept:
        cands = normalizer.tag_candidates(ev.raw_tag)
        ev.tag = cands[0] if cands else None
        if len(cands) > 1:
            ev.extra["tag_candidates"] = cands
        if ev.pid is not None and ev.pid in normalizer.pid_to_process:
            ev.process = normalizer.pid_to_process[ev.pid]
        mod = normalizer.module_for_tag(ev.tag)
        if mod is None and ev.extra.get("app_frame"):
            mod = normalizer.module_for_package(ev.extra["app_frame"]["class"])
        if mod is None and ev.has_stacktrace:
            mod = normalizer.module_for_package(" ".join(ev.stacktrace[:6]))
        if mod is None and ev.process:
            mod = normalizer.module_for_package(ev.process)
        ev.module = mod

    data_status = "ok"
    if stream.total_lines == 0 or (not kept and not events):
        data_status = "empty"
    elif time_range or pid is not None:
        timed = [e for e in kept if e.ts_ms is not None]
        if not kept or (time_range and not timed):
            data_status = "filter_empty"

    ts = [e.timestamp for e in kept if e.timestamp]
    meta: dict[str, Any] = {
        "file": str(p),
        "size_bytes": p.stat().st_size,
        "encoding": stream.encoding,
        "mojibake_repaired": stream.mojibake_repaired,
        "repaired_lines": stream.repaired_lines,
        "total_lines": stream.total_lines,
        "events_total": len(events),
        "events_kept": len(kept),
        "processes": {str(k): v for k, v in sorted(normalizer.pid_to_process.items())},
        "data_status": data_status,
        "time_wraps_midnight": wraps,
        "filter_policy": {
            "untimed_events": "excluded_when_time_range_set",
            "unpid_events": "excluded_when_pid_set",
            "process_map": "learned_from_full_stream_before_filter",
        },
        "untimed_excluded": untimed_excluded,
        "unpid_excluded": unpid_excluded,
        "time_start": ts[0] if ts else None,
        "time_end": ts[-1] if ts else None,
    }
    if time_range or pid is not None:
        meta["filter"] = {
            "time_range": time_range,
            "pid": pid,
            "events_after_filter": len(kept),
            "wraps_midnight": wraps,
        }
    return ParsedLog(str(p), kept, meta, normalizer)
