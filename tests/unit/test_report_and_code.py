from pathlib import Path

from adaslog.analyzer.code_analyzer import analyze_code
from adaslog.core.pipeline import run_analysis
from adaslog.models import Evidence, LogEvent


def test_run_id_prevents_overwrite(tmp_path):
    p = tmp_path / "same.log"
    p.write_text("08-11 16:11:00.000  1  1 I Tag: service started\n08-11 16:11:01.000  1  1 I Tag: connection established\n", encoding="utf-8")
    out = tmp_path / "reports"
    a = run_analysis(p, formats=["md", "json", "txt"], out_dir=out, llm_provider="rule", time_range="16:11:00-16:11:30", progress=False)
    b = run_analysis(p, formats=["md", "json", "txt"], out_dir=out, llm_provider="rule", time_range="16:11:00-16:12:00", progress=False)
    assert a["report"].run_id != b["report"].run_id
    stems = {Path(x).name for x in a["outputs"] + b["outputs"]}
    assert len(stems) == 6
    md = Path(next(p for p in a["outputs"] if p.endswith(".md"))).read_text(encoding="utf-8")
    js = Path(next(p for p in a["outputs"] if p.endswith(".json"))).read_text(encoding="utf-8")
    tx = Path(next(p for p in a["outputs"] if p.endswith(".txt"))).read_text(encoding="utf-8")
    assert "正常" in md and "NORMAL" in js and "正常" in tx
    assert a["report"].run_id in md and a["report"].run_id in tx and a["report"].run_id in js
    assert "候选" in md or "Hypothesis" in md or "不是已确认" in md


def test_ambiguous_source_files_not_guessed(tmp_path):
    src = tmp_path / "src"
    (src / "flavorA").mkdir(parents=True)
    (src / "flavorB").mkdir(parents=True)
    (src / "flavorA" / "A.kt").write_text("fun foo() {}\n", encoding="utf-8")
    (src / "flavorB" / "A.kt").write_text("fun foo() {}\n", encoding="utf-8")
    ev = LogEvent(id=0, line_no=1, raw="x", message="java.lang.NullPointerException", tag="A")
    ev.extra["frames"] = [{"class": "com.chery.ivi.adas.A", "method": "foo", "file": "A.kt", "line": 1}]
    ev.extra["app_frame"] = ev.extra["frames"][0]
    hits = analyze_code([ev], [Evidence(id="E1", label="EVIDENCE", category="fatal", event_id=0, text="t", why_it_matters="w")], src, {})
    assert hits
    assert hits[0].how_found == "ambiguous"
    assert hits[0].candidates
