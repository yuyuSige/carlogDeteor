"""adaslog command line interface.

  adaslog version
  adaslog parse   <log> [--time-range HH:MM:SS-HH:MM:SS] [--pid N] [--json out.json] [--stats]
  adaslog analyze <log> [--source DIR] [--format md|json|txt|all] [--out DIR] [--llm rule|openai|anthropic]
                        [--focus-signal F1,F2] [--time-range ...] [--pid N] [--question TEXT]
  adaslog run-tests [--cases DIR] [--results DIR]
  adaslog metrics   [--results DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from adaslog import __version__


def _ensure_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def cmd_version(_: argparse.Namespace) -> int:
    print(f"adaslog {__version__} (python {sys.version.split()[0]})")
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    from adaslog.parser import load_log

    parsed = load_log(args.log, time_range=args.time_range, pid=args.pid, encoding=getattr(args, "encoding", None))
    ev = parsed.events
    print(json.dumps(parsed.meta, ensure_ascii=False, indent=2))
    if args.stats:
        lv = Counter(e.level or "?" for e in ev)
        tags = Counter(e.tag or "?" for e in ev)
        mods = Counter(e.module or "?" for e in ev)
        print("levels:", dict(lv))
        print("top tags:", tags.most_common(15))
        print("modules:", mods.most_common(15))
        print("events with stacktrace:", sum(1 for e in ev if e.has_stacktrace))
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            json.dump([_event_dict(e) for e in ev], f, ensure_ascii=False, indent=1)
        print(f"events written: {out}")
    if args.show:
        for e in ev[: args.show]:
            print(e.short())
    return 0


def _event_dict(e) -> dict:
    return {
        "id": e.id, "line_no": e.line_no, "timestamp": e.timestamp, "level": e.level, "tag": e.tag,
        "raw_tag": e.raw_tag, "pid": e.pid, "tid": e.tid, "process": e.process, "module": e.module,
        "message": e.message, "stacktrace": e.stacktrace, "extra": e.extra,
    }


def cmd_analyze(args: argparse.Namespace) -> int:
    from adaslog.core.pipeline import run_analysis

    focus = [s.strip() for s in args.focus_signal.split(",")] if args.focus_signal else None
    result = run_analysis(
        log_path=args.log,
        source_dir=args.source,
        formats=["md", "json", "txt"] if args.format == "all" else [args.format],
        out_dir=args.out,
        llm_provider=args.llm,
        focus_signals=focus,
        time_range=args.time_range,
        pid=args.pid,
        question=args.question,
        config_path=args.config,
        progress=not getattr(args, "no_progress", False),
        encoding=getattr(args, "encoding", None),
    )
    for path in result["outputs"]:
        print(f"报告: {path}")
    rep = result["report"]
    from adaslog.report.labels import issue as issue_zh, severity as sev_zh, confidence as conf_zh
    print(
        f"问题类型={issue_zh(rep.issue_type)} 严重程度={sev_zh(rep.severity)} "
        f"分类置信度={conf_zh(rep.classification_confidence or rep.confidence)} "
        f"根因置信度={conf_zh(rep.root_cause_confidence or rep.confidence)} run_id={rep.run_id}"
    )
    if args.print:
        print(result["rendered"].get("txt") or result["rendered"].get("md") or "")
    return 0


def cmd_run_tests(args: argparse.Namespace) -> int:
    from adaslog.testing.runner import run_cases

    summary = run_cases(cases_dir=args.cases, results_dir=args.results, source_dir=args.source)
    print(f"passed {summary['passed']}/{summary['total']}  -> {summary['results_md']}")
    return 0 if summary["failed"] == 0 else 1


def cmd_metrics(args: argparse.Namespace) -> int:
    from adaslog.testing.metrics import compute_metrics

    m = compute_metrics(results_dir=args.results, cases_dir=getattr(args, "cases", None))
    print(json.dumps(m, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="adaslog", description="ADAS Android log analysis (Evidence First)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("version", help="print version")
    s.set_defaults(func=cmd_version)

    s = sub.add_parser("parse", help="parse a log into structured events")
    s.add_argument("log")
    s.add_argument("--time-range", help="HH:MM:SS-HH:MM:SS (clock of day)")
    s.add_argument("--pid", type=int)
    s.add_argument("--encoding", help="force log encoding (utf-8, utf-16-le, gbk, ...)")
    s.add_argument("--json", help="write events as JSON to this file")
    s.add_argument("--stats", action="store_true")
    s.add_argument("--show", type=int, default=0, help="print first N events")
    s.set_defaults(func=cmd_parse)

    s = sub.add_parser("analyze", help="run the full analysis pipeline")
    s.add_argument("log")
    s.add_argument("--source", help="source directory (.kt/.java/.xml) for code context, read-only")
    s.add_argument("--format", default="md", choices=["md", "json", "txt", "all"])
    s.add_argument("--out", help="output directory (default: reports/)")
    s.add_argument("--llm", default=None, choices=["rule", "openai", "anthropic"], help="LLM provider（省略则用配置/.env，默认 rule）")
    s.add_argument("--no-progress", action="store_true", help="do not print progress to stderr")
    s.add_argument("--focus-signal", help="comma separated signal field names, e.g. FcwAcitveSt,AebAcitveSt")
    s.add_argument("--time-range", help="HH:MM:SS-HH:MM:SS")
    s.add_argument("--pid", type=int, help="restrict analysis to this pid (system lines are kept)")
    s.add_argument("--question", help="the user's question / symptom, recorded in the report")
    s.add_argument("--config", help="user config JSON merged over config/default.json")
    s.add_argument("--encoding", help="force log encoding (utf-8, utf-16-le, gbk, ...)")
    s.add_argument("--print", action="store_true", help="print the report to stdout as well")
    s.set_defaults(func=cmd_analyze)

    s = sub.add_parser("run-tests", help="run tests/cases and write tests/results")
    s.add_argument("--cases", default=None)
    s.add_argument("--results", default=None)
    s.add_argument("--source", default=None, help="optional source dir for cases that reference code")
    s.set_defaults(func=cmd_run_tests)

    s = sub.add_parser("metrics", help="compute metrics from tests/results")
    s.add_argument("--results", default=None)
    s.add_argument("--cases", default=None, help="golden cases dir used to resolve expected.json")
    s.set_defaults(func=cmd_metrics)
    return p


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # surface a clean error, keep traceback for --debug via env
        import os, traceback
        if os.environ.get("ADASLOG_DEBUG"):
            traceback.print_exc()
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
