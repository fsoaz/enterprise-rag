from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from domain.errors import DomainError, ValidationError

ERROR_STATUS: dict[str, int] = {
    "validation-failed": 422,
    "not-found": 404,
    "permission-denied": 403,
    "conflict": 409,
    "quota-exceeded": 429,
    "rate-limited": 429,
    "upload-too-large": 413,
    "unsupported-media-type": 415,
    "retrieval-unavailable": 503,
    "generation-unavailable": 503,
    "method-not-allowed": 405,
    "internal-error": 500,
}

ERROR_TITLES: dict[str, str] = {
    "validation-failed": "Validation failed",
    "not-found": "Not found",
    "permission-denied": "Permission denied",
    "conflict": "Conflict",
    "quota-exceeded": "Quota exceeded",
    "rate-limited": "Rate limited",
    "upload-too-large": "Upload too large",
    "unsupported-media-type": "Unsupported media type",
    "retrieval-unavailable": "Retrieval unavailable",
    "generation-unavailable": "Generation unavailable",
    "method-not-allowed": "Method Not Allowed",
    "internal-error": "Internal error",
}


def get_request_id(request: Request) -> str:
    existing = getattr(request.state, "request_id", None)
    if isinstance(existing, str) and existing:
        return existing
    header = request.headers.get("X-Request-Id")
    if header:
        return header
    return str(uuid4())


def problem_response(
    *,
    status: int,
    type_slug: str,
    title: str,
    detail: str,
    request: Request,
    errors: list[dict[str, str]] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    request_id = get_request_id(request)
    body: dict[str, Any] = {
        "type": f"https://errors.enterprise-rag.dev/{type_slug}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": str(request.url.path),
        "request_id": request_id,
        "errors": errors or [],
    }
    if extra:
        body.update(extra)
    return JSONResponse(
        status_code=status,
        content=body,
        media_type="application/problem+json",
        headers={"X-Request-Id": request_id},
    )


def domain_error_response(request: Request, exc: DomainError) -> JSONResponse:
    status = ERROR_STATUS.get(exc.type_slug, 500)
    title = ERROR_TITLES.get(exc.type_slug, "Error")
    errors: list[dict[str, str]] | None = None
    if isinstance(exc, ValidationError):
        errors = exc.errors
    return problem_response(
        status=status,
        type_slug=exc.type_slug,
        title=title,
        detail=exc.message,
        request=request,
        errors=errors,
    )


async def attach_request_id(request: Request, call_next: Any) -> Response:
    raw = request.headers.get("X-Request-Id")
    try:
        # Accept only a real UUID; otherwise mint one so callers cannot poison logs.
        request_id = str(UUID(raw)) if raw else str(uuid4())
    except (ValueError, TypeError):
        request_id = str(uuid4())
    request.state.request_id = request_id
    response: Response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response
