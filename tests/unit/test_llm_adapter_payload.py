import json

from adaslog.core.errors import LLMProviderError
from adaslog.core.pipeline import run_analysis
from adaslog.llm.anthropic import AnthropicProvider
from adaslog.llm.openai_compat import OpenAICompatibleProvider


class _Resp:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8") if not isinstance(payload, bytes) else payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._raw


def _crash_log(tmp_path):
    p = tmp_path / "c.log"
    p.write_text(
        "08-11 16:09:14.790  4577  4577 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-11 16:09:14.790  4577  4577 E AndroidRuntime: java.lang.NullPointerException: x\n"
        "08-11 16:09:14.790  4577  4577 E AndroidRuntime: \tat com.chery.ivi.adas.A.foo(A.kt:1)\n",
        encoding="utf-8",
    )
    return p


def test_openai_unknowns_int_raises_provider_error(monkeypatch):
    provider = OpenAICompatibleProvider({"llm": {}})
    provider.api_key = "sk-test"
    inner = json.dumps({"candidates": [], "unknowns": 42})
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _Resp({"choices": [{"message": {"content": inner}}]}),
    )
    try:
        provider.reason({"issue_type": "CRASH", "evidence": []})
        assert False, "expected LLMProviderError"
    except LLMProviderError as exc:
        assert "unknowns" in str(exc).lower()


def test_openai_choices_missing_is_provider_error(monkeypatch):
    provider = OpenAICompatibleProvider({"llm": {}})
    provider.api_key = "sk-test"
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp({"hello": 1}))
    try:
        provider.reason({"issue_type": "CRASH", "evidence": []})
        assert False
    except LLMProviderError:
        pass


def test_anthropic_content_not_object_is_provider_error(monkeypatch):
    provider = AnthropicProvider({"llm": {}})
    provider.api_key = "sk-test"
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp({"content": ["not-an-object"]}))
    try:
        provider.reason({"issue_type": "CRASH", "evidence": []})
        assert False
    except LLMProviderError:
        pass


def test_pipeline_unknowns_int_falls_back_not_typeerror(monkeypatch, tmp_path):
    inner = json.dumps({"candidates": [], "unknowns": 42})

    def fake_open(*a, **k):
        return _Resp({"choices": [{"message": {"content": inner}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    p = _crash_log(tmp_path)
    result = run_analysis(p, formats=["json"], out_dir=tmp_path / "out", llm_provider="openai", progress=False)
    assert result["report"].issue_type == "CRASH"
    assert "fallback" in str(result["report"].meta.get("llm_status"))
    assert result["report"].meta.get("llm_error")
    assert result["report"].root_causes


def test_unknowns_string_does_not_split_chars(monkeypatch):
    provider = OpenAICompatibleProvider({"llm": {}})
    provider.api_key = "sk-test"
    inner = json.dumps({"candidates": [], "unknowns": "not-a-list"})
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _Resp({"choices": [{"message": {"content": inner}}]}),
    )
    try:
        provider.reason({"issue_type": "CRASH", "evidence": []})
        assert False
    except LLMProviderError as exc:
        assert "unknowns" in str(exc).lower()
