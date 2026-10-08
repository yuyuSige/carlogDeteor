"""Configuration: packaged defaults + optional user overlay + .env.

Installed wheels load JSON via importlib.resources. A user --config file overlays
defaults. Reports are never written into the package directory.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

try:
    from importlib.resources import files as _res_files
except ImportError:  # pragma: no cover
    _res_files = None


def _repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() and (parent / "src" / "adaslog").exists():
            return parent
    return None


PROJECT_ROOT = _repo_root() or Path.cwd()
CONFIG_DIR = PROJECT_ROOT / "config"
RULES_DIR = CONFIG_DIR / "rules"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "default.json"


def default_output_dir() -> Path:
    """Writable location: cwd/reports. Never the installed package dir."""
    return Path.cwd() / "reports"


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_json_resource(relative: str) -> dict[str, Any]:
    """Load packaged JSON (e.g. 'default.json' or 'rules/signal_text.json')."""
    if _res_files is not None:
        try:
            ref = _res_files("adaslog.resources").joinpath(*relative.split("/"))
            if ref.is_file():
                return json.loads(ref.read_text(encoding="utf-8"))
        except (ModuleNotFoundError, FileNotFoundError, OSError):
            pass
    fallback = CONFIG_DIR / relative
    if fallback.exists():
        return json.loads(fallback.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"resource not found: {relative}")


def load_dotenv(path: Path | None = None) -> dict[str, str]:
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
    cfg = load_json_resource("default.json")
    if user_config:
        with Path(user_config).open(encoding="utf-8-sig") as f:
            cfg = _deep_merge(cfg, json.load(f))
    load_dotenv()
    if os.environ.get("LLM_PROVIDER"):
        cfg.setdefault("llm", {})["provider"] = os.environ["LLM_PROVIDER"]
    if os.environ.get("LLM_TIMEOUT"):
        try:
            cfg.setdefault("llm", {})["timeout"] = int(os.environ["LLM_TIMEOUT"])
        except ValueError:
            pass
    return cfg
