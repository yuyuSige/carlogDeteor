"""Chinese-facing parameter checks for the workbench (no analysis logic)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from adaslog.core.errors import LogLoadError
from adaslog.parser.loader import parse_time_range
from adaslog.ui.settings import ALLOWED_SUFFIXES, MAX_UPLOAD_BYTES, MAX_UPLOAD_LABEL, format_bytes


@dataclass
class AnalysisParams:
    question: str = ""
    time_range: str | None = None
    pid: int | None = None
    focus_signals: list[str] | None = None
    encoding: str | None = None
    source_dir: str | None = None


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    params: AnalysisParams | None = None


_TIME_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}\s*-\s*\d{1,2}:\d{2}:\d{2}$")


def validate_upload(filename: str | None, size: int | None) -> list[str]:
    errors: list[str] = []
    if not filename:
        errors.append("请先上传日志文件（.log / .txt / .logcat）。")
        return errors
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in ALLOWED_SUFFIXES:
        errors.append(f"不支持的文件类型：仅接受 {', '.join(sorted(ALLOWED_SUFFIXES))}。")
    if size is not None and size <= 0:
        errors.append("上传文件为空，请选择有效日志。")
    if size is not None and size > MAX_UPLOAD_BYTES:
        errors.append(
            f"文件过大（{format_bytes(size)}），上传上限为 {MAX_UPLOAD_LABEL}。"
            "请裁剪时间窗或拆分后再分析。"
        )
    return errors


def validate_params(
    question: str,
    time_range: str,
    pid_text: str,
    focus_signal: str,
    encoding: str,
    source_dir: str,
) -> ValidationResult:
    errors: list[str] = []
    tr = (time_range or "").strip() or None
    if tr:
        compact = tr.replace(" ", "")
        if not _TIME_RE.match(compact):
            errors.append("时间窗格式须为 HH:MM:SS-HH:MM:SS，例如 16:11:00-16:12:00。")
        else:
            try:
                start_ms, end_ms, wraps = parse_time_range(compact)
                if wraps:
                    # Informational — not an error. Caller may surface as tip.
                    pass
                _ = start_ms, end_ms
            except LogLoadError as exc:
                errors.append(str(exc))
            tr = compact

    pid: int | None = None
    pid_raw = (pid_text or "").strip()
    if pid_raw:
        if not pid_raw.isdigit():
            errors.append("PID 须为正整数。")
        else:
            pid = int(pid_raw)
            if pid <= 0:
                errors.append("PID 须为正整数。")

    focus = [s.strip() for s in (focus_signal or "").split(",") if s.strip()] or None

    enc = (encoding or "").strip() or None
    if enc and enc.lower() in ("auto", "自动", "自动识别"):
        enc = None
    if enc and enc.lower() not in {
        "utf-8", "utf-8-sig", "gbk", "utf-16", "utf-16-le", "utf-16-be",
    }:
        errors.append("编码仅支持：自动识别 / utf-8 / gbk / utf-16-le / utf-16-be。")

    src = (source_dir or "").strip() or None
    if src:
        from pathlib import Path
        p = Path(src)
        if not p.exists() or not p.is_dir():
            errors.append("源码目录不存在或不是目录（须为只读本地路径）。")

    if errors:
        return ValidationResult(ok=False, errors=errors)
    return ValidationResult(
        ok=True,
        params=AnalysisParams(
            question=(question or "").strip(),
            time_range=tr,
            pid=pid,
            focus_signals=focus,
            encoding=enc,
            source_dir=src,
        ),
    )


def params_fingerprint(params: AnalysisParams, log_name: str, size: int) -> str:
    focus = ",".join(params.focus_signals or [])
    return "|".join([
        log_name,
        str(size),
        params.question or "",
        params.time_range or "",
        str(params.pid or ""),
        focus,
        params.encoding or "auto",
        params.source_dir or "",
    ])
