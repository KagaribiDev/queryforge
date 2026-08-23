from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import QueryForgeContext
from app.agent.llm import llm
from app.agent.state import QueryForgeState
from app.core.logging import logger
from app.prompt.prompt_loader import load_prompt


def _format_history(history: list[dict]) -> str:
    if not history:
        return "(无)"
    lines = []
    for i, item in enumerate(history, 1):
        lines.append(f"{i}. 问题: {item.get('query', '')} | 结果: {item.get('result_summary', '')}")
    return "\n".join(lines)


async def rewrite_query(state: QueryForgeState, runtime: Runtime[QueryForgeContext]):
    """多轮指代消解:结合会话历史把当前问题改写为独立完整的查询。

    无历史或改写失败时原样返回(不阻塞);发生改写时推送「改写问题」阶段
    并在 detail 中展示改写结果,提升用户对多轮理解的感知。
    """
    writer = runtime.stream_writer
    original = state["query"]
    history = state.get("conversation_history") or []

    if not history:
        return {"query": original}

    try:
        prompt = PromptTemplate(template=load_prompt("rewrite_query"),
                                input_variables=["history", "query"])
        output_parser = StrOutputParser()
        chain = prompt | llm | output_parser

        rewritten = (await chain.ainvoke({
            "history": _format_history(history),
            "query": original,
        })).strip()

        if not rewritten or rewritten == original:
            logger.info(f"无需改写,沿用原问题: {original}")
            return {"query": original}

        logger.info(f"问题改写: [{original}] → [{rewritten}]")
        writer({"stage": "改写问题", "detail": f"已结合前文补全为: {rewritten}"})
        return {"query": rewritten}
    except Exception as e:
        logger.warning(f"问题改写失败,沿用原问题: {e}")
        return {"query": original}
