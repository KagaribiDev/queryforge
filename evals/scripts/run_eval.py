"""QueryForge 评估脚本:对评估集跑完整 Agent 流程,量化 SQL 生成准确率。

用法:
    python evals/scripts/run_eval.py [--concurrency 4] [--ids E001,E002]

判定标准:执行准确率(execution accuracy)。黄金 SQL 与 Agent 生成的 SQL 在同一 dw 库
执行后比对规范化结果集(忽略列名,数值统一转 float 字符串)。

失败分类:
    correct            SQL 校验通过且执行结果与黄金结果一致
    wrong_semantics    SQL 校验通过但执行结果不一致(语义错误)
    sql_error          校验/执行报错(语法错误、编造列名等)
    fallback           误触 no_result / answer_question 兜底(查询类用例)
    classify_correct   非查询用例被入口分类正确拦截(走回答问题)
    classify_wrong     非查询用例未被拦截(走了查询链路)
"""
import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import create_async_engine

# 允许从任意工作目录直接运行该脚本
EVALS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = EVALS_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.context import QueryForgeContext
from app.agent.graph import graph
from app.agent.state import QueryForgeState
from app.clients.embedding_client import embedding_client_manager
from app.clients.es_client import es_client_manager
from app.clients.mysql_client import dw_client_manager, meta_client_manager
from app.clients.qdrant_client import qdrant_client_manager
from app.config.app_config import app_config
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_repository_qdrant import ColumnQdrantRepository
from app.repositories.qdrant.metric_repository_qdrant import MetricQdrantRepository

DATASET_PATH = EVALS_DIR / "datasets" / "dataset.yaml"
REPORT_DIR = EVALS_DIR / "reports" / "evaluation"
DW_URL = (f"mysql+asyncmy://{app_config.db_dw.user}:{app_config.db_dw.password}"
          f"@{app_config.db_dw.host}:{app_config.db_dw.port}/{app_config.db_dw.database}")

CASE_TIMEOUT_SECONDS = 240


def normalize_value(value) -> str:
    """数值统一转 float 字符串,其余 str,用于结果集比对。"""
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(float(value))
    if hasattr(value, "is_integer") or value.__class__.__name__ == "Decimal":
        return str(float(value))
    return str(value)


def normalize_rows(rows) -> list[set[str]]:
    """每行转为值集合(忽略列名/列序),用于行级包含比对。"""
    return [{normalize_value(v) for v in row} for row in rows]


def results_match(expected_rows, actual_rows) -> bool:
    """判定标准:行数相等,且每个黄金行是某个实际行的值超集之外——即黄金行值 ⊆ 实际行值。

    这样允许 LLM 额外输出辅助列(如占比问题多输出销售额列),但对数值/内容差异保持严格。
    """
    expected = normalize_rows(expected_rows)
    actual = normalize_rows(actual_rows)
    if len(expected) != len(actual):
        return False
    unused = list(actual)
    for exp_row in expected:
        hit = next((i for i, act_row in enumerate(unused) if exp_row <= act_row), None)
        if hit is None:
            return False
        unused.pop(hit)
    return True


async def execute_sql(sql: str) -> list[tuple]:
    engine = create_async_engine(DW_URL)
    try:
        async with engine.connect() as conn:
            result = await conn.exec_driver_sql(sql)
            return result.fetchall()
    finally:
        await engine.dispose()


async def run_case(case: dict, golden_cache: dict, semaphore: asyncio.Semaphore) -> dict:
    """跑单条用例的完整 Agent 流程并判定结果。"""
    record = {
        "id": case["id"], "category": case["category"], "query": case["query"],
        "verdict": "unknown", "correct_count": None, "elapsed": None,
        "generated_sql": None, "error_detail": None,
    }
    async with semaphore:
        start = time.monotonic()
        state = QueryForgeState(query=case["query"])

        async with (meta_client_manager.session_factory() as meta_session,
                    dw_client_manager.session_factory() as dw_session):
            context = QueryForgeContext(
                metric_qdrant_repository=MetricQdrantRepository(qdrant_client_manager.client),
                value_es_repository=ValueESRepository(es_client_manager.client),
                column_qdrant_repository=ColumnQdrantRepository(qdrant_client_manager.client),
                embedding_client=embedding_client_manager.client,
                meta_mysql_repository=MetaMySQLRepository(meta_session),
                dw_mysql_repository=DWMySQLRepository(dw_session))

            events, final_state = [], None
            try:
                async for mode, chunk in graph.astream(
                        input=state, context=context,
                        stream_mode=["custom", "values"]):
                    if mode == "custom":
                        events.append(chunk)
                    else:
                        final_state = chunk
            except Exception as e:
                record["error_detail"] = str(e)[:300]
                record["verdict"] = "sql_error"
                record["elapsed"] = round(time.monotonic() - start, 1)
                return record

            record["elapsed"] = round(time.monotonic() - start, 1)
            record["generated_sql"] = final_state.get("sql") if final_state else None
            record["correct_count"] = final_state.get("correct_count") if final_state else None

            event_types = {k for evt in events for k in evt if k in ("stage", "result", "error", "answer")}

            if case["category"] == "non_query":
                record["verdict"] = ("classify_correct"
                                     if final_state and final_state.get("is_query") is False
                                     else "classify_wrong")
                return record

            # 查询类判定
            if "answer" in event_types:
                record["verdict"] = "fallback"
            elif "error" in event_types and "result" not in event_types:
                record["verdict"] = "fallback"
            elif "result" not in event_types:
                record["verdict"] = "sql_error"
            else:
                expected_rows = golden_cache[case["id"]]
                generated_sql = final_state.get("sql") or ""
                try:
                    actual_rows = await execute_sql(generated_sql)
                except Exception as e:
                    record["error_detail"] = str(e)[:300]
                    record["verdict"] = "sql_error"
                    return record
                record["verdict"] = ("correct"
                                     if results_match(expected_rows, actual_rows)
                                     else "wrong_semantics")
            return record


