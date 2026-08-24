"""「校验 → 校正 → 再校验」循环的集成测试(收编自根目录 test_correct_loop.py)。

需要真实 MySQL(dw 库)与 LLM 调用,默认跳过;本地手动运行:
    pytest -m integration
"""
import asyncio

import pytest

from app.agent.context import QueryForgeContext
from app.agent.graph import graph
from app.agent.state import QueryForgeState
from app.clients.mysql_client import dw_client_manager
from app.repositories.mysql.dw_mysql_repository import DWMySQLRepository

pytestmark = pytest.mark.integration

# 与 meta 库一致的 fact_order 列信息(供 correct_sql 的 LLM 修复时参考)
TABLE_INFOS = [{
    "name": "fact_order",
    "role": "fact",
    "description": "订单事实表,记录每一笔订单",
    "columns": [
        {"name": "order_id", "type": "varchar(32)", "role": "primary_key",
         "description": "订单唯一标识", "alias": ["订单号"], "examples": []},
        {"name": "order_amount", "type": "float", "role": "measure",
         "description": "订单金额", "alias": ["销售额", "订单金额"], "examples": [8999.0]},
        {"name": "order_quantity", "type": "int", "role": "measure",
         "description": "购买数量", "alias": ["销量", "件数"], "examples": [2]},
        {"name": "date_id", "type": "varchar(20)", "role": "foreign_key",
         "description": "日期维度外键", "alias": ["日期"], "examples": []},
        {"name": "customer_id", "type": "varchar(20)", "role": "foreign_key",
         "description": "客户外键", "alias": ["客户"], "examples": []},
        {"name": "product_id", "type": "varchar(20)", "role": "foreign_key",
         "description": "商品外键", "alias": ["商品"], "examples": []},
        {"name": "region_id", "type": "varchar(20)", "role": "foreign_key",
         "description": "地区外键", "alias": ["地区"], "examples": []},
    ],
}]

BAD_SQL = "SELECT SUM(order_amout) FROM fact_order"  # order_amout 拼写错误


def test_correct_loop_structure():
    """结构断言:回边与条件边存在(无需外部服务,始终可跑)。"""
    mermaid = graph.get_graph().draw_mermaid()
    assert "correct_sql --> validate_sql" in mermaid
    assert "validate_sql -.-> correct_sql" in mermaid


async def _run_loop():
    """从 validate_sql 起重建与主图一致的结构,注入拼错列名的 SQL 走真实循环。"""
    from langgraph.constants import END, START
    from langgraph.graph import StateGraph

    from app.agent.graph import route_after_validate
    from app.agent.nodes.correct_sql import correct_sql
    from app.agent.nodes.execute_sql import execute_sql
    from app.agent.nodes.validate_sql import validate_sql

    subgraph_builder = StateGraph(state_schema=QueryForgeState, context_schema=QueryForgeContext)
    subgraph_builder.add_node("validate_sql", validate_sql)
    subgraph_builder.add_node("correct_sql", correct_sql)
    subgraph_builder.add_node("execute_sql", execute_sql)
    subgraph_builder.add_edge(START, "validate_sql")
    subgraph_builder.add_conditional_edges(
        "validate_sql",
        route_after_validate,
        path_map={"execute_sql": "execute_sql", "correct_sql": "correct_sql"},
    )
    subgraph_builder.add_edge("correct_sql", "validate_sql")
    subgraph_builder.add_edge("execute_sql", END)
    subgraph = subgraph_builder.compile()

    state = QueryForgeState(
        query="所有订单的总销售额是多少",
        sql=BAD_SQL,
        error=None,
        correct_count=0,
        table_infos=TABLE_INFOS,
        metric_infos=[],
        date_info={"date": "2026-08-17", "weekday": "星期日", "quarter": "Q3"},
        db_info={"dialect": "mysql", "version": "8.0"},
    )

    dw_client_manager.init()
    try:
        async with dw_client_manager.session_factory() as dw_session:
            context = QueryForgeContext(
                dw_mysql_repository=DWMySQLRepository(dw_session),
                meta_mysql_repository=None,
                metric_qdrant_repository=None,
                column_qdrant_repository=None,
                value_es_repository=None,
                embedding_client=None,
            )
            events = []
            async for chunk in subgraph.astream(
                    input=state, context=context, stream_mode="custom"):
                events.append(chunk)
    finally:
        await dw_client_manager.close()

    stages = [e.get("stage") for e in events if isinstance(e, dict) and "stage" in e]
    results = [e for e in events if isinstance(e, dict) and "result" in e]
    return stages, results


@pytest.mark.integration
def test_correct_loop_full_cycle():
    """真实行为:校验失败 → 校正 → 再校验 → 执行,事件序列完整且返回真实结果。"""
    stages, results = asyncio.run(_run_loop())

    assert "校正SQL" in stages, "校正SQL 阶段未触发"
    assert stages.count("验证SQL语句") >= 2, "校正后未回到校验节点"
    assert stages[-1] == "执行SQL语句", "校验通过后未执行 SQL"
    assert results, "没有返回执行结果"
