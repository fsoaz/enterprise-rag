from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.harness.manifest import CorpusError, read_manifest
from worker.pipeline.chunk import chunk_document
from worker.pipeline.parse import parse_bytes

ROOT = Path(__file__).resolve().parents[1]


def test_acme_and_globex_manifests_validate() -> None:
    acme = read_manifest(ROOT / "corpus.json", fixture_dir=ROOT / "fixtures")
    globex = read_manifest(ROOT / "corpus_globex.json", fixture_dir=ROOT / "fixtures")
    assert acme["tenant"] == "acme"
    assert globex["tenant"] == "globex"
    assert len([d for d in acme["documents"] if d["kind"] == "policy"]) == 40
    assert len([d for d in acme["documents"] if d["kind"] == "attack"]) == 40
    assert len(globex["documents"]) == 40


def test_every_generated_fixture_parses_and_chunks() -> None:
    acme = read_manifest(ROOT / "corpus.json", fixture_dir=ROOT / "fixtures")
    globex = read_manifest(ROOT / "corpus_globex.json", fixture_dir=ROOT / "fixtures")
    fixtures = {
        version["fixture"]
        for manifest in (acme, globex)
        for document in manifest["documents"]
        for version in document["versions"]
    }
    for relative in fixtures:
        parsed = parse_bytes(
            (ROOT / "fixtures" / relative).read_bytes(),
            mime_type="text/markdown",
            filename=relative,
        )
        assert chunk_document(parsed), relative


def test_rendered_artifacts_are_reproducible() -> None:
    import subprocess

    result = subprocess.run(
        ["python", "-m", "evals.build_corpus", "--check"],
        cwd=ROOT.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout


@pytest.mark.parametrize(
    ("field", "replacement"),
    [("fixture", "../outside.md"), ("source_sha256", "0" * 64)],
)
def test_manifest_rejects_changed_or_escaping_fixture(
    tmp_path: Path, field: str, replacement: str
) -> None:
    source = json.loads((ROOT / "corpus.json").read_text())
    source["documents"][0]["versions"][0][field] = replacement
    manifest = tmp_path / "corpus.json"
    manifest.write_text(json.dumps(source))
    with pytest.raises(CorpusError):
        read_manifest(manifest, fixture_dir=ROOT / "fixtures")


def test_fixture_privacy_guard_rejects_unreserved_email(tmp_path: Path) -> None:
    source = json.loads((ROOT / "corpus.json").read_text())
    version = source["documents"][0]["versions"][0]
    fixture = ROOT / "fixtures" / version["fixture"]
    fixture_copy = tmp_path / "fixture.md"
    fixture_copy.write_text(
        fixture.read_text() + " Contact person at person@real-company.example.org"
    )
    version["fixture"] = fixture_copy.name
    import hashlib

    version["source_sha256"] = hashlib.sha256(fixture_copy.read_bytes()).hexdigest()
    manifest = tmp_path / "corpus.json"
    manifest.write_text(json.dumps(source))
    with pytest.raises(CorpusError, match="non-reserved email"):
        read_manifest(manifest, fixture_dir=tmp_path)
