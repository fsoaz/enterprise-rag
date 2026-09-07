"""Validate synthetic source manifests completely before ingestion has side effects."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from domain.temporal import parse_as_of


class CorpusError(RuntimeError):
    """The corpus cannot be safely loaded or resolved."""


class SourceVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    label: str = Field(pattern=r"^[a-z][a-z0-9-]+$")
    fixture: str
    current: bool
    effective_from: str
    effective_to: str | None
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_interval(self) -> SourceVersion:
        start, end = parse_as_of(self.effective_from), parse_as_of(self.effective_to)
        if self.current != (end is None) or (
            end is not None and start is not None and end <= start
        ):
            raise ValueError("invalid version interval or current flag")
        return self


class SourceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1)
    collection: str
    language: Literal["pt", "en"]
    kind: Literal["legacy", "policy", "routing", "restricted", "attack", "attack-companion"]
    scenario_id: str | None = None
    attack_family: str | None = None
    attack_target: str | None = None
    versions: list[SourceVersion] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_versions(self) -> SourceDocument:
        if sum(version.current for version in self.versions) != 1 or not self.versions[-1].current:
            raise ValueError("exactly the final version must be current")
        for previous, following in zip(self.versions, self.versions[1:], strict=False):
            end, start = parse_as_of(previous.effective_to), parse_as_of(following.effective_from)
            if end is None or start is None or end > start:
                raise ValueError("versions overlap or are out of order")
        if self.kind != "legacy" and not self.scenario_id:
            raise ValueError("scenario_id required")
        if self.kind.startswith("attack") and not (self.attack_family and self.attack_target):
            raise ValueError("attack metadata required")
        return self


class SourceCollection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1)
    description: str | None = None
    read_groups: list[str] = Field(min_length=1)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    tenant: Literal["acme", "globex"]
    collections: list[SourceCollection] = Field(min_length=1)
    documents: list[SourceDocument] = Field(min_length=1)


def check_fixture_privacy(text: str) -> None:
    """Conservative fixture guard, not a general personal-data detector."""
    emails = re.findall(r"[\w.+-]+@([\w.-]+\.[a-zA-Z]{2,})", text)
    if any(not domain.lower().endswith((".example", ".test", ".invalid")) for domain in emails):
        raise CorpusError("fixture contains a non-reserved email address")
    patterns = (
        r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b",  # CPF-shaped
        r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b",  # CNPJ-shaped
        r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)",  # card-shaped
        r"(?<!\d)\d{11}(?!\d)",  # unformatted CPF-shaped
    )
    if any(re.search(pattern, text) for pattern in patterns):
        raise CorpusError("fixture contains a personal/financial identifier pattern")


def read_manifest(path: Path, *, fixture_dir: Path) -> dict[str, Any]:
    try:
        manifest = Manifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise CorpusError(f"invalid corpus manifest {path.name}: {exc}") from exc
    groups = {"acme": {"engineering", "legal"}, "globex": {"ops", "finance"}}[manifest.tenant]
    collections = {collection.name for collection in manifest.collections}
    if len(collections) != len(manifest.collections):
        raise CorpusError("duplicate collection name")
    for collection in manifest.collections:
        if not set(collection.read_groups) <= groups:
            raise CorpusError("collection names an unknown seeded group")
    titles, labels, fixtures = set(), set(), set()
    root = fixture_dir.resolve()
    for document in manifest.documents:
        if document.title in titles or document.collection not in collections:
            raise CorpusError("duplicate document title or unknown collection")
        titles.add(document.title)
        for version in document.versions:
            if version.label in labels or version.fixture in fixtures:
                raise CorpusError("duplicate version label or fixture mapping")
            labels.add(version.label)
            fixtures.add(version.fixture)
            source = (root / version.fixture).resolve()
            if not source.is_relative_to(root) or source.suffix != ".md":
                raise CorpusError("fixture path escapes root or has unsupported format")
            try:
                raw = source.read_bytes()
                text = raw.decode("utf-8")
            except (OSError, UnicodeError) as exc:
                raise CorpusError(f"unreadable fixture {version.fixture}") from exc
            if not text.strip() or hashlib.sha256(raw).hexdigest() != version.source_sha256:
                raise CorpusError(f"empty or changed fixture {version.fixture}")
            check_fixture_privacy(text)
    return manifest.model_dump()
