from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Response
from sqlalchemy import text

from api.settings import get_settings
from db.session import get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness only — the process is up. Never touches dependencies."""
    return {"status": "ok"}


async def _check_database() -> bool:
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("readiness: database unreachable", exc_info=True)
        return False


async def _check_redis() -> bool:
    try:
        import redis.asyncio as redis

        client = redis.from_url(get_settings().redis_url, decode_responses=True)
        try:
            await client.ping()
        finally:
            await client.close()
        return True
    except Exception:
        logger.warning("readiness: redis unreachable", exc_info=True)
        return False


async def _check_inference() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{get_settings().inference_base_url.rstrip('/')}/ready")
        return response.status_code == 200
    except httpx.HTTPError:
        logger.warning("readiness: inference unreachable", exc_info=True)
        return False


@router.get("/ready")
async def ready(response: Response) -> dict[str, object]:
    """Readiness — reports 503 when a hard dependency is down.

    Previously this returned ``ready`` unconditionally, which made it useless as a
    probe: an API with an unreachable database still advertised itself as ready and
    would be sent traffic it could not serve.
    """
    checks = {
        "database": await _check_database(),
        "redis": await _check_redis(),
        "inference": await _check_inference(),
    }
    ok = all(checks.values())
    if not ok:
        response.status_code = 503
    return {"status": "ready" if ok else "degraded", "checks": checks}
