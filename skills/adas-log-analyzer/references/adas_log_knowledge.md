# E02 ADAS log knowledge (read-only extract)

- App tag prefix `IVI_ADAS_APP_` (max 23 chars). Protocol prefix `IVI_ADAS_`.
- State machine states: INIT, IDLE, PARK_*, HPA_*, VPA_*, VPD_*.
  Illegal: `未定义的状态转换: 当前状态 X -> 预触发 Y`.
- Driving text: tag `DrivingTextManager`. Idle: `队列为空且无当前显示，等待新文言触发`.
  Handlers log `FcwAcitveSt变化: a -> b` then Profile maps the value to a text id or `NO_TEXT`.
- VDS publisher (often pid 1736 on the 1611 sample): `CommonAdapter: notifyCallback() Struct, msg:Struct{k=v, ...}`.
- Known trigger fields: `FcwAcitveSt` (2/3), `AebAcitveSt` (2), `EssSts`, `AesSts`. **0 = no text**.
- Modules: app / driving_text_tip / avm / avmcalibration / common_protocol (Kanzi) / avmarbitration.
