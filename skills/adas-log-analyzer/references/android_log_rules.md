# Android log rules

- Formats: threadtime `MM-DD HH:MM:SS.mmm pid tid L tag: msg`, time `L/tag(pid):`, brief, custom `YYYY-MM-DD … L/tag:`.
- Markers: `--------- beginning of crash|main|system`.
- Stack merge: `FATAL EXCEPTION` / `Process:` / `java.lang.X` / `at …` / `Caused by:` / `... N more`.
- Levels: V D I W E F. First E/F is `first_error`; fatal + stack is `fatal`.
- ANR: `ANR in`, `Input dispatching timed out`.
- Process map: `Start proc PID:pkg/` and `Process pkg (pid N) has died`.
