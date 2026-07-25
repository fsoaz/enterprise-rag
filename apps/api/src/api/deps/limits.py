"""Per-user rate limiting and per-tenant spend guards.

``QuotaExceededError`` existed and mapped to 429 from the start but was never
raised, and nothing read ``cost_ledger`` to stop anything. Any authenticated user
could therefore drive unbounded generation spend and unbounded embedding load
through ``/chat/completions``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

import redis.asyncio as redis
from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps.auth import AuthUser, get_current_user
from api.settings import Settings, get_settings
from db.models import CostLedger
from domain.errors import QuotaExceededError

logger = logging.getLogger(__name__)

_client: redis.Redis[str] | None = None


def _get_client(settings: Settings) -> redis.Redis[str] | None:
    global _client
    if _client is None:
        try:
            _client = redis.from_url(settings.redis_url, decode_responses=True)
        except Exception:
            logger.warning("redis unavailable; rate limiting disabled", exc_info=True)
            return None
    return _client


async def reset_rate_limiter() -> None:
    """Drop the cached Redis client — for tests."""
    global _client
    client = _client
    _client = None
    if client is not None:
        await client.close()


async def _hit(key: str, *, limit: int, window_seconds: int, settings: Settings) -> bool:
    """Count one request in a fixed window. True when the caller is over the limit.

    Fails open: a Redis outage must not take the whole API down with it. The
    tenant spend guard below reads Postgres instead, so cost protection survives
    a cache outage even though request-rate protection does not.
    """
    client = _get_client(settings)
    if client is None:
        return False
    bucket = int(time.time()) // window_seconds
    redis_key = f"ratelimit:{key}:{bucket}"
    try:
        pipe = client.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds * 2)
        used, _ = await pipe.execute()
        return int(used) > limit
    except Exception:
        # Drop the cached client so the next request rebuilds it. A client created
        # on a since-closed event loop fails permanently otherwise, silently
        # disabling rate limiting for the rest of the process.
        global _client
        _client = None
        logger.warning("rate limit check failed; allowing request", exc_info=True)
        return False


def rate_limit(
    scope: str, *, limit_attr: str = "rate_limit_per_minute", window_seconds: int = 60
) -> Callable[..., Coroutine[Any, Any, AuthUser]]:
    """Dependency factory: cap requests per user per window for one route group."""

    async def _checker(
        user: Annotated[AuthUser, Depends(get_current_user)],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> AuthUser:
        limit = int(getattr(settings, limit_attr))
        if limit <= 0:
            return user
        over = await _hit(
            f"{scope}:{user.tenant_id}:{user.user_id}",
            limit=limit,
            window_seconds=window_seconds,
            settings=settings,
        )
        if over:
            raise QuotaExceededError(
                f"Rate limit exceeded for {scope}: {limit} requests per "
                f"{window_seconds}s. Retry shortly."
            )
        return user

    return _checker


async def assert_within_budget(
    session: AsyncSession, *, tenant_id: Any, settings: Settings
) -> None:
    """Refuse generation once the tenant has burned its daily budget.

    Reads the ledger the system already writes, so it holds even when Redis is
    down. A budget of 0 disables the check.
    """
    budget = Decimal(str(settings.tenant_daily_budget_usd))
    if budget <= 0:
        return
    since = datetime.now(UTC) - timedelta(days=1)
    spent = await session.scalar(
        select(func.coalesce(func.sum(CostLedger.computed_cost_usd), 0)).where(
            CostLedger.tenant_id == tenant_id,
            CostLedger.created_at >= since,
        )
    )
    if Decimal(str(spent or 0)) >= budget:
        raise QuotaExceededError(
            f"Tenant daily generation budget of ${budget} is exhausted. "
            "It resets on a rolling 24-hour window."
        )


ChatRateLimited = Annotated[
    AuthUser, Depends(rate_limit("chat", limit_attr="chat_rate_limit_per_minute"))
]
SearchRateLimited = Annotated[AuthUser, Depends(rate_limit("search"))]
UploadRateLimited = Annotated[
    AuthUser, Depends(rate_limit("upload", limit_attr="upload_rate_limit_per_minute"))
]
