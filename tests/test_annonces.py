from __future__ import annotations

import fcntl
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.annonces import collectors as c
from app.annonces import service as s

ROOT = Path(__file__).resolve().parents[1]


def raw_ad(ident=1, **changes):
    return {**{
        "id": ident, "url": f"/annonce/opel-gt-a{ident}", "title": "1969 Opel GT 1900",
        "year": "1969", "attributes": {"engineSize": "1900"}, "isSold": False,
        "location": {"countryCode": "FR", "town": "Limours", "regionCode": "91"},
        "sellerType": "private", "advert": {"createdAt": "2026-10-18T23:10:00+00:00"},
        "images": [{"url": "/uploads/cars/opel/fixture.jpg"}],
    }, **changes}


def inertia(ads, *, total=None, pages=1):
    props = {"listings": ads, "pagination": {"total": len(ads) if total is None else total, "last_page": pages}}
    return '<script data-page="app" type="application/json">' + json.dumps({"props": props}) + '</script>'


class Pages:
    def __init__(self, *pages):
        self.pages, self.urls = iter(pages), []

    def get(self, url):
        self.urls.append(url)
        return next(self.pages)


@pytest.fixture
def data(monkeypatch, tmp_path):
    monkeypatch.setattr(s, "directory", lambda: tmp_path)
    for source in c.SOURCES[2:]:
        monkeypatch.setitem(s.COLLECTORS, source.id, lambda client: [])
    return tmp_path


def test_france_classics_original_dates_photos_and_direct_links():
    ads = [raw_ad(), raw_ad(2, title="Opel GT 1100", attributes={"engineSize": 1078}),
           raw_ad(3, title="1973 Opel GT/J", year="1973", sellerType="pro"),
           raw_ad(4, title="2007 Opel GT Roadster", year="2007"),
           raw_ad(5, location={"countryCode": "NL"}), raw_ad(6, isSold=True),
           raw_ad(7, title="Pièce détachée Opel GT 1900"), raw_ad(8, title="Opel Manta 1900")]
    client = Pages(inertia(ads))
    rows = c.collect_lesanciennes(client)
    assert [item["model"] for item in rows] == ["1900", "1100", "GT/J"]
    assert rows[0]["seller_type"] == "particulier" and rows[2]["seller_type"] == "professionnel"
    assert rows[0]["department"] == "91" and rows[0]["location"] == "Limours"
    assert rows[0]["published_at"] == "2026-10-19"
    assert rows[0]["image_url"] == "https://assets.lesanciennes.com/uploads/cars/opel/fixture.jpg"
    assert rows[0]["url"] == "https://www.lesanciennes.com/annonce/opel-gt-a1"
    assert client.urls == [c.SOURCES[0].url]


def test_missing_information_is_not_invented_and_trader_metadata_is_explicit():
    rows = c.collect_lesanciennes(Pages(inertia([
        raw_ad(sellerType=None, advert={}, images=[], attributes={}, title="1969 Opel GT"),
        raw_ad(2, sellerType=None, seller={"thumbnailUrl": "https://assets.example/uploads/traders/photo.jpg"}),
    ])))
    assert rows[0]["seller_type"] == "inconnu" and rows[0]["model"] == "Modèle non précisé"
    assert rows[0]["published_at"] is None and rows[0]["image_url"] is None
    assert rows[1]["seller_type"] == "professionnel"


@pytest.mark.parametrize("region,postal,expected", [("91", "", "91"), ("2A", "", "2A"), ("", "20100", "2A"), ("", "20200", "2B"), ("", "97410", "974"), ("xx", "", None)])
def test_departments(region, postal, expected):
    assert c.department_code(region, postal) == expected


@pytest.mark.parametrize("title,year,expected", [("Opel GT1900", 1969, "1900"), ("Opel GT J 1900", 1973, "GT/J"), ("Opel GT 1,1", 1970, "1100"), ("Opel GT 2.0 Turbo", 2008, None), ("Miniature Opel GT 1900", 1969, None)])
def test_models(title, year, expected):
    assert c.model_of(title, "", None, year) == expected


def test_pagination_completes_and_partial_results_fail():
    client = Pages(inertia([raw_ad()], total=2, pages=2), inertia([raw_ad(2)], total=2, pages=2))
    assert len(c.collect_lesanciennes(client)) == 2 and client.urls[1].endswith('?page=2')
    for html in [inertia([raw_ad()], total=2), inertia([raw_ad()], pages=21), "<html>Maintenance</html>"]:
        with pytest.raises(c.CollectionError):
            c.collect_lesanciennes(Pages(html))


