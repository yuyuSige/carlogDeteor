import time
import tracemalloc

from adaslog.parser import load_log
from adaslog.utils.io import LineStream, detect_encoding


def test_encodings_utf8_utf16_gbk(tmp_path):
    text = "08-11 16:11:27.391  5636  5636 D DrivingTextManager: 队列为空\n"
    cases = {
        "utf8.log": text.encode("utf-8"),
        "utf16.log": b"\xff\xfe" + text.encode("utf-16-le"),
        "gbk.log": text.encode("gbk"),
    }
    for name, raw in cases.items():
        p = tmp_path / name
        p.write_bytes(raw)
        parsed = load_log(p)
        assert parsed.events
        assert "队列为空" in parsed.events[0].message or "DrivingTextManager" in (parsed.events[0].tag or "")


def test_detect_encoding_bom():
    assert detect_encoding(b"\xff\xfeA\x00") == "utf-16-le"
    assert detect_encoding("队列".encode("utf-8")) == "utf-8"


def test_original_line_numbers_survive_stream(tmp_path):
    p = tmp_path / "n.log"
    p.write_text("\n\n08-11 16:11:00.000  1  1 I Tag: hello\n", encoding="utf-8")
    parsed = load_log(p)
    assert parsed.events[0].line_no == 3


def test_repeatable_large_log_stream_metrics(tmp_path):
    p = tmp_path / "large.log"
    line = "08-11 16:11:00.000  1736  1811 D CommonAdapter: notifyCallback() AdasActiveSafetyFcnInfo, msg:AdasActiveSafetyFcnInfo{FcwAcitveSt=0}\n"
    # ~2MB repeatable synthetic log (not a production sample)
    n = 15000
    p.write_text(line * n, encoding="utf-8")
    size = p.stat().st_size
    tracemalloc.start()
    t0 = time.perf_counter()
    parsed = load_log(p)
    elapsed = time.perf_counter() - t0
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert parsed.meta["total_lines"] == n
    assert parsed.meta["events_kept"] == n
    assert parsed.events[0].line_no == 1
    assert parsed.events[-1].line_no == n
    # store on parsed.meta for docs; assertions only check sanity, not a SLA
    parsed.meta["perf"] = {
        "size_bytes": size,
        "events": len(parsed.events),
        "seconds": round(elapsed, 3),
        "peak_tracemalloc_bytes": peak,
        "note": "tracemalloc peak is Python allocations only, not RSS",
    }
    assert elapsed < 30
    assert peak > 0
    print(parsed.meta["perf"])
