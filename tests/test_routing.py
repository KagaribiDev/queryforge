"""路由纯函数测试:四个条件路由的三分支行为。

这些函数是 LangGraph 流程的"交通指挥",分支写错会导致流程断裂
(如校正死循环、兜底不触发),必须逐分支固化。
"""
from app.agent.graph import (
    route_after_classify,
    route_after_generate_sql,
    route_after_merge,
    route_after_validate,
)


class TestClassifyRoute:
    """入口分类路由:非查询→回答,查询→改写(多轮)后进召回链"""

    def test_non_query_goes_answer(self):
        assert route_after_classify({"is_query": False}) == "answer_question"

    def test_query_goes_rewrite(self):
        assert route_after_classify({"is_query": True}) == "rewrite_query"

    def test_missing_is_query_defaults_to_query(self):
        # 分类失败时按查询问题处理(节点兜底逻辑)
        assert route_after_classify({}) == "rewrite_query"


class TestMergeRoute:
    """合并召回路由:召回全空→兜底,否则并行筛选"""

    def test_empty_tables_goes_no_result(self):
        assert route_after_merge({"table_infos": []}) == "no_result"

    def test_has_tables_goes_filters(self):
        assert route_after_merge({"table_infos": [{"name": "fact_order"}]}) == [
            "filter_table_info",
            "filter_metric_info",
        ]


class TestGenerateSqlRoute:
    """生成 SQL 路由:正常→校验,NOT_A_QUERY→回答,SELECT NULL→兜底"""

    def test_normal_sql_goes_validate(self):
        assert route_after_generate_sql({"sql": "SELECT 1"}) == "validate_sql"

    def test_not_a_query_goes_answer(self):
        assert route_after_generate_sql({"sql": "NOT_A_QUERY"}) == "answer_question"

    def test_select_null_goes_no_result(self):
        assert route_after_generate_sql({"sql": "SELECT NULL;"}) == "no_result"

    def test_empty_sql_goes_validate(self):
        assert route_after_generate_sql({"sql": ""}) == "validate_sql"


class TestValidateRoute:
    """校验路由:通过→执行,失败未达上限→校正,失败达上限→强制执行"""

    def test_pass_goes_execute(self):
        assert route_after_validate({"error": None}) == "execute_sql"

    def test_fail_below_limit_goes_correct(self):
        assert route_after_validate({"error": "syntax error", "correct_count": 0}) == "correct_sql"

    def test_fail_at_limit_goes_execute(self):
        assert route_after_validate({"error": "syntax error", "correct_count": 3}) == "execute_sql"
