"""ACL resolution → SQL predicates (architecture § 5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, false, or_, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from db.models import AclEntry, AclVersion, Document, RoleAssignment, UserGroup
from domain.types import AclEffect, AclPermission, AclResourceType, AclSubjectType, Role


@dataclass(frozen=True, slots=True)
class AclSubjectSet:
    user_id: UUID
    group_ids: frozenset[UUID]
    roles: frozenset[str]
    is_admin: bool


@dataclass(frozen=True, slots=True)
class AclResolution:
    acl_version: int
    subjects: AclSubjectSet
    allowed_collection_ids: frozenset[UUID]
    allowed_document_ids: frozenset[UUID]
    denied_document_ids: frozenset[UUID]


async def load_subject_set(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID
) -> AclSubjectSet:
    group_rows = await session.scalars(
        select(UserGroup.group_id).where(
            UserGroup.tenant_id == tenant_id,
            UserGroup.user_id == user_id,
        )
    )
    group_ids = frozenset(group_rows.all())
    role_rows = await session.scalars(
        select(RoleAssignment.role).where(
            RoleAssignment.tenant_id == tenant_id,
            RoleAssignment.user_id == user_id,
        )
    )
    roles = frozenset(role_rows.all())
    return AclSubjectSet(
        user_id=user_id,
        group_ids=group_ids,
        roles=roles,
        is_admin=Role.ADMIN.value in roles,
    )


def _subject_match(subjects: AclSubjectSet) -> ColumnElement[bool]:
    clauses: list[ColumnElement[bool]] = [
        and_(
            AclEntry.subject_type == AclSubjectType.USER.value,
            AclEntry.subject_id == str(subjects.user_id),
        )
    ]
    if subjects.group_ids:
        clauses.append(
            and_(
                AclEntry.subject_type == AclSubjectType.GROUP.value,
                AclEntry.subject_id.in_([str(g) for g in subjects.group_ids]),
            )
        )
    if subjects.roles:
        clauses.append(
            and_(
                AclEntry.subject_type == AclSubjectType.ROLE.value,
                AclEntry.subject_id.in_(list(subjects.roles)),
            )
        )
    return or_(*clauses)


async def resolve_acl(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    permission: AclPermission = AclPermission.READ,
) -> AclResolution:
    subjects = await load_subject_set(session, tenant_id=tenant_id, user_id=user_id)
    version = await session.scalar(
        select(AclVersion.version).where(AclVersion.tenant_id == tenant_id)
    )
    acl_version = int(version or 1)

    if subjects.is_admin:
        # Tenant admin bypasses ACL within the tenant (architecture § 5.2).
        return AclResolution(
            acl_version=acl_version,
            subjects=subjects,
            allowed_collection_ids=frozenset(),
            allowed_document_ids=frozenset(),
            denied_document_ids=frozenset(),
        )

    entries = (
        await session.scalars(
            select(AclEntry).where(
                AclEntry.tenant_id == tenant_id,
                AclEntry.permission == permission.value,
                _subject_match(subjects),
            )
        )
    ).all()

    allowed_collections: set[UUID] = set()
    denied_collections: set[UUID] = set()
    allowed_documents: set[UUID] = set()
    denied_documents: set[UUID] = set()

    for entry in entries:
        if entry.resource_type == AclResourceType.COLLECTION.value:
            if entry.effect == AclEffect.ALLOW.value:
                allowed_collections.add(entry.resource_id)
            else:
                denied_collections.add(entry.resource_id)
        elif entry.resource_type == AclResourceType.DOCUMENT.value:
            if entry.effect == AclEffect.ALLOW.value:
                allowed_documents.add(entry.resource_id)
            else:
                denied_documents.add(entry.resource_id)

    # Collection deny wins over collection allow.
    allowed_collections -= denied_collections
    # Document deny beats everything.
    allowed_documents -= denied_documents

    return AclResolution(
        acl_version=acl_version,
        subjects=subjects,
        allowed_collection_ids=frozenset(allowed_collections),
        allowed_document_ids=frozenset(allowed_documents),
        denied_document_ids=frozenset(denied_documents),
    )


def document_acl_predicate(
    resolution: AclResolution,
    *,
    document_id_col: Any = Document.id,
    collection_id_col: Any = Document.collection_id,
) -> ColumnElement[bool]:
    """SQL fragment: document is readable under the resolved ACL.

    Resolution order (architecture § 5.2):
    document deny > document allow > collection deny (already applied) > collection allow.
    """
    if resolution.subjects.is_admin:
        return true()

    allowed_by_collection: ColumnElement[bool]
    if resolution.allowed_collection_ids:
        allowed_by_collection = collection_id_col.in_(list(resolution.allowed_collection_ids))
    else:
        allowed_by_collection = false()

    allowed_by_document: ColumnElement[bool]
    if resolution.allowed_document_ids:
        allowed_by_document = document_id_col.in_(list(resolution.allowed_document_ids))
    else:
        allowed_by_document = false()

    denied_document: ColumnElement[bool]
    if resolution.denied_document_ids:
        denied_document = document_id_col.in_(list(resolution.denied_document_ids))
    else:
        denied_document = false()

    return and_(
        ~denied_document,
        or_(allowed_by_document, allowed_by_collection),
    )


def apply_document_acl(stmt: Select[Any], resolution: AclResolution) -> Select[Any]:
    return stmt.where(document_acl_predicate(resolution))


async def bump_acl_version(session: AsyncSession, *, tenant_id: UUID) -> int:
    """Increment acl_versions in the same transaction as an ACL write.

    Uses a single atomic UPDATE rather than read-modify-write: two concurrent ACL
    changes both reading the same version produced one increment instead of two,
    so a cache keyed on this value would keep serving results computed under the
    superseded ACL.
    """
    new_version = await session.scalar(
        update(AclVersion)
        .where(AclVersion.tenant_id == tenant_id)
        .values(version=AclVersion.version + 1)
        .returning(AclVersion.version)
    )
    if new_version is None:
        session.add(AclVersion(tenant_id=tenant_id, version=1))
        await session.flush()
        return 1
    await session.flush()
    return int(new_version)


async def create_acl_entry(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    subject_type: str,
    subject_id: str,
    resource_type: str,
    resource_id: UUID,
    permission: str,
    effect: str,
) -> AclEntry:
    entry = AclEntry(
        tenant_id=tenant_id,
        subject_type=subject_type,
        subject_id=subject_id,
        resource_type=resource_type,
        resource_id=resource_id,
        permission=permission,
        effect=effect,
    )
    session.add(entry)
    await bump_acl_version(session, tenant_id=tenant_id)
    await session.flush()
    return entry


async def delete_acl_entry(session: AsyncSession, *, tenant_id: UUID, entry_id: UUID) -> bool:
    """Remove one ACL row and bump acl_versions. Returns False if missing."""
    entry = await session.scalar(
        select(AclEntry).where(AclEntry.id == entry_id, AclEntry.tenant_id == tenant_id)
    )
    if entry is None:
        return False
    await session.delete(entry)
    await bump_acl_version(session, tenant_id=tenant_id)
    await session.flush()
    return True
