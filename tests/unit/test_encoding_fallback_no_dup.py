"""Regression: encoding fallback must not replay already-yielded lines."""
from collections import Counter

from adaslog.parser import load_log
from adaslog.utils.io import LineStream


def test_ascii_head_gbk_tail_no_duplicate_replay(tmp_path):
    """ASCII sample selects UTF-8; GBK Chinese appears after the probe.

    Before the fix, UTF-8 yielded ~60k lines then GBK replayed from the start
    (~118k outputs) while meta.total_lines stayed ~60k.
    """
    n = 60_000
    body = b"".join(f"line {i}\n".encode("ascii") for i in range(n))
    body += "中文队列为空\n".encode("gbk")
    p = tmp_path / "late_gbk.log"
    p.write_bytes(body)

    stream = LineStream(p, repair=False, sample_bytes=2_000)
    out = list(stream)

    assert stream.encoding == "gbk"
    assert stream.encoding_fallback == "gbk"
    assert stream.total_lines == n + 1
    assert len(out) == n + 1
    assert [ln for ln, _ in out] == list(range(1, n + 2))
    counts = Counter(text for _, text in out)
    assert counts.most_common(1)[0][1] == 1
    assert any("中文" in t or "队列" in t for _, t in out)

    parsed = load_log(p)
    assert parsed.meta["total_lines"] == n + 1
    assert parsed.meta["encoding"] == "gbk"
    assert len(parsed.events) == n + 1


def test_fallback_does_not_restart_after_partial_yield(tmp_path):
    """Smaller fixture: first lines ASCII, then illegal UTF-8 / valid GBK."""
    p = tmp_path / "small.log"
    p.write_bytes(b"alpha\nbeta\n" + "中文\n".encode("gbk"))
    stream = LineStream(p, repair=False, sample_bytes=8)
    lines = list(stream)
    assert len(lines) == 3
    assert stream.total_lines == 3
    assert lines[0] == (1, "alpha")
    assert lines[1] == (2, "beta")
    assert "中" in lines[2][1]
