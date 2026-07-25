"""Problem+json helpers (RFC 7807)."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def problem(
    *,
    status: int,
    title: str,
    detail: str,
    type_slug: str,
    errors: list[dict[str, str]] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://errors.enterprise-rag.dev/{type_slug}",
        "title": title,
        "status": status,
        "detail": detail,
        "errors": errors or [],
    }
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status, content=body, media_type="application/problem+json")
