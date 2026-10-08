#!/usr/bin/env python3
"""Re-render an existing analysis JSON as md/txt."""
from __future__ import annotations

import json
import sys
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from adaslog.models import AnalysisReport, Classification, Evidence  # noqa: E402
from adaslog.report import render_report  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if len(argv) < 1:
        print("usage: format_report.py <analysis.json> [md|txt|json]", file=sys.stderr)
        return 2
    raw = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    fmt = argv[1] if len(argv) > 1 else "md"
    # Best-effort: print JSON as-is if full dataclass rebuild is too heavy
    if fmt == "json":
        print(json.dumps(raw, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(raw, ensure_ascii=False, indent=2) if fmt == "json" else "")
    # Fallback textual view from the dict (avoids brittle nested rebuild)
    print(f"Issue Type: {raw.get('issue_type')}")
    print(f"Severity: {raw.get('severity')}")
    print(f"Summary: {raw.get('summary')}")
    print("Key Evidence:")
    for e in raw.get("key_evidence") or []:
        print(f"  {e.get('id')} [{e.get('category')}] {e.get('text')}")
    print("Root Causes:")
    for c in raw.get("root_causes") or []:
        print(f"  {c.get('status')}: {c.get('title')} ({c.get('confidence')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
