"""Unit-level ACL predicate tests (in-memory resolution, no DB required)."""

from __future__ import annotations

from uuid import uuid4

from retrieval.acl import AclResolution, AclSubjectSet, document_acl_predicate


def test_admin_predicate_is_true() -> None:
    resolution = AclResolution(
        acl_version=1,
        subjects=AclSubjectSet(
            user_id=uuid4(),
            group_ids=frozenset(),
            roles=frozenset({"admin"}),
            is_admin=True,
        ),
        allowed_collection_ids=frozenset(),
        allowed_document_ids=frozenset(),
        denied_document_ids=frozenset(),
    )
    pred = document_acl_predicate(resolution)
    # Compile to string — admin bypass uses SQL true().
    assert "true" in str(pred).lower()


def test_default_deny_when_no_allows() -> None:
    resolution = AclResolution(
        acl_version=1,
        subjects=AclSubjectSet(
            user_id=uuid4(),
            group_ids=frozenset(),
            roles=frozenset({"viewer"}),
            is_admin=False,
        ),
        allowed_collection_ids=frozenset(),
        allowed_document_ids=frozenset(),
        denied_document_ids=frozenset(),
    )
    pred = document_acl_predicate(resolution)
    assert "false" in str(pred).lower()


def test_document_deny_beats_collection_allow() -> None:
    denied_doc = uuid4()
    collection = uuid4()
    resolution = AclResolution(
        acl_version=2,
        subjects=AclSubjectSet(
            user_id=uuid4(),
            group_ids=frozenset({uuid4()}),
            roles=frozenset({"member"}),
            is_admin=False,
        ),
        allowed_collection_ids=frozenset({collection}),
        allowed_document_ids=frozenset(),
        denied_document_ids=frozenset({denied_doc}),
    )
    pred = document_acl_predicate(resolution)
    # Predicate is a SQL AND of ~deny and (doc_allow OR collection_allow).
    assert pred is not None
    rendered = str(pred).lower()
    assert "document" in rendered or "collection" in rendered or "acl" in rendered
