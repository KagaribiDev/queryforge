# QueryForge 评测资产

本目录集中保存 QueryForge 的评估数据、可执行脚本、历史结果和优化文档。

## 目录结构

```text
evals/
├── datasets/                  # 评估数据集与黄金 SQL
├── scripts/                   # 可直接执行的评测脚本
├── reports/
│   ├── evaluation/           # 完整 Agent 准确率报告
│   └── stress/               # HTTP 压测报告
└── docs/
    └── OPTIMIZATION_REPORT.md # SQL 准确率优化过程与实验总结
```

准确率提升、召回参数实验和压力测试的分析总结见
[`docs/OPTIMIZATION_REPORT.md`](docs/OPTIMIZATION_REPORT.md)。

## 脚本评测范围

| 脚本 | 评测方面 | 核心检查与指标 | 运行依赖 | 输出 |
|---|---|---|---|---|
| `verify_dataset.py` | 评估数据集质量 | 逐条执行查询类用例的黄金 SQL，检查 SQL 是否可执行、结果是否非空，确保评估基准本身可靠 | MySQL 数据仓库 | 控制台输出每条用例状态及通过总数 |
| `run_eval.py` | Agent 端到端准确率 | 运行完整 LangGraph 链路，将生成 SQL 与黄金 SQL 的执行结果进行比较；统计 Execution Accuracy、非查询分类准确率、平均耗时、SQL 校正触发率及失败类型 | MySQL、Qdrant、Elasticsearch、Embedding、LLM | `reports/evaluation/` 下的 JSON 明细及控制台汇总 |
| `run_10k_eval.py` | 大规模真实 LLM 评测 | 动态生成 14 类唯一问法和黄金 SQL，逐条调用完整 LangGraph/LLM/RAG/MySQL 链路；支持 10k 默认运行、任意规模、断点续跑和按 ID 定向回归 | MySQL、Qdrant、Elasticsearch、Embedding、LLM | `reports/evaluation_10k/` 下逐条 JSONL 和汇总 JSON |
| `recall_bench.py` | RAG 召回层质量 | 隔离测试字段、表、字段值和指标召回；扫描不同 score 阈值与 top-k 组合，统计列命中率、完整命中率、表命中率、值命中率、指标命中率和平均噪音列数 | Qdrant、Elasticsearch、Embedding、LLM | 控制台参数对比表 |
| `multi_turn_check.py` | 多轮问题改写能力 | 使用10组对话场景测试指代消解和上下文继承，例如“那3月份呢”；按关键语义要素判断改写结果是否正确 | LLM | 控制台逐场景结果及改写准确率 |
| `stress_test.py` | API 稳定性与复杂输入处理 | 并发请求50条正常、模糊、复杂、陷阱、边界、对抗和非查询问题；统计响应状态、耗时、阶段数、结果行数、图表事件及错误信息 | 已启动的 QueryForge 后端及其基础设施 | `reports/stress/` 下的 JSON 明细及控制台汇总 |

这5个脚本从不同层级形成完整评测链路：先验证黄金数据可靠性，再分别度量召回、多轮改写和完整 Agent 准确率，最后通过 HTTP 压测检查系统级稳定性。

## 执行方式

以下命令均可在项目根目录执行：

```powershell
.venv/Scripts/python evals/scripts/verify_dataset.py
.venv/Scripts/python evals/scripts/run_eval.py --concurrency 4
.venv/Scripts/python evals/scripts/run_10k_eval.py --count 500 --concurrency 32 --retries 3
# 默认运行 10,000 条；中断后可用 --resume 指向已有 JSONL 继续
.venv/Scripts/python evals/scripts/run_10k_eval.py --concurrency 16
.venv/Scripts/python evals/scripts/recall_bench.py
.venv/Scripts/python evals/scripts/multi_turn_check.py
.venv/Scripts/python evals/scripts/stress_test.py
```

`run_eval.py` 的新报告写入 `reports/evaluation/`；`stress_test.py` 的新报告写入
`reports/stress/`。压测脚本运行前需要启动 QueryForge 后端服务。

`run_10k_eval.py` 默认生成并测试 10,000 个问题，本次赶时间可用 `--count 500`。脚本按固定
seed 生成相同用例，使用 `--ids K00320,K00342` 可以只回归指定失败样本；所有运行均真实调用模型，
`--dry-run` 才会跳过 Agent/LLM。
