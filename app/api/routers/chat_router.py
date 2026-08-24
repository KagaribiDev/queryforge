import json
import uuid

from fastapi import APIRouter, Depends
from starlette.responses import StreamingResponse

from app.api.deps import get_chat_service
from app.schemas.chat import QuerySchema
from app.service.conversation_service import clear_all_history, clear_history

chat_router = APIRouter(prefix="/api")


@chat_router.post("/query")
async def date_query(query: QuerySchema, chat_service=Depends(get_chat_service)):
    # 会话管理:客户端未传 session_id 则服务端新建,并在首个 SSE 事件回传供前端保存
    session_id = query.session_id or uuid.uuid4().hex

    async def event_stream():
        # 首事件:告知前端会话标识(仅新建会话时客户端才需要保存)
        yield f"data: {json.dumps({'session_id': session_id}, ensure_ascii=False)}\n\n"
        try:
            async for chunk in chat_service.stream_chat(query.query, session_id):
                yield f"data: {json.dumps(chunk, ensure_ascii=False, default=str)}\n\n"
        except Exception as e:
            # 给用户友好的提示，原始错误信息放入 detail 供排查
            yield f"data: {json.dumps({'error': '查询执行失败，请尝试换个说法重新提问', 'detail': str(e)}, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )


@chat_router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """删除单个会话:清空 Redis 中该会话的历史记录。"""
    await clear_history(session_id)
    return {"ok": True, "session_id": session_id}


@chat_router.delete("/sessions")
async def delete_all_sessions():
    """清空所有会话:删除 Redis 中全部会话历史,防止数据无限增长。"""
    await clear_all_history()
    return {"ok": True, "cleared": "all"}
