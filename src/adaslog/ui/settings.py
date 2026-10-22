"""Central UI settings. Keep limits and paths here — not scattered in widgets."""
from __future__ import annotations

from pathlib import Path

from adaslog.core.config import PROJECT_ROOT

# Field logs around 173MB must fit; keep a single configurable ceiling.
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MiB
MAX_UPLOAD_LABEL = "200 MB"

TEMP_ROOT_NAME = "tmp/ui_workbench"
ALLOWED_SUFFIXES = {".log", ".txt", ".logcat"}

# Default bind for the local internal tool.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8501

# How many context lines to show around an evidence anchor (on-demand read).
CONTEXT_LINES_BEFORE = 8
CONTEXT_LINES_AFTER = 12


def temp_root() -> Path:
    root = PROJECT_ROOT / TEMP_ROOT_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"
