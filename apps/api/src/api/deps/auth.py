from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.settings import Settings, get_settings
from db.models import Group, RoleAssignment, User, UserGroup
from domain.errors import PermissionDeniedError
from domain.types import Role

_jwks_client: PyJWKClient | None = None
_identity_engine: AsyncEngine | None = None
_identity_factory: async_sessionmaker[AsyncSession] | None = None


@dataclass(frozen=True, slots=True)
class AuthUser:
    user_id: UUID
    tenant_id: UUID
    external_subject: str
    email: str
    roles: tuple[str, ...]
    groups: tuple[str, ...]

    # Compat aliases for early routers written against a draft shape.
    @property
    def id(self) -> UUID:
        return self.user_id

    @property
    def role(self) -> str:
        return self.roles[0] if self.roles else "viewer"


def _get_jwks_client(settings: Settings) -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(
            settings.oidc_jwks_url,
            cache_keys=True,
            lifespan=settings.oidc_jwks_cache_ttl_seconds,
        )
    return _jwks_client


def _get_identity_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    """BYPASSRLS sessions for resolving external_subject before tenant GUC is set."""
    global _identity_engine, _identity_factory
    if _identity_factory is None:
        _identity_engine = create_async_engine(
            settings.async_identity_url(),
            pool_pre_ping=True,
        )
        _identity_factory = async_sessionmaker(
            _identity_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _identity_factory


async def reset_auth_caches() -> None:
    """Test helper — drop JWKS client and identity engine."""
    global _jwks_client, _identity_engine, _identity_factory
    _jwks_client = None
    _identity_factory = None
    engine = _identity_engine
    _identity_engine = None
    if engine is not None:
        await engine.dispose()


def _unauthorized(detail: str = "Missing or invalid credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _extract_bearer(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()


async def _load_roles_and_groups(
    session: AsyncSession, user_id: UUID
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    role_rows = await session.scalars(
        select(RoleAssignment.role).where(RoleAssignment.user_id == user_id)
    )
    roles = tuple(role_rows.all())
    group_rows = await session.scalars(
        select(Group.name)
        .join(UserGroup, UserGroup.group_id == Group.id)
        .where(UserGroup.user_id == user_id)
    )
    groups = tuple(group_rows.all())
    return roles, groups


async def _auth_user_from_db_row(session: AsyncSession, user: User) -> AuthUser:
    roles, groups = await _load_roles_and_groups(session, user.id)
    return AuthUser(
        user_id=user.id,
        tenant_id=user.tenant_id,
        external_subject=user.external_subject,
        email=user.email,
        roles=roles,
        groups=groups,
    )


async def _lookup_by_external_subject(subject: str, settings: Settings) -> AuthUser:
    factory = _get_identity_factory(settings)
    async with factory() as session:
        user = await session.scalar(select(User).where(User.external_subject == subject))
        if user is None or user.status != "active":
            raise _unauthorized("Unknown or inactive user")
        return await _auth_user_from_db_row(session, user)


def _verify_oidc_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        client = _get_jwks_client(settings)
        signing_key = client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise _unauthorized("Invalid token") from exc

    required = ("sub", "tenant_id", "roles", "groups")
    missing = [k for k in required if k not in payload]
    if missing:
        raise _unauthorized(f"Token missing claims: {', '.join(missing)}")
    return payload


async def _auth_from_oidc_claims(claims: dict[str, Any], settings: Settings) -> AuthUser:
    try:
        tenant_id = UUID(str(claims["tenant_id"]))
    except (ValueError, TypeError) as exc:
        raise _unauthorized("Invalid tenant_id claim") from exc

    subject = str(claims["sub"])
    roles_raw = claims["roles"]
    groups_raw = claims["groups"]
    if not isinstance(roles_raw, list) or not isinstance(groups_raw, list):
        raise _unauthorized("roles and groups claims must be arrays")

    factory = _get_identity_factory(settings)
    async with factory() as session:
        user = await session.scalar(
            select(User).where(
                User.external_subject == subject,
                User.tenant_id == tenant_id,
            )
        )
        if user is None or user.status != "active":
            raise _unauthorized("Unknown or inactive user")
        # Authorization comes from the database, not the token. The roles/groups
        # claims are required (so a malformed token is rejected early) but are not
        # trusted for access decisions — otherwise require_role and retrieval's
        # resolve_acl, which reads role_assignments directly, could disagree.
        return await _auth_user_from_db_row(session, user)


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    x_dev_user: Annotated[str | None, Header(alias="X-Dev-User")] = None,
) -> AuthUser:
    """Resolve the caller. Tenant comes only from verified identity — never request params."""
    settings = get_settings()
    if settings.dev_auth_bypass:
        subject: str | None = None
        if x_dev_user:
            subject = x_dev_user.strip()
        else:
            bearer = _extract_bearer(authorization)
            if bearer is not None and bearer.startswith("dev:"):
                subject = bearer.removeprefix("dev:").strip()
        if not subject:
            raise _unauthorized()
        return await _lookup_by_external_subject(subject, settings)

    bearer = _extract_bearer(authorization)
    if not bearer:
        raise _unauthorized()
    claims = _verify_oidc_token(bearer, settings)
    return await _auth_from_oidc_claims(claims, settings)


def require_role(*roles: str) -> Callable[..., Coroutine[Any, Any, AuthUser]]:
    """Dependency factory: require the caller to hold at least one of the given roles."""
    allowed = frozenset(roles)

    async def _checker(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
        if allowed.isdisjoint(user.roles):
            raise PermissionDeniedError(f"Requires one of roles: {', '.join(sorted(allowed))}")
        return user

    return _checker


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]

# Curators may create collections, upload documents, and archive them.
CuratorUser = Annotated[AuthUser, Depends(require_role(Role.ADMIN.value, Role.STEWARD.value))]
# ACL grants are an administrative action — a member must not be able to widen
# their own access by writing acl_entries.
AclAdminUser = Annotated[AuthUser, Depends(require_role(Role.ADMIN.value))]