async def build_golden_cache(cases) -> dict:
    cache = {}
    for case in cases:
        if case["category"] != "non_query":
            cache[case["id"]] = await execute_sql(case["expected_sql"])
    return cache


def print_report(results: list[dict], cases: list[dict]):
    query_cases = [c for c in cases if c["category"] != "non_query"]
    non_query_cases = [c for c in cases if c["category"] == "non_query"]

    def verdict_of(cid):
        return next(r["verdict"] for r in results if r["id"] == cid)

    # 按类别汇总
    categories = {}
    for case in query_cases:
        categories.setdefault(case["category"], []).append(verdict_of(case["id"]))

    print("\n" + "=" * 70)
    print("评估结果汇总(按类别)")
    print("=" * 70)
    total_correct, total = 0, 0
    for cat, verdicts in sorted(categories.items()):
        ok = verdicts.count("correct")
        total_correct += ok
        total += len(verdicts)
        detail = ", ".join(f"{v}={verdicts.count(v)}" for v in
                           ["correct", "wrong_semantics", "sql_error", "fallback"]
                           if verdicts.count(v))
        print(f"  {cat:<12} {ok}/{len(verdicts)}  ({detail})")

    print("-" * 70)
    print(f"  查询类 Execution Accuracy: {total_correct}/{total} = {total_correct / total * 100:.1f}%")

    if non_query_cases:
        nc_ok = sum(1 for c in non_query_cases
                    if verdict_of(c["id"]) == "classify_correct")
        print(f"  非查询类分类准确率: {nc_ok}/{len(non_query_cases)} = "
              f"{nc_ok / len(non_query_cases) * 100:.1f}%")
    else:
        print("  非查询类分类准确率: 本次未包含非查询用例")

    avg_elapsed = sum(r["elapsed"] for r in results if r["elapsed"]) / max(len(results), 1)
    corr_rate = sum(1 for r in results if r["correct_count"]) / max(
        sum(1 for c in query_cases), 1) * 100
    print(f"  平均耗时: {avg_elapsed:.1f}s/条 | 校正循环触发率: {corr_rate:.0f}%")

    # 失败明细
    fails = [r for r in results if r["verdict"] not in ("correct", "classify_correct")]
    if fails:
        print("\n失败明细:")
        for r in fails:
            print(f"  [{r['id']}] {r['verdict']}: {r['query'][:40]}"
                  + (f" | sql: {r['generated_sql'][:60]!r}" if r["generated_sql"] else ""))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--ids", type=str, default="", help="逗号分隔的用例id,只跑子集")
    args = parser.parse_args()

    with open(DATASET_PATH, encoding="utf-8") as f:
        cases = yaml.safe_load(f)
    if args.ids:
        wanted = set(args.ids.split(","))
        cases = [c for c in cases if c["id"] in wanted]

    print(f"加载 {len(cases)} 条用例, 并发 {args.concurrency}")
    golden_cache = await build_golden_cache(cases)
    print(f"黄金结果缓存就绪({len(golden_cache)} 条)")

    # 初始化全局共享客户端(仅一次)
    qdrant_client_manager.init()
    es_client_manager.init()
    embedding_client_manager.init()
    dw_client_manager.init()
    meta_client_manager.init()

    try:
        semaphore = asyncio.Semaphore(args.concurrency)
        results = await asyncio.gather(
            *(run_case(case, golden_cache, semaphore) for case in cases))
    finally:
        await qdrant_client_manager.close()
        await es_client_manager.close()
        await dw_client_manager.close()
        await meta_client_manager.close()

    # 写明细报告
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明细报告: {report_path}")

    print_report(results, cases)


if __name__ == "__main__":
    asyncio.run(main())
