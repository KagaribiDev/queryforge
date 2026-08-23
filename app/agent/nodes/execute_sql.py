from langgraph.runtime import Runtime

from app.agent.context import QueryForgeContext
from app.agent.state import QueryForgeState
from app.core.logging import logger
from app.repositories.mysql.dw_mysql_repository import DWMySQLRepository


async def execute_sql(state: QueryForgeState, runtime: Runtime[QueryForgeContext]):
    writer = runtime.stream_writer
    writer({"stage": "执行SQL语句"})

    sql = state["sql"]
    dw_mysql_repository: DWMySQLRepository = runtime.context['dw_mysql_repository']

    try:
        result = await dw_mysql_repository.execute_sql(sql)
        logger.info(f"SQL执行结果: {result}")
        # 结果先经 SSE 推送,同时写入 state 供图表建议节点使用
        writer({"result": result})
        return {"result": result}
    except Exception as e:
        logger.error(f"SQL执行失败: {e}")
        raise
