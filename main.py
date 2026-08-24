from fastapi import FastAPI

from app.api.routers.chat_router import chat_router
from app.core.lifespan import lifespan
from app.core.middleware import RequestIDMiddleware

app = FastAPI(
    title="QueryForge",
    description="LLM-powered, metadata-driven Text-to-SQL agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(chat_router)

app.add_middleware(RequestIDMiddleware)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000)
