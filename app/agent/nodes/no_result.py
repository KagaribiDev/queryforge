from langgraph.runtime import Runtime

from app.agent.context import QueryForgeContext
from app.agent.state import QueryForgeState
from app.core.logging import logger


async def no_result(state: QueryForgeState, runtime: Runtime[QueryForgeContext]):
    """三路召回全部落空时兜底：向用户返回友好提示并结束流程，
    避免 LLM 在无任何表/字段信息的情况下生成并执行 SELECT NULL 之类的无效 SQL。"""
    writer = runtime.stream_writer
    writer({
        "error": "没有找到与问题相关的数据，请尝试换个说法提问",
        "detail": "知识库中没有与问题匹配的表/字段/指标信息，无法生成可执行的查询",
    })
    logger.warning(f"召回结果为空，query={state['query']}")
