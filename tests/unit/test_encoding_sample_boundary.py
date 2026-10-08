from adaslog.parser import load_log
from adaslog.utils.io import LineStream, detect_encoding


def test_utf8_truncated_sample_not_gbk(tmp_path):
    """Legal UTF-8 whose 2MiB probe cuts a 3-byte character must stay UTF-8."""
    raw = b"a" * (2_000_000 - 2) + "中文".encode("utf-8") + b"\n"
    probe = raw[:2_000_000]
    assert detect_encoding(probe) == "utf-8"
    p = tmp_path / "cut.log"
    p.write_bytes(raw)
    stream = LineStream(p, sample_bytes=2_000_000, repair=False)
    lines = list(stream)
    assert stream.encoding == "utf-8"
    assert any("中文" in t for _, t in lines)


def test_utf8_truncation_positions(tmp_path):
    char2 = "¢".encode("utf-8")  # c2 a2
    char3 = "中".encode("utf-8")  # e4 b8 ad
    char4 = "😀".encode("utf-8")  # f0 9f 98 80
    for blob, cut in (
        (char2, 1),
        (char3, 1),
        (char3, 2),
        (char4, 1),
        (char4, 2),
        (char4, 3),
    ):
        raw = b"x" * 100 + blob
        probe = raw[: 100 + cut]
        assert detect_encoding(probe) == "utf-8", (blob, cut)


def test_gbk_boundary_and_roundtrip(tmp_path):
    text = "08-11 16:11:27.391  5636  5636 D DrivingTextManager: 队列为空\n"
    raw = text.encode("gbk")
    p = tmp_path / "g.log"
    p.write_bytes(raw)
    parsed = load_log(p, encoding="gbk")
    assert "队列为空" in parsed.events[0].message
    # truncated last GBK byte of a probe of the raw file should not force utf-8 misread of a GBK-only body
    # when the sample contains invalid UTF-8 in the middle:
    gbk_body = ("测" * 20).encode("gbk")
    assert detect_encoding(gbk_body) == "gbk"


def test_chunk_boundary_multibyte(tmp_path):
    prefix = b"a" * (64 * 1024 - 1)
    raw = prefix + "中".encode("utf-8") + b"\n"
    p = tmp_path / "chunk.log"
    p.write_bytes(raw)
    stream = LineStream(p, repair=False, chunk_size=64 * 1024)
    lines = list(stream)
    assert any("中" in t for _, t in lines)


def test_true_eof_truncation_is_recorded(tmp_path):
    p = tmp_path / "eof.log"
    p.write_bytes(b"hello " + b"\xe4\xb8")  # truncated 中
    stream = LineStream(p, repair=False)
    list(stream)
    assert stream.encoding == "utf-8"
    assert stream.incomplete_eof is True


def test_ascii_head_utf8_tail(tmp_path):
    p = tmp_path / "late.log"
    p.write_bytes(b"ok\n" + "中文队列为空\n".encode("utf-8"))
    parsed = load_log(p)
    assert parsed.meta["encoding"].startswith("utf-8")
    assert any("队列为空" in e.message for e in parsed.events)


def test_mojibake_still_repaired(tmp_path):
    # UTF-8 队列为空 misread as GBK then stored as UTF-8 characters
    damaged = "队列为空".encode("utf-8").decode("gbk")
    p = tmp_path / "moji.log"
    p.write_text(f"08-11 16:11:27.391  5636  5636 D DrivingTextManager: {damaged}\n", encoding="utf-8")
    parsed = load_log(p)
    assert any("队列为空" in (e.message or "") for e in parsed.events)


def test_explicit_encoding_overrides(tmp_path):
    text = "08-11 16:11:27.391  5636  5636 D DrivingTextManager: 队列为空\n"
    p = tmp_path / "e.log"
    p.write_bytes(text.encode("gbk"))
    parsed = load_log(p, encoding="gbk")
    assert parsed.events[0].message.endswith("队列为空")
