from __future__ import annotations

import copy
import json
from types import SimpleNamespace as NS

import lbc
import pytest
from curl_cffi.requests.exceptions import Timeout

from app.annonces import collectors as c
from app.annonces import leboncoin
from app.annonces import service as s
from app.annonces.leboncoin import SEARCH_URL


def advert(ident, *, classic=True, owner="private", country="FR", **changes):
    return {
        "list_id": ident, "category_id": "2", "status": "active", "ad_type": "offer",
        "subject": "Opel GT 1900" if classic else "Opel GT Roadster", "body": "",
        "url": f"https://www.leboncoin.fr/ad/voitures/{ident}", "price_cents": 1750000,
        "attributes": [{"key": "regdate", "value": "1969" if classic else "2008", "values": []}],
        "owner": {"type": owner, "user_id": "unused-test-user"},
        "location": {"country_id": country, "city": "Limours", "city_label": "Limours",
                     "department_id": "91", "zipcode": "91470"},
        "first_publication_date": "2026-10-24 10:00:00", "images": {"urls_large": []}, **changes,
    }


def page(ads, total=None, **changes):
    return {"ads": ads, "total": len(ads) if total is None else total, **changes}


class Transport:
    """Only HTTP is replaced: exercise the installed SDK and actual collector."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.closed = 0
        self.headers = {}
        self.initial_calls = []

    def get(self, url, *, verify, timeout):
        self.initial_calls.append({"url": url, "verify": verify, "timeout": timeout})
        return NS(status_code=200)

    def request(self, *, method, url, json, verify, timeout):
        assert method == "POST" and url == SEARCH_URL  # No seller lookup.
        assert verify is True and 0 < timeout <= 20
        self.calls.append(copy.deepcopy(json))
        answer = self.reply(json, len(self.calls))
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, int):
            return NS(ok=False, status_code=answer)
        return NS(ok=True, status_code=200, json=lambda: answer)

    def close(self):
        self.closed += 1


def transport(monkeypatch, reply):
    remote = Transport(reply)
    monkeypatch.setattr(leboncoin.curl_requests, "Session", lambda **kwargs: remote)
    monkeypatch.setattr(c.time, "sleep", lambda delay: None)
    return remote


def test_sixty_two_results_and_eleven_classics_need_only_one_http_request(monkeypatch):
    ads = [advert(i, classic=i < 11) for i in range(62)]
    def reply(body, attempt):
        assert attempt == 1  # A second request would receive DataDome 403.
        assert body["limit"] == 100 and body["owner_type"] == "all"
        assert body["filters"]["category"] == {"id": "2"}
        assert body["filters"]["keywords"] == {"text": "opel gt"}
        assert body["disable_total"] is True and body["extend"] is True
        assert body["offset"] == 0 and body["limit_alu"] == 0
        return page(ads, total_all=62, total_private=62, total_pro=0, max_pages=1)
    remote = transport(monkeypatch, reply)
    rows = c.collect_leboncoin(None)
    assert len(rows) == 11 and len({row["id"] for row in rows}) == 11
    assert all(row["seller_type"] == "particulier" and row["price"] == 17500 for row in rows)
    assert len(remote.calls) == 1 and remote.closed == 1


def test_session_preserves_sdk_identity_and_initializes_cookies_with_a_timeout(monkeypatch):
    calls = []
    remote = Transport(lambda body, attempt: page([]))
    def session(**kwargs):
        calls.append(kwargs)
        return remote
    monkeypatch.setattr(leboncoin.curl_requests, "Session", session)
    monkeypatch.setattr(lbc.Client, "_generate_user_agent", lambda self: "LBC;fixture-only")
    for _ in range(3):
        client = c.create_lbc_client()
        assert client.max_retries == 0
        client.session.close()
    assert calls == [{"impersonate": "safari170", "verify": True, "timeout": 20}] * 3
    assert remote.headers["User-Agent"] == "LBC;fixture-only" and not remote.calls
    assert remote.initial_calls == [{"url": "https://www.leboncoin.fr/", "verify": True, "timeout": 20}] * 3


def test_mixed_sellers_and_unknown_year_keep_the_original_vehicle_scope(monkeypatch):
    ads = [advert(1), advert(2, owner="pro", subject="Opel GT/J"), advert(3, subject="Opel GT 1100"),
           advert(4, attributes=[]), advert(5, classic=False), advert(6, country="DE"),
           advert(7, subject="Pièce détachée Opel GT 1900"), advert(8, subject="Opel Manta 1900")]
    # Seller counters can describe a wider result set; they are not page lengths.
    remote = transport(monkeypatch, lambda body, attempt: page(ads, total_private=500, total_pro=500, max_pages=1))
    rows = c.collect_leboncoin(None)
    assert [row["model"] for row in rows] == ["1900", "GT/J", "1100", "1900"]
    assert [row["seller_type"] for row in rows] == ["particulier", "professionnel", "particulier", "particulier"]
    assert rows[-1]["year"] is None and len(remote.calls) == 1


@pytest.mark.parametrize("pivot", [None, '{"es_pivot":"fixture-only","page_number":1}'])
def test_actual_page_size_and_server_cursor_are_used_when_size_is_capped(monkeypatch, pivot):
    ads = [advert(i) for i in range(62)]
    def reply(body, attempt):
        if attempt == 1:
            assert "pivot" not in body
            return page(ads[:35], total=62, max_pages=2, pivot=pivot)
        assert attempt == 2 and body["offset"] == 35  # Not the requested 100.
        if pivot:
            assert body["pivot"] == pivot
        else:
            assert "pivot" not in body
        return page(ads[35:], total=62, max_pages=2)
    remote = transport(monkeypatch, reply)
    rows = c.collect_leboncoin(None)
    assert len(rows) == 62 and len(remote.calls) == 2 and remote.closed == 1


def test_cursor_is_reset_for_a_new_search_and_not_reused_for_another_query(monkeypatch):
    remote = transport(monkeypatch, lambda body, attempt: page([advert(attempt)], total=2, pivot="first-cursor"))
    client = c.create_lbc_client()
    try:
        client.search(text="opel gt", owner_type=lbc.OwnerType.ALL)
        client.search(text="opel gt", owner_type=lbc.OwnerType.ALL, page=2)
        assert remote.calls[1]["offset"] == 1 and remote.calls[1]["pivot"] == "first-cursor"
        client.search(text="opel manta", owner_type=lbc.OwnerType.ALL)
        assert remote.calls[-1]["offset"] == 0 and "pivot" not in remote.calls[-1]
        with pytest.raises(c.CollectionError, match="correspondante"):
            client.search(text="other", owner_type=lbc.OwnerType.ALL, page=2)
        assert len(remote.calls) == 3
    finally:
        client.session.close()


@pytest.mark.parametrize("owner", [None, {}, {"type": "unknown"}, "not-a-dictionary"])
def test_unknown_seller_is_not_guessed_and_never_fetches_a_profile(monkeypatch, owner):
    remote = transport(monkeypatch, lambda body, attempt: page([{**advert(1), "owner": owner}]))
    rows = c.collect_leboncoin(None)
    assert len(rows) == 1 and rows[0]["seller_type"] == "inconnu"
    assert len(remote.calls) == 1 and remote.closed == 1


@pytest.mark.parametrize("refusal", [403, 429, 503, Timeout("fixture timeout")])
def test_first_request_refusal_has_no_retry_and_always_closes_the_session(monkeypatch, refusal):
    remote = transport(monkeypatch, lambda body, attempt: refusal)
    with pytest.raises(c.AccessRestricted if refusal == 403 else c.CollectionError):
        c.collect_leboncoin(None)
    assert len(remote.calls) == 1 and remote.closed == 1


@pytest.mark.parametrize("failure", [403, 503, Timeout("fixture timeout")])
def test_later_failure_retains_observations_without_claiming_either_seller_complete(monkeypatch, failure):
    remote = transport(monkeypatch, lambda body, attempt: page([advert(1), advert(2, owner="pro")], total=3)
                       if attempt == 1 else failure)
    with pytest.raises(c.PartialCollection) as caught:
        c.collect_leboncoin(None)
    assert len(caught.value.items) == 2 and caught.value.completed_sellers == set()
    assert caught.value.restricted == (failure == 403)
    assert len(remote.calls) == 2 and remote.closed == 1


@pytest.mark.parametrize("raw", [None, {}, {"ads": {}}, {"ads": [None]},
                                     page([advert(1)], pivot={}), page([advert(1)], pivot="x" * 65537)])
def test_invalid_transport_response_never_becomes_an_empty_success(monkeypatch, raw):
    remote = transport(monkeypatch, lambda body, attempt: raw)
    with pytest.raises(c.CollectionError):
        c.collect_leboncoin(None)
    assert len(remote.calls) == 1 and remote.closed == 1


def test_real_sdk_repeated_page_remains_partial_but_wrong_page_count_does_not_abort(monkeypatch):
    remote = transport(monkeypatch, lambda body, attempt: page([advert(1)], total=3, max_pages=2))
    with pytest.raises(c.PartialCollection, match="répétée") as caught:
        c.collect_leboncoin(None)
    assert len(caught.value.items) == 1 and len(remote.calls) == 2
    remote.calls.clear()
    remote.reply = lambda body, attempt: page([advert(attempt)], total=3, max_pages=1)
    rows = c.collect_leboncoin(None)
    assert len(remote.calls) == 3 and len(rows) == 3


def test_transport_success_recovers_failed_cache_and_preserves_user_data(monkeypatch, tmp_path):
    monkeypatch.setattr(s, "directory", lambda: tmp_path)
    for source in s.SOURCES:
        monkeypatch.setitem(s.COLLECTORS, source.id, c.collect_leboncoin if source.id == "leboncoin" else lambda client: [])
    ads = [advert(i, owner="private" if i < 9 else "pro") for i in range(11)]
    remote = transport(monkeypatch, lambda body, attempt: page(ads, total_private=9, total_pro=2))
    rows = c.collect_leboncoin(None)
    for number, row in enumerate(rows, 1):
        row.update(number=number, geo={"lat": 48.6463, "lon": 2.0823, "precision": "commune"})
    s.write_json(tmp_path / "leboncoin.json", {"items": rows, "status": "failed", "last_success_at": None,
                                               "message": "Nombre maximal de pages Leboncoin atteint"})
    preferences = {"favorites": ["leboncoin:1"], "hidden": ["leboncoin:2"]}
    s.write_json(tmp_path / "users/test.json", preferences)
    before = (tmp_path / "users/test.json").read_bytes()
    assert s.synchronize() == 0
    saved = s.read_json(tmp_path / "leboncoin.json")
    assert saved["status"] == "ok" and saved["last_success_at"]
    assert len(saved["items"]) == 11 and {row["seller_type"] for row in saved["items"]} == {"particulier", "professionnel"}
    assert [row["number"] for row in saved["items"]] == list(range(1, 12))
    assert all(row.get("geo") for row in saved["items"])
    assert (tmp_path / "users/test.json").read_bytes() == before
    assert json.loads((tmp_path / "leboncoin.json").read_text())["last_success_at"]
    assert len(remote.calls) == 2  # Fixture setup plus one real synchronization.


def test_sdk_collects_twenty_one_capped_pages_without_trusting_max_pages(monkeypatch):
    def reply(body, attempt):
        start = body["offset"]
        assert start == (attempt - 1) * 35
        ads = [advert(i, classic=i < 11) for i in range(start, min(start + 35, 735))]
        return page(ads, total=735, total_private=31, total_pro=704, max_pages=8)
    remote = transport(monkeypatch, reply)
    rows = c.collect_leboncoin(None)
    assert len(rows) == 11 and len(remote.calls) == 21
    assert remote.calls[-1]["offset"] == 700 and remote.closed == 1


@pytest.mark.parametrize("terminal", ["empty", "repeated"])
@pytest.mark.parametrize("total", [0, 63, None])
def test_short_final_page_is_confirmed_despite_a_stale_total(monkeypatch, total, terminal):
    def reply(body, attempt):
        if attempt == 1:
            ids = range(35)
        elif attempt == 2 or terminal == "repeated":
            ids = range(35, 61)
        else:
            ids = []
        return page([advert(i, classic=i < 11) for i in ids], total=total, max_pages=1)
    # page() treats None as a default; supply the missing value explicitly.
    def response(body, attempt):
        return {**reply(body, attempt), "total": total}
    remote = transport(monkeypatch, response)
    assert len(c.collect_leboncoin(None)) == 11
    assert len(remote.calls) == 3 and remote.closed == 1


def test_safety_budget_keeps_partial_observations_and_closes_the_session(monkeypatch):
    monkeypatch.setattr(c, "LBC_MAX_PAGES", 2)
    remote = transport(monkeypatch, lambda body, attempt: page([advert(attempt)], total=100, max_pages=100))
    with pytest.raises(c.PartialCollection, match="Nombre maximal") as caught:
        c.collect_leboncoin(None)
    assert len(caught.value.items) == 2 and len(remote.calls) == 2 and remote.closed == 1


def test_an_earlier_short_page_cannot_hide_a_later_pagination_failure(monkeypatch):
    def reply(body, attempt):
        ids = range(35) if attempt == 1 else range(35, 61) if attempt == 2 else range(61, 96)
        return page([advert(i, classic=i < 11) for i in ids], total=200, max_pages=2)
    remote = transport(monkeypatch, reply)
    with pytest.raises(c.PartialCollection, match="répétée") as caught:
        c.collect_leboncoin(None)
    assert len(caught.value.items) == 11 and len(remote.calls) == 4 and remote.closed == 1


def test_initial_cookie_request_failure_closes_the_unfinished_client(monkeypatch):
    remote = transport(monkeypatch, lambda body, attempt: page([]))
    def failed_get(*args, **kwargs):
        raise Timeout("initialization timeout")
    remote.get = failed_get
    with pytest.raises(c.CollectionError):
        c.collect_leboncoin(None)
    assert not remote.calls and remote.closed == 1
