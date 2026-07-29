from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.problem import (
    attach_request_id,
    domain_error_response,
    get_request_id,
    problem_response,
)
from api.routers import (
    acl,
    admin,
    chat,
    collections,
    documents,
    feedback,
    health,
    me,
    search,
)
from api.settings import get_settings
from domain.errors import DomainError
from observability.logging import configure_logging

# The observability package existed but nothing ever called it, so the API emitted
# default uvicorn logging and none of the structured JSON it was built to produce.
configure_logging(get_settings().log_level)

app = FastAPI(
    title="Enterprise RAG API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

_cors_origins = [
    origin.strip() for origin in get_settings().cors_allow_origins.split(",") if origin.strip()
]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.middleware("http")(attach_request_id)


@app.middleware("http")
async def security_headers(request: Request, call_next: object) -> object:
    response = await call_next(request)  # type: ignore[operator]
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    response.headers.setdefault("Cache-Control", "no-store, private")
    return response


app.include_router(health.router)
app.include_router(me.router)
app.include_router(collections.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(acl.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return domain_error_response(request, exc)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    type_slug = "internal-error"
    if exc.status_code == 401:
        type_slug = "unauthorized"
    elif exc.status_code == 403:
        type_slug = "permission-denied"
    elif exc.status_code == 404:
        type_slug = "not-found"
    elif exc.status_code == 422:
        type_slug = "validation-failed"
    elif exc.status_code == 429:
        type_slug = "rate-limited"
    elif exc.status_code == 405:
        type_slug = "method-not-allowed"
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    titles = {
        401: "Unauthorized",
        403: "Permission denied",
        404: "Not found",
        422: "Validation failed",
        429: "Rate limited",
        405: "Method Not Allowed",
    }
    response = problem_response(
        status=exc.status_code,
        type_slug=type_slug,
        title=titles.get(exc.status_code, "Error"),
        detail=detail,
        request=request,
    )
    if exc.headers:
        response.headers.update({k: str(v) for k, v in exc.headers.items()})
    return response


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return await http_exception_handler(
        request, HTTPException(status_code=exc.status_code, detail=exc.detail, headers=exc.headers)
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = [
        {
            "field": ".".join(str(loc) for loc in err.get("loc", ())),
            "message": str(err.get("msg", "invalid")),
        }
        for err in exc.errors()
    ]
    return problem_response(
        status=422,
        type_slug="validation-failed",
        title="Validation failed",
        detail="Request validation failed",
        request=request,
        errors=errors,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, _exc: Exception) -> JSONResponse:
    request_id = get_request_id(request)
    return JSONResponse(
        status_code=500,
        content={
            "type": "https://errors.enterprise-rag.dev/internal-error",
            "title": "Internal error",
            "status": 500,
            "detail": "An unexpected error occurred",
            "instance": str(request.url.path),
            "request_id": request_id,
            "errors": [],
        },
        media_type="application/problem+json",
        headers={"X-Request-Id": request_id},
    )
