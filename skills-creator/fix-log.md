# Fix Log

Chronological record of problems found while building the analyzer, their root cause, the fix and how it was verified.

---

## 2026-10-08 — Real sample log unreadable (all searches returned 0 matches)

Problem:
`c:\Users\TS\Desktop\1611.log` (173 MB) decoded as UTF-8 failed at byte 0 (`0xff`); every content search returned nothing.

Root Cause:
The file is UTF-16 LE with BOM. Additionally the Chinese text inside is "double encoded": the original UTF-8 logcat
output was interpreted as GBK and then re-saved as UTF-16, so `队列为空` appears as `闃熷垪涓虹┖`.

Fix:
`src/adaslog/utils/io.py`: BOM-based decoding (UTF-8-sig / UTF-16 LE/BE / GBK fallback) plus a sampled heuristic that
detects double-encoded text and repairs it line by line with `encode('gbk').decode('utf-8')`, tolerating lossy lines
(`?` already replaced some bytes) with `errors='replace'`.

Verification:
`adaslog parse 1611.log` reports `encoding=utf-16-le`, `mojibake_repaired=true`, `repaired_lines=5241`; the
`DrivingTextManager` lines read `队列为空且无当前显示，等待新文言触发`. Unit test `test_mojibake_repair` passes.

---

## 2026-10-08 — Mojibake heuristic missed the sample (`mojibake_repaired=false`)

Problem:
First version of the heuristic only counted lines that could be repaired losslessly; on the sample only 44 % of CJK lines
repaired strictly (the rest had `?` substitutions), under the 50 % threshold.

Root Cause:
Lossy lines were not counted as repairable.

Fix:
Count lossy repairs when the result still contains plausible CJK / box-drawing characters and few replacement chars.

Verification:
`repaired_lines` went from 0 to 5241; `test_mojibake_repair` and `test_process_resolution` pass.

---

## 2026-10-08 — Truncated tag ambiguity (`IVI_ADAS_APP_StateMachi`)

Problem:
Logcat truncates tags to 23 chars; `StateMachi` matches both `StateMachine` and `StateMachineManager`.

Root Cause:
First implementation returned `StateMachine~` (marker suffix) which broke module mapping and tests.

Fix:
`TagNormalizer.tag_candidates()` returns all candidates; the shortest becomes `event.tag`, the full list is kept in
`event.extra["tag_candidates"]` so the report can show the ambiguity instead of hiding it.

Verification:
`test_tag_normalizer_prefix_and_truncation` passes; module for the event resolves to `statemachine`.

---

## 2026-10-08 — User inputs received; pipeline completed

Problem:
Need a runnable analyzer that explains `1611.log`: when a signal stays 0, the corresponding driving-text prompt is not shown. LLM credentials are not required yet.

Root Cause:
`driving_text_tip` Profile maps idle/0 to `NO_TEXT`; handlers only `addTextToQueue` for a non-`NO_TEXT` id.

Fix:
Implemented detector/classifier/extractor/signal timeline/`LLMProvider` (default rule, OpenAI/Anthropic adapters)/report/Skill. Domain rule encoded in `config/rules/signal_text.json` and `context/signals.py`.

Verification:
`pytest tests/unit` 13 passed; `adaslog run-tests` 8/8; `1611_adas_slice.log` → `SIGNAL_NOT_TRIGGERED` HIGH, Fcw/Aeb=0 (108 samples), DrivingTextManager idle x28, trigger=0.

---

## 2026-10-08 — Kanzi rule over-classified exception_case

Problem:
`exception_case_01` mentioned "Kanzi session init" and was classified MODULE_COMMUNICATION.

Root Cause:
`communication.json` treated any "Kanzi" substring as a failure.

Fix:
Narrowed the rule to disconnect/failure phrases.

Verification:
`exception_case_01` → EXCEPTION; suite 8/8.
