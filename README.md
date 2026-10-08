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
Raw log → stream decode → parser → detector → classifier (+ incidents)
        → extractor → context/signals → optional code analyzer (--source, read-only)
        → LLMProvider (default: offline RuleBased; OpenAI/Anthropic optional)
        → Evidence Validator → Markdown / JSON / TXT report (run_id in filename)
```

## 核心功能

| 能力 | 状态 |
|---|---|
| 读取 .log/.txt，UTF-16 / GBK / mojibake 修复；流式解码 | Implemented |
| Logcat 多格式 + 同进程堆栈合并 + TAG 归一化 | Implemented |
| 空日志 / 过滤后无事件 → UNKNOWN，与 NORMAL（未发现异常）区分 | Implemented |
| 跨午夜时间窗 `23:59-00:01`；无时间戳行在设时间窗时排除 | Implemented |
| 异常检测 / 分类 / 关键日志 / 上下文 | Implemented |
| 多故障按 pid / 模块 / 时间间隔拆分，顶层保留主问题类型 | Implemented |
| 信号时间线：按字段 `trigger_values` 判断；未知字段不把 0 当成 NO_TEXT | Implemented |
| 离线规则根因；分类置信度与根因置信度分开；Evidence 校验 | Implemented |
| `LLMProvider`（省略 `--llm` 用配置/环境变量，默认 rule） | Implemented（远端需 .env；超时/非法 JSON 回退 rule） |
| `--source` 只读代码映射；同名/多 flavor 文件保留歧义 | Implemented |
| 打包默认配置与规则（`adaslog.resources`），报告写到 cwd | Implemented |
| Skill 渐进加载 | Implemented |
| RAG / 多 Agent Harness | Planned |

Issue types: CRASH, EXCEPTION, BINDER_IPC, STATE_MACHINE, MODULE_COMMUNICATION, SYSTEM_ERROR, BUSINESS_ERROR, ANR, PERFORMANCE, SIGNAL_NOT_TRIGGERED, NORMAL, UNKNOWN。

根因候选是 Hypothesis，不是已确认根因。有证据编号不等于结论正确。时序只表示「先于」，不表示因果。

## 使用方式 / 运行方式

```bat
cd /d D:\carlogDeteor
py -3.11 -m pip install -e . -q
py -3.11 -m adaslog version
py -3.11 -m adaslog parse path\to\file.log --stats
py -3.11 -m adaslog analyze path\to\file.log --format all --out D:\carlogDeteor\tmp\out --no-progress
```

`--format all` 写出 md/json/txt；文件名含 `run_id`，避免同名日志、不同时间窗互相覆盖。进度打到 stderr（`--no-progress` 关闭），不会写入 JSON。省略 `--llm` 时用 `config` / `LLM_PROVIDER`，不会被 CLI 强行改成 rule。

针对本地日志（真实样本，不拷进 E02 工程）：

```bat
py -3.11 -m adaslog analyze c:\Users\TS\Desktop\1611.log --time-range 16:11:00-16:12:00 --focus-signal FcwAcitveSt,AebAcitveSt --question "XXX相应文言没有触发" --format all --out D:\carlogDeteor\reports

py -3.11 -m adaslog analyze c:\Users\TS\Desktop\1540.log --time-range 15:41:26-15:41:27 --focus-signal ParkingQuitInd --question "不显示暂停超时，泊车功能退出" --format all --out D:\carlogDeteor\reports
```

LLM：先用自带规则引擎。要换模型时复制 `.env.example` 为 `.env`，填 `OPENAI_API_KEY` / `OPENAI_BASE_URL` 或 `ANTHROPIC_API_KEY`，再加 `--llm openai` 或 `--llm anthropic`。源码不写死 Key。

## 测试方式

```bat
py -3.11 -m pytest D:\carlogDeteor\tests\unit -q
py -3.11 -m adaslog run-tests --results D:\carlogDeteor\tmp\latest_results
py -3.11 -m adaslog metrics --results D:\carlogDeteor\tmp\latest_results --cases D:\carlogDeteor\tests\cases
```

黄金用例在 `tests/cases/{positive,negative}`，全部标注 `sample_kind=synthetic`，不是生产准确率。自定义 `--cases` 时评估会读取该目录下的 `expected.json`。CI：`.github/workflows/ci.yml`。

## 效果指标

见 `tmp/latest_results/metrics.json`（或你指定的 `--results`）。人工耗时均为 **估算值并已标注 estimate**。

`hallucination_rate` / `candidate_without_evidence_ids_rate` 只统计「CANDIDATE 但没有任何证据编号」，**不能**解读为根因正确。结论对错看 `claim_mismatch_rate` 与用例里的 `forbidden_root_cause_substrings`。提取精确率只在 `must_have` / `forbidden` 标注范围内计算，未标注的多余证据记为 `unlabelled_extra_categories`。

## Skill 使用方式

目录 `skills/adas-log-analyzer/`：

- Level 1 `SKILL.md` — 触发、规则、Evidence First、自由度
- Level 2 `references/` — Android / Binder / E02 / 根因 / 置信度 / 示例
- Level 3 `scripts/analyze_log.py` — 与 CLI 同一管道

把该目录加到 Claude Code / Cursor Skill 搜索路径即可。Agent 只分析、定位、给建议，不改业务代码。

## 项目目录

见 `docs/design.md`。本轮改动说明见 `docs/improvement_record.md`。规范要求的 `README.md` / `proposal.md` / `midterm.md` / `src/` / `tests/` / `docs/` / `skills/` / `skills-creator/fix-log.md` 均在本根下。

## 安装与资源

默认配置和规则在包内 `adaslog.resources`（`importlib.resources`），wheel 安装后无需源码树。报告默认写到 **当前工作目录** `reports/`，不会写入安装目录。用户 `--config` 覆盖内置 JSON；省略 `--llm` 时使用配置或环境变量 `LLM_PROVIDER`，CLI 不会把 llm 强行写成 rule。

空日志或时间过滤后无事件 → `UNKNOWN`（数据不足），与「窗口内有日志且未发现异常」的 `NORMAL` 不同。跨午夜时间窗（如 `23:59:00-00:01:00`）按时钟环绕处理。报告文件名含 `run_id`，避免同名日志不同时间窗互相覆盖。

## 已知限制

- 全量系统 logcat（如 1611.log，173MB UTF-16）建议加时间窗 / 焦点信号；解析已改为流式解码，但仍会在内存中保留过滤后的事件。时间/PID 过滤在堆栈合并之后。
- 文言映射表只固化了 `signal_text.json` 中的字段；未知字段不能把 0 解释为 NO_TEXT。未见入队日志不能证明未入队。
- 远端 LLM 仅在 `LLMProviderError`（超时、HTTP、非法 JSON）时回退 rule；程序内部异常会抛出。日志内容按数据分析，不当模型指令。
- `candidate_without_evidence_ids_rate` / `hallucination_rate` 不是根因正确率。黄金集准确率不是生产准确率。
- 多 flavor 同名源文件会列出候选并标记 `ambiguous`，不会默认第一个文件就是命中。
- 不写入 `D:\E02_adas`。

## 后续计划

RAG（历史缺陷库）、多 Agent Harness、更多 Profile 字段表。标为 Planned，未实现不写「已支持」。
