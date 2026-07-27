from domain.text import detect_supported_language


def test_detects_portuguese_without_diacritics() -> None:
    assert detect_supported_language("Qual o prazo para revisar a politica?") == "pt"


def test_detects_english_question() -> None:
    assert detect_supported_language("What is the security policy?") == "en"
