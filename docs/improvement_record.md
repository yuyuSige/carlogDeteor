# 改进记录（0.2.0）

日期：2026-10-08。范围：诊断准确性、测试评估、安装资源、大日志与多故障、源码上下文与报告追溯。未 git commit / push。未修改 `D:\E02_adas`。未调用付费模型。

## 1. 按优先级的实际修改

### 第一阶段 诊断准确性

| 主题 | 文件 |
|---|---|
| 空数据 / 过滤后无事件 → UNKNOWN，与 NORMAL 区分 | `parser/loader.py` `classifier/issue_classifier.py` `core/pipeline.py` |
| 跨午夜时间窗、时分秒范围校验；无时间戳行在设时间窗时排除 | `utils/timeparse.py` `parser/loader.py` |
| 焦点信号严格限定；保留全部取值时段；`trigger_values`；未知字段不套用 0→NO_TEXT | `context/signals.py` `config/rules/signal_text.json` `extractor/key_log_extractor.py` |
| 「未见入队 ≠ 未入队」；用户问题不覆盖已检出故障 | `analyzer/root_cause.py` `core/pipeline.py` |
| 校验结构/枚举/证据编号/证据类型/反证；分类与根因置信度拆开 | `llm/validator.py` `models/__init__.py` `report/markdown.py` `report/text.py` |

### 第二阶段 测试与评估

| 主题 | 文件 |
|---|---|
| 回归：空日志、过滤空、跨午夜、信号 0→2、焦点、校验对抗、多 PID、间隔崩溃、LLM 回退 | `tests/unit/test_*.py` `tests/cases/**` |
| 执行器检查禁止证据/禁止根因文本/`data_status`/`min_incidents` | `testing/runner.py` |
| `hallucination_rate` 明确为「CANDIDATE 无证据编号」；多余未标注证据不算正确 | `testing/metrics.py` |
| CI | `.github/workflows/ci.yml` |

### 第三阶段 安装与资源

| 主题 | 文件 |
|---|---|
| 默认配置/规则打进 wheel；`importlib.resources` | `pyproject.toml` `MANIFEST.in` `src/adaslog/resources/` `core/config.py` |
| 报告写到 cwd/`reports`，不写安装目录；`--llm` 默认 None | `core/config.py` `cli/main.py` |
| 用户配置支持 UTF-8 BOM | `core/config.py` |

### 第四阶段 大日志与多故障

| 主题 | 文件 |
|---|---|
| 增量解码 `LineStream`；解析保留原始行号 | `utils/io.py` `parser/loader.py` `parser/logcat.py` |
| 堆栈合并限制同 pid/tid/tag 且 Δt≤2s | `parser/stacktrace.py` |
| 重复异常合并键含 pid + 30s 桶 | `detector/rules_engine.py` |
| 故障按 pid/类别/60s 间隔拆 `incidents` | `classifier/incidents.py` `models/__init__.py` |

### 第五阶段 源码上下文与报告

| 主题 | 文件 |
|---|---|
| 代码片段按字符预算纳入模型输入；同名文件 `how_found=ambiguous` | `core/pipeline.py` `analyzer/code_analyzer.py` |
| 仅捕获 `LLMProviderError` 回退；日志标为 DATA 非指令 | `core/pipeline.py` `llm/openai_compat.py` `llm/anthropic.py` `llm/prompts.py` |
| `run_id` 进文件名；MD/JSON/TXT 含任务编号、过滤策略、反证、问题列表 | `core/pipeline.py` `report/*` |
| 文档与能力对齐 | `README.md` `docs/design.md` 本文件 |

## 2. 已复现问题：修复前后

| 问题 | 修复前 | 修复后（本轮实测） |
|---|---|---|
| 空日志 | NORMAL / HIGH | UNKNOWN / 分类 LOW / 根因 LOW，摘要说明数据不足 |
| 时间过滤后 0 事件 | NORMAL / HIGH | `data_status=filter_empty`，UNKNOWN |
| `23:59-00:01` | 带时间戳事件被滤光 | `time_wraps_midnight=true`，23:59 与 00:00 事件保留 |
| FcwAcitveSt 0→2 | HIGH「焦点信号保持为 0」 | `observation=saw_trigger`，分类不为 SIGNAL_NOT_TRIGGERED |
| `focus_signals=["AebAcitveSt"]` | Fcw 仍进焦点 | 焦点集合仅 Aeb |
| 引用 E1「队列为空」断言 GPU 损坏 HIGH | 校验接受 | 证据类型不支持 → UNKNOWN / LOW |
| 安装后加载规则 | FileNotFoundError | wheel 含 `adaslog/resources/**/*.json`，隔离目录可分析 |

