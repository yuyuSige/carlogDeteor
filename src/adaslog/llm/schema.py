"""Shared validation of remote LLM JSON (OpenAI-compatible and Anthropic)."""
from __future__ import annotations

from typing import Any

from adaslog.core.errors import LLMProviderError
from adaslog.llm.provider import LLMResult


def as_unknown_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise LLMProviderError(f"unknowns must be a list of strings or null, got {type(value).__name__}")
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise LLMProviderError(f"unknowns[{i}] must be a string, got {type(item).__name__}")
        out.append(item)
    return out


def as_candidate_list(value: Any) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise LLMProviderError(f"candidates must be a list or null, got {type(value).__name__}")
    return value


def llm_result_from_parsed(parsed: Any, *, provider: str, raw: str) -> LLMResult:
    if not isinstance(parsed, dict):
        raise LLMProviderError("model JSON must be an object")
    return LLMResult(
        candidates=as_candidate_list(parsed.get("candidates")),
        unknowns=as_unknown_list(parsed.get("unknowns")),
        raw=raw,
        provider=provider,
        status="ok",
    )


def openai_message_content(body: Any) -> str:
    if not isinstance(body, dict):
        raise LLMProviderError("OpenAI response body must be an object")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMProviderError("OpenAI response missing choices[]")
    first = choices[0]
    if not isinstance(first, dict):
        raise LLMProviderError("OpenAI choices[0] must be an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise LLMProviderError("OpenAI message must be an object")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMProviderError("OpenAI message content must be a non-empty string")
    return content


def anthropic_message_text(body: Any) -> str:
    if not isinstance(body, dict):
        raise LLMProviderError("Anthropic response body must be an object")
    content = body.get("content")
    if content is None:
        content = []
    if not isinstance(content, list):
        raise LLMProviderError("Anthropic content must be a list")
    parts: list[str] = []
    for i, item in enumerate(content):
        if not isinstance(item, dict):
            raise LLMProviderError(f"Anthropic content[{i}] must be an object")
        if item.get("type") == "text":
            text = item.get("text")
            if text is None:
                continue
            if not isinstance(text, str):
                raise LLMProviderError(f"Anthropic content[{i}].text must be a string")
            parts.append(text)
    joined = "".join(parts)
    if not joined.strip():
        raise LLMProviderError("Anthropic message text is empty")
    return joined
