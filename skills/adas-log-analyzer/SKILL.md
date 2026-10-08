---
name: adas-log-analyzer
description: Evidence-first ADAS Android log analysis and root-cause diagnosis. Use when the user provides logcat/.log/.txt, asks why a crash/ANR/Binder/state/text prompt failed, or wants a structured ADAS analysis report.
---

# ADAS Log Analyzer Skill

## 1. Skill Description

Analyze ADAS / Android logs (Logcat, module logs, Binder/IPC, exception stacks, VDS signal dumps) and produce an **Evidence First** report. The executable pipeline is `adaslog` (`src/adaslog`). This Skill tells the agent **when** and **how** to run it and how to interpret the JSON.

## 2. Trigger Conditions

- User attaches or points to a `.log` / `.txt` / logcat dump
- User asks 根因 / 为什么没弹文言 / Binder / 状态机 / crash / ANR
- User mentions E02 / IVI ADAS / DrivingText / signal stayed 0

## 3. When to Use

- Offline diagnosis of a single log (MVP)
- Optional `--source D:\E02_adas` for read-only code context
- Optional `--focus-signal FcwAcitveSt,AebAcitveSt` and `--time-range 16:11:00-16:12:00`

## 4. When Not to Use

- Do **not** modify E02 (or any) business code
- Do **not** git commit / push / Gerrit / auto-fix / delete files
- Do **not** invent a root cause when the report says UNKNOWN
- Do **not** treat signal=0 + empty text queue as a DrivingTextManager bug

## 5. Input Format

```text
adaslog analyze <log>
    [--source DIR]          # read-only .kt/.java/.xml
    [--format md|json|txt|all]
    [--out DIR]
    [--llm rule|openai|anthropic]   # default rule (offline)
    [--focus-signal F1,F2]
    [--time-range HH:MM:SS-HH:MM:SS]
    [--question TEXT]
```

Switch LLM later without code changes: copy `.env.example` → `.env`, set `LLM_PROVIDER=openai` and `OPENAI_API_KEY` / `OPENAI_BASE_URL`, then `--llm openai`.

## 6. Output Format

报告（md/txt）使用中文章节；JSON 中 issue_type 等枚举仍为英文。11 节：

```text
1. 问题类型  2. 严重程度  3. 摘要  4. 关键证据
5. 事件时间线  6. 可能根因  7. 置信度
8. 相关模块  9. 相关代码  10. 排查建议
11. 未知 / 缺失信息
```

Labels: **Fact / Evidence / Hypothesis / Recommendation / Unknown**.

## 7. Workflow

1. Load Level 2 `references/` only if the symptom needs domain rules (Binder / state / signal-text).
2. Run Level 3 `scripts/analyze_log.py` (same code as CLI). Prefer `--format json`.
3. Quote evidence ids (E1…) from the JSON. Do not add uncited claims.
4. If `issue_type == NORMAL`, do not invent a root cause.
5. If `issue_type == UNKNOWN` or candidates have `status=UNKNOWN`, say so.

## 8. Log Analysis Rules

- Parse threadtime / time / brief / custom / generic lines; merge stacks.
- Tags may be prefixed `IVI_ADAS_APP_` and truncated to 23 chars.
- Sample logs may be UTF-16 with GBK-mojibake Chinese; the parser repairs this.
- Issue types: CRASH, EXCEPTION, BINDER_IPC, STATE_MACHINE, MODULE_COMMUNICATION,
  SYSTEM_ERROR, BUSINESS_ERROR, ANR, PERFORMANCE, SIGNAL_NOT_TRIGGERED, NORMAL, UNKNOWN.

## 9. Evidence First Rules

Every Hypothesis must cite existing evidence ids. Uncited claims are dropped or become UNKNOWN.

## 10. Root Cause Rules

Prefer: log fact → evidence → (optional code hit) → candidate + confidence + need-verification.

Domain rule (E02 `driving_text_tip` Profile, read-only):

> If a mapped signal stays **0** in the window, Profile returns `NO_TEXT` and DrivingTextManager does **not** queue that prompt. This is expected, not a text-manager defect. If the user expected a prompt, look at the **publisher** (VDS / SOME-IP), not the queue.

## 11. Confidence Rules

- HIGH: stack + module, or signal=0 plus text-idle, with consistent timeline
- MEDIUM: pattern match without code / publisher confirmation
- LOW / UNKNOWN: single ERROR, no stack, no module, no signal context

## 12. Negative Control Rules

- Healthy start/connect/complete logs → `NORMAL`, no root-cause section
- `ERROR something happened` alone → `UNKNOWN` + `Insufficient evidence.`
- Never hallucinate a file:line that is not in the log or `--source` hit

## 13. Error Handling

- Missing file → tell the user, do not invent content
- LLM API missing/failing → pipeline already falls back to `--llm rule`
- Huge full-system logcat → require `--time-range` and/or `--focus-signal`

## 14. Examples

See `references/examples.md`. Real sample: `c:\Users\TS\Desktop\1611.log` (UTF-16, ~16:11 window, Fcw/Aeb = 0 → no 文言).
