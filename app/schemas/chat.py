from typing import Optional

from pydantic import BaseModel, field_validator


class QuerySchema(BaseModel):
    query: str
    session_id: Optional[str] = None  # 会话标识:传则续接多轮记忆,不传则服务端新建

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query 不能为空")
        return v
