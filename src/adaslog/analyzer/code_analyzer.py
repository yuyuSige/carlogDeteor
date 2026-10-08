"""Read-only source mapping: stack frames / tags -> .kt/.java/.xml snippets.

Never writes into the source tree. Flavor source sets are all searched;
ambiguous hits are listed as candidates, not guessed.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from adaslog.models import CodeHit, Evidence, LogEvent

_SKIP_DIR = {".git", "build", ".gradle", ".idea", "__pycache__", "out"}
_RISK = [
    (re.compile(r"!!"), "unchecked_not_null"),
    (re.compile(r"lateinit\s+var"), "lateinit"),
    (re.compile(r"as\s+[A-Z]\w+"), "unsafe_cast"),
    (re.compile(r"RemoteException|DeadObjectException|binderDied|linkToDeath"), "binder_call"),
    (re.compile(r"Handler\(|Handler\s*\{"), "handler"),
    (re.compile(r"launch\s*\{|async\s*\{|viewModelScope|Coroutine"), "coroutine"),
    (re.compile(r"StateFlow|MutableStateFlow"), "stateflow"),
    (re.compile(r"addTransition|handleEvent|IllegalTransition"), "state_machine"),
    (re.compile(r"NO_TEXT|addTextToQueue|removeTextFromQueue"), "driving_text"),
]


def _iter_sources(root: Path, extensions: set[str]) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR]
        for name in filenames:
            if Path(name).suffix.lower() in extensions:
                out.append(Path(dirpath) / name)
    return out


def _index(files: list[Path]) -> dict[str, list[Path]]:
    idx: dict[str, list[Path]] = {}
    for f in files:
        idx.setdefault(f.name, []).append(f)
        idx.setdefault(f.stem, []).append(f)
    return idx


def _snippet(path: Path, lineno: int | None, radius: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    if not lineno:
        # first 12 non-empty lines
        body = [ln for ln in lines[:40] if ln.strip()][:12]
        return "\n".join(body)
    i = max(1, lineno - radius)
    j = min(len(lines), lineno + radius)
    out = []
    for n in range(i, j + 1):
        mark = ">" if n == lineno else " "
        out.append(f"{mark}{n:5d}| {lines[n - 1]}")
    return "\n".join(out)


def _risks(text: str) -> list[str]:
    return [name for rx, name in _RISK if rx.search(text)]


def analyze_code(
    events: list[LogEvent],
    evidence: list[Evidence],
    source_dir: str | Path | None,
    cfg: dict | None = None,
    max_hits: int = 12,
) -> list[CodeHit]:
    if not source_dir:
        return []
    root = Path(source_dir)
    if not root.exists() or not root.is_dir():
        return []
    code_cfg = (cfg or {}).get("code", {})
    exts = set(code_cfg.get("extensions") or [".kt", ".java", ".xml"])
    radius = int(code_cfg.get("snippet_radius", 8))
    max_hits = int(code_cfg.get("max_hits", max_hits))

    files = _iter_sources(root, exts)
    idx = _index(files)
    hits: list[CodeHit] = []
    seen: set[tuple] = set()

    def add(path: Path, line: int | None, symbol: str, how: str, ev_ids: list[str], alts: list[str]) -> None:
        key = (str(path), line, symbol)
        if key in seen or len(hits) >= max_hits:
            return
        seen.add(key)
        snip = _snippet(path, line, radius)
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = str(path)
        hits.append(
            CodeHit(
                file=rel,
                line=line,
                symbol=symbol,
                snippet=snip[:2000],
                risk_patterns=_risks(snip),
                evidence_ids=ev_ids,
                how_found=how,
                candidates=alts,
            )
        )

    # 1) stack frames
    for ev in events:
        frames = ev.extra.get("frames") or []
        app = ev.extra.get("app_frame")
        if app and app not in frames:
            frames = [app] + frames
        ev_ids = [e.id for e in evidence if e.event_id == ev.id]
        for fr in frames[:4]:
            fname = fr.get("file")
            cands = idx.get(fname, []) if fname else []
            if not cands:
                # try class simple name
                simple = (fr.get("class") or "").rsplit(".", 1)[-1]
                cands = idx.get(simple + ".kt", []) or idx.get(simple, [])
            if not cands:
                continue
            rels = []
            for pth in cands:
                try:
                    rels.append(str(pth.relative_to(root)))
                except ValueError:
                    rels.append(str(pth))
            how = "ambiguous" if len(cands) > 1 else "stack_frame"
            add(
                cands[0],
                fr.get("line"),
                f"{fr.get('class','')}.{fr.get('method','')}",
                how,
                ev_ids,
                rels[1:],
            )

    # 2) tags of key evidence
    for evd in evidence:
        ev = next((e for e in events if e.id == evd.event_id), None)
        if ev is None or not ev.tag:
            continue
        for name in ev.extra.get("tag_candidates") or [ev.tag]:
            cands = idx.get(name + ".kt", []) or idx.get(name, [])
            if cands:
                how = "ambiguous" if len(cands) > 1 else "tag_class"
                add(cands[0], None, name, how, [evd.id], [str(p) for p in cands[1:]])
                break

    return hits
