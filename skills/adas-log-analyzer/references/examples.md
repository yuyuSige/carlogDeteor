# Examples

## Positive — crash

`FATAL EXCEPTION` + NPE in `AvmViewPresenter.showView` → CRASH, evidence fatal + first_exception.

## Positive — signal = 0 (1611.log)

```
CommonAdapter: notifyCallback() AdasActiveSafetyFcnInfo{FcwAcitveSt=0, AebAcitveSt=0}
DrivingTextManager: 队列为空且无当前显示，等待新文言触发
```

→ SIGNAL_NOT_TRIGGERED. Root cause: Profile maps 0 → NO_TEXT.

Command:

```
py -3.11 -m adaslog analyze c:\Users\TS\Desktop\1611.log --time-range 16:11:00-16:12:00 --focus-signal FcwAcitveSt,AebAcitveSt --question "信号为0则文言未触发" --format all
```

## Negative — normal

`service started` / `connection established` / `request completed` → NORMAL, no root cause.

## Negative — insufficient

`ERROR something happened` → UNKNOWN, Insufficient evidence.
