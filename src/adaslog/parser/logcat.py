"""Line-level parser for Android logcat and generic ADAS text logs.

Supported shapes (auto-detected per line):
  threadtime : 08-11 16:11:27.391  5636  5636 D DrivingTextManager: msg
  threadtime+year : 2026-08-11 16:11:27.391  5636  5636 D Tag: msg
  time       : 08-11 16:11:27.391 D/Tag( 5636): msg
  brief      : D/Tag( 5636): msg
  custom     : 2026-09-29 10:31:22.123 E/CarService: msg
  generic    : 2026-09-29 10:31:22.123 ERROR msg   |  ERROR msg  |  bare text
  markers    : --------- beginning of crash
Lines that match nothing become continuation lines of the previous event
(multi-line messages / stack traces).  Stack trace aggregation is a separate pass.
"""
from __future__ import annotations

import re
from typing import Iterable

from adaslog.models import LogEvent
from adaslog.utils.timeparse import parse_timestamp

_TS_NOYEAR = r"\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}"
_TS_YEAR = r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[.,]\d{1,6}"
_LVL = r"[VDIWEFS]"

RX_THREADTIME = re.compile(
    rf"^(?P<ts>{_TS_YEAR}|{_TS_NOYEAR})\s+(?P<pid>\d+)\s+(?P<tid>\d+)\s+(?P<lvl>{_LVL})\s(?P<tag>.*?)\s*:\s?(?P<msg>.*)$"
)
RX_TIME = re.compile(
    rf"^(?P<ts>{_TS_YEAR}|{_TS_NOYEAR})\s+(?P<lvl>{_LVL})/(?P<tag>.*?)\(\s*(?P<pid>\d+)\):\s?(?P<msg>.*)$"
)
RX_BRIEF = re.compile(rf"^(?P<lvl>{_LVL})/(?P<tag>.*?)\(\s*(?P<pid>\d+)\):\s?(?P<msg>.*)$")
RX_CUSTOM = re.compile(rf"^(?P<ts>{_TS_YEAR}|{_TS_NOYEAR})\s+(?P<lvl>{_LVL})/(?P<tag>[^:(]+?)\s*:\s?(?P<msg>.*)$")
RX_GENERIC_TS = re.compile(
    rf"^(?P<ts>{_TS_YEAR}|{_TS_NOYEAR})\s+(?:\[?(?P<lvl>VERBOSE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|[VDIWEF])\]?\s*[:/\-]?\s*)?(?P<msg>.*)$"
)
RX_GENERIC_LVL = re.compile(r"^\[?(?P<lvl>VERBOSE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\]?\s*[:\-]?\s+(?P<msg>.*)$", re.I)
RX_MARKER = re.compile(r"^-{5,}\s*beginning of (?P<buf>\w+)")

_WORD_LEVEL = {"VERBOSE": "V", "DEBUG": "D", "INFO": "I", "WARN": "W", "WARNING": "W", "ERROR": "E", "FATAL": "F"}

# continuation detection (stack frames etc.)
RX_STACK_FRAME = re.compile(r"^\s*(at\s+[\w$.<>]+\(.*\)|Caused by:|\.\.\.\s*\d+\s+more|Suppressed:)")
RX_EXC_HEAD = re.compile(r"^\s*(?:[\w$]+\.)+[\w$]*(?:Exception|Error|Throwable|Death)\b(?::|$)")
RX_FATAL = re.compile(r"^FATAL EXCEPTION")
RX_PROCESS_LINE = re.compile(r"^Process:\s*\S+,\s*PID:\s*\d+")


def _lvl(s: str | None) -> str | None:
    if not s:
        return None
    s = s.upper()
    return _WORD_LEVEL.get(s, s if len(s) == 1 else None)


def parse_line(line: str) -> dict | None:
    """Return a dict with parsed fields, or None when the line is a continuation."""
    if not line.strip():
        return None
    m = RX_MARKER.match(line)
    if m:
        return {"marker": m.group("buf"), "msg": line.strip()}
    for rx in (RX_THREADTIME, RX_TIME, RX_BRIEF, RX_CUSTOM):
        m = rx.match(line)
        if m:
            d = m.groupdict()
            d["lvl"] = _lvl(d.get("lvl"))
            return d
    m = RX_GENERIC_TS.match(line)
    if m:
        d = m.groupdict()
        d["lvl"] = _lvl(d.get("lvl"))
        return d
    m = RX_GENERIC_LVL.match(line)
    if m:
        d = m.groupdict()
        d["lvl"] = _lvl(d.get("lvl"))
        return d
    return None


def _is_continuation(line: str) -> bool:
    return bool(RX_STACK_FRAME.match(line) or RX_EXC_HEAD.match(line) or line.startswith((" ", "\t")))


def parse_lines(lines: Iterable[str], bare_lines_as_events: bool = True) -> list[LogEvent]:
    events: list[LogEvent] = []
    next_id = 0
    for idx, line in enumerate(lines, start=1):
        line = line.rstrip("\r\n")
        if not line.strip():
            continue
        parsed = parse_line(line)
        if parsed is None or (
            parsed.get("ts") is None and parsed.get("lvl") is None and parsed.get("tag") is None and "marker" not in parsed
        ):
            # bare text line: continuation if it looks like one and we have a previous event
            if events and (_is_continuation(line) or not bare_lines_as_events):
                prev = events[-1]
                if RX_STACK_FRAME.match(line) or RX_EXC_HEAD.match(line):
                    prev.stacktrace.append(line.strip())
                else:
                    prev.message += "\n" + line.strip()
                prev.raw += "\n" + line
                continue
            if not bare_lines_as_events:
                continue
            msg = parsed["msg"] if parsed else line.strip()
            ev = LogEvent(id=next_id, line_no=idx, raw=line, message=msg)
            ev.level = _lvl(parsed.get("lvl")) if parsed else None
            # bare "service started" style lines: treat leading word as tag if "Tag: msg"
            if ev.level is None and ":" in msg and " " not in msg.split(":", 1)[0] and len(msg.split(":", 1)[0]) < 40:
                ev.raw_tag, ev.message = msg.split(":", 1)[0], msg.split(":", 1)[1].strip()
            events.append(ev)
            next_id += 1
            continue

        ev = LogEvent(id=next_id, line_no=idx, raw=line, message=parsed.get("msg", "") or "")
        if "marker" in parsed:
            ev.extra["marker"] = parsed["marker"]
            ev.raw_tag = "logcat"
            ev.level = "I"
        else:
            ts = parsed.get("ts")
            if ts:
                ev.timestamp = ts
                ev.ts_ms = parse_timestamp(ts)
            ev.level = parsed.get("lvl")
            if parsed.get("pid") is not None:
                ev.pid = int(parsed["pid"])
            if parsed.get("tid") is not None:
                ev.tid = int(parsed["tid"])
            tag = parsed.get("tag")
            ev.raw_tag = tag.strip() if tag is not None else None
            if ev.raw_tag == "":
                ev.raw_tag = None
        events.append(ev)
        next_id += 1
    return events
