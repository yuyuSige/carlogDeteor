"""OpenAI-compatible Chat Completions adapter (OpenAI / DeepSeek / Qwen / vLLM).

No SDK. Keys from OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL only.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from adaslog.core.errors import LLMProviderError
from adaslog.llm.prompts import SYSTEM, user_payload
from adaslog.llm.provider import LLMProvider, LLMResult


class OpenAICompatibleProvider(LLMProvider):
    name = "openai"

    def __init__(self, cfg: dict | None = None):
        llm = (cfg or {}).get("llm", {})
        self.api_key = os.environ.get("OPENAI_API_KEY") or llm.get("openai_api_key") or ""
        self.base_url = (os.environ.get("OPENAI_BASE_URL") or llm.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self.model = os.environ.get("OPENAI_MODEL") or llm.get("model") or "gpt-4o-mini"
        self.timeout = int(os.environ.get("LLM_TIMEOUT") or llm.get("timeout") or 60)

    def reason(self, bundle: dict[str, Any]) -> LLMResult:
        if not self.api_key:
            raise LLMProviderError("OPENAI_API_KEY is not set; use --llm rule or set the key in .env")
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_payload(_public_bundle(bundle))},
            ],
        }
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise LLMProviderError(f"OpenAI-compatible HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise LLMProviderError(f"OpenAI-compatible network error: {exc.reason}") from exc
        text = body["choices"][0]["message"]["content"]
        parsed = _parse_json_block(text)
        return LLMResult(
            candidates=parsed.get("candidates") or [],
            unknowns=parsed.get("unknowns") or [],
            raw=text,
            provider="openai",
            status="ok",
        )


def _public_bundle(bundle: dict) -> dict:
    return {k: v for k, v in bundle.items() if not str(k).startswith("_")}


def _parse_json_block(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)
