"""Robust text loading for Android/ADAS logs.

Handles:
  * UTF-8 / UTF-8-BOM / UTF-16 LE / UTF-16 BE / GBK fallback
  * "double encoded" Chinese: UTF-8 bytes that were read as GBK and then re-saved
    (e.g. as UTF-16).  Example: 闃熷垪涓虹┖ -> 队列为空
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_CJK = re.compile(r"[\u4e00-\u9fff]")


@dataclass
class LoadedText:
    text: str
    encoding: str
    mojibake_repaired: bool
    repaired_lines: int


def decode_bytes(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16-le", errors="replace").lstrip("\ufeff"), "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be", errors="replace").lstrip("\ufeff"), "utf-16-be"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    # Heuristic for BOM-less UTF-16 LE: many NUL bytes at odd positions
    if len(raw) >= 4 and raw[1:200:2].count(0) > 60:
        return raw.decode("utf-16-le", errors="replace"), "utf-16-le(no-bom)"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gbk"), "gbk"
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace"), "utf-8(replace)"


def repair_mojibake_line(line: str) -> tuple[str, bool]:
    """Try to undo UTF-8-read-as-GBK damage on one line. Returns (text, changed)."""
    if not _CJK.search(line):
        return line, False
    try:
        fixed = line.encode("gbk").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        # lossy case ('?' replaced bytes): decode what we can
        try:
            fixed = line.encode("gbk", errors="ignore").decode("utf-8", errors="replace")
        except UnicodeEncodeError:
            return line, False
        # only accept if the result is plausible text (not mostly replacement chars)
        good = len(_PLAUSIBLE.findall(fixed))
        if good < 1 or fixed.count("\ufffd") > max(2, good):
            return line, False
    if fixed != line:
        return fixed, True
    return line, False


_PLAUSIBLE = re.compile(r"[\u4e00-\u9fff\u2500-\u257f\u3000-\u303f\uff00-\uffef]")


def _looks_double_encoded(lines: list[str], sample: int = 3000) -> bool:
    checked = repaired = 0
    for line in lines:
        if not _CJK.search(line):
            continue
        checked += 1
        try:
            fixed = line.encode("gbk").decode("utf-8")
            if fixed != line and _PLAUSIBLE.search(fixed):
                repaired += 1
        except (UnicodeEncodeError, UnicodeDecodeError):
            # lossy: count it if the repaired text still yields plausible CJK / box-drawing output
            try:
                fixed = line.encode("gbk", errors="ignore").decode("utf-8", errors="replace")
                bad = fixed.count("\ufffd")
                good = len(_PLAUSIBLE.findall(fixed))
                if good > 0 and bad <= max(2, good):
                    repaired += 1
            except UnicodeEncodeError:
                pass
        if checked >= sample:
            break
    return checked > 0 and repaired / checked > 0.5


def load_text(path: str | Path, repair: bool | None = None) -> LoadedText:
    raw = Path(path).read_bytes()
    text, enc = decode_bytes(raw)
    lines = text.splitlines()
    do_repair = _looks_double_encoded(lines) if repair is None else repair
    repaired_count = 0
    if do_repair:
        out = []
        for line in lines:
            fixed, changed = repair_mojibake_line(line)
            repaired_count += int(changed)
            out.append(fixed)
        lines = out
    return LoadedText("\n".join(lines), enc, do_repair, repaired_count)
