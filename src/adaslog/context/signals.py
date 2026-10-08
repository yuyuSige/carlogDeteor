"""Cross-process signal timeline: VDS notifyCallback structs + DrivingTextManager.

Domain rule (E02 driving_text_tip Profile, read-only):
  a field value of 0 (idle) maps to NO_TEXT, so the corresponding prompt is not queued.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from adaslog.core.config import RULES_DIR
from adaslog.models import LogEvent, SignalPeriod, SignalSummary

RX_NOTIFY = re.compile(
    r"notifyCallback\(\)\s+(?P<struct>\w+),\s*msg:(?P<s2>\w+)\{(?P<body>[^{}]*)\}"
)
RX_STRUCT = re.compile(r"(?P<struct>\w+)\{(?P<body>[^{}]{0,4000})\}")
RX_KV = re.compile(r"(\w+)\s*=\s*([^,]+)")


def _load_field_map() -> dict:
    path = RULES_DIR / "signal_text.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_fields(body: str) -> dict[str, str]:
    return {k: v.strip() for k, v in RX_KV.findall(body)}


def _extract_struct(message: str) -> tuple[str, dict[str, str]] | None:
    m = RX_NOTIFY.search(message)
    if m:
        return m.group("struct"), _parse_fields(m.group("body"))
    m = RX_STRUCT.search(message)
    if m and "=" in m.group("body"):
        return m.group("struct"), _parse_fields(m.group("body"))
    return None


def _field_wanted(field: str, focus: list[str] | None, patterns: list[str]) -> bool:
    if focus:
        return field in focus or any(field == f.split(".")[-1] for f in focus)
    return any(re.search(p, field) for p in patterns)


def analyze_signals(
    events: list[LogEvent],
    focus_signals: list[str] | None = None,
    cfg: dict | None = None,
) -> SignalSummary:
    cfg = cfg or {}
    sig_cfg = cfg.get("signals", {})
    patterns = sig_cfg.get("trigger_field_patterns") or ["ActiveSt$", "TextInfo", "TextInfomation", "Warning$", "WarnTypeSts$"]
    idle_msg = sig_cfg.get("text_idle_message") or "队列为空且无当前显示"
    trigger_msgs = sig_cfg.get("text_trigger_messages") or ["文言加入队列", "显示文言", "变化: "]
    knowledge = _load_field_map()
    known_fields = set((knowledge.get("fields") or {}).keys())

    # field -> list of (ts, value, line, pid)
    series: dict[str, list[tuple]] = defaultdict(list)
    struct_counts: dict[str, int] = defaultdict(int)

    for ev in events:
        parsed = _extract_struct(ev.message)
        if not parsed:
            continue
        struct, fields = parsed
        struct_counts[struct] += 1
        for field, value in fields.items():
            if not _field_wanted(field, focus_signals, patterns) and field not in known_fields:
                if focus_signals:
                    continue
                # keep only trigger-like or known fields to limit memory on huge logs
                continue
            key = f"{struct}.{field}"
            series[key].append((ev.timestamp, value, ev.line_no, ev.pid))

    constant: list[SignalPeriod] = []
    changed: dict[str, list[tuple]] = {}
    focus_periods: list[SignalPeriod] = []

    def to_periods(key: str, samples: list[tuple]) -> list[SignalPeriod]:
        struct, field = key.split(".", 1)
        periods: list[SignalPeriod] = []
        start_ts, start_val, start_line, start_pid = samples[0]
        count = 0
        last_ts, last_line = start_ts, start_line
        for ts, val, line, pid in samples:
            if val != start_val:
                periods.append(
                    SignalPeriod(struct, field, start_val, start_ts, last_ts, count, start_line, last_line, start_pid)
                )
                start_ts, start_val, start_line, start_pid = ts, val, line, pid
                count = 0
            count += 1
            last_ts, last_line = ts, line
        periods.append(
            SignalPeriod(struct, field, start_val, start_ts, last_ts, count, start_line, last_line, start_pid)
        )
        return periods

    focus_names = set(focus_signals or []) | known_fields

    for key, samples in series.items():
        field = key.split(".", 1)[1]
        periods = to_periods(key, samples)
        values = {p.value for p in periods}
        if len(values) == 1:
            constant.append(periods[0])
        else:
            changed[key] = [(p.start_ts, p.value) for p in periods]
        if field in focus_names or (focus_signals and field in focus_names):
            focus_periods.extend(periods)

    # If user named focus signals, keep only those; else keep idle (0) trigger-like fields
    if focus_signals:
        focus_periods = [p for p in focus_periods if p.field in focus_names]
    else:
        idle_focus = [p for p in focus_periods if p.value in ("0", "0.0") and p.samples >= 1]
        # prefer idle periods of known trigger fields
        focus_periods = idle_focus[:8] or focus_periods[:4]

    idle_count = 0
    trigger_count = 0
    text_tag = None
    for ev in events:
        if ev.tag != "DrivingTextManager" and ev.raw_tag != "DrivingTextManager":
            continue
        text_tag = "DrivingTextManager"
        if idle_msg in ev.message or "等待新文言触发" in ev.message:
            idle_count += 1
        elif any(t in ev.message for t in trigger_msgs):
            trigger_count += 1

    ts = [e.timestamp for e in events if e.timestamp]
    window = f"{ts[0]} .. {ts[-1]}" if ts else None
    return SignalSummary(
        structs=dict(struct_counts),
        constant_fields=constant,
        changed_fields=changed,
        focus=focus_periods,
        text_manager_idle_count=idle_count,
        text_manager_trigger_count=trigger_count,
        text_manager_tag=text_tag,
        window=window,
    )
