import redis.asyncio as aioredis

from app.config.app_config import RedisConfig, app_config


class RedisClientManager:
    def __init__(self, config: RedisConfig):
        self.config = config
        self.client: aioredis.Redis | None = None

    def init(self):
        self.client = aioredis.Redis(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            decode_responses=True,
        )

    async def close(self):
        if self.client:
            await self.client.aclose()


redis_client_manager = RedisClientManager(app_config.redis)
