# Confidence

| Label | When |
|---|---|
| HIGH | Stack + app frame, or signal=0 plus text-idle with samples |
| MEDIUM | Rule match, missing code or publisher confirmation |
| LOW | Single ERROR, no stack / module / signal context |

Numeric classifier score is mapped: ≥0.75 HIGH, ≥0.45 MEDIUM, else LOW.
