"""Offline retrieval eval — runs the real retrieval pipeline against a real corpus.

Requires a migrated + seeded database and a reachable inference service. It never
fabricates results: if the corpus is missing the run fails loudly rather than
reporting metrics computed against the gold set itself.

    uv run python -m evals.harness.run --load-corpus
    uv run python -m evals.harness.run --strategy hybrid_rrf
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.session import get_session_factory, set_tenant_context
from evals.harness.corpus import (
    DEFAULT_MANIFEST,
    CorpusError,
    load_corpus,
    resolve_existing_labels,
    resolve_tenant_id,
)
from evals.harness.metrics import EvalItem, aggregate_retrieval_metrics, load_dataset
from retrieval.pipeline import retrieve

DEFAULT_TENANT = "acme"
DEFAULT_USER = "acme-member"


async def _resolve_users(
    session: AsyncSession, tenant_id: UUID, subjects: set[str]
) -> dict[str, UUID]:
    rows = await session.execute(
        select(User.external_subject, User.id).where(
            User.tenant_id == tenant_id,
            User.external_subject.in_(sorted(subjects)),
        )
    )
    resolved = {str(subject): UUID(str(uid)) for subject, uid in rows.all()}
    missing = subjects - resolved.keys()
    if missing:
        raise CorpusError(f"unknown eval users {sorted(missing)} — run `make seed` first")
    return resolved


def _score_item(item: EvalItem, retrieved_labels: list[str]) -> tuple[list[str], list[str]] | None:
    if not item.gold_chunk_ids:
        return None
    return retrieved_labels, item.gold_chunk_ids


async def run(args: argparse.Namespace) -> int:
    if not os.environ.get("DATABASE_URL"):
        print(
            "DATABASE_URL is not set. The eval harness runs real retrieval and has no "
            "offline mode; start Postgres and run `make migrate && make seed` first.",
            file=sys.stderr,
        )
        return 2

    items = load_dataset(args.datasets)
    if not items:
        print(f"no datasets found under {args.datasets}", file=sys.stderr)
        return 2

    factory = get_session_factory()
    async with factory() as session:
        await session.begin()
        tenant_id = await resolve_tenant_id(session, args.tenant)
        await set_tenant_context(session, tenant_id)

        if args.load_corpus:
            labels = await load_corpus(session, manifest_path=args.manifest, tenant_id=tenant_id)
            await session.commit()
            await session.begin()
            await set_tenant_context(session, tenant_id)
        else:
            labels = await resolve_existing_labels(
                session, manifest_path=args.manifest, tenant_id=tenant_id
            )

        required = {label for item in items for label in item.gold_chunk_ids}
        missing = required - labels.keys()
        if missing:
            print(
                f"corpus incomplete — no document version for {sorted(missing)}. "
                "Run with --load-corpus.",
                file=sys.stderr,
            )
            return 2
        version_to_label = {vid: label for label, vid in labels.items()}

        subjects = {item.acting_user or args.user for item in items}
        users = await _resolve_users(session, tenant_id, subjects)

        rows_by_slice: dict[str, list[tuple[list[str], list[str]]]] = defaultdict(list)
        # Retrieval-stage signal only. Whether the *system* abstains is decided by
        # the groundedness gate in the chat service, which this harness does not
        # exercise — do not read this as an abstention rate.
        empty_retrieval_by_slice: dict[str, list[bool]] = defaultdict(list)
        injection_exclusions: list[bool] = []
        per_item: list[dict[str, object]] = []

        for item in items:
            subject = item.acting_user or args.user
            result = await retrieve(
                session,
                tenant_id=tenant_id,
                user_id=users[subject],
                query=item.question,
                strategy=args.strategy,
                top_k=args.top_k,
            )
            retrieved_labels = [
                version_to_label[h.document_version_id]
                for h in result.hits
                if h.document_version_id in version_to_label
            ]
            scored = _score_item(item, retrieved_labels)
            if scored is not None:
                rows_by_slice[item.slice].append(scored)
            if item.should_abstain:
                empty_retrieval_by_slice[item.slice].append(not result.hits)
            excluded = not bool(set(retrieved_labels).intersection(item.must_exclude_chunk_ids))
            if item.must_exclude_chunk_ids:
                injection_exclusions.append(excluded)
            per_item.append(
                {
                    "id": item.id,
                    "slice": item.slice,
                    "acting_user": subject,
                    "gold": item.gold_chunk_ids,
                    "retrieved": retrieved_labels,
                    "hit": bool(set(retrieved_labels) & set(item.gold_chunk_ids)),
                    "should_abstain": item.should_abstain,
                    "retrieved_count": len(result.hits),
                    "unsupported_as_of": item.as_of is not None,
                    "must_exclude": item.must_exclude_chunk_ids,
                    "excluded": excluded if item.must_exclude_chunk_ids else None,
                }
            )

        await session.rollback()

    all_rows = [row for rows in rows_by_slice.values() for row in rows]
    injection_exclusion_rate = (
        sum(injection_exclusions) / len(injection_exclusions) if injection_exclusions else None
    )
    report: dict[str, object] = {
        "strategy": args.strategy,
        "tenant": args.tenant,
        "default_user": args.user,
        "items": len(items),
        "slices": sorted({i.slice for i in items}),
        "overall": aggregate_retrieval_metrics(all_rows),
        "security": {
            "injection_exclusion_rate": injection_exclusion_rate,
            "injection_cases": len(injection_exclusions),
        },
        "by_slice": {
            name: {
                "retrieval": aggregate_retrieval_metrics(rows_by_slice.get(name, [])),
                "empty_retrieval_rate": (
                    sum(empty_retrieval_by_slice[name]) / len(empty_retrieval_by_slice[name])
                    if empty_retrieval_by_slice.get(name)
                    else None
                ),
            }
            for name in sorted({i.slice for i in items})
        },
    }
    if args.verbose:
        report["items_detail"] = per_item
    print(json.dumps(report, indent=2))
    if (
        injection_exclusion_rate is not None
        and injection_exclusion_rate < args.min_injection_exclusion
    ):
        print(
            "injection exclusion gate failed: "
            f"{injection_exclusion_rate:.3f} < {args.min_injection_exclusion:.3f}",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retrieval evals against a live corpus")
    parser.add_argument("--datasets", type=Path, default=Path("evals/datasets"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--strategy", default="hybrid_rrf")
    parser.add_argument("--tenant", default=DEFAULT_TENANT)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--min-injection-exclusion",
        type=float,
        default=1.0,
        help="Fail when known injection chunks are retrieved (default: 1.0).",
    )
    parser.add_argument(
        "--load-corpus",
        action="store_true",
        help="Ingest evals/fixtures into the tenant before scoring (idempotent).",
    )
    parser.add_argument("--verbose", action="store_true", help="Include per-item detail.")
    args = parser.parse_args()

    try:
        sys.exit(asyncio.run(run(args)))
    except CorpusError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
