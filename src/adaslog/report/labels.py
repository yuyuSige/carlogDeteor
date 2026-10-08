"""Chinese display labels for human-readable reports. Machine enums stay English."""
from __future__ import annotations

ISSUE_TYPE = {
    "CRASH": "崩溃",
    "EXCEPTION": "异常",
    "BINDER_IPC": "Binder/IPC 失败",
    "STATE_MACHINE": "状态机异常",
    "MODULE_COMMUNICATION": "模块通信失败",
    "SYSTEM_ERROR": "系统错误",
    "BUSINESS_ERROR": "业务错误",
    "ANR": "ANR",
    "PERFORMANCE": "性能问题",
    "SIGNAL_NOT_TRIGGERED": "信号未触发文言",
    "NORMAL": "正常",
    "UNKNOWN": "未知",
}

SEVERITY = {
    "CRITICAL": "严重",
    "HIGH": "高",
    "MEDIUM": "中",
    "LOW": "低",
    "NONE": "无",
}

CONFIDENCE = {
    "HIGH": "高",
    "MEDIUM": "中",
    "LOW": "低",
}

STATUS = {
    "CANDIDATE": "候选根因",
    "UNKNOWN": "未知",
}

CATEGORY = {
    "first_error": "首条错误",
    "first_exception": "首条异常",
    "fatal": "Fatal",
    "crash": "崩溃",
    "binder_failure": "Binder 失败",
    "service_disconnected": "服务断开",
    "state_transition_failure": "非法状态转换",
    "timeout": "超时",
    "communication_failure": "通信失败",
    "anr": "ANR",
    "key_warning": "关键告警",
    "system_error": "系统错误",
    "signal_idle": "信号空闲(0)",
    "text_idle": "文言未触发",
    "text_trigger": "文言已触发",
}

RELATION = {
    "precedes": "先于",
    "triggers": "触发",
    "repeats": "重复",
}

HOW_FOUND = {
    "stack_frame": "堆栈帧",
    "tag_class": "日志 TAG",
    "log_message": "日志内容",
}


def issue(code: str | None) -> str:
    if not code:
        return "未知"
    name = ISSUE_TYPE.get(code, code)
    return f"{name}（{code}）" if code in ISSUE_TYPE else code


def severity(code: str | None) -> str:
    if not code:
        return "未知"
    return f"{SEVERITY.get(code, code)}（{code}）"


def confidence(code: str | None) -> str:
    if not code:
        return "未知"
    return f"{CONFIDENCE.get(code, code)}（{code}）"


def status(code: str | None) -> str:
    if not code:
        return "未知"
    return STATUS.get(code, code)


def category(code: str | None) -> str:
    if not code:
        return ""
    return CATEGORY.get(code, code)


def relation(code: str | None) -> str:
    return RELATION.get(code or "", code or "")


def how_found(code: str | None) -> str:
    return HOW_FOUND.get(code or "", code or "")
