#!/usr/bin/env python3
"""Skill entry: same pipeline as `adaslog analyze`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from adaslog.cli.main import main  # noqa: E402


if __name__ == "__main__":
    # prepend the analyze verb when the script is invoked directly
    argv = sys.argv[1:]
    if argv and argv[0] != "analyze":
        argv = ["analyze", *argv]
    raise SystemExit(main(argv))