正常合成日志用例（`normal_case_01`、无异常短日志）仍为 NORMAL。

## 3. 验证结果（均已执行）

### 单元测试

```
py -3.11 -m pytest tests/unit -q
53 passed in 1.33s
```

### 场景测试（独立目录，未覆盖历史 `tests/results`）

```
py -3.11 -m adaslog run-tests --results D:\carlogDeteor\tmp\phase_verify_results2
passed 14/14
```

全部 `sample_kind=synthetic`。分类 accuracy 1.0 **仅对该黄金集**，不是生产准确率。  
`hallucination_rate=0.0` 表示没有「无证据编号的 CANDIDATE」，**不是**根因正确。  
`key_log_extraction.unlabelled_extra_categories=13`：未标注的多余证据未计入精确率分子。

### 安装包

- 构建：`adaslog-0.2.0-py3-none-any.whl`，内含 `resources/default.json` 与 6 个 rules JSON。
- 隔离 venv + 工作目录 `tmp/isolated_cwd`（非源码树）：
  - `adaslog version` → `0.2.0`
  - 分析 `crash.log` → CRASH，报告带 run_id
  - 分析 `signal.log` + 用户配置 → SIGNAL_NOT_TRIGGERED
  - `load_json_resource('rules/signal_text.json')` 成功
  - `default_output_dir()` = 该工作目录下 `reports/`
  - 安装包目录内无 `reports/`

### 性能（合成日志，非 1611.log）

| 项 | 值 |
|---|---|
| 文件 | `tmp/perf_large.log` |
| 大小 | 11 920 000 字节（约 11.4 MiB） |
| 行/事件 | 80 000 / 80 000 |
| `load_log` | 5.647 s |
| 全流程 `run_analysis` | 13.675 s（load 6.013 + detect_classify 7.545 + reason 0.002） |
| tracemalloc 峰值 | 87 810 557 字节（约 83.7 MiB，仅 Python 分配） |
| RSS / 工作集 | **未测** |
| 相对旧「全量读入再解析」的加速比 | **未测**（本轮无旧实现对照） |

## 4. 未解决问题与限制

- 流式解码后仍在内存中持有全部解析事件；时间/PID 过滤在堆栈合并之后，不能在解码阶段丢弃需要合并的栈帧邻居。
- 进程映射依赖全量流学习 pid，因此不能在见到 Start proc 之前按 pid 丢弃行。
- 同名/多 flavor 源文件仍取第一个做 snippet，同时标记 `ambiguous` 并列候选，不消歧。
- 自由文本语义无法可靠验证；校验靠证据类型矩阵和信号反证，不是完整 NLI。
- 未对 173MB `1611.log` 做本轮耗时/内存测量。
- 未测操作系统 RSS。
- 历史案例检索、多 Agent、界面：明确不在范围。
- setuptools 对 `project.license` 表格式发出弃用警告，构建仍成功。

## 5. 常用验证命令

```bat
cd /d D:\carlogDeteor
py -3.11 -m pytest tests/unit -q
py -3.11 -m adaslog run-tests --results D:\carlogDeteor\tmp\latest_results
py -3.11 -m adaslog metrics --results D:\carlogDeteor\tmp\latest_results --cases D:\carlogDeteor\tests\cases
py -3.11 -m adaslog version
py -3.11 -m adaslog analyze path\to\file.log --format all --out D:\carlogDeteor\tmp\out --no-progress
py -3.11 -m build --wheel --outdir D:\carlogDeteor\tmp\dist
```

空数据与跨午夜：

```bat
py -3.11 -m adaslog analyze tests\cases\negative\empty_log_case_01\input.log --format json --out D:\carlogDeteor\tmp\out --no-progress
py -3.11 -m adaslog analyze tests\cases\positive\midnight_wrap_case_01\input.log --time-range 23:59:00-00:01:00 --format json --out D:\carlogDeteor\tmp\out --no-progress
```
