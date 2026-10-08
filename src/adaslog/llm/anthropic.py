"""Anthropic Messages API adapter. Keys from ANTHROPIC_API_KEY / ANTHROPIC_MODEL only."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from adaslog.core.errors import LLMProviderError
from adaslog.llm.prompts import SYSTEM, user_payload
from adaslog.llm.openai_compat import _parse_json_block, _public_bundle
from adaslog.llm.provider import LLMProvider, LLMResult
from adaslog.llm.schema import anthropic_message_text, llm_result_from_parsed


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, cfg: dict | None = None):
        llm = (cfg or {}).get("llm", {})
        self.api_key = os.environ.get("ANTHROPIC_API_KEY") or llm.get("anthropic_api_key") or ""
        self.model = os.environ.get("ANTHROPIC_MODEL") or llm.get("anthropic_model") or "claude-3-5-sonnet-latest"
        self.timeout = int(os.environ.get("LLM_TIMEOUT") or llm.get("timeout") or 60)
        self.base_url = (os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")

    def reason(self, bundle: dict[str, Any]) -> LLMResult:
        if not self.api_key:
            raise LLMProviderError("ANTHROPIC_API_KEY is not set; use --llm rule or set the key in .env")
        payload = {
            "model": self.model,
            "max_tokens": 2048,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": user_payload(_public_bundle(bundle))}],
        }
        req = urllib.request.Request(
            self.base_url + "/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw_body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise LLMProviderError(f"Anthropic HTTP {exc.code}: {exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMProviderError(f"Anthropic network error: {exc}") from exc
        try:
            body = json.loads(raw_body)
            text = anthropic_message_text(body)
            parsed = _parse_json_block(text)
            return llm_result_from_parsed(parsed, provider="anthropic", raw=text)
        except LLMProviderError:
            raise
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMProviderError(f"Anthropic malformed response: {exc}") from exc
