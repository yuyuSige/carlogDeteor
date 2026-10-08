# Final report (working draft — numbers refreshed after `adaslog run-tests`)

## 项目背景

见 README / proposal。本工具服务 E02 ADAS 日志诊断，工程文件全部在 `D:\carlogDeteor`，不改 `D:\E02_adas`。

## 问题定义

从混杂 logcat 中给出带证据的根因候选；在证据不足时明确 UNKNOWN；在信号为 0 时解释文言未触发是 Profile 预期。

## 技术方案

Python 3.11，标准库核心，JSON 规则包，可替换 `LLMProvider`。

## 架构设计 / AI 设计 / Skill 设计

见 `docs/design.md` 与 `skills/adas-log-analyzer/SKILL.md`。默认离线规则推理；远端模型可选。

## 关键实现

- UTF-16 + mojibake 修复（1611.log 可检索中文）
- TAG 23 字符截断回映射
- 信号结构体解析 + `FcwAcitveSt=0` → SIGNAL_NOT_TRIGGERED
- Evidence Validator 防止无证据根因

## 测试数据

合成 5+1 正例、2 反例；真实样本 `c:\Users\TS\Desktop\1611.log`（不复制进 E02）。

## 测试结果 / 效果指标

`adaslog run-tests` **8/8 PASS**（5 规范正例 + signal_zero + 2 负例）。`pytest tests/unit` **13 passed**.

| 指标 | 值 | 说明 |
|---|---|---|
| Classification Accuracy | 1.0 | 8 golden cases |
| Macro Precision / Recall / F1 | 1.0 / 1.0 / 1.0 | 测试集内，不宣称泛化 |
| Key-log Precision / Recall | 1.0 / 1.0 | vs `expected.json` 必选 category |
| Evidence Coverage | 1.0 | 有证据 id 的结论 / 全部结论 |
| Hallucination Rate | 0.0 | 无证据却给出 CANDIDATE |
| Negative-control pass rate | 1.0 | NORMAL + UNKNOWN |

人工时间均为 **估算值（estimate）**，见 `tests/results/metrics.json`。

## 人工 vs AI

| 场景 | 人工（估算） | AI 辅助（实测墙钟，见 results） |
|---|---|---|
| Crash / Binder / 状态机 | 15–25 min（估算） | 秒级 + 人工复核约 5 min（估算） |
| 1611 信号未触发文言 | 30 min（估算） | 加时间窗后秒级 + 复核约 6 min（估算） |

## Hallucination 分析

Validator 要求每个 CANDIDATE 至少引用一个已存在的 evidence id。Negative 用例禁止在 NORMAL 上编根因。

## 案例分析

- `crash_case_01`：NPE @ AvmViewPresenter  
- `signal_zero_case_01` / 1611.log：Fcw/Aeb=0，DrivingTextManager 空队列  
- `normal_case_01` / `insufficient_evidence_01`：负对照

## 问题与限制

全量系统日志必须切片；字段映射表未覆盖全部 Profile。

## 总结

MVP 可运行、可测试、文档与代码对齐。LLM 切换只改 `.env` / `--llm`。
