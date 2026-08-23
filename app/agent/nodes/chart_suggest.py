from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import QueryForgeContext
from app.agent.llm import llm
from app.agent.state import QueryForgeState
from app.core.logging import logger
from app.prompt.prompt_loader import load_prompt

# 图表建议失败或非法时静默降级(前端只显示表格),不阻塞主流程
# 需要前端渲染图表的类型;table 类型表示"不适合图表",不发事件(表格本身已渲染)
VALID_CHART_TYPES = ("bar", "line", "pie")


async def chart_suggest(state: QueryForgeState, runtime: Runtime[QueryForgeContext]):
    """执行完成后为结果生成图表建议(LLM 判定图表类型与 x/y 字段)。

    输入只传列名与少量样例行,不传全量数据;失败时不发送 chart 事件,前端回退为纯表格。
    """
    writer = runtime.stream_writer
    writer({"stage": "生成图表"})

    result = state.get("result") or []
    if not result:
        return

    columns = list(result[0].keys()) if result else []
    sample_rows = result[:3]

    try:
        prompt = PromptTemplate(
            template=load_prompt("chart_suggest"),
            input_variables=["query", "columns", "row_count", "sample_rows"],
        )
        output_parser = JsonOutputParser()
        chain = prompt | llm | output_parser

        suggestion = await chain.ainvoke({
            "query": state["query"],
            "columns": ", ".join(columns),
            "row_count": len(result),
            "sample_rows": sample_rows,
        })

        chart_type = suggestion.get("type")
        x_field = suggestion.get("x")
        y_fields = suggestion.get("y") or []
        if not isinstance(y_fields, list):
            y_fields = [y_fields]

        # 合法性校验:类型合法、字段必须真实存在于结果列中
        if (chart_type in VALID_CHART_TYPES and x_field in columns
                and all(y in columns for y in y_fields)):
            chart = {"type": chart_type, "x": x_field, "y": y_fields,
                     "title": suggestion.get("title") or ""}
            logger.info(f"图表建议: {chart}")
            writer({"chart": chart})
        else:
            logger.warning(f"图表建议非法,已跳过: {suggestion}")
    except Exception as e:
        logger.warning(f"图表建议失败,前端回退为纯表格: {e}")
