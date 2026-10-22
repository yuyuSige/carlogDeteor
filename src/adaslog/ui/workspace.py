"""Task directories and safe file handling for the local workbench."""
from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from adaslog.ui.settings import ALLOWED_SUFFIXES, temp_root

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")


def safe_filename(name: str) -> str:
    """Strip path components; never let upload names choose arbitrary disk paths."""
    base = Path(name.replace("\\", "/")).name
    base = _SAFE_NAME.sub("_", base).strip("._") or "upload.log"
    if len(base) > 120:
        stem = Path(base).stem[:80]
        suffix = Path(base).suffix[:20]
        base = stem + suffix
    suffix = Path(base).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        base = base + ".log"
    return base


@dataclass
class TaskWorkspace:
    task_id: str
    root: Path
    log_path: Path
    out_dir: Path


def create_task(upload_name: str, data: bytes) -> TaskWorkspace:
    task_id = uuid.uuid4().hex[:12]
    root = temp_root() / task_id
    root.mkdir(parents=True, exist_ok=False)
    out_dir = root / "reports"
    out_dir.mkdir()
    log_path = root / safe_filename(upload_name)
    log_path.write_bytes(data)
    return TaskWorkspace(task_id=task_id, root=root, log_path=log_path, out_dir=out_dir)


def read_line_window(
    path: Path,
    anchor_line: int,
    before: int = 8,
    after: int = 12,
    encoding: str = "utf-8",
) -> list[tuple[int, str]]:
    """On-demand context around a 1-based line number. Does not load the whole file."""
    if anchor_line < 1:
        return []
    start = max(1, anchor_line - before)
    end = anchor_line + after
    out: list[tuple[int, str]] = []
    # Prefer the encoding used for analysis; fall back to replace.
    try:
        fh = path.open("r", encoding=encoding, errors="replace")
    except LookupError:
        fh = path.open("r", encoding="utf-8", errors="replace")
    with fh:
        for idx, line in enumerate(fh, start=1):
            if idx < start:
                continue
            if idx > end:
                break
            out.append((idx, line.rstrip("\r\n")))
    return out


def cleanup_task(root: Path) -> None:
    if root.exists() and root.is_dir():
        shutil.rmtree(root, ignore_errors=True)


def cleanup_old_tasks(keep_latest: int = 20) -> int:
    """Remove oldest task dirs beyond keep_latest. Returns removed count."""
    root = temp_root()
    dirs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
    removed = 0
    while len(dirs) > keep_latest:
        shutil.rmtree(dirs.pop(0), ignore_errors=True)
        removed += 1
    return removed
