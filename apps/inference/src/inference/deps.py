"""Service-to-service auth for the inference API.

The API and worker send ``Authorization: Bearer $INFERENCE_SERVICE_TOKEN``. This
dependency is what actually checks it. When the variable is unset the service
stays open so a bare ``uvicorn inference.main:app`` works for local development;
every packaged deployment (compose, CI, Dockerfile) sets it.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Annotated

from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)


def service_token() -> str | None:
    token = os.environ.get("INFERENCE_SERVICE_TOKEN", "").strip()
    return token or None


def _extract_bearer(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()


async def require_service_token(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Reject callers that do not present the configured service token."""
    expected = service_token()
    if expected is None:
        return
    presented = _extract_bearer(authorization)
    if presented is None or not hmac.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid service token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def warn_if_unauthenticated() -> None:
    if service_token() is None:
        logger.warning(
            "INFERENCE_SERVICE_TOKEN is not set — /v1/embed and /v1/rerank are unauthenticated"
        )
