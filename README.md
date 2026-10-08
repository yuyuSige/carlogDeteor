# AI-Assisted ADAS Android Log Analysis and Root Cause Diagnosis Skill

Project root: `D:\carlogDeteor`  
CLI: `adaslog` (Python 3.11+)  
Target app (read-only, never modified): `D:\E02_adas`

## 项目背景

E02 IVI ADAS 的现场问题几乎都先落在一份混杂的 logcat 上：kernel、system_server、VDS 信号发布进程、ADAS 应用（状态机 / AVM / 泊车 / 驾驶文言 / Kanzi）。工程师靠人工 grep 在多个 pid 之间对因对果，一份日志常常要 **20–30 分钟（估算）**。

## 项目目标

把「日志输入 → 预处理 → 异常检测 → 分类 → 关键日志 → 上下文 → 可选源码 → 根因候选 → Evidence 校验 → 结构化报告」做成可运行的 CLI + Claude Code Skill。

核心不是让模型猜原因，而是 **Evidence First**：没有证据 id 就不能给出确定根因。

## 业务痛点

- 日志编码经常是 UTF-16 + 中文二次编码，直接搜中文会 0 命中。
- TAG 被 `AppLogger` 加上 `IVI_ADAS_APP_` 并截断到 23 字符。
- 「信号为 0 → 对应文言不触发」是 Profile 的预期行为，容易被误判成文言模块缺陷。

## 整体架构

```
Raw log → parser → detector → classifier → extractor → context/signals
        → optional code analyzer (--source, read-only)
        → LLMProvider (default: offline RuleBased; OpenAI/Anthropic optional)
        → Evidence Validator → Markdown / JSON / TXT report
```

## 核心功能

| 能力 | 状态 |
|---|---|
| 读取 .log/.txt，UTF-16 / GBK / mojibake 修复 | Implemented |
| Logcat 多格式 + 堆栈合并 + TAG 归一化 | Implemented |
| 异常检测 / 分类 / 关键日志 / 上下文 | Implemented |
| 信号时间线 +「信号=0 ⇒ 文言不触发」 | Implemented |
| 离线规则根因 + Evidence / Confidence | Implemented |
| `LLMProvider` 接口（`--llm rule\|openai\|anthropic`） | Implemented（默认 rule；远端需 .env） |
| `--source` 只读代码映射 | Implemented |
| Skill 渐进加载 | Implemented |
| RAG / 多 Agent Harness | Planned |

Issue types: CRASH, EXCEPTION, BINDER_IPC, STATE_MACHINE, MODULE_COMMUNICATION, SYSTEM_ERROR, BUSINESS_ERROR, ANR, PERFORMANCE, SIGNAL_NOT_TRIGGERED, NORMAL, UNKNOWN.

## 使用方式 / 运行方式

```bat
cd /d D:\carlogDeteor
py -3.11 -m pip install -e . -q
py -3.11 -m adaslog version
py -3.11 -m adaslog parse path\to\file.log --stats
py -3.11 -m adaslog analyze path\to\file.log --format all --print
```

针对 `1611.log`（桌面上的真实样本，不要拷进 E02 工程）：

```bat
py -3.11 -m adaslog analyze c:\Users\TS\Desktop\1611.log --time-range 16:11:00-16:12:00 --focus-signal FcwAcitveSt,AebAcitveSt --question "某时间段信号为0，则该信号的相应文言没有触发" --format all --out D:\carlogDeteor\reports
```

LLM：先用自带规则引擎。要换模型时复制 `.env.example` 为 `.env`，填 `OPENAI_API_KEY` / `OPENAI_BASE_URL` 或 `ANTHROPIC_API_KEY`，再加 `--llm openai` 或 `--llm anthropic`。源码不写死 Key。

## 测试方式

```bat
py -3.11 -m pytest D:\carlogDeteor\tests\unit -q
py -3.11 -m adaslog run-tests
py -3.11 -m adaslog metrics
```

至少 5 个 Positive + 2 个 Negative；额外 `signal_zero_case_01` 覆盖 1611 场景。结果在 `tests/results/`。

## 效果指标

见 `tests/results/metrics.json` 与 `docs/report.md`。人工耗时均为 **估算值并已标注 estimate**。Hallucination Rate 统计「无证据却给出明确根因」。

## Skill 使用方式

目录 `skills/adas-log-analyzer/`：

- Level 1 `SKILL.md` — 触发、规则、Evidence First、自由度
- Level 2 `references/` — Android / Binder / E02 / 根因 / 置信度 / 示例
- Level 3 `scripts/analyze_log.py` — 与 CLI 同一管道

把该目录加到 Claude Code / Cursor Skill 搜索路径即可。Agent 只分析、定位、给建议，不改业务代码。

## 项目目录

见 `docs/design.md`。规范要求的 `README.md` / `proposal.md` / `midterm.md` / `src/` / `tests/` / `docs/` / `skills/` / `skills-creator/fix-log.md` 均在本根下。

## 已知限制

- 全量系统 logcat（如 1611.log，173MB UTF-16）必须加时间窗 / 焦点信号，否则噪声（kernel E）会干扰。
- 文言映射表只固化了常见 ActiveSafety 字段；其它字段靠 `--focus-signal`。
- 远端 LLM 未配置时自动回退 rule，不会中断。
- 不写入 `D:\E02_adas`。

## 后续计划

RAG（历史缺陷库）、多 Agent Harness、更多 Profile 字段表。标为 Planned，未实现不写「已支持」。
