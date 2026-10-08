# Proposal — AI-Assisted ADAS Android Log Analysis and Root Cause Diagnosis Skill

## 1. Problem

ADAS Android (IVI) issues arrive as hundreds of MB of mixed logcat: kernel, system_server, the Vehicle Data Service
(VDS) that publishes CAN/SOME-IP signals, and the ADAS app itself (state machine, AVM, parking, driving text/TTS, Kanzi
HMI bridge). Finding *why* a text prompt did not appear, why a Binder service dropped, or which state transition was
illegal takes an engineer 20–60 minutes per log (estimate, see README metrics) and the result depends on who looks.

## 2. Background

The E02 project (`D:\E02_adas`, read-only for this tool) is a Kotlin Android app with 614 Kotlin files, 9 Gradle
modules, a generic `StateMachine<S,E>` (31 states / 23 events), AIDL services (`IAvmSdkService`, Kanzi `IDataService`),
gRPC / SOME-IP / VDBus adapters and a signal-driven driving-text module (`driving_text_tip`). Its logs are bilingual
(Chinese + English), tags are prefixed (`IVI_ADAS_APP_`) and truncated to 23 chars, and exported files are frequently
UTF-16 with double-encoded Chinese.

## 3. Current Pain Point

* Manual grep across processes (signal publisher pid vs. app pid) to correlate cause and effect.
* Encoding damage hides Chinese messages entirely.
* No consistent separation of *fact* vs. *guess*; conclusions are hard to review.
* Knowledge about which tag belongs to which module lives in people's heads.

## 4. Solution

A Python CLI + Claude Code Skill that turns a raw log into a structured, evidence-referenced report:

```
Raw log -> parse (encoding repair, multi-line/stack merge, tag normalisation, pid->process)
        -> anomaly detection (bilingual rule packs) -> classification (type + confidence + evidence)
        -> key evidence extraction -> context & causal chain -> cross-process signal timeline
        -> optional source-code context (read-only) -> root cause candidates (rule-based, LLM optional)
        -> evidence validation -> Markdown / JSON / TXT report
```

Core principle: **Evidence First**. A conclusion without evidence ids is downgraded or becomes `UNKNOWN`.

## 5. Technical Architecture

See `docs/design.md`. Python 3.11, standard library only for the core; JSON rule packs under `config/rules/`;
`LLMProvider` interface with an offline `RuleBasedProvider` default and OpenAI-compatible / Anthropic adapters
(keys via `.env` / env vars only).

## 6. AI Usage

* Deterministic stages (parse, detect, classify, extract, correlate) are done in code — reproducible and testable.
* The reasoning stage builds an *evidence bundle* (ids E1..En) and asks the provider for root-cause candidates that may
  only cite those ids. A validator drops uncited claims. Default provider is rule-based so the tool works offline.
* The Skill (`skills/adas-log-analyzer/SKILL.md`) tells the agent how to run the scripts, how to read the JSON, and
  the rules it must obey (Fact / Evidence / Hypothesis / Recommendation / Unknown; NORMAL and UNKNOWN handling).

## 7. Skill Design

Progressive loading: `SKILL.md` (rules, ~1 screen) → `references/` (Android, Binder, ADAS/E02 knowledge, root-cause
and confidence rules, examples) → `scripts/` (thin wrappers around the same Python package the CLI uses).

## 8. Evaluation Method

* 5 positive + 2 negative golden cases plus the real `1611.log` sample (signal stayed 0 → text not triggered).
* Metrics: classification Accuracy / macro Precision / Recall / F1, key-log Precision / Recall, Evidence Coverage,
  Hallucination Rate, negative-control pass rate, manual-vs-AI time (manual time is an engineer estimate, labelled).

## 9. Expected Benefit

* Minutes instead of tens of minutes to get a reviewable first diagnosis with line-level evidence.
* Consistent vocabulary and module mapping across engineers.
* Negative control prevents "confident nonsense".

## 10. Schedule

| Week | Scope |
|---|---|
| 1 | Init, structure, README, proposal, CLI, log loading & parsing |
| 2 | Anomaly detection, classification, key-log extraction, context |
| 3 | LLM layer, Evidence First, root-cause candidates, confidence, report |
| 4 | Source analysis, Skill, positive/negative cases, midterm |
| 5 | Metrics, tuning, final tests, report, demo, fix-log |
