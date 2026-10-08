"""Cross-process signal timeline: VDS notifyCallback structs + DrivingTextManager.

Mapped fields (config/rules/signal_text.json) may treat idle values as NO_TEXT.
Unknown fields MUST NOT inherit that business rule.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from adaslog.core.config import load_json_resource
from adaslog.models import LogEvent, SignalFieldStatus, SignalPeriod, SignalSummary

RX_NOTIFY = re.compile(
    r"notifyCallback\(\)\s+(?P<struct>\w+),\s*msg:(?P<s2>\w+)\{(?P<body>[^{}]*)\}"
)
RX_STRUCT = re.compile(r"(?P<struct>\w+)\{(?P<body>[^{}]{0,4000})\}")
RX_KV = re.compile(r"(\w+)\s*=\s*([^,]+)")


def _load_field_map() -> dict:
    try:
        return load_json_resource("rules/signal_text.json")
    except FileNotFoundError:
        return {}


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


def _focus_tokens(focus: list[str] | None) -> list[tuple[str | None, str]]:
    """Return (optional_struct, field) pairs. Struct.field is strict; bare field matches any struct."""
    if not focus:
        return []
    out = []
    for raw in focus:
        raw = raw.strip()
        if not raw:
            continue
        if "." in raw:
            struct, field = raw.split(".", 1)
            out.append((struct, field))
        else:
            out.append((None, raw))
    return out


def _wanted(struct: str, field: str, focus_tokens: list[tuple[str | None, str]], patterns: list[str], known: set[str]) -> bool:
    if focus_tokens:
        for st, fl in focus_tokens:
            if fl != field:
                continue
            if st is None or st == struct:
                return True
        return False
    if field in known:
        return True
    return any(re.search(p, field) for p in patterns)


def _spec_for(field: str, struct: str, knowledge: dict) -> dict | None:
    fields = knowledge.get("fields") or {}
    spec = fields.get(field)
    if not spec:
        return None
    want_struct = spec.get("struct")
    if want_struct and want_struct != struct:
        return None
    return spec


def _classify_values(values: list[str], spec: dict | None, default_idle: str) -> tuple[str, bool, str]:
    """Return (observation, mapped, note)."""
    if not values:
        return "not_sampled", False, "窗口内未采到该字段。"
    if spec is None:
        return "unknown_mapping", False, "字段无 Profile 映射，不能将 0 解释为 NO_TEXT。"
    idle = str(spec.get("idle", default_idle))
    triggers = {str(v) for v in (spec.get("trigger_values") or [])}
    uniq = list(dict.fromkeys(values))
    if any(v in triggers for v in uniq):
        return "saw_trigger", True, "出现过映射表中的触发值。"
    non_idle = [v for v in uniq if v != idle]
    if non_idle:
        return "saw_unmapped_value", True, f"出现过非空闲且未列入 trigger_values 的值：{non_idle}。"
    return "idle_entire_window", True, "全窗口观测均为空闲值。"


def analyze_signals(
    events: list[LogEvent],
    focus_signals: list[str] | None = None,
    cfg: dict | None = None,
) -> SignalSummary:
    cfg = cfg or {}
    sig_cfg = cfg.get("signals", {})
    patterns = sig_cfg.get("trigger_field_patterns") or ["ActiveSt$", "TextInfo", "TextInfomation", "Warning$", "WarnTypeSts$"]
    idle_msg = sig_cfg.get("text_idle_message") or "队列为空且无当前显示"
    trigger_msgs = sig_cfg.get("text_trigger_messages") or ["文言加入队列", "显示文言"]
    default_idle = str(sig_cfg.get("idle_value") or "0")
    knowledge = _load_field_map()
    known_fields = set((knowledge.get("fields") or {}).keys())
    focus_tokens = _focus_tokens(focus_signals)

    series: dict[str, list[tuple]] = defaultdict(list)
    struct_counts: dict[str, int] = defaultdict(int)

    for ev in events:
        parsed = _extract_struct(ev.message)
        if not parsed:
            continue
        struct, fields = parsed
        struct_counts[struct] += 1
        for field, value in fields.items():
            if not _wanted(struct, field, focus_tokens, patterns, known_fields):
                continue
            key = f"{struct}.{field}"
            series[key].append((ev.timestamp, value, ev.line_no, ev.pid))

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

    constant: list[SignalPeriod] = []
    changed: dict[str, list[tuple]] = {}
    focus_periods: list[SignalPeriod] = []
    field_status: list[SignalFieldStatus] = []

    target_keys: list[str] = []
    if focus_tokens:
        # Ensure not_sampled entries exist for requested fields.
        requested = []
        for st, fl in focus_tokens:
            if st:
                requested.append(f"{st}.{fl}")
            else:
                matched = [k for k in series if k.endswith("." + fl)]
                requested.extend(matched or [f"?.{fl}"])
        target_keys = list(dict.fromkeys(requested))
    else:
        target_keys = list(series.keys())

    seen_keys = set()
    for key in target_keys:
        seen_keys.add(key)
        if key not in series:
            struct, field = (key.split(".", 1) + [""])[:2]
            field_status.append(
                SignalFieldStatus(
                    key=key, struct=struct, field=field, observation="not_sampled",
                    mapped=False, note="指定了焦点信号但窗口内没有采样。",
                )
            )
            continue
        samples = series[key]
        struct, field = key.split(".", 1)
        periods = to_periods(key, samples)
        values = [p.value for p in periods for _ in range(max(p.samples, 1))]
        unique_vals = list(dict.fromkeys(p.value for p in periods))
        if len(unique_vals) == 1:
            constant.append(periods[0])
        else:
            changed[key] = [(p.start_ts, p.value) for p in periods]
        spec = _spec_for(field, struct, knowledge)
        observation, mapped, note = _classify_values(unique_vals, spec, default_idle)
        field_status.append(
            SignalFieldStatus(
                key=key, struct=struct, field=field, observation=observation,
                values_seen=unique_vals, mapped=mapped,
                idle_value=str(spec.get("idle", default_idle)) if spec else None,
                trigger_values=list(spec.get("trigger_values") or []) if spec else [],
                periods=periods, note=note,
            )
        )
        focus_periods.extend(periods)

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

    if trigger_count:
        text_corr = "trigger_seen"
    elif idle_count:
        text_corr = "idle_seen"
    else:
        text_corr = "none"

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
        field_status=field_status,
        text_correlation=text_corr,
        enqueue_unobserved_is_unknown=True,
    )
