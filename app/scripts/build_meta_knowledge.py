import argparse
import asyncio
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# 允许以 `python app/scripts/build_meta_knowledge.py` 直接运行
sys.path.insert(0, str(Path(__file__).parents[2]))

from app.clients.embedding_client import embedding_client_manager
from app.clients.es_client import es_client_manager
from app.clients.mysql_client import dw_client_manager, meta_client_manager
from app.clients.qdrant_client import qdrant_client_manager
from app.config.app_config import app_config
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_repository_qdrant import ColumnQdrantRepository
from app.repositories.qdrant.metric_repository_qdrant import MetricQdrantRepository
from app.service.meta_knowledge_service import MetaKnowledgeService

# 基础设施就绪等待:最长等待时间与轮询间隔
READY_TIMEOUT_SECONDS = 300
READY_POLL_INTERVAL_SECONDS = 5


def _http_ok(url: str, timeout: int = 3) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False


def _port_open(host: str, port: int, timeout: int = 3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_infrastructure(max_wait_seconds: int = READY_TIMEOUT_SECONDS):
    """等待 Docker 基础设施全部就绪再构建。

    删除数据卷重启服务后,MySQL/ES/Qdrant/Embedding 各自需要初始化时间
    (尤其 Embedding 加载 1.3GB 模型、ES 首次启动),期间运行构建会因连接被重置
    或服务不可用而失败。这里统一轮询健康状态,就绪后才继续。
    """
    checks = [
        ("MySQL", lambda: _port_open(app_config.db_meta.host, app_config.db_meta.port)),
        ("Qdrant", lambda: _http_ok(f"http://{app_config.qdrant.host}:{app_config.qdrant.port}/healthz")),
        ("Elasticsearch", lambda: _http_ok(f"http://{app_config.es.host}:{app_config.es.port}")),
        ("Embedding", lambda: _http_ok(f"http://{app_config.embedding.host}:{app_config.embedding.port}/info")),
        ("Redis", lambda: _port_open(app_config.redis.host, app_config.redis.port)),
    ]

    deadline = time.monotonic() + max_wait_seconds
    pending = list(checks)
    while pending:
        for name, check in list(pending):
            if check():
                pending.remove((name, check))
                print(f"[就绪] {name} 已就绪")
        if not pending:
            return
        if time.monotonic() >= deadline:
            waiting = ", ".join(name for name, _ in pending)
            raise TimeoutError(
                f"等待基础设施就绪超时({max_wait_seconds}s),仍未就绪的服务: {waiting}。"
                f"请检查 docker compose ps 与各容器日志。")
        print(f"[等待] 未就绪服务: {', '.join(name for name, _ in pending)}, "
              f"{READY_POLL_INTERVAL_SECONDS}s 后重试...")
        time.sleep(READY_POLL_INTERVAL_SECONDS)


async def build(meta_config: Path):
    wait_for_infrastructure()
    dw_client_manager.init()
    meta_client_manager.init()
    embedding_client_manager.init()
    qdrant_client_manager.init()
    es_client_manager.init()
    async with dw_client_manager.session_factory() as dw_session, meta_client_manager.session_factory() as meta_session:
        dw_mysql_repository = DWMySQLRepository(dw_session)
        meta_mysql_repository = MetaMySQLRepository(meta_session)
        column_qdrant_repository = ColumnQdrantRepository(qdrant_client_manager.client)
        metric_qdrant_repository = MetricQdrantRepository(qdrant_client_manager.client)
        embedding_client = embedding_client_manager.client
        value_es_repository = ValueESRepository(es_client_manager.client)

        meta_knowledge_service = MetaKnowledgeService(
            dw_mysql_repository=dw_mysql_repository,
            meta_mysql_repository=meta_mysql_repository,
            embedding_client=embedding_client,
            column_qdrant_repository=column_qdrant_repository,
            metric_qdrant_repository=metric_qdrant_repository,
            value_es_repository=value_es_repository
        )
        await meta_knowledge_service.build_meta_knowledge(meta_config)

    await dw_client_manager.close()
    await meta_client_manager.close()
    await qdrant_client_manager.close()
    await es_client_manager.close()


if __name__ == '__main__':
    """解析命令行参数"""
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    args = parser.parse_args()

    asyncio.run(build(Path(args.config)))
