# Midterm

Date: 2026-10-08  
Root: `D:\carlogDeteor`

## 当前完成度

约 **85% MVP**。Pipeline（parse → detect → classify → extract → signal context → rule root-cause → report → tests → Skill）可运行。RAG / 多 Agent 为 Planned。

## 已完成模块

- 项目骨架、CLI（`version` / `parse` / `analyze` / `run-tests` / `metrics`）
- 日志加载（UTF-16、mojibake）、解析、堆栈合并、TAG 归一化
- 规则检测、分类（含 ANR / PERFORMANCE / SIGNAL_NOT_TRIGGERED）
- 关键日志、上下文、VDS 信号时间线
- `LLMProvider` 接口：默认 `RuleBasedProvider`，OpenAI 兼容 / Anthropic 可切换
- 报告 md/json/txt、黄金用例、Skill 三级加载、fix-log

## 已实现功能（与代码一致）

- 读取并分析合成用例 + 真实 `1611.log`（需 `--time-range`）
- 信号为 0 → 文言不触发（Profile `NO_TEXT`）
- Negative：NORMAL 不编根因；证据不足 → UNKNOWN

## 当前测试结果

- `py -3.11 -m pytest tests/unit` → **13 passed**
- `py -3.11 -m adaslog run-tests` → **8/8**
- Accuracy / macro F1 / Evidence Coverage = 1.0；Hallucination Rate = 0.0
- 真实切片 `examples/sample_logs/1611_adas_slice.log` → `SIGNAL_NOT_TRIGGERED` HIGH（Fcw/Aeb=0，文言 idle×28，trigger=0）
- 报告：`reports/1611_adas_slice_analysis.md`

## 问题

- 全量 1611.log 含大量 kernel ERROR，不加时间窗会冲淡 ADAS 信号结论。
- 本机 sandbox 策略导致部分命令需非沙箱执行。

## 风险

见 `docs/phase1_assessment.md`。LLM 幻觉由 Evidence Validator 兜底；默认不走远端。

## 下一阶段计划

- 对照 `1611.log` 16:11 窗口出一份正式报告放入 `reports/`
- 补全更多 Profile 字段
- ≥5 次 git commit 记录（允许在本仓库提交，工具运行期仍不执行 git）

## Commit 记录

开发过程中的重要提交将列在本仓库 `git log`。Phase 1 仅有空仓库；本迭代补齐实现后分批提交。

## 用户确认的输入（2026-10-08）

1. 真实样本 `c:\Users\TS\Desktop\1611.log`，规则：某时间段信号为 0 则相应文言不触发  
2. 先用自带规则引擎，接口预留，便于直接切换 LLM  
3. Python 3.11  
4. 允许在 `D:\carlogDeteor` 内 git commit  
5. 人工耗时用估算值并标注  
6. ANR / PERFORMANCE / SIGNAL_NOT_TRIGGERED 在条件允许时启用（已启用）
