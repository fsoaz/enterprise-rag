from llm.judge import parse_judgement, rubric_hash, rubric_text


def test_rubric_is_versioned_and_hashed() -> None:
    assert "Allowed labels" in rubric_text()
    assert len(rubric_hash()) == 64


def test_judge_requires_exactly_one_label_per_pair() -> None:
    parsed = parse_judgement("0: entailed\n1: partial", 2)
    assert parsed.complete is True
    assert parsed.labels == ["entailed", "partial"]


def test_missing_or_extra_judge_lines_are_incomplete() -> None:
    missing = parse_judgement("0: entailed", 2)
    extra = parse_judgement("0: entailed\n0: partial", 1)
    malformed = parse_judgement("preamble\n0: entailed", 1)
    assert not missing.complete
    assert not extra.complete
    assert not malformed.complete
    assert all(label == "unrelated" for label in missing.labels[1:])
