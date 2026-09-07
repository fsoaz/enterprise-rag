from pathlib import Path

import pytest

from evals.harness.dataset import validate_dataset
from evals.harness.manifest import CorpusError

ROOT = Path(__file__).resolve().parents[1]


def test_all_eight_slices_have_forty_valid_items() -> None:
    items = validate_dataset(
        ROOT / "datasets",
        manifest_paths=(ROOT / "corpus.json", ROOT / "corpus_globex.json"),
    )
    assert len(items) == 320
    assert {item["slice"] for item in items} == {
        "factual_pt",
        "factual_en",
        "crosslingual",
        "multi_hop",
        "versioned",
        "unanswerable",
        "permission",
        "injection",
    }


def test_dataset_validator_rejects_missing_case(tmp_path: Path) -> None:
    source = ROOT / "datasets" / "factual_en.jsonl"
    (tmp_path / "factual_en.jsonl").write_text(
        "\n".join(source.read_text().splitlines()[:-1]) + "\n"
    )
    for name in (
        "factual_pt",
        "crosslingual",
        "multi_hop",
        "versioned",
        "unanswerable",
        "permission",
        "injection",
    ):
        (tmp_path / f"{name}.jsonl").write_text((ROOT / "datasets" / f"{name}.jsonl").read_text())
    with pytest.raises(CorpusError, match="expected 40"):
        validate_dataset(
            tmp_path, manifest_paths=(ROOT / "corpus.json", ROOT / "corpus_globex.json")
        )
