"""LangGraph 图结构测试:编译成功、16 个节点齐全、关键边存在。

防止后续加节点/改路由时无意破坏流程结构
(如校验-校正回边丢失、图表节点断链、入口分支丢失)。
"""
from app.agent.graph import graph

EXPECTED_NODES = [
    "classify_query",
    "rewrite_query",
    "extract_keywords",
    "column_recall",
    "metric_recall",
    "value_recall",
    "merge_retrieved_info",
    "filter_table_info",
    "filter_metric_info",
    "no_result",
    "answer_question",
    "add_context",
    "generate_sql",
    "validate_sql",
    "correct_sql",
    "execute_sql",
    "chart_suggest",
]


def _mermaid() -> str:
    return graph.get_graph().draw_mermaid()


def test_graph_compiles():
    mermaid = _mermaid()
    assert "__start__" in mermaid and "__end__" in mermaid


def test_all_17_nodes_present():
    mermaid = _mermaid()
    missing = [n for n in EXPECTED_NODES if n not in mermaid]
    assert not missing, f"图中缺少节点: {missing}"


def test_start_goes_classify():
    assert "__start__ --> classify_query" in _mermaid()


def test_classify_has_two_branches():
    mermaid = _mermaid()
    assert "classify_query -.-> answer_question" in mermaid
    assert "classify_query -.-> rewrite_query" in mermaid


def test_rewrite_to_extract():
    """多轮改写节点必须接到召回链入口。"""
    assert "rewrite_query --> extract_keywords" in _mermaid()


def test_correct_loop_back_edge():
    """校验-校正循环回边必须存在,否则校正结果无处可去。"""
    assert "correct_sql --> validate_sql" in _mermaid()


def test_validate_has_three_branches():
    mermaid = _mermaid()
    assert "validate_sql -.-> execute_sql" in mermaid
    assert "validate_sql -.-> correct_sql" in mermaid


def test_execute_to_chart_to_end():
    mermaid = _mermaid()
    assert "execute_sql --> chart_suggest" in mermaid
    assert "chart_suggest --> __end__" in mermaid


def test_no_result_and_answer_terminate():
    mermaid = _mermaid()
    assert "no_result --> __end__" in mermaid
    assert "answer_question --> __end__" in mermaid
