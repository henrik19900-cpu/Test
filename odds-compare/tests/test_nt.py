import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import load_fixture

from oddscompare.config import NorskTippingConfig
from oddscompare.sources import SourceError
from oddscompare.sources.nt import NorskTipping, _messages, decimal_odds, parse_event_groups

SAMPLE = load_fixture("nt_sample.json")
FETCHED = datetime.fromisoformat(SAMPLE["fetched_at_utc"])


@pytest.mark.parametrize(
    ("up", "down", "decimal"), [("31", "10", 4.10), ("29", "10", 3.90), ("3", "4", 1.75), ("4", "7", 1.57)]
)
def test_fractional_prices_become_decimal_odds_as_shown(up, down, decimal):
    assert decimal_odds(up, down) == decimal


def test_the_fixture_parses_to_1x2_odds():
    events = parse_event_groups(SAMPLE["event_groups"], FETCHED, 14)
    assert len(events) == 88
    match = next(e for e in events if e.home == "Fredrikstad" and e.away == "Rosenborg")
    assert match.odds == {"home": 4.10, "draw": 3.90, "away": 1.75}  # as the page showed it
    assert match.league == "Norge - Eliteserien"
    assert match.kickoff_utc == datetime(2026, 10, 31, 15, 0, tzinfo=UTC)  # 16:00 in Oslo
    assert match.source == "norsk_tipping" and match.source_event_id == "8894610.1"


def test_only_matches_within_the_days_ahead_are_kept():
    events = parse_event_groups(SAMPLE["event_groups"], FETCHED, 1)
    assert events and all(FETCHED < e.kickoff_utc <= FETCHED + timedelta(days=1) for e in events)
    assert parse_event_groups(SAMPLE["event_groups"], FETCHED + timedelta(days=30), 7) == []


def test_a_changed_format_fails_loudly():
    broken = {"1": {"events": [{"idfoevent": "1", "name": "A - B"}, {"idfoevent": "2"}]}}
    with pytest.raises(SourceError, match="forventet format") as caught:
        parse_event_groups(broken, FETCHED, 7)
    assert not caught.value.retryable


def test_matches_without_an_open_1x2_market_are_skipped():
    group = next(iter(SAMPLE["event_groups"].values()))
    event = json.loads(json.dumps(group["events"][0]))
    event["markets"][0]["selections"][0]["idfoselectionsuspensiontype"] = "SUSPENDED"
    assert parse_event_groups({"g": {"events": [event]}}, FETCHED, 14) == []


def test_sockjs_frames():
    inner = json.dumps(
        {"version": 1, "data": [{"contentId": {"type": "eventGroup", "id": "1"}, "changeType": "refreshed"}]}
    )
    assert [m["contentId"]["id"] for m in _messages("a" + json.dumps([inner]))] == ["1"]
    assert (
        list(_messages("o")) == []
        and list(_messages("h")) == []
        and list(_messages('c[3000,"Go away!"]')) == []
    )


# A Norsk Tipping that answers from the fixture, over a fake HTTP transport and a fake websocket.

NAVIGATION = {
    "1355/42978.1": {"name": "Fotball", "bonavigationnodes": [
        {"idfwbonavigation": "66760.1", "name": "Norge", "numevents": "57"},
        {"idfwbonavigation": "1.1", "name": "Brasil", "numevents": "12"},
    ]},
    "1355/66760.1": {"name": "Norge", "marketgroups": [], "bonavigationnodes": [
        {"idfwbonavigation": "66761.1", "name": "Eliteserien", "numevents": "7"},
        {"idfwbonavigation": "67886.1", "name": "Eliteserien", "numevents": "0"},
    ]},
    "1355/66761.1": {"name": "Eliteserien", "bonavigationnodes": [], "marketgroups": [
        {"idfwmarketgroup": "89295.1", "idfwmarketgrouptype": "MATCHESCOUPON"},
    ]},
}  # fmt: skip


class FakeSite:
    def __init__(self):
        self.calls = []
        self.subscribed = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        action = request.url.path.rsplit("/", 1)[-1]
        self.calls.append((action, body["contentId"]["id"]))
        assert request.headers["user-agent"] == "test-agent"
        if action == "subscribe":
            assert body["subscriberId"] == "SUB1"
            self.subscribed.append(body["contentId"]["id"])
            return httpx.Response(200, json={"version": 1})
        return httpx.Response(200, json={"data": NAVIGATION[body["contentId"]["id"]], "version": 1})


