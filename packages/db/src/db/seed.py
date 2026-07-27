"""Seed two demo tenants (acme, globex) with users, groups, roles, collections, ACL.

Callable as: ``python -m db.seed`` (uses DATABASE_URL_MIGRATE / DATABASE_URL).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import (
    AclEntry,
    AclVersion,
    Collection,
    Group,
    RoleAssignment,
    Tenant,
    User,
    UserGroup,
)
from domain.types import (
    AclEffect,
    AclPermission,
    AclResourceType,
    AclSubjectType,
    Role,
)


@dataclass(frozen=True, slots=True)
class SeedUser:
    external_subject: str
    email: str
    display_name: str
    role: Role
    groups: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TenantSeed:
    slug: str
    name: str
    groups: tuple[str, ...]
    users: tuple[SeedUser, ...]
    collection_name: str
    acl_group: str


ACME = TenantSeed(
    slug="acme",
    name="Acme Corporation",
    groups=("engineering", "legal"),
    users=(
        SeedUser(
            external_subject="acme-admin",
            email="admin@acme.example",
            display_name="Acme Admin",
            role=Role.ADMIN,
            groups=("engineering", "legal"),
        ),
        SeedUser(
            external_subject="acme-steward",
            email="steward@acme.example",
            display_name="Acme Steward",
            role=Role.STEWARD,
            groups=("engineering",),
        ),
        SeedUser(
            external_subject="acme-member",
            email="member@acme.example",
            display_name="Acme Member",
            role=Role.MEMBER,
            groups=("engineering",),
        ),
        SeedUser(
            external_subject="acme-viewer",
            email="viewer@acme.example",
            display_name="Acme Viewer",
            role=Role.VIEWER,
            groups=("legal",),
        ),
    ),
    collection_name="Acme Policies",
    acl_group="engineering",
)

GLOBEX = TenantSeed(
    slug="globex",
    name="Globex Industries",
    groups=("ops", "finance"),
    users=(
        SeedUser(
            external_subject="globex-admin",
            email="admin@globex.example",
            display_name="Globex Admin",
            role=Role.ADMIN,
            groups=("ops", "finance"),
        ),
        SeedUser(
            external_subject="globex-steward",
            email="steward@globex.example",
            display_name="Globex Steward",
            role=Role.STEWARD,
            groups=("ops",),
        ),
        SeedUser(
            external_subject="globex-member",
            email="member@globex.example",
            display_name="Globex Member",
            role=Role.MEMBER,
            groups=("ops",),
        ),
        SeedUser(
            external_subject="globex-viewer",
            email="viewer@globex.example",
            display_name="Globex Viewer",
            role=Role.VIEWER,
            groups=("finance",),
        ),
    ),
    collection_name="Globex Runbooks",
    acl_group="ops",
)

SEEDS: tuple[TenantSeed, ...] = (ACME, GLOBEX)

# The development identity provider has to put the same tenant identifier in its
# signed token that the API resolves in Postgres. Random tenant ids made a static
# Keycloak realm impossible to provision: every database reset invalidated every
# token. These UUIDv5 values are stable while remaining namespaced to this project.
TENANT_IDS: dict[str, UUID] = {
    spec.slug: uuid5(NAMESPACE_URL, f"https://enterprise-rag.local/tenants/{spec.slug}")
    for spec in SEEDS
}


def _async_url() -> str:
    url = os.environ.get("DATABASE_URL_MIGRATE") or os.environ.get("DATABASE_URL")
    if not url:
        msg = "DATABASE_URL_MIGRATE or DATABASE_URL must be set"
        raise RuntimeError(msg)
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def seed_tenant(session: AsyncSession, spec: TenantSeed) -> UUID:
    existing = await session.scalar(select(Tenant).where(Tenant.slug == spec.slug))
    if existing is not None:
        # Idempotent: ensure collection + ACL exist for already-seeded tenants.
        await _ensure_collection_acl(session, existing.id, spec)
        return existing.id

    tenant_id = TENANT_IDS[spec.slug]
    session.add(
        Tenant(
            id=tenant_id,
            slug=spec.slug,
            name=spec.name,
            status="active",
            settings={},
        )
    )
    await session.flush()

    group_ids: dict[str, UUID] = {}
    for group_name in spec.groups:
        gid = uuid4()
        session.add(Group(id=gid, tenant_id=tenant_id, name=group_name))
        group_ids[group_name] = gid
    await session.flush()

    for user_spec in spec.users:
        uid = uuid4()
        session.add(
            User(
                id=uid,
                tenant_id=tenant_id,
                external_subject=user_spec.external_subject,
                email=user_spec.email,
                display_name=user_spec.display_name,
                status="active",
            )
        )
        await session.flush()
        session.add(
            RoleAssignment(
                tenant_id=tenant_id,
                user_id=uid,
                role=user_spec.role.value,
            )
        )
        for group_name in user_spec.groups:
            session.add(
                UserGroup(
                    tenant_id=tenant_id,
                    user_id=uid,
                    group_id=group_ids[group_name],
                )
            )

    session.add(AclVersion(tenant_id=tenant_id, version=1))
    await session.flush()
    await _ensure_collection_acl(session, tenant_id, spec, group_ids=group_ids)
    return tenant_id


async def _ensure_collection_acl(
    session: AsyncSession,
    tenant_id: UUID,
    spec: TenantSeed,
    *,
    group_ids: dict[str, UUID] | None = None,
) -> None:
    collection = await session.scalar(
        select(Collection).where(
            Collection.tenant_id == tenant_id,
            Collection.name == spec.collection_name,
        )
    )
    if collection is None:
        collection = Collection(
            id=uuid4(),
            tenant_id=tenant_id,
            name=spec.collection_name,
            description=f"Default collection for {spec.slug}",
        )
        session.add(collection)
        await session.flush()

    if group_ids is None:
        groups = (await session.scalars(select(Group).where(Group.tenant_id == tenant_id))).all()
        group_ids = {g.name: g.id for g in groups}

    acl_gid = group_ids.get(spec.acl_group)
    if acl_gid is None:
        return

    existing_acl = await session.scalar(
        select(AclEntry).where(
            AclEntry.tenant_id == tenant_id,
            AclEntry.subject_type == AclSubjectType.GROUP.value,
            AclEntry.subject_id == str(acl_gid),
            AclEntry.resource_type == AclResourceType.COLLECTION.value,
            AclEntry.resource_id == collection.id,
            AclEntry.permission == AclPermission.READ.value,
        )
    )
    if existing_acl is None:
        session.add(
            AclEntry(
                tenant_id=tenant_id,
                subject_type=AclSubjectType.GROUP.value,
                subject_id=str(acl_gid),
                resource_type=AclResourceType.COLLECTION.value,
                resource_id=collection.id,
                permission=AclPermission.READ.value,
                effect=AclEffect.ALLOW.value,
            )
        )
        # Also grant write to the same group for steward workflows.
        session.add(
            AclEntry(
                tenant_id=tenant_id,
                subject_type=AclSubjectType.GROUP.value,
                subject_id=str(acl_gid),
                resource_type=AclResourceType.COLLECTION.value,
                resource_id=collection.id,
                permission=AclPermission.WRITE.value,
                effect=AclEffect.ALLOW.value,
            )
        )
        version = await session.scalar(select(AclVersion).where(AclVersion.tenant_id == tenant_id))
        if version is not None:
            version.version = int(version.version) + 1
        await session.flush()


async def run_seed() -> None:
    engine = create_async_engine(_async_url(), pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session, session.begin():
        # Migrate role has BYPASSRLS; still clear any leftover GUC.
        await session.execute(text("SELECT set_config('app.current_tenant', '', false)"))
        for spec in SEEDS:
            tenant_id = await seed_tenant(session, spec)
            print(f"seeded tenant {spec.slug} ({tenant_id})")
    await engine.dispose()


def main() -> None:
    asyncio.run(run_seed())


if __name__ == "__main__":
    main()
