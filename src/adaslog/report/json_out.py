from __future__ import annotations

import json

from adaslog.models import AnalysisReport


def render_json(report: AnalysisReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