def test_leboncoin_uses_lbc_paginates_and_preserves_seller_type(monkeypatch):
    from types import SimpleNamespace as NS

    import lbc
    calls, closed = [], []
    def ad(ident, **changes):
        return NS(**{**dict(id=ident,category_id="2",status="active",subject="Opel GT 1100",body="",price=16000.0,
            attributes={"regdate":NS(value="1969",values=[])},
            location=NS(country_id="FR",city_label="Bastia",city="Bastia",department_id="",zipcode="20200"),
            first_publication_date="2026-10-10 10:00:00",images=["https://img.leboncoin.fr/api/v1/fixture.jpg"],
            url=f"https://www.leboncoin.fr/ad/voitures/{ident}"),**changes})
    def search(**kwargs):
        calls.append(kwargs)
        private = kwargs['owner_type'] == lbc.OwnerType.PRIVATE
        return NS(total=2 if private else 1,ads=[ad(kwargs['page'] if private else 3)])
    remote=NS(search=search,session=NS(close=lambda:closed.append(True)))
    monkeypatch.setattr(c,'create_lbc_client',lambda:remote)
    monkeypatch.setattr(c.time,'sleep',lambda _:None)
    rows=c.collect_leboncoin(None)
    assert [r['seller_type'] for r in rows] == ['particulier','particulier','professionnel']
    assert all(r['department']=='2B' and r['published_at']=='2026-10-10' and r['price']==16000 for r in rows)
    assert [v['page'] for v in calls] == [1,2,1]
    assert all(v['category']==lbc.Category.VEHICULES_VOITURES and v['limit_alu']==0 for v in calls)
    assert closed == [True]
    def fail(**kwargs): raise lbc.exceptions.DatadomeError('blocked')
    remote.search=fail
    with pytest.raises(c.AccessRestricted,match='lbc.*403'):
        c.collect_leboncoin(None)
    assert closed == [True,True]


def test_leboncoin_rejects_incomplete_pages_and_closes_session(monkeypatch):
    from types import SimpleNamespace as NS
    closed=[]
    remote=NS(search=lambda **kwargs:NS(total=1,ads=[]),session=NS(close=lambda:closed.append(True)))
    monkeypatch.setattr(c,'create_lbc_client',lambda:remote)
    with pytest.raises(c.CollectionError,match='incomplète'):
        c.collect_leboncoin(None)
    assert closed


@pytest.mark.parametrize("url", ['javascript:alert(1)', 'https://www.lesanciennes.com.evil.test/annonce/a', 'https://user@www.lesanciennes.com/annonce/a', 'http://www.lesanciennes.com/annonce/a', 'https://www.lesanciennes.com:8080/annonce/a'])
def test_unsafe_urls(url):
    assert c.safe_url(url, c.SOURCES[0].url) is None


def test_robots_disallow_prevents_request_to_results(monkeypatch):
    client = c.PublicClient(c.SOURCES[1])
    calls = []
    def get(url):
        calls.append(url)
        return 'User-agent: *\nDisallow: /'
    monkeypatch.setattr(client, '_get', get)
    with pytest.raises(c.AccessRestricted, match='robots.txt'):
        client.get(client.source.url)
    assert calls == ['https://www.leboncoin.fr/robots.txt']
    client.close()


@pytest.mark.parametrize('status', [401, 403, 429])
def test_access_refusal_stops_without_repeated_requests(monkeypatch, status):
    client = c.PublicClient(c.SOURCES[0])
    calls = []
    class Response:
        status_code = status
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    def get(*args, **kwargs):
        calls.append(args[0])
        assert kwargs['allow_redirects'] is False and kwargs['timeout'] == (10, 20)
        return Response()
    monkeypatch.setattr(client.session, 'get', get)
    with pytest.raises(c.AccessRestricted):
        client._get(client.source.url)
    assert len(calls) == 1
    client.close()


def test_source_failure_preserves_ads_and_concurrent_update_cannot_start(data, monkeypatch):
    old = [{'id': 'old', 'seller_type': 'particulier'}]
    s.write_json(data / 'leboncoin.json', {'items': old, 'last_success_at': '2026-01-01'})
    fresh = c.collect_lesanciennes(Pages(inertia([raw_ad()])))
    def collect(client):
        assert s.snapshot()['running'] is True and s.snapshot()['items'] == []
        assert s.synchronize() == 0
        return fresh
    def restricted(client):
        raise c.AccessRestricted('HTTP 403')
    monkeypatch.setitem(s.COLLECTORS, 'lesanciennes', collect)
    monkeypatch.setitem(s.COLLECTORS, 'leboncoin', restricted)
    assert s.synchronize() == 0
    snapshot = s.snapshot()
    assert snapshot['running'] is False and snapshot['count'] == 2 and snapshot['last_completed_at']
    assert s.read_json(data / 'leboncoin.json')['items'] == old
    assert s.read_json(data / 'leboncoin.json')['last_success_at'] == '2026-01-01'
    assert snapshot['sources'][1]['status'] == 'restricted'


