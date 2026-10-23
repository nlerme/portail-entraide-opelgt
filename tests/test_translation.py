import pytest

from app.pieces.scrapers.sites import SITES
from app.pieces.services.translation import verified_query_candidates_for_language, verified_query_for_language


class NoNetworkClient:
    async def get(self, *args, **kwargs):
        raise AssertionError("Le lexique embarqué doit suffire")


@pytest.mark.asyncio
async def test_cable_clutch_is_translated_for_every_supplier_language():
    expected = {"fr": "câble embrayage", "en": "clutch cable", "de": "kupplungszug", "nl": "koppelingskabel"}
    for site in SITES.values():
        query = await verified_query_for_language(
            "câble embrayage", site.language, ["1900"], NoNetworkClient()
        )
        assert query == expected[site.language]
        assert "1900" not in query


@pytest.mark.asyncio
async def test_german_catalog_synonyms_are_both_queried():
    queries = await verified_query_candidates_for_language(
        "câble embrayage", "de", ["1900"], NoNetworkClient()
    )
    assert queries == ["kupplungszug", "kupplungsseil"]


@pytest.mark.asyncio
async def test_search_operators_are_not_sent_to_supplier():
    queries = await verified_query_candidates_for_language(
        "+câble +embrayage -occasion", "en", ["1900"], NoNetworkClient()
    )
    assert queries == ["clutch cable"]


@pytest.mark.asyncio
async def test_wiper_blades_are_translated_with_catalog_synonyms():
    expected = {
        "fr": ["essuie-glace", "essuie glace"],
        "en": ["wiper arms", "wiper arm", "wiper blades", "wiper blade", "windshield wiper", "wiper"],
        "de": [
            "wischerarme",
            "wischerarm",
            "scheibenwischerarme",
            "scheibenwischerblatt",
            "scheibenwischer",
            "wischer",
        ],
        "nl": ["ruitenwisserblad", "ruitenwisser"],
    }
    for language, expected_queries in expected.items():
        queries = await verified_query_candidates_for_language(
            "essuie glace", language, ["1900"], NoNetworkClient()
        )
        assert queries == expected_queries


@pytest.mark.asyncio
async def test_cable_d_apostrophe_clutch_is_translated_without_grammar_tokens():
    expected = {
        "fr": "câble d'embrayage",
        "en": "clutch cable",
        "de": "kupplungszug",
        "nl": "koppelingskabel",
    }
    for language, expected_query in expected.items():
        query = await verified_query_for_language("câble d'embrayage", language, ["1900"], NoNetworkClient())
        assert query == expected_query


@pytest.mark.asyncio
async def test_clutch_cable_supplier_candidates_never_degrade_to_one_word():
    for language in ("fr", "en", "de", "nl"):
        queries = await verified_query_candidates_for_language(
            "câble embrayage", language, ["1900"], NoNetworkClient()
        )
        canonical_full_terms = {
            "câble embrayage",
            "cable embrayage",
            "clutch cable",
            "kupplungszug",
            "kupplungsseil",
            "koppelingskabel",
        }
        assert queries
        assert set(queries) <= canonical_full_terms
        assert not ({"clutch", "cable", "kupplung", "kabel", "embrayage", "câble"} & set(queries))
