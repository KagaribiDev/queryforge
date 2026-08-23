from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import QueryForgeContext
from app.agent.llm import llm
from app.agent.state import QueryForgeState
from app.core.logging import logger
from app.prompt.prompt_loader import load_prompt


async def answer_question(state: QueryForgeState, runtime: Runtime[QueryForgeContext]):
    """非查询问题兜底：不再生成/校验/执行 SQL，直接调用 LLM 以助手身份回答用户。"""
    writer = runtime.stream_writer
    writer({"stage": "回答问题"})

    query = state["query"]

    try:
        # 系统提示词单独注入，保证回答专业、边界清晰；用户消息仅作为 human 输入
        prompt = ChatPromptTemplate.from_messages([
            ("system", load_prompt("answer_question")),
            ("human", "{query}"),
        ])
        output_parser = StrOutputParser()
        chain = prompt | llm | output_parser

        result = await chain.ainvoke({"query": query})

        logger.info(f"LLM直接回答: {result}")
        writer({"answer": result})
        # 回答写入 state,供会话历史记录(非查询轮次也保留上下文)
        return {"answer": result}
    except Exception as e:
        logger.error(f"回答问题失败: {e}")
        raise
