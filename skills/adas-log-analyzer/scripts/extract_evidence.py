#!/usr/bin/env python3
"""Parse a log and print key evidence JSON (no LLM)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from adaslog.core.config import load_config  # noqa: E402
from adaslog.context.signals import analyze_signals  # noqa: E402
from adaslog.detector import detect_anomalies  # noqa: E402
from adaslog.extractor import extract_evidence  # noqa: E402
from adaslog.parser import load_log  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if not argv:
        print("usage: extract_evidence.py <log> [--focus-signal A,B]", file=sys.stderr)
        return 2
    focus = None
    if "--focus-signal" in argv:
        i = argv.index("--focus-signal")
        focus = [s.strip() for s in argv[i + 1].split(",")]
        argv = argv[:i] + argv[i + 2 :]
    parsed = load_log(argv[0])
    cfg = load_config()
    an = detect_anomalies(parsed.events)
    sig = analyze_signals(parsed.events, focus_signals=focus, cfg=cfg)
    ev = extract_evidence(parsed.events, an, sig)
    print(json.dumps([e.__dict__ for e in ev], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
