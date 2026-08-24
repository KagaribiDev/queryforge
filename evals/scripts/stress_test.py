"""强度测试脚本:50 条覆盖正常/模糊/陷阱/边界/对抗/时间/非查询的问题,并发调 HTTP API。

每条记录:状态(result/answer/error/empty)、阶段数、耗时、结果行数、错误信息、是否含 chart。
汇总统计各状态分布,输出明细 JSON。
"""
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

# (id, query, 期望类别)
CASES = [
    # ---- 正常查询 ----
    ("S01", "各品类的销售额是多少", "normal"),
    ("S02", "2025年1月份的GMV是多少", "normal"),
    ("S03", "哪个省份的订单最多", "normal"),
    ("S04", "销量最高的商品是什么", "normal"),
    ("S05", "各品牌的销售额占比", "normal"),
    ("S06", "2025年各个月的销售趋势", "normal"),
    ("S07", "各会员等级的客户数", "normal"),
    ("S08", "男性和女性客户分别消费了多少", "normal"),
    ("S09", "华东大区的销售额", "normal"),
    ("S10", "销售额最高的三个品类", "normal"),
    # ---- 模糊/口语化 ----
    ("S11", "这个月卖得怎么样", "ambiguous"),
    ("S12", "上个月赚了多少", "ambiguous"),
    ("S13", "去年生意好不好", "ambiguous"),
    ("S14", "哪个牌子卖得好", "ambiguous"),
    ("S15", "手机卖了多少", "ambiguous"),
    ("S16", "谁买得最多", "ambiguous"),
    ("S17", "广东人爱买什么", "ambiguous"),
    ("S18", "北京和上海哪边卖得多", "ambiguous"),
    ("S19", "生意怎么样", "ambiguous"),
    ("S20", "一共卖了多少件东西", "ambiguous"),
    # ---- 复合/深链 ----
    ("S21", "各品类在各省份的销售额", "complex"),
    ("S22", "3月份比2月份销售额增长了多少", "complex"),
    ("S23", "各品类的销售额和订单数分别是多少", "complex"),
    ("S24", "华东区黄金会员购买手机数码的金额", "complex"),
    ("S25", "2025年第一季度各品类的GMV", "complex"),
    ("S26", "销售额超过30000的品类有哪些", "complex"),
    ("S27", "订单数超过10笔的客户有哪些", "complex"),
    ("S28", "各品类平均订单金额", "complex"),
    ("S29", "1月和3月都买过东西的客户有多少", "complex"),
    ("S30", "每个品牌在每个月的销量", "complex"),
    # ---- 陷阱/不存在概念 ----
    ("S31", "平均客单价是多少", "trap"),
    ("S32", "一共有多少个客户", "trap"),
    ("S33", "一共有多少种商品", "trap"),
    ("S34", "退货的有多少单", "trap"),
    ("S35", "客户年龄分布是怎样的", "trap"),
    ("S36", "哪个渠道卖得好", "trap"),
    ("S37", "2024年的销售额是多少", "trap"),
    ("S38", "库存还有多少", "trap"),
    ("S39", "订单的折扣率是多少", "trap"),
    ("S40", "利润率是多少", "trap"),
    # ---- 边界/对抗输入 ----
    ("S41", "   ", "edge"),          # 纯空白(应 422)
    ("S42", "2025", "edge"),          # 纯数字
    ("S43", "😀😀😀", "edge"),          # emoji
    ("S44", "'; DROP TABLE fact_order;--", "edge"),  # SQL 注入试探
    ("S45", "SELECT * FROM fact_order", "edge"),     # 直接给 SQL
    ("S46", "GMV of February 2025", "edge"),         # 英文
    ("S47", "帮我删掉所有订单数据", "edge"),           # 危险操作请求
    ("S48", "统计一下2025年1月份各品类的销售额占比是多少顺便告诉我今天股票行情怎么样", "edge"),  # 混合请求
    ("S49", "你说这个数据对不对：2025年2月GMV是80009", "edge"),  # 求证型
    ("S50", "你好", "non_query"),    # 非查询
]


async def run_case(case: tuple, semaphore: asyncio.Semaphore) -> dict:
    cid, query, expect = case
    record = {"id": cid, "query": query[:50], "expect": expect,
              "status": "unknown", "elapsed": None, "stages": [],
              "has_result": False, "result_rows": None, "has_chart": False,
              "error": None, "http_error": None}
    async with semaphore:
        start = time.monotonic()
        try:
            data = json.dumps({"query": query}).encode("utf-8")
            reader, writer = await asyncio.open_connection("127.0.0.1", 8000)
            request = (f"POST /api/query HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n"
                       f"Content-Type: application/json\r\nContent-Length: {len(data)}\r\n"
                       f"Connection: close\r\n\r\n").encode() + data
            writer.write(request)
            await writer.drain()
            body = b""
            while True:
                chunk = await asyncio.wait_for(reader.read(65536), timeout=200)
                if not chunk:
                    break
                body += chunk
            writer.close()
            await writer.wait_closed()

            # 分离 HTTP 头与 body
            head, _, payload = body.partition(b"\r\n\r\n")
            status_line = head.split(b"\r\n")[0].decode(errors="ignore")
            if " 200" not in status_line:
                record["http_error"] = status_line
                record["status"] = "http_error"
                record["elapsed"] = round(time.monotonic() - start, 1)
                return record

            for line in payload.decode("utf-8", errors="ignore").split("\n"):
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except Exception:
                    record["error"] = f"SSE 解析失败: {line[:80]}"
                    record["status"] = "parse_error"
                    continue
                if "stage" in evt:
                    record["stages"].append(evt["stage"])
                elif "result" in evt:
                    record["has_result"] = True
                    record["result_rows"] = len(evt["result"])
                elif "chart" in evt:
                    record["has_chart"] = True
                elif "answer" in evt:
                    record["status"] = "answer"
                elif "error" in evt:
                    record["error"] = evt.get("detail", "")[:150] or evt["error"]

            if record["status"] == "answer":
                pass
            elif record["has_result"]:
                record["status"] = "result"
            elif record["error"]:
                record["status"] = "error"
            else:
                record["status"] = "empty"
        except Exception as e:
            record["error"] = str(e)[:150]
            record["status"] = "exception"
        record["elapsed"] = round(time.monotonic() - start, 1)
        return record


async def main():
    semaphore = asyncio.Semaphore(4)
    results = await asyncio.gather(*(run_case(c, semaphore) for c in CASES))

    report_dir = Path(__file__).resolve().parents[1] / "reports" / "stress"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"stress_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    from collections import Counter
    dist = Counter(r["status"] for r in results)
    print(f"状态分布: {dict(dist)}")
    print(f"明细报告: {report_path}")
    for r in results:
        if r["status"] not in ("result",):
            print(f"  [{r['id']}] {r['status']} | {r['query'][:30]} | "
                  f"{r['elapsed']}s | {r['error'] or ''} | stages={len(r['stages'])}")
    print("\n正常结果样例(前5条):")
    shown = 0
    for r in results:
        if r["status"] == "result" and shown < 5:
            print(f"  [{r['id']}] {r['query'][:25]} rows={r['result_rows']} chart={r['has_chart']} stages={len(r['stages'])}")
            shown += 1


if __name__ == "__main__":
    asyncio.run(main())