def test_suspicious_drop_preserves_last_valid_source(data, monkeypatch):
    old = [{'id': str(i), 'seller_type': 'particulier'} for i in range(10)]
    for source in s.SOURCES:
        s.write_json(data / f'{source.id}.json', {'items': old})
        monkeypatch.setitem(s.COLLECTORS, source.id, lambda client: [])
    assert s.synchronize() == 1 and len(s.snapshot()['items']) == 10 * len(s.SOURCES)
    assert all(source['status'] == 'failed' for source in s.snapshot()['sources'])


def test_dead_process_lock_and_stale_metadata_do_not_block(data):
    s.write_json(data / 'sync.json', {'started_at': '2000-01-01', 'finished_at': None})
    s.write_json(data / 'lesanciennes.json', {'items': [{'id': 'fixture'}]})
    command = [sys.executable, '-u', '-c', 'import fcntl,sys,time; f=open(sys.argv[1],"a"); fcntl.flock(f,fcntl.LOCK_EX); print("ready"); time.sleep(30)', str(data / 'update.lock')]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'ready'
        assert s.snapshot()['running'] and s.snapshot()['items'] == []
    finally:
        process.terminate()
        process.wait(timeout=3)
        process.stdout.close()
    assert not s.snapshot()['running'] and len(s.snapshot()['items']) == 1


def test_shared_reader_prevents_partial_snapshot(data):
    with s.read_lock() as running:
        assert not running
        with (data / 'update.lock').open('a') as stream:
            with pytest.raises(BlockingIOError):
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_daily_paris_timer_and_service_lifecycle():
    timer = (ROOT / 'systemd/portail-entraide-opel-gt-annonces-update.timer').read_text()
    unit = (ROOT / 'systemd/portail-entraide-opel-gt-annonces-update.service').read_text()
    script = (ROOT / 'run_server.sh').read_text()
    assert 'OnCalendar=*-*-* 02:00:00 Europe/Paris' in timer and 'Persistent=true' in timer
    assert 'RandomizedDelaySec=0' in timer
    assert 'User=opelgt' in unit and 'TimeoutStartSec=15min' in unit and 'KillMode=control-group' in unit
    assert '-m app.annonces.service' in unit
    assert 'systemctl start --no-block' in script
    all_units = script.split('ALL_UNIT_FILES=(', 1)[1].split(')', 1)[0]
    assert '-annonces-update.service' in all_units and '-annonces-update.timer' in all_units


def test_five_browser_sorts_are_reversible_and_unknowns_last():
    program = r'''
const assert = require('node:assert/strict');
const ui = require(process.argv[1]);
const a = {id:'a',seller_type:'particulier',model:'1100',year:1969,published_at:'2020-01-01',department:'19'};
const b = {id:'b',seller_type:'professionnel',model:'GT/J',year:1973,published_at:'2024-01-01',department:'21'};
const missing = {id:'x',seller_type:'inconnu',model:'Modèle non précisé'};
for (const key of ['seller_type','model','year','published_at','department']) {
  assert.deepEqual(ui.sortItems([b,missing,a], key, 1).map(i=>i.id), ['a','b','x']);
  assert.deepEqual(ui.sortItems([a,missing,b], key, -1).map(i=>i.id), ['b','a','x']);
}
assert.deepEqual(ui.sortItems([{id:'b',department:'2B'},{id:'c',department:'21'},{id:'a',department:'2A'}], 'department',1).map(i=>i.id), ['a','b','c']);
assert.equal(ui.formatDate(null), 'Non précisée');
assert.equal(ui.formatDate('2026-01-02'), '02/01/2026');
assert.equal(ui.validUrl('javascript:alert(1)'), '');
assert.equal(ui.validUrl('https://evil.test/ad/a'), '');
assert.equal(ui.formatPrice({price:null}), 'Non précisé');
assert.equal(ui.formatPrice({price:null,price_label:'Enchères'}), 'Enchères');
assert.match(ui.formatPrice({price:16000,currency:'EUR'}), /16.*000.*€/);
assert.ok(ui.validUrl('https://www.classicnumber.com/opel-gt-collection-a-vendre-123.html'));
assert.ok(ui.validUrl('https://www.classic-trader.com/fr/voitures/annonce/opel/gt/gt-1900/1970/123'));
assert.ok(ui.validUrl('https://cdn.classic-trader.com/I/images/fixture.jpg', true));
assert.ok(ui.validUrl('https://www.leboncoin.fr/ad/voitures/123'));
'''
    result = subprocess.run(['node', '-e', program, str(ROOT / 'static/annonces/app.js')], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr



def test_daily_update_waits_for_a_short_snapshot_reader(data, monkeypatch):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    reading = threading.Event()
    def reader():
        with s.read_lock():
            reading.set()
            time.sleep(0.15)
    for source in s.SOURCES:
        monkeypatch.setitem(s.COLLECTORS, source.id, lambda client: [])
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(reader)
        assert reading.wait(timeout=1)
        assert s.synchronize() == 0
        future.result(timeout=1)
    assert s.read_json(data / 'sync.json')['finished_at']
    assert all(source['status'] == 'ok' for source in s.snapshot()['sources'])
