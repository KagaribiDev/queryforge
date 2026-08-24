"""Prompt 模板测试:防止 LangChain PromptTemplate 花括号转义回归(历史 bug)。

背景:classify_query.prompt 曾把 JSON 示例 {"is_query": true} 误写成单花括号,
PromptTemplate 将其识别为模板变量导致 format 时 missing variables 报错,
当时所有请求的分类全部失败。本测试对全部 prompt 做两重防护:
1. 单花括号变量中不得出现 JSON 示例键(is_query/type/x/y/title 等);
2. 每个模板按推断变量渲染一遍,确保无运行时错误。
"""
import re

import pytest
from langchain_core.prompts import PromptTemplate

from app.prompt.prompt_loader import load_prompt

# 与当前代码中 load_prompt 调用一一对应
ALL_PROMPTS = [
    "answer_question",
    "chart_suggest",
    "classify_query",
    "correct_sql",
    "extend_keywords_for_column_recall",
    "extend_keywords_for_metric_recall",
    "extend_keywords_for_value_recall",
    "filter_metric_info",
    "filter_table_info",
    "generate_sql",
]

# prompt 里 JSON 示例常用的键,若以单花括号模板变量出现说明未转义
FORBIDDEN_TEMPLATE_KEYS = {"is_query", "type", "x", "y", "title"}


def _single_brace_vars(template: str) -> set[str]:
    """提取单花括号模板变量(排除 {{ 转义形式)。"""
    return set(re.findall(r"\{(\w+)\}", template))


def test_all_prompts_exist_and_loadable():
    for name in ALL_PROMPTS:
        content = load_prompt(name)
        assert content.strip(), f"{name}.prompt 内容为空"


def test_no_unintended_template_vars():
    """单花括号变量中不得混入 JSON 示例键(转义回归防护)。"""
    for name in ALL_PROMPTS:
        vars_ = _single_brace_vars(load_prompt(name))
        leaked = vars_ & FORBIDDEN_TEMPLATE_KEYS
        assert not leaked, (
            f"{name}.prompt 中存在未转义的 JSON 键: {sorted(leaked)}。"
            f"请改用双花括号转义(如 {{{{'is_query'}}}})。"
        )


def test_all_templates_render():
    """按推断出的模板变量填充后渲染,确保模板可被 PromptTemplate 正常使用。

    answer_question.prompt 是纯 system 提示词(无变量,human 消息由代码注入),
    因此只断言渲染成功、不要求包含填充值。
    """
    for name in ALL_PROMPTS:
        template = load_prompt(name)
        prompt = PromptTemplate(template=template)
        rendered = prompt.format(**{v: "测试值" for v in prompt.input_variables})
        assert isinstance(rendered, str) and rendered.strip(), f"{name}.prompt 渲染结果异常"
