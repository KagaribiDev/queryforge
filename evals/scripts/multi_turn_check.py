"""多轮改写评估:10 组对话场景,验证「改写问题」节点的指代消解准确率。

直接调用改写链路(与线上同一 prompt + LLM),比对改写结果与期望改写。
用法: python evals/scripts/multi_turn_check.py
"""
import asyncio
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = EVALS_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from app.agent.llm import llm
from app.agent.nodes.rewrite_query import _format_history
from app.prompt.prompt_loader import load_prompt

# (历史轮次, 当前问题, 期望改写)
# 期望改写用"关键要素"表达:改写结果必须包含这些语义要素(容忍"那/呢/？"等语气词差异)
SCENARIOS = [
    ([{"query": "2025年2月份的GMV是多少", "result_summary": "1行 | GMV=80009.0"}],
     "那3月份呢", ["3月份", "GMV"]),
    ([{"query": "2025年2月份的GMV是多少", "result_summary": "1行 | GMV=80009.0"},
      {"query": "2025年3月份的GMV是多少", "result_summary": "1行 | GMV=90120.0"}],
     "那4月份呢", ["4月份", "GMV"]),
    ([{"query": "各品类的销售额是多少", "result_summary": "6行 | category=手机数码, sales_amount=194771.0"}],
     "那销量呢", ["销量", "品类"]),
    ([{"query": "各品类的销售额是多少", "result_summary": "6行 | category=手机数码, sales_amount=194771.0"},
      {"query": "各品类的销量是多少", "result_summary": "6行 | 品类=手机数码, 销量=29"}],
     "广东的呢", ["广东", "销售额"]),
    ([{"query": "2025年1月份的销售额是多少", "result_summary": "1行 | 109030.5"}],
     "2月呢", ["2月份", "销售额"]),
    ([{"query": "哪个省份的订单最多", "result_summary": "1行 | 广东省"}],
     "那第二名呢", ["第二", "省份"]),
    ([{"query": "各品牌的销售额占比是多少", "result_summary": "15行 | 苹果=25.8%"}],
     "只看前5个", ["前5", "占比"]),
    ([{"query": "手机数码品类的GMV是多少", "result_summary": "1行 | GMV=194771.0"}],
     "家用电器呢", ["家用电器", "GMV"]),
    ([{"query": "2025年2月份的GMV是多少", "result_summary": "1行 | GMV=80009.0"}],
     "各品类的销售额占比是多少", ["各品类", "占比"]),  # 无指代,应原样输出
    ([{"query": "2025年2月份的GMV是多少", "result_summary": "1行 | GMV=80009.0"}],
     "你好", ["你好"]),  # 非查询,应原样输出
]


async def main():
    prompt = PromptTemplate(template=load_prompt("rewrite_query"),
                            input_variables=["history", "query"])
    chain = prompt | llm | StrOutputParser()

    passed = 0
    for i, (history, query, required_keys) in enumerate(SCENARIOS, 1):
        result = (await chain.ainvoke({
            "history": _format_history(history),
            "query": query,
        })).strip()
        ok = all(k in result for k in required_keys)
        passed += ok
        print(f"[{'✓' if ok else '✗'}] 场景{i}: 「{query}」 → 「{result}」"
              + ("" if ok else f" (缺少要素: {[k for k in required_keys if k not in result]})"))

    print(f"\n改写准确率(语义要素判定): {passed}/{len(SCENARIOS)} = {passed / len(SCENARIOS) * 100:.0f}%")


if __name__ == "__main__":
    asyncio.run(main())
