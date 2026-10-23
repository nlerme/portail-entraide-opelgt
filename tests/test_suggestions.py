from app.pieces.models import Offer
from app.pieces.services.search import analyze_ambiguity, suggest_keywords


def _offer(i: int, title: str, price: float, confidence: float = 0.75) -> Offer:
    return Offer(
        id=str(i),
        site_id="x",
        site_name="X",
        title=title,
        url=f"https://x.test/{i}",
        price=price,
        currency="EUR",
        query_confidence=confidence,
    )


def test_zero_result_suggestions_are_distinct():
    suggestions = suggest_keywords("câble embrayage", model="1900")
    assert "câble d'embrayage" in suggestions
    assert "câble embrayage" not in suggestions
    assert len(suggestions) <= 6


def test_ambiguous_results_generate_reasons_and_refinements():
    offers = [_offer(i, f"Câble pièce variante {i}", 5.0 if i == 0 else 100.0 + i) for i in range(20)]
    ambiguous, reasons = analyze_ambiguity("câble", offers)
    assert ambiguous
    assert reasons
    assert suggest_keywords("câble", offers=offers, model="1900")
