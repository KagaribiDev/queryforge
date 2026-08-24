from langchain_huggingface import HuggingFaceEndpointEmbeddings
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import QueryForgeContext
from app.agent.state import QueryForgeState
from app.core.logging import logger
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_repository_qdrant import ColumnQdrantRepository
from app.repositories.qdrant.metric_repository_qdrant import MetricQdrantRepository
from app.service.conversation_service import (
    append_history,
    build_result_summary,
    get_history,
)


class ChatService:
    def __init__(self, graph: CompiledStateGraph,
                 embedding_client: HuggingFaceEndpointEmbeddings,
                 meta_mysql_repository: MetaMySQLRepository,
                 dw_mysql_repository: DWMySQLRepository,
                 column_qdrant_repository: ColumnQdrantRepository,
                 value_es_repository: ValueESRepository,
                 metric_qdrant_repository: MetricQdrantRepository,
                 ):
        self.graph = graph
        self.embedding_client = embedding_client
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository
        self.column_qdrant_repository = column_qdrant_repository
        self.value_es_repository = value_es_repository
        self.metric_qdrant_repository = metric_qdrant_repository

    async def stream_chat(self, query: str, session_id: str = ""):
        # 多轮记忆:读取该会话最近 N 轮历史,注入 state 供「改写问题」节点做指代消解
        history = await get_history(session_id)
        if history:
            logger.info(f"会话 {session_id} 载入 {len(history)} 轮历史")

        state = QueryForgeState(query=query, conversation_history=history)
        context = QueryForgeContext(
            metric_qdrant_repository=self.metric_qdrant_repository,
            value_es_repository=self.value_es_repository,
            column_qdrant_repository=self.column_qdrant_repository,
            embedding_client=self.embedding_client,
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository)

        final_state = None
        async for mode, chunk in self.graph.astream(
                input=state, context=context, stream_mode=["custom", "values"]):
            if mode == "custom":
                yield chunk
            else:
                final_state = chunk  # values 模式最后一次输出即最终 state

        # 所有轮次都写入会话历史(查询/回答/无结果),保证多轮上下文完整
        if final_state:
            executed_query = final_state.get("query") or query
            if final_state.get("result"):
                summary = build_result_summary(final_state["result"])
            elif final_state.get("answer"):
                answer = str(final_state["answer"]).strip().replace("\n", " ")
                summary = f"回答: {answer[:60]}"
            else:
                summary = "无查询结果"
            await append_history(session_id, executed_query, summary)
            logger.info(f"会话 {session_id} 已写入历史: [{executed_query}] → {summary}")
