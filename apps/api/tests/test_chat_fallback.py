from __future__ import annotations

from api.services.chat import fallback_verdict


def test_fallback_without_lexical_evidence_remains_unsupported() -> None:
    assert fallback_verdict(verdict="unsupported", has_lexical_match=False) == "unsupported"


def test_fallback_with_lexical_evidence_is_only_partially_supported() -> None:
    assert fallback_verdict(verdict="unsupported", has_lexical_match=True) == "partial"
