"""Stack trace aggregation.

In logcat every frame of a Java stack trace is its own log line, e.g.

  E AndroidRuntime: FATAL EXCEPTION: main
  E AndroidRuntime: Process: com.chery.ivi.adas, PID: 5636
  E AndroidRuntime: java.lang.NullPointerException: ...
  E AndroidRuntime:     at com.chery.ivi.adas.manager.avm.AvmViewPresenter.show(AvmViewPresenter.kt:123)
  E AndroidRuntime: Caused by: ...

This pass merges consecutive events with the same pid/tid/tag whose message is a stack
frame / exception head into the first event's `stacktrace`, so one LogEvent == one exception.
It also extracts `exception_class`, `exception_message`, `process` and `fatal` into event.extra.
"""
from __future__ import annotations

import re

from adaslog.models import LogEvent
from adaslog.parser.logcat import RX_EXC_HEAD, RX_FATAL, RX_PROCESS_LINE, RX_STACK_FRAME

RX_EXC_CLASS = re.compile(r"^\s*((?:[\w$]+\.)+[\w$]*(?:Exception|Error|Throwable|Death))\b:?\s*(.*)$")
RX_FRAME_LOC = re.compile(r"at\s+([\w$.<>]+)\.([\w$<>]+)\((\w+\.(?:kt|java)):(\d+)\)")


def _same_stream(a: LogEvent, b: LogEvent) -> bool:
    return a.pid == b.pid and a.tid == b.tid and (a.raw_tag or "") == (b.raw_tag or "")


def _is_frame(msg: str) -> bool:
    return bool(RX_STACK_FRAME.match(msg) or RX_EXC_HEAD.match(msg) or RX_PROCESS_LINE.match(msg))


def _is_exception_start(msg: str) -> bool:
    return bool(RX_FATAL.match(msg) or RX_EXC_HEAD.match(msg))


def aggregate_stacktraces(events: list[LogEvent]) -> list[LogEvent]:
    out: list[LogEvent] = []
    i = 0
    n = len(events)
    while i < n:
        ev = events[i]
        first = ev.message.split("\n", 1)[0]
        if _is_exception_start(first) or (
            i + 1 < n and _same_stream(ev, events[i + 1]) and _is_frame(events[i + 1].message) and ev.level in ("E", "F", "W")
        ):
            j = i + 1
            while j < n and _same_stream(ev, events[j]) and _is_frame(events[j].message):
                ev.stacktrace.append(events[j].message.strip())
                ev.raw += "\n" + events[j].raw
                j += 1
            if j > i + 1 or ev.stacktrace:
                _annotate(ev)
                out.append(ev)
                i = j
                continue
        if ev.stacktrace or RX_EXC_CLASS.match(first):
            _annotate(ev)
        out.append(ev)
        i += 1
    # re-number ids sequentially so later stages can index by id
    for k, e in enumerate(out):
        e.id = k
    return out


def _annotate(ev: LogEvent) -> None:
    lines = [ev.message.split("\n", 1)[0]] + ev.message.split("\n")[1:] + ev.stacktrace
    if RX_FATAL.match(lines[0]):
        ev.extra["fatal"] = True
    for ln in lines:
        m = RX_PROCESS_LINE.match(ln)
        if m:
            ev.extra["process"] = ln.split("Process:", 1)[1].split(",")[0].strip()
        m = RX_EXC_CLASS.match(ln)
        if m and "exception_class" not in ev.extra:
            ev.extra["exception_class"] = m.group(1)
            ev.extra["exception_message"] = m.group(2).strip()
    frames = []
    for ln in ev.stacktrace:
        m = RX_FRAME_LOC.search(ln)
        if m:
            frames.append({"class": m.group(1), "method": m.group(2), "file": m.group(3), "line": int(m.group(4))})
    if frames:
        ev.extra["frames"] = frames
        # first application frame (not android.*/java.*/kotlin.*)
        for fr in frames:
            if not fr["class"].startswith(("android.", "java.", "kotlin.", "kotlinx.", "androidx.", "com.android.", "dalvik.")):
                ev.extra["app_frame"] = fr
                break
