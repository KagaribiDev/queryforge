import asyncio

from langgraph.constants import START, END
from langgraph.graph import StateGraph

from app.agent.context import QueryForgeContext
from app.agent.nodes.add_context import add_context
from app.agent.nodes.answer_question import answer_question
from app.agent.nodes.chart_suggest import chart_suggest
from app.agent.nodes.classify_query import classify_query
from app.agent.nodes.column_recall import column_recall
from app.agent.nodes.correct_sql import correct_sql
from app.agent.nodes.execute_sql import execute_sql
from app.agent.nodes.extract_keywords import extract_keywords
from app.agent.nodes.filter_metric_info import filter_metric_info
from app.agent.nodes.filter_table_info import filter_table_info
from app.agent.nodes.generate_sql import generate_sql
from app.agent.nodes.merge_retrieved_info import merge_retrieved_info
from app.agent.nodes.metric_recall import metric_recall
from app.agent.nodes.no_result import no_result
from app.agent.nodes.rewrite_query import rewrite_query
from app.agent.nodes.validate_sql import validate_sql
from app.agent.nodes.value_recall import value_recall
from app.agent.state import QueryForgeState
from app.clients.embedding_client import embedding_client_manager
from app.clients.es_client import es_client_manager
from app.clients.mysql_client import meta_client_manager, dw_client_manager
from app.clients.qdrant_client import qdrant_client_manager
from app.core.context import request_id_ctx_var
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_repository_qdrant import ColumnQdrantRepository
from app.repositories.qdrant.metric_repository_qdrant import MetricQdrantRepository

# SQL 校验失败后允许校正的最大次数，防止 校验→校正 循环无限执行
MAX_CORRECT_COUNT = 3


def route_after_classify(state: QueryForgeState) -> str:
    """问题分类后的路由:非查询问题直接走 answer_question,跳过整条召回链。"""
    if state.get("is_query") is False:
        return "answer_question"
    return "rewrite_query"


def route_after_validate(state: QueryForgeState) -> str:
    """
    SQL 校验后的路由：
    - 校验通过(error 为空) → execute_sql
    - 校验失败且校正次数未达上限 → correct_sql(重新校正后再回 validate_sql)
    - 校验失败且校正次数已达上限 → execute_sql(交由执行节点抛出最终错误)
    """
    if state["error"] is None:
        return "execute_sql"
    if state.get("correct_count", 0) < MAX_CORRECT_COUNT:
        return "correct_sql"
    return "execute_sql"


def route_after_merge(state: QueryForgeState) -> str | list[str]:
    """合并召回信息后的路由：三路召回全部落空时走 no_result 兜底结束，
    否则并行进入表信息与指标信息的筛选。"""
    if not state.get("table_infos"):
        return "no_result"
    return ["filter_table_info", "filter_metric_info"]


def route_after_generate_sql(state: QueryForgeState) -> str:
    """生成 SQL 后的路由：
    - LLM 判定为非查询问题(NOT_A_QUERY) → answer_question 直接回答，跳过校验/执行
    - LLM 生成 SELECT NULL(无法映射到任何表) → no_result 兜底
    - 其余 → validate_sql 正常校验
    """
    sql = (state.get("sql") or "").strip().rstrip(";").strip()
    if sql.upper() == "NOT_A_QUERY":
        return "answer_question"
    if sql.upper() == "SELECT NULL":
        return "no_result"
    return "validate_sql"


graph_builder = StateGraph(state_schema=QueryForgeState, context_schema=QueryForgeContext)

graph_builder.add_node("classify_query", classify_query)
graph_builder.add_node("rewrite_query", rewrite_query)
graph_builder.add_node("extract_keywords", extract_keywords)
graph_builder.add_node("column_recall", column_recall)
graph_builder.add_node("value_recall", value_recall)
graph_builder.add_node("metric_recall", metric_recall)
graph_builder.add_node("merge_retrieved_info", merge_retrieved_info)
graph_builder.add_node("filter_table_info", filter_table_info)
graph_builder.add_node("filter_metric_info", filter_metric_info)
graph_builder.add_node("no_result", no_result)
graph_builder.add_node("answer_question", answer_question)
graph_builder.add_node("add_context", add_context)
graph_builder.add_node("generate_sql", generate_sql)
graph_builder.add_node("validate_sql", validate_sql)
graph_builder.add_node("correct_sql", correct_sql)
graph_builder.add_node("execute_sql", execute_sql)
graph_builder.add_node("chart_suggest", chart_suggest)

graph_builder.add_edge(START, "classify_query")
graph_builder.add_conditional_edges(
    "classify_query",
    route_after_classify,
    path_map={"rewrite_query": "rewrite_query", "answer_question": "answer_question"},
)
graph_builder.add_edge("rewrite_query", "extract_keywords")
graph_builder.add_edge("extract_keywords", "column_recall")
graph_builder.add_edge("extract_keywords", "value_recall")
graph_builder.add_edge("extract_keywords", "metric_recall")
graph_builder.add_edge("value_recall", "merge_retrieved_info")
graph_builder.add_edge("column_recall", "merge_retrieved_info")
graph_builder.add_edge("metric_recall", "merge_retrieved_info")
graph_builder.add_conditional_edges(
    "merge_retrieved_info",
    route_after_merge,
    path_map={
        "filter_table_info": "filter_table_info",
        "filter_metric_info": "filter_metric_info",
        "no_result": "no_result",
    },
)
graph_builder.add_edge("no_result", END)
graph_builder.add_edge("filter_table_info", "add_context")
graph_builder.add_edge("filter_metric_info", "add_context")
graph_builder.add_edge("add_context", "generate_sql")
graph_builder.add_conditional_edges(
    "generate_sql",
    route_after_generate_sql,
    path_map={
        "validate_sql": "validate_sql",
        "no_result": "no_result",
        "answer_question": "answer_question",
    },
)
graph_builder.add_edge("answer_question", END)
graph_builder.add_conditional_edges(
    "validate_sql",
    route_after_validate,
    path_map={"execute_sql": "execute_sql", "correct_sql": "correct_sql"},
)
graph_builder.add_edge("correct_sql", "validate_sql")
graph_builder.add_edge("execute_sql", "chart_suggest")
graph_builder.add_edge("chart_suggest", END)
graph = graph_builder.compile()


async def main():
    request_id_ctx_var.set("1")
    state = QueryForgeState(query="统计一下2025年1月份各品类的销售额占比")

    qdrant_client_manager.init()
    column_qdrant_repository = ColumnQdrantRepository(qdrant_client_manager.client)
    metric_qdrant_repository = MetricQdrantRepository(qdrant_client_manager.client)

    embedding_client_manager.init()
    embedding_client = embedding_client_manager.client

    es_client_manager.init()
    value_es_repository = ValueESRepository(es_client_manager.client)

    meta_client_manager.init()
    dw_client_manager.init()
    async with (meta_client_manager.session_factory() as meta_session,
                dw_client_manager.session_factory() as dw_session):
        meta_mysql_repository = MetaMySQLRepository(meta_session)
        dw_mysql_repository = DWMySQLRepository(dw_session)
        context = QueryForgeContext(
            metric_qdrant_repository=metric_qdrant_repository,
            value_es_repository=value_es_repository,
            column_qdrant_repository=column_qdrant_repository,
            embedding_client=embedding_client,
            meta_mysql_repository=meta_mysql_repository,
            dw_mysql_repository=dw_mysql_repository)

        async for chunk in graph.astream(input=state, context=context, stream_mode="custom"):
            print(chunk)


if __name__ == "__main__":
    print(graph.get_graph().draw_mermaid())
