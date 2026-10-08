# Test results

Passed 8/8

| Case | Expected | Actual | Pass/Fail | Seconds | Evidence | Error |
|---|---|---|---|---|---|---|
| binder_case_01 | BINDER_IPC | BINDER_IPC | PASS | 0.003 | first_error, binder_failure, service_disconnected, first_exception, communication_failure |  |
| communication_case_01 | MODULE_COMMUNICATION | MODULE_COMMUNICATION | PASS | 0.003 | first_error, first_exception, communication_failure, communication_failure, communication_failure |  |
| crash_case_01 | CRASH | CRASH | PASS | 0.003 | first_error, fatal, first_exception, crash, crash |  |
| exception_case_01 | EXCEPTION | EXCEPTION | PASS | 0.003 | first_exception, first_exception |  |
| signal_zero_case_01 | SIGNAL_NOT_TRIGGERED | SIGNAL_NOT_TRIGGERED | PASS | 0.003 | signal_idle, signal_idle, text_idle |  |
| state_case_01 | STATE_MACHINE | STATE_MACHINE | PASS | 0.002 | state_transition_failure |  |
| insufficient_evidence_01 | UNKNOWN | UNKNOWN | PASS | 0.002 | first_error |  |
| normal_case_01 | NORMAL | NORMAL | PASS | 0.002 |  |  |
