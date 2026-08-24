"""验证数据集里的黄金 SQL 全部可执行且结果非空(一次性校验脚本)。"""
import asyncio
from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import create_async_engine

EVALS_DIR = Path(__file__).resolve().parents[1]
DATASET = EVALS_DIR / "datasets" / "dataset.yaml"


async def main():
    with open(DATASET, encoding="utf-8") as f:
        cases = yaml.safe_load(f)

    engine = create_async_engine('mysql+asyncmy://queryforge:QueryForge.123@127.0.0.1:3306/dw')
    passed, failed = 0, []
    async with engine.connect() as conn:
        for case in cases:
            if case["category"] == "non_query":
                continue
            try:
                result = await conn.exec_driver_sql(case["expected_sql"])
                rows = result.fetchall()
                if not rows:
                    failed.append((case["id"], "EMPTY_RESULT"))
                else:
                    passed += 1
                    print(f"[OK] {case['id']} rows={len(rows)} first={rows[0][:3]}")
            except Exception as e:
                failed.append((case["id"], str(e)[:120]))
                print(f"[FAIL] {case['id']} {e}")

    await engine.dispose()
    print(f"\n通过 {passed}/{len([c for c in cases if c['category'] != 'non_query'])}")
    if failed:
        print("失败明细:")
        for cid, err in failed:
            print(f"  {cid}: {err}")
    else:
        print("全部黄金 SQL 验证通过")


if __name__ == "__main__":
    asyncio.run(main())
