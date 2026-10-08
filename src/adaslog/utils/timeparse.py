"""Timestamp parsing for the timestamp shapes seen in Android / ADAS logs."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

_SHAPES = [
    # 2026-09-29 10:31:22.123 | 2026-09-29T10:31:22,123
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,6}))?"), True),
    # 08-11 16:11:27.391  (logcat threadtime / time, no year)
    (re.compile(r"^(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?"), False),
]
_SYNTHETIC_YEAR = 2000  # used for year-less logcat so ordering/arithmetic works


def parse_timestamp(text: str) -> Optional[int]:
    """Return milliseconds since epoch (UTC) or None."""
    for rx, has_year in _SHAPES:
        m = rx.match(text)
        if not m:
            continue
        g = m.groups()
        if has_year:
            y, mo, d, h, mi, s, frac = g
        else:
            mo, d, h, mi, s, frac = g
            y = _SYNTHETIC_YEAR
        ms = int((frac or "0").ljust(3, "0")[:3])
        try:
            dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), ms * 1000, tzinfo=timezone.utc)
        except ValueError:
            return None
        return int(dt.timestamp() * 1000)
    return None


def parse_clock(text: str) -> Optional[int]:
    """Parse HH:MM:SS[.mmm] into milliseconds of day."""
    m = re.match(r"^(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$", text.strip())
    if not m:
        return None
    h, mi, s, frac = m.groups()
    return ((int(h) * 60 + int(mi)) * 60 + int(s)) * 1000 + int((frac or "0").ljust(3, "0"))


def ms_of_day(ts_ms: int) -> int:
    return ts_ms % (24 * 3600 * 1000)


def fmt_delta(ms: int) -> str:
    sign = "-" if ms < 0 else "+"
    ms = abs(ms)
    if ms < 1000:
        return f"{sign}{ms}ms"
    return f"{sign}{ms / 1000:.3f}s"
