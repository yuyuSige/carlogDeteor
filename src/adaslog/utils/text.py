"""Small text helpers."""
from __future__ import annotations

import re

_NUM = re.compile(r"-?\b\d+(?:\.\d+)?\b|0x[0-9a-fA-F]+")
_HEX_OBJ = re.compile(r"@[0-9a-f]{4,}")


def normalize_message(msg: str, width: int = 200) -> str:
    """Replace numbers/object hashes so repeated messages collapse to one shape."""
    s = _HEX_OBJ.sub("@X", msg)
    s = _NUM.sub("N", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:width]


def truncate(s: str, width: int = 200) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= width else s[: width - 3] + "..."
