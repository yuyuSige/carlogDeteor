# Root cause rules

1. No evidence ids → UNKNOWN, reason `Insufficient evidence.`
2. NORMAL window → no candidate at all.
3. Crash: first app frame + exception class is the candidate, not "code is wrong".
4. Signal idle: if focus field stays 0 and DrivingTextManager never queues, the candidate is
   **publisher stayed idle / Profile maps 0 to NO_TEXT**, not a queue bug.
5. Always add Need Verification (what would confirm or refute).
