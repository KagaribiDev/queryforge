"""会话历史服务:基于 Redis List 存取多轮对话记录,供「改写问题」节点做指代消解。

存储结构:
    key:  conversation:{session_id}
    value: Redis List,每元素为 JSON 字符串
           {"query": "用户问题", "result_summary": "结果概要", "ts": 时间戳}
保留最近 max_history 轮(在写入时 LTRIM 裁剪)。
"""
import json
import time

from app.clients.redis_client import redis_client_manager
from app.config.app_config import app_config


def _key(session_id: str) -> str:
    return f"conversation:{session_id}"


def build_result_summary(result: list[dict]) -> str:
    """从执行结果生成一句话概要:行数 + 首行列名与取值。零额外 LLM 调用。"""
    if not result:
        return "0行"
    head = result[0]
    cols = list(head.keys())
    preview = ", ".join(f"{c}={head[c]}" for c in cols[:3])
    more = "..." if len(result) > 1 else ""
    return f"{len(result)}行 | {preview}{more}"


async def get_history(session_id: str, max_rounds: int | None = None) -> list[dict]:
    """读取最近 N 轮对话记录(按时间正序返回)。"""
    if not session_id:
        return []
    limit = max_rounds or app_config.redis.max_history
    client = redis_client_manager.client
    if client is None:
        return []
    raw_list = await client.lrange(_key(session_id), -limit, -1)
    history = []
    for raw in raw_list:
        try:
            history.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
    return history


async def append_history(session_id: str, query: str, result_summary: str):
    """写入一轮对话记录,并裁剪到最近 max_history 轮。"""
    if not session_id:
        return
    client = redis_client_manager.client
    if client is None:
        return
    record = json.dumps({
        "query": query,
        "result_summary": result_summary,
        "ts": int(time.time()),
    }, ensure_ascii=False)
    key = _key(session_id)
    await client.rpush(key, record)
    await client.ltrim(key, -app_config.redis.max_history, -1)


async def clear_history(session_id: str):
    """清空会话历史(新对话)。"""
    if not session_id:
        return
    client = redis_client_manager.client
    if client is None:
        return
    await client.delete(_key(session_id))


async def clear_all_history():
    """清空所有会话历史(清空聊天记录)。"""
    client = redis_client_manager.client
    if client is None:
        return
    async for key in client.scan_iter(match="conversation:*"):
        await client.delete(key)
