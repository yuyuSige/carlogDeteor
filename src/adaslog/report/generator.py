from __future__ import annotations

from pathlib import Path

from adaslog.models import AnalysisReport
from adaslog.report.json_out import render_json
from adaslog.report.markdown import render_markdown
from adaslog.report.text import render_text


def render_report(report: AnalysisReport, fmt: str) -> str:
    if fmt in ("md", "markdown"):
        return render_markdown(report)
    if fmt == "json":
        return render_json(report)
    if fmt in ("txt", "text"):
        return render_text(report)
    raise ValueError(f"unknown format: {fmt}")


def write_reports(report: AnalysisReport, out_dir: str | Path, formats: list[str], stem: str = "analysis") -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    ext = {"md": ".md", "markdown": ".md", "json": ".json", "txt": ".txt", "text": ".txt"}
    for fmt in formats:
        text = render_report(report, fmt)
        path = out / f"{stem}{ext.get(fmt, '.' + fmt)}"
        path.write_text(text, encoding="utf-8")
        written[fmt] = path
    return written
