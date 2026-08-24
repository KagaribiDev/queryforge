"""QuerySchema 入参校验测试:防止空 query 流入 Agent 流程(历史 bug)。"""
import pytest
from pydantic import ValidationError

from app.schemas.chat import QuerySchema


class TestQuerySchema:
    def test_empty_rejected(self):
        with pytest.raises(ValidationError):
            QuerySchema(query="")

    def test_blank_rejected(self):
        with pytest.raises(ValidationError):
            QuerySchema(query="   ")

    def test_whitespace_only_rejected(self):
        with pytest.raises(ValidationError):
            QuerySchema(query="\t\n ")

    def test_normal_query_ok(self):
        assert QuerySchema(query="2025年1月销售额").query == "2025年1月销售额"

    def test_query_is_stripped(self):
        assert QuerySchema(query="  统计一下销售额  ").query == "统计一下销售额"
