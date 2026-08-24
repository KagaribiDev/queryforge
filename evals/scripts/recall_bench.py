"""召回层参数实验:扫描 Qdrant/ES 的 score 阈值与 top-k,量化召回命中率与噪音。

指标:
    列命中率   黄金 SQL 必需列被召回的占比
    用例完全命中 必需列全部被召回的用例占比
    表命中率   黄金 SQL 涉及的表被召回的占比
    平均噪音列  召回的列中不属于黄金 SQL 的数量(越小越好)
    值命中率   黄金 SQL 字符串常量被字段值召回覆盖的占比
    指标命中率  GMV/AOV 类用例中指标被召回的占比

用法: python evals/scripts/recall_bench.py
"""
import asyncio
import re
import sys
from collections import defaultdict
from pathlib import Path

import jieba.analyse
import yaml
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

EVALS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = EVALS_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.llm import llm
from app.agent.nodes.extract_keywords import is_numeric
from app.clients.embedding_client import embedding_client_manager
from app.clients.es_client import es_client_manager
from app.clients.qdrant_client import qdrant_client_manager
from app.prompt.prompt_loader import load_prompt

ALLOW_POS = ("n", "nr", "ns", "nt", "nz", "v", "vn", "a", "an", "eng", "i", "l")

SCORES = [0.4, 0.5, 0.6, 0.7]
TOP_KS = [3, 5, 10]


def parse_golden(sql: str) -> dict:
    """从黄金 SQL 提取:表集合、必需列集合(表.列)、字符串常量集合。"""
    tables, alias_map, columns, values = set(), {}, set(), set(re.findall(r"'([^']*)'", sql))

    for m in re.finditer(r'FROM\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?', sql, re.I):
        table, alias = m.group(1), m.group(2)
        tables.add(table)
        alias_map[alias or table] = table
    for m in re.finditer(r'JOIN\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?', sql, re.I):
        table, alias = m.group(1), m.group(2)
        tables.add(table)
        alias_map[alias or table] = table
    for m in re.finditer(r'\b(\w+)\.(\w+)\b', sql):
        alias, col = m.group(1), m.group(2)
        if alias in alias_map:
            columns.add(f"{alias_map[alias]}.{col}")
    # 主外键列(如 *_id)由 merge 节点从 meta 库补全,不依赖向量召回,不计入必需召回列
    columns = {c for c in columns if not c.rsplit(".", 1)[-1].endswith("_id")}
    return {"tables": tables, "columns": columns, "values": values}


async def prepare_keywords(case: dict) -> dict:
    """复现线上关键词流程:jieba + LLM 扩展(column/value 两组),并缓存向量。"""
    query = case["query"]
    keywords = jieba.analyse.extract_tags(query, withWeight=False, allowPOS=ALLOW_POS) + [query]
    keywords = list(set(w for w in keywords if not is_numeric(w)))

    col_keywords, val_keywords = list(keywords), list(keywords)
    for prompt_name, target in [("extend_keywords_for_column_recall", "col"),
                                ("extend_keywords_for_value_recall", "val")]:
        try:
            prompt = PromptTemplate(template=load_prompt(prompt_name), input_variables=["query"])
            chain = prompt | llm | JsonOutputParser()
            result = await chain.ainvoke({"query": query})
            extra = [w for w in result if isinstance(w, str) and not is_numeric(w)]
            if target == "col":
                col_keywords = list(set(col_keywords + extra))
            else:
                val_keywords = list(set(val_keywords + extra))
        except Exception:
            pass  # LLM 扩展失败则只用 jieba 关键词

    emb_cache = {}
    for kw in set(col_keywords) | set(val_keywords):
        emb_cache[kw] = await embedding_client_manager.client.aembed_query(kw)
    return {"col_keywords": col_keywords, "val_keywords": val_keywords, "emb": emb_cache}


async def column_search(score: float, top_k: int, kw_vectors: list[list[float]]):
    ids = set()
    for vec in kw_vectors:
        result = await qdrant_client_manager.client.query_points(
            collection_name="queryforge_column", query=vec,
            score_threshold=score, limit=top_k)
        for point in result.points:
            ids.add(point.payload["id"])
    return ids


async def metric_search(score: float, top_k: int, kw_vectors: list[list[float]]):
    names = set()
    for vec in kw_vectors:
        result = await qdrant_client_manager.client.query_points(
            collection_name="queryforge_metric", query=vec,
            score_threshold=score, limit=top_k)
        for point in result.points:
            names.add(point.payload["name"])
    return names


async def value_search(score: float, top_k: int, keywords: list[str]):
    pairs = set()
    for kw in keywords:
        resp = await es_client_manager.client.search(
            index="queryforge", query={"match": {"value": kw}},
            min_score=score, size=top_k)
        for hit in resp.get("hits", {}).get("hits", []):
            src = hit["_source"]
            pairs.add((src["column_id"], str(src["value"])))
    return pairs


async def main():
    with open(EVALS_DIR / "datasets" / "dataset.yaml", encoding="utf-8") as f:
        cases = [c for c in yaml.safe_load(f) if c["category"] != "non_query"]

    embedding_client_manager.init()
    qdrant_client_manager.init()
    es_client_manager.init()

    # 1. 解析黄金必需集 + 准备关键词(与参数无关,只做一次)
    prepared = []
    for case in cases:
        golden = parse_golden(case["expected_sql"])
        kw = await prepare_keywords(case)
        # 指标需求:query 提及 GMV/AOV
        needed_metrics = {m for m in ("GMV", "AOV") if m in case["query"]}
        prepared.append({"case": case, "golden": golden, "kw": kw,
                         "needed_metrics": needed_metrics})
    print(f"用例 {len(prepared)} 条,关键词/向量准备完成")

    # 2. 网格扫描
    print(f"\n{'score':<6}{'topk':<6}{'列命中':<10}{'完全命中':<10}{'表命中':<10}{'噪音列':<8}{'值命中':<10}{'指标命中':<10}")
    for score in SCORES:
        for top_k in TOP_KS:
            col_hits, full_hits, tbl_hits, noise, val_hits, met_hits = 0, 0, 0, 0, 0, 0
            col_total, val_total, met_total = 0, 0, 0
            n = len(prepared)
            for item in prepared:
                golden, kw = item["golden"], item["kw"]
                col_vecs = [kw["emb"][w] for w in kw["col_keywords"]]
                cols = await column_search(score, top_k, col_vecs)
                metrics = await metric_search(score, top_k, col_vecs)
                pairs = await value_search(score, top_k, kw["val_keywords"])

                # 列命中
                needed = golden["columns"]
                got = len(needed & cols)
                col_hits += got
                col_total += len(needed)
                if needed and needed <= cols:
                    full_hits += 1
                tbl_hits += len(golden["tables"] & {c.split(".")[0] for c in cols})
                noise += max(0, len(cols) - len(needed & cols))
                # 值命中
                vals = {v for _, v in pairs}
                if golden["values"]:
                    val_hits += len(golden["values"] & vals)
                    val_total += len(golden["values"])
                # 指标命中
                met_hits += len(item["needed_metrics"] & metrics)
                met_total += len(item["needed_metrics"])

            def pct(a, b):
                return f"{a}/{b}={a / b * 100:.0f}%" if b else "-"

            print(f"{score:<6}{top_k:<6}{pct(col_hits, col_total):<10}{pct(full_hits, n):<10}"
                  f"{pct(tbl_hits, n * 1):<10}{noise / n:<8.1f}{pct(val_hits, val_total):<10}"
                  f"{pct(met_hits, met_total):<10}")

    await qdrant_client_manager.close()
    await es_client_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
