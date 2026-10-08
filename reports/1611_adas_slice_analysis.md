# ADAS Log Analysis Report

- **Issue Type:** SIGNAL_NOT_TRIGGERED
- **Severity:** MEDIUM
- **Confidence:** HIGH (score=0.783)
- **LLM:** ok / rule

## 1. Issue Type

SIGNAL_NOT_TRIGGERED

Reason: Highest category SIGNAL_NOT_TRIGGERED (score=4.00). User question points to a missing driving-text prompt; signal/text correlation is the primary hypothesis.

## 2. Severity

MEDIUM

## 3. Summary

SIGNAL_NOT_TRIGGERED (confidence 0.783). Key evidence: E1, E2, E3. Candidate: Focus signal stayed at 0 so the corresponding driving-text prompt was not queued (Profile maps idle/0 to NO_TEXT).

## 4. Key Evidence

- **E1** [signal_idle] 08-11 16:11:27.394 L34
  - AdasActiveSafetyFcnInfo.FcwAcitveSt=0 from 08-11 16:11:27.394 to 08-11 16:11:32.067 (108 samples, lines 34-777)
  - Why: Focus signal stayed at idle (0); Profile maps this to NO_TEXT.
- **E2** [signal_idle] 08-11 16:11:27.394 L34
  - AdasActiveSafetyFcnInfo.AebAcitveSt=0 from 08-11 16:11:27.394 to 08-11 16:11:32.067 (108 samples, lines 34-777)
  - Why: Focus signal stayed at idle (0); Profile maps this to NO_TEXT.
- **E3** [text_idle] 08-11 16:11:27.391 L22 x28
  - DrivingTextManager idle x28 (empty queue, waiting for a new prompt).
  - Why: DrivingTextManager reported an empty queue / no current display.

## 5. Event Timeline

- 08-11 16:11:27.391 L22 (E3): text_idle: DrivingTextManager idle x28 (empty queue, waiting for a new prompt).
- 08-11 16:11:27.394 L34 (E1): signal_idle: AdasActiveSafetyFcnInfo.FcwAcitveSt=0 from 08-11 16:11:27.394 to 08-11 16:11:32.067 (108 samples, lines 34-777)
- 08-11 16:11:27.394 L34 (E2): signal_idle: AdasActiveSafetyFcnInfo.AebAcitveSt=0 from 08-11 16:11:27.394 to 08-11 16:11:32.067 (108 samples, lines 34-777)

Causal chain:
- E3 --precedes--> E1
- E1 --precedes--> E2

## 6. Possible Root Causes

### CANDIDATE: Focus signal stayed at 0 so the corresponding driving-text prompt was not queued (Profile maps idle/0 to NO_TEXT).

- Confidence: HIGH
- Evidence: E1, E2, E3
- Reasoning: E02 driving_text_tip handlers only call addTextToQueue when Profile.map*(value) returns a text id. Value 0 maps to NO_TEXT. Observed idle fields: AdasActiveSafetyFcnInfo.FcwAcitveSt=0, AdasActiveSafetyFcnInfo.AebAcitveSt=0. DrivingTextManager trigger count=0, idle count=28.
- Need verification:
  - Confirm the expected non-zero value for the focus signal in that time window.
  - If the signal should have been non-zero, inspect VDS / SOME-IP publisher (not the text manager).

## 7. Confidence

HIGH

## 8. Related Modules

avm, driving_text_tip, vds/signal_publisher

## 9. Related Code

_No --source provided, or no frame/tag mapped to a file. Planned/optional._

## 10. Recommended Investigation

- Treat signal=0 as expected NO_TEXT: do not look for a DrivingTextManager bug unless a non-zero value was published. (evidence E1, E2, E3)
- Confirm the expected non-zero value for the focus signal in that time window. (evidence E1, E2, E3)
- If the signal should have been non-zero, inspect VDS / SOME-IP publisher (not the text manager). (evidence E1, E2, E3)

## 11. Unknown / Missing Information

- No --source directory: Related Code is empty (optional).

## Signal summary

Window: 08-11 16:11:25.291 .. 08-11 16:11:32.094
Structs sampled: {'AdasAccInfo': 29, 'AdasIntelligentEvasionInfo': 29, 'AdasHodDmsInfo': 29, 'AdasALCInfo': 29, 'AdasUNOPFunctionInfo': 29, 'AdasDAIInfo': 29, 'AdasIHCInfo': 29, 'AdasISLIInfo': 29, 'AdasLSSInfo': 29, 'AdasICAInfo': 29, 'AdasAccSupplementInfo': 29, 'AdasTrafficSignIdentity': 29, 'AdasTrajectoryPoint': 89, 'AdasTrafficSign2': 29, 'AdasVPDParkingInfo': 30, 'AdasParkingGenaralInfo': 30, 'AdasESSInfo': 54, 'AdasActiveSafetyFcnInfo': 108, 'AdasHpaUseData': 29, 'AdasUIState': 41, 'AdasSensorSt': 14}
DrivingTextManager idle=28 trigger=0
Focus periods:
- AdasActiveSafetyFcnInfo.FcwAcitveSt=0 08-11 16:11:27.394..08-11 16:11:32.067 n=108 L34-777
- AdasActiveSafetyFcnInfo.AebAcitveSt=0 08-11 16:11:27.394..08-11 16:11:32.067 n=108 L34-777

---
meta: `{'file': 'D:\\carlogDeteor\\examples\\sample_logs\\1611_adas_slice.log', 'size_bytes': 705113, 'encoding': 'utf-8', 'mojibake_repaired': False, 'repaired_lines': 0, 'total_lines': 800, 'events_total': 800, 'processes': {}, 'time_start': '08-11 16:11:25.291', 'time_end': '08-11 16:11:32.094', 'llm_provider': 'rule', 'llm_status': 'ok', 'question': '某时间段信号为0，则该信号的相应文言没有触发', 'focus_signals': ['FcwAcitveSt', 'AebAcitveSt'], 'anomaly_count': 0, 'event_count': 800}`
