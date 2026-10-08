"""Replaceable LLM provider interface.

Default is the offline RuleBasedProvider. OpenAI-compatible and Anthropic adapters
read keys only from the environment / .env — never from source.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResult:
    candidates: list[dict[str, Any]] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    raw: str = ""
    provider: str = "rule"
    status: str = "ok"  # ok | skipped | fallback | error
    error: str = ""


class LLMProvider(ABC):
    name = "base"

    @abstractmethod
    def reason(self, bundle: dict[str, Any]) -> LLMResult:
        """Return candidates that may only cite evidence ids present in the bundle."""


def get_provider(name: str | None, cfg: dict | None = None) -> LLMProvider:
    cfg = cfg or {}
    chosen = (name or cfg.get("llm", {}).get("provider") or "rule").lower()
    if chosen in ("rule", "rule_based", "offline", ""):
        from adaslog.llm.rule_based import RuleBasedProvider

        return RuleBasedProvider()
    if chosen in ("openai", "openai_compat", "deepseek", "qwen"):
        from adaslog.llm.openai_compat import OpenAICompatibleProvider

        return OpenAICompatibleProvider(cfg)
    if chosen in ("anthropic", "claude"):
        from adaslog.llm.anthropic import AnthropicProvider

        return AnthropicProvider(cfg)
    from adaslog.llm.rule_based import RuleBasedProvider

    return RuleBasedProvider()
