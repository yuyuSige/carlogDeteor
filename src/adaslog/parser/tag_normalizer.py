"""Tag normalisation, module derivation and pid -> process resolution.

E02 specifics (verified against source, read-only):
  * AppLogger prefixes tags with "IVI_ADAS_APP_" and truncates to 23 chars
    -> "IVI_ADAS_APP_StateMachi" really is "StateMachine".
  * common_protocol uses prefix "IVI_ADAS_".
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from adaslog.core.config import load_json_resource
from adaslog.models import LogEvent

RX_START_PROC = re.compile(r"Start proc (\d+):([\w.:$]+)/")
RX_PROC_DIED = re.compile(r"Process ([\w.:$]+) \(pid (\d+)\) has died")
RX_PKG_IN_FRAME = re.compile(r"((?:[a-z][\w]*\.){2,}[a-z_][\w]*)\.[A-Z]\w*")


class TagNormalizer:
    def __init__(self, modules_file: Path | None = None):
        if modules_file:
            data = json.loads(Path(modules_file).read_text(encoding="utf-8")) if Path(modules_file).exists() else {}
        else:
            try:
                data = load_json_resource("rules/e02_modules.json")
            except FileNotFoundError:
                data = {}
        self.prefixes: list[str] = sorted(data.get("tag_prefixes", []), key=len, reverse=True)
        self.max_len: int = data.get("max_tag_length", 23)
        self.known_tags: list[str] = data.get("known_tags", [])
        self.tag_to_module: dict[str, str] = data.get("tag_to_module", {})
        self.package_to_module: dict[str, str] = data.get("package_to_module", {})
        self._pkg_keys = sorted(self.package_to_module, key=len, reverse=True)
        self.pid_to_process: dict[int, str] = {}

    # -- tag ---------------------------------------------------------------
    def tag_candidates(self, raw_tag: str | None) -> list[str]:
        """Possible full tags for a (possibly truncated / prefixed) raw tag, shortest first."""
        if raw_tag is None:
            return []
        tag = raw_tag.strip()
        truncated = len(tag) >= self.max_len
        for p in self.prefixes:
            if tag.startswith(p):
                tag = tag[len(p):]
                break
        if not tag:
            return []
        if truncated:
            cands = sorted((k for k in self.known_tags if k.startswith(tag)), key=len)
            if cands:
                return cands
        return [tag]

    def normalize_tag(self, raw_tag: str | None) -> str | None:
        cands = self.tag_candidates(raw_tag)
        return cands[0] if cands else None

    def module_for_tag(self, tag: str | None) -> str | None:
        if not tag:
            return None
        t = tag
        if t in self.tag_to_module:
            return self.tag_to_module[t]
        for key, mod in self.tag_to_module.items():
            if key.lower() in t.lower():
                return mod
        return None

    def module_for_package(self, text: str) -> str | None:
        for key in self._pkg_keys:
            if key in text:
                return self.package_to_module[key]
        return None

    # -- process -----------------------------------------------------------
    def learn_processes(self, events: list[LogEvent]) -> None:
        for ev in events:
            m = RX_START_PROC.search(ev.message)
            if m:
                self.pid_to_process[int(m.group(1))] = m.group(2)
                continue
            m = RX_PROC_DIED.search(ev.message)
            if m:
                self.pid_to_process.setdefault(int(m.group(2)), m.group(1))
            if ev.extra.get("process") and ev.pid is not None:
                self.pid_to_process.setdefault(ev.pid, ev.extra["process"])

    # -- apply -------------------------------------------------------------
    def apply(self, events: list[LogEvent]) -> None:
        self.learn_processes(events)
        for ev in events:
            cands = self.tag_candidates(ev.raw_tag)
            ev.tag = cands[0] if cands else None
            if len(cands) > 1:
                ev.extra["tag_candidates"] = cands
            if ev.pid is not None and ev.pid in self.pid_to_process:
                ev.process = self.pid_to_process[ev.pid]
            mod = self.module_for_tag(ev.tag)
            if mod is None and ev.extra.get("app_frame"):
                mod = self.module_for_package(ev.extra["app_frame"]["class"])
            if mod is None and ev.has_stacktrace:
                mod = self.module_for_package(" ".join(ev.stacktrace[:6]))
            if mod is None and ev.process:
                mod = self.module_for_package(ev.process)
            ev.module = mod
