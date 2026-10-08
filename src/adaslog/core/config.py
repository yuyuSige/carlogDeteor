"""Configuration loading: config/default.json + optional user override + .env.

No secrets are stored in source. API keys come from environment variables or a .env
file in the project root (loaded here without external dependencies).
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = PROJECT_ROOT / "config"
RULES_DIR = CONFIG_DIR / "rules"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "default.json"


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Minimal .env loader. Existing environment variables take precedence."""
    path = path or (PROJECT_ROOT / ".env")
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


def load_config(user_config: str | Path | None = None) -> dict[str, Any]:
    with DEFAULT_CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = json.load(f)
    if user_config:
        with Path(user_config).open(encoding="utf-8") as f:
            cfg = _deep_merge(cfg, json.load(f))
    load_dotenv()
    # environment overrides for the LLM layer
    if os.environ.get("LLM_PROVIDER"):
        cfg.setdefault("llm", {})["provider"] = os.environ["LLM_PROVIDER"]
    if os.environ.get("LLM_TIMEOUT"):
        try:
            cfg.setdefault("llm", {})["timeout"] = int(os.environ["LLM_TIMEOUT"])
        except ValueError:
            pass
    return cfg
