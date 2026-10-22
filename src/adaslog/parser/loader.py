"""Load a log file into structured LogEvents (stream decode -> parse -> filter -> stack merge)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from adaslog.core.errors import LogLoadError
from adaslog.models import LogEvent
from adaslog.parser.logcat import parse_line, parse_lines, _is_continuation
from adaslog.parser.stacktrace import aggregate_stacktraces, _is_exception_start, _is_frame
from adaslog.parser.tag_normalizer import TagNormalizer, RX_PROC_DIED, RX_START_PROC
from adaslog.utils.io import LineStream
from adaslog.utils.timeparse import in_clock_range, ms_of_day, parse_clock, parse_timestamp

_PROCESS_HINT = ("Start proc ", "Process ", " has died")
# Align with stacktrace._same_stream time bound.
_STACK_GAP_MS = 2000


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


def _learn_processes_from_text(normalizer: TagNormalizer, text: str, line_no: int = 0) -> None:
    d = parse_line(text) or {}
    ts_ms = parse_timestamp(d["ts"]) if d.get("ts") else None
    m = RX_START_PROC.search(text)
    if m:
        normalizer.record_start_proc(int(m.group(1)), m.group(2), ts_ms, line_no)
        return
    m = RX_PROC_DIED.search(text)
    if m:
        pid = int(m.group(2))
        if pid not in normalizer.pid_to_process:
            normalizer.record_start_proc(pid, m.group(1), ts_ms, line_no)


def _filtered_lines(
    path: Path,
    start_ms: int | None,
    end_ms: int | None,
    pid: int | None,
    encoding: str | None,
    normalizer: TagNormalizer,
) -> tuple[list[tuple[int, str]], LineStream, int, int]:
    """Pass 1: learn pid map. Pass 2: keep in-window lines and whole stacks that touch the window.

    Unprefixed continuation lines inherit the open stack's filter result.
    A new exception head / time gap / pid-tid-tag change closes the previous stack buffer
    so unrelated older faults are not pulled into a later window.
    Output lines are sorted by original line number.
    """
    scan = LineStream(path, encoding=encoding)
    for line_no, text in scan:
        _learn_processes_from_text(normalizer, text, line_no)
    scanned = scan.total_lines

    kept_lines: list[tuple[int, str]] = []
    # key -> list of (line_no, text, in_win, pid_ok, ts_ms)
    open_stacks: dict[tuple, list[tuple[int, str, bool, bool, int | None]]] = {}
    # Bare (unprefixed) continuations inherit from the last opened stack context.
    bare_ctx: tuple[tuple, bool, bool] | None = None
    untimed = 0
    unpid = 0

    def flush(key: tuple) -> None:
        nonlocal bare_ctx
        buf = open_stacks.pop(key, None)
        if not buf:
            return
        if any(in_win and pid_ok for *_rest, in_win, pid_ok, _ts in buf):
            for line_no, text, _w, _p, _ts in buf:
                kept_lines.append((line_no, text))
        if bare_ctx is not None and bare_ctx[0] == key:
            bare_ctx = None

    def stack_key(d: dict) -> tuple | None:
        if d.get("pid") is None:
            return None
        return (int(d["pid"]), int(d.get("tid") or d["pid"]), (d.get("tag") or "").strip())

    stream = LineStream(path, encoding=scan.encoding if encoding is None else encoding)
    if scan.encoding_fallback:
        stream.encoding_fallback = scan.encoding_fallback
    for line_no, text in stream:
        parsed = parse_line(text)
        d = parsed or {}
        ts = d.get("ts")
        ts_ms = parse_timestamp(ts) if ts else None
        in_win = True if start_ms is None else (
            ts_ms is not None and in_clock_range(ms_of_day(ts_ms), start_ms, end_ms)
        )
        line_pid = int(d["pid"]) if d.get("pid") is not None else None
        pid_ok = True if pid is None else (line_pid is not None and line_pid == pid)
        if start_ms is not None and parsed is not None and ts_ms is None:
            # Prefixed line without usable timestamp under a time window.
            # Bare continuations inherit via the open stack and are not counted here.
            untimed += 1
        if pid is not None and parsed is not None and line_pid is None:
            unpid += 1

        msg = d.get("msg") if parsed is not None else text
        # Unprefixed lines: attach to open stack when they look like frames/continuations;
        # otherwise exclude under a time window (counted as untimed).
        if parsed is None:
            looks_cont = bool(text.strip()) and (
                _is_frame(text) or _is_exception_start(text) or _is_continuation(text)
            )
            if looks_cont and bare_ctx is not None:
                key, b_win, b_pid = bare_ctx
                open_stacks.setdefault(key, []).append((line_no, text, b_win, b_pid, None))
            elif start_ms is not None:
                untimed += 1
            continue

        key = stack_key(d)
        is_exc_start = bool(msg) and _is_exception_start(msg)
        is_frame = bool(msg) and _is_frame(msg)
        is_stackish = is_exc_start or is_frame

        if is_stackish and key is not None:
            buf = open_stacks.get(key)
            if buf:
                # New exception head closes the previous independent fault.
                if is_exc_start:
                    flush(key)
                    buf = None
                else:
                    prev_ts = buf[-1][4]
                    if (
                        ts_ms is not None
                        and prev_ts is not None
                        and abs(ts_ms - prev_ts) > _STACK_GAP_MS
                    ):
                        flush(key)
                        buf = None
            open_stacks.setdefault(key, []).append((line_no, text, in_win, pid_ok, ts_ms))
            bare_ctx = (key, in_win, pid_ok)
            continue

        # Non-stack prefixed line: close this stream's open stack, then maybe keep the line.
        if key is not None:
            flush(key)
        # Prefixed non-stack lines end bare-continuation inheritance.
        bare_ctx = None
        if in_win and pid_ok:
            kept_lines.append((line_no, text))

    for key in list(open_stacks):
        flush(key)

    kept_lines.sort(key=lambda item: item[0])
    return kept_lines, stream, untimed, unpid


def load_log(
    path: str | Path,
    time_range: str | None = None,
    pid: int | None = None,
    normalizer: TagNormalizer | None = None,
    progress=None,
    encoding: str | None = None,
) -> ParsedLog:
    p = Path(path)
    if not p.exists():
        raise LogLoadError(f"log file not found: {p}")
    start_ms, end_ms, wraps = parse_time_range(time_range)
    normalizer = normalizer or TagNormalizer()
    filtered = bool(time_range or pid is not None)
    untimed_excluded = 0
    unpid_excluded = 0
    scanned_lines = 0

    if filtered:
        numbered, stream, untimed_excluded, unpid_excluded = _filtered_lines(
            p, start_ms, end_ms, pid, encoding, normalizer,
        )
        scanned_lines = stream.total_lines
        events = parse_lines(numbered)
        if progress:
            progress(f"scanned {scanned_lines} lines, kept {len(numbered)} for parse")
        events = aggregate_stacktraces(events)
        # pid map already learned in pass 1; do not overwrite with the filtered subset.
    else:
        stream = LineStream(p, encoding=encoding)
        events = parse_lines(stream)
        scanned_lines = stream.total_lines
        if progress:
            progress(f"decoded {stream.total_lines} lines, parsed {len(events)} events")
        events = aggregate_stacktraces(events)
        normalizer.learn_processes(events)

    kept = events

    for k, e in enumerate(kept):
        e.id = k
    # Re-apply tags/modules on the kept set using the already-learned pid map.
    for ev in kept:
        cands = normalizer.tag_candidates(ev.raw_tag)
        ev.tag = cands[0] if cands else None
        if len(cands) > 1:
            ev.extra["tag_candidates"] = cands
        if ev.pid is not None:
            ev.process = normalizer.process_at(ev.pid, ev.ts_ms, ev.line_no)
        mod = normalizer.module_for_tag(ev.tag)
        if mod is None and ev.extra.get("app_frame"):
            mod = normalizer.module_for_package(ev.extra["app_frame"]["class"])
        if mod is None and ev.has_stacktrace:
            mod = normalizer.module_for_package(" ".join(ev.stacktrace[:6]))
        if mod is None and ev.process:
            mod = normalizer.module_for_package(ev.process)
        ev.module = mod

    data_status = "ok"
    scanned = stream.total_lines or scanned_lines
    if scanned == 0 or (not kept and not filtered):
        data_status = "empty"
    elif filtered:
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
        "total_lines": stream.total_lines or scanned_lines,
        "lines_scanned": scanned_lines or stream.total_lines,
        "events_total": len(events),
        "events_kept": len(kept),
        "memory_strategy": "filter_early" if filtered else "full_retain",
        "encoding_fallback": getattr(stream, "encoding_fallback", None),
        "incomplete_eof": getattr(stream, "incomplete_eof", False),
        "processes": {str(k): v for k, v in sorted(normalizer.pid_to_process.items())},
        "data_status": data_status,
        "time_wraps_midnight": wraps,
        "filter_policy": {
            "untimed_events": "excluded_when_time_range_set",
            "unpid_events": "excluded_when_pid_set",
            "process_map": "learned_from_full_stream_before_filter",
            "process_identity": "resolved_at_event_time_for_pid_reuse",
            "memory": "filter_early_keeps_in_window_lines_and_touching_stacks" if filtered else "full_retain",
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