class FakeSocket:
    def __init__(self, site: FakeSite):
        self.site = site
        self.sent = []
        self.frames = ["o"]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def send(self, text):
        self.sent.append(text)
        hello = json.loads(json.loads(text)[0])
        assert hello["subscriberId"] is None
        started = json.dumps({"version": 1, "data": "SUB1", "notificationType": "LISTENING_STARTED"})
        self.frames += ["h", "a" + json.dumps([started])]

    def recv(self, timeout=None):
        if not self.frames and self.site.subscribed:
            group = {gid: g for gid, g in SAMPLE["event_groups"].items() if gid == "89295.1"}["89295.1"]
            push = json.dumps({"version": 1, "data": [
                {"contentId": {"type": "boNavigationList", "id": "x"}, "changeType": "refreshed", "change": {}},
                {"contentId": {"type": "eventGroup", "id": "89295.1"}, "changeType": "refreshed", "change": group},
            ]})  # fmt: skip
            self.site.subscribed.clear()
            return "a" + json.dumps([push])
        if not self.frames:
            raise TimeoutError
        return self.frames.pop(0)


def make_source(tmp_path, site, clock, **cfg):
    sockets = []

    def stream(url, headers):
        assert url.startswith("wss://velnt") and url.endswith("/websocket")
        sockets.append(FakeSocket(site))
        return sockets[-1]

    source = NorskTipping(
        NorskTippingConfig(countries=["Norge"], timeout_seconds=2, **cfg),
        "test-agent",
        cache_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(site.handle)),
        stream_factory=stream,
        clock=clock,
    )
    return source, sockets


def test_fetch_walks_the_menu_subscribes_and_reads_the_websocket(tmp_path):
    site = FakeSite()
    now = [FETCHED]
    source, sockets = make_source(tmp_path, site, lambda: now[0])

    events = source.fetch(7)
    assert {e.home for e in events} >= {"Fredrikstad", "Brann", "Vålerenga"}
    assert all(e.league == "Norge - Eliteserien" for e in events)
    # Only the configured country, only nodes with matches, then one subscription per coupon.
    assert site.calls == [
        ("get", "1355/42978.1"),
        ("get", "1355/66760.1"),
        ("get", "1355/66761.1"),
        ("subscribe", "89295.1"),
    ]
    assert (tmp_path / "norsk_tipping.json").exists()

    assert source.fetched_at == FETCHED

    # Within five minutes the cached answer is used, without a single call, and keeps its time.
    site.calls.clear()
    now[0] = FETCHED + timedelta(minutes=4)
    assert len(source.fetch(7)) == len(events)
    assert site.calls == [] and len(sockets) == 1
    assert source.fetched_at == FETCHED

    # After five minutes it fetches again, but the league menu still comes from its own cache.
    now[0] = FETCHED + timedelta(minutes=6)
    source.fetch(7)
    assert site.calls == [("subscribe", "89295.1")] and len(sockets) == 2


def test_login_wall_stops_without_retrying(tmp_path):
    source = NorskTipping(
        NorskTippingConfig(),
        "test-agent",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401))),
        stream_factory=lambda url, headers: pytest.fail("no websocket without a menu"),
    )
    with pytest.raises(SourceError, match="innlogging") as caught:
        source.fetch(7)
    assert not caught.value.retryable


def test_unknown_countries_are_reported(tmp_path):
    source, _ = make_source(tmp_path, FakeSite(), lambda: FETCHED)
    source.cfg = NorskTippingConfig(countries=["Atlantis"])
    with pytest.raises(SourceError, match="Atlantis"):
        source.fetch(7)


def test_silent_websocket_is_an_error(tmp_path):
    site = FakeSite()
    source, sockets = make_source(tmp_path, site, lambda: FETCHED)

    class Silent(FakeSocket):
        def recv(self, timeout=None):
            if self.frames:
                return self.frames.pop(0)
            raise TimeoutError

    source.stream_factory = lambda url, headers: Silent(site)
    source.cfg = source.cfg.model_copy(update={"timeout_seconds": 0.2})
    with pytest.raises(SourceError, match="ingen kamper"):
        source.fetch(7)
