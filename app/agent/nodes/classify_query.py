from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import QueryForgeContext
from app.agent.llm import llm
from app.agent.state import QueryForgeState
from app.core.logging import logger
from app.prompt.prompt_loader import load_prompt


async def classify_query(state: QueryForgeState, runtime: Runtime[QueryForgeContext]):
    """流程入口:判断用户输入是否为数据查询请求。非查询问题直接路由到 answer_question,
    避免无谓地走完整条召回链,提升用户体验。"""
    writer = runtime.stream_writer
    writer({"stage": "理解问题"})

    query = state["query"]

    try:
        prompt = PromptTemplate(template=load_prompt("classify_query"), input_variables=["query"])
        output_parser = JsonOutputParser()
        chain = prompt | llm | output_parser

        result = await chain.ainvoke({"query": query})
        is_query = bool(result.get("is_query", True))
        logger.info(f"问题分类结果: is_query={is_query}")
        return {"is_query": is_query}
    except Exception as e:
        # 分类失败时按查询问题处理,走正常流程兜底,不让分类器成为单点故障
        logger.error(f"问题分类失败,默认按查询问题处理: {e}")
        return {"is_query": True}
