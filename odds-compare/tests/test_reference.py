from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest
from conftest import load_fixture

from oddscompare.config import OddsApiIoConfig, OddsLinkConfig, TheOddsApiConfig
from oddscompare.sources import RawEvent, SourceError
from oddscompare.sources.reference import (
    FallbackReference,
    OddsApiIo,
    OddsLink,
    TheOddsApi,
    parse_h2h,
    parse_odds,
)

SAMPLE = load_fixture("odds_api_io_sample.json")
NOW = datetime(2026, 10, 31, 5, 0, tzinfo=UTC)


def test_parse_odds_reads_the_ml_market():
    events = parse_odds(SAMPLE["odds"], "Betfair Exchange")
    assert len(events) == 98
    match = next(e for e in events if e.home == "Fredrikstad FK")
    assert match.away == "Rosenborg BK"
    assert match.league == "Norway - Eliteserien"
    assert match.kickoff_utc.tzinfo is not None
    assert set(match.odds) == {"home", "draw", "away"} and all(o > 1 for o in match.odds.values())


def test_events_without_the_bookmaker_or_market_are_skipped():
    event = dict(SAMPLE["odds"][0])
    assert parse_odds([event], "Pinnacle") == []
    event["bookmakers"] = {
        "Betfair Exchange": [{"name": "Totals", "odds": [{"over": "1.9", "under": "1.9"}]}]
    }
    assert parse_odds([event], "Betfair Exchange") == []


def test_a_changed_format_fails_loudly():
    with pytest.raises(SourceError, match="uventet format"):
        parse_odds({"error": "nope"}, "Betfair Exchange")
    broken = {
        "id": 1,
        "bookmakers": {
            "Betfair Exchange": [{"name": "ML", "odds": [{"home": "2", "draw": "3", "away": "4"}]}]
        },
    }
    with pytest.raises(SourceError, match="uventet format"):
        parse_odds([broken], "Betfair Exchange")  # no teams or date


class FakeApi:
    def __init__(self, status=200):
        self.status = status
        self.requests = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        self.requests.append((request.url.path, params))
        assert params["apiKey"] == "secret"
        if self.status != 200:
            return httpx.Response(self.status, text="no")
        if request.url.path.endswith("/events"):
            assert params["bookmaker"] == "Betfair Exchange" and params["sport"] == "football"
            return httpx.Response(
                200, json=[{k: v for k, v in e.items() if k != "bookmakers"} for e in SAMPLE["odds"]]
            )
        ids = params["eventIds"].split(",")
        assert len(ids) <= 10 and params["markets"] == "ML"
        return httpx.Response(200, json=[e for e in SAMPLE["odds"] if str(e["id"]) in ids])


def make_source(api, tmp_path, key="secret", **cfg):
    return OddsApiIo(
        OddsApiIoConfig(**cfg),
        key,
        "test-agent",
        cache_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(api.handle)),
        clock=lambda: NOW,
    )


def test_fetch_lists_events_then_fetches_odds_ten_at_a_time(tmp_path):
    api = FakeApi()
    events = make_source(api, tmp_path).fetch(7)
    assert len(events) == 98
    paths = [p for p, _ in api.requests]
    assert (
        paths[0].endswith("/v3/events") and paths.count("/v3/odds/multi") == 10
    )  # 98 events, 10 per request
    assert (
        api.requests[0][1]["from"] == "2026-10-31T05:00:00Z"
        and api.requests[0][1]["to"] == "2026-11-07T05:00:00Z"
    )
    assert (tmp_path / "odds_api_io.json").exists()


def test_want_limits_the_odds_requests(tmp_path):
    api = FakeApi()
    events = make_source(api, tmp_path).fetch(7, want=lambda home, away, kickoff: home == "Fredrikstad FK")
    assert [e.home for e in events] == ["Fredrikstad FK"]
    assert [p for p, _ in api.requests].count("/v3/odds/multi") == 1


def test_one_events_request_per_configured_league(tmp_path):
    api = FakeApi()
    make_source(api, tmp_path, leagues=["norway-eliteserien", "england-premier-league"]).fetch(
        7, want=lambda *a: False
    )
    assert [q["league"] for p, q in api.requests if p.endswith("/events")] == [
        "norway-eliteserien",
        "england-premier-league",
    ]


def test_missing_key(tmp_path):
    with pytest.raises(SourceError, match="ODDS_API_IO_KEY") as caught:
        make_source(FakeApi(), tmp_path, key=None).fetch(7)
    assert not caught.value.retryable


@pytest.mark.parametrize(
    ("status", "message", "retryable"), [(401, "avviste", False), (429, "kvoten", False), (502, "502", True)]
)
def test_http_errors(tmp_path, status, message, retryable):
    with pytest.raises(SourceError, match=message) as caught:
        make_source(FakeApi(status), tmp_path).fetch(7)
    assert caught.value.retryable is retryable


# The Odds API (the free default). Answers in the shape its v4 documentation gives.


def odds_event(event_id, home, away, commence, prices, bookmaker="pinnacle", sport="soccer_epl", others=None):
    """others: {bookmaker key: (home, draw, away)} for competitors' odds on the same match."""
    event = {
        "id": event_id,
        "sport_key": sport,
        "sport_title": "EPL" if sport == "soccer_epl" else "Eliteserien - Norway",
        "commence_time": commence,
        "home_team": home,
        "away_team": away,
        "bookmakers": [
            {
                "key": bookmaker,
                "title": "Pinnacle",
                "last_update": "2026-10-31T04:50:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": home, "price": prices[0]},
                            {"name": away, "price": prices[2]},
                            {"name": "Draw", "price": prices[1]},
                        ],
                    }
                ],
            }
        ],
    }
    for key, (h, d, a) in (others or {}).items():
        outcomes = [{"name": home, "price": h}, {"name": away, "price": a}, {"name": "Draw", "price": d}]
        event["bookmakers"].append(
            {"key": key, "title": key, "markets": [{"key": "h2h", "outcomes": outcomes}]}
        )
    return event


EPL = [
    odds_event(
        "e1",
        "Chelsea",
        "Manchester United",
        "2026-10-31T13:30:00Z",
        (1.95, 3.9, 3.85),
        others={"betsson": (1.91, 3.75, 3.7), "unibet_se": (1.93, 3.8, 3.6)},
    ),  # fmt: skip
    odds_event("e2", "Liverpool", "Arsenal", "2026-11-01T17:30:00Z", (2.30, 3.6, 3.05)),
]
NORWAY = [
    odds_event(
        "n1",
        "Fredrikstad",
        "Rosenborg",
        "2026-10-31T15:00:00Z",
        (4.30, 4.05, 1.80),
        sport="soccer_norway_eliteserien",
    )
]


def test_parse_h2h_maps_team_names_and_draw():
    [match] = parse_h2h(NORWAY, "pinnacle")
    assert (match.home, match.away, match.league) == ("Fredrikstad", "Rosenborg", "Eliteserien - Norway")
    assert match.odds == {"home": 4.30, "draw": 4.05, "away": 1.80}
    assert match.source == "the_odds_api" and match.kickoff_utc.tzinfo is not None
    assert parse_h2h(NORWAY, "betfair_ex_eu") == []  # another bookmaker's odds are not mixed in


def test_parse_h2h_fails_loudly_on_a_changed_format():
    with pytest.raises(SourceError, match="uventet format"):
        parse_h2h({"message": "nope"}, "pinnacle")
    broken = [
        {
            "id": "x",
            "bookmakers": [{"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [{"price": 2}]}]}],
        }
    ]
    with pytest.raises(SourceError, match="uventet format"):
        parse_h2h(broken, "pinnacle")


class FakeTheOddsApi:
    LEAGUES = {"soccer_epl": EPL, "soccer_norway_eliteserien": NORWAY, "soccer_sweden_allsvenskan": []}

    def __init__(self, status=200):
        self.status = status
        self.requests = []
        self.credits = 500

    def handle(self, request: httpx.Request) -> httpx.Response:
        params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        path = request.url.path.removeprefix("/v4")
        self.requests.append((path, params))
        assert params["apiKey"] == "free-key"
        if self.status != 200:
            return httpx.Response(self.status, json={"message": "no"})
        _, league, kind = path.strip("/").split("/")
        events = self.LEAGUES[league]
        if kind == "events":  # free: no credits
            listed = [{k: v for k, v in e.items() if k != "bookmakers"} for e in events]
            return httpx.Response(
                200, json=listed, headers={"x-requests-remaining": str(self.credits), "x-requests-last": "0"}
            )
        bookmakers = params["bookmakers"].split(",")
        assert (
            bookmakers[0] == "pinnacle" and len(bookmakers) <= 10
        )  # one credit per league, competitors included
        assert params["markets"] == "h2h" and params["oddsFormat"] == "decimal"
        ids = params["eventIds"].split(",")
        self.credits -= 1
        return httpx.Response(
            200,
            json=[e for e in events if e["id"] in ids],
            headers={"x-requests-remaining": str(self.credits), "x-requests-last": "1"},
        )


def make_free_source(api, tmp_path, key="free-key", clock=lambda: NOW):
    cfg = TheOddsApiConfig(
        leagues=["soccer_epl", "soccer_norway_eliteserien", "soccer_sweden_allsvenskan"],
        competitors=["unibet_se", "betsson"],
    )
    return TheOddsApi(
        cfg,
        key,
        "test-agent",
        cache_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(api.handle)),
        clock=clock,
    )


def test_the_odds_api_spends_credits_only_on_leagues_with_wanted_matches(tmp_path):
    api = FakeTheOddsApi()
    source = make_free_source(api, tmp_path)
    events = source.fetch(7, want=lambda home, away, kickoff: home in ("Fredrikstad", "Chelsea"))
    assert sorted(e.home for e in events) == ["Chelsea", "Fredrikstad"]
    odds_calls = [(p, q) for p, q in api.requests if p.endswith("/odds")]
    assert [p for p, _ in odds_calls] == ["/sports/soccer_epl/odds", "/sports/soccer_norway_eliteserien/odds"]
    assert odds_calls[0][1]["eventIds"] == "e1"  # only the wanted match
    assert api.requests[0][1]["commenceTimeFrom"] == "2026-10-31T05:00:00Z"
    assert source.remaining == 498 and source.spent == 2 and source.fetched_at == NOW


def test_a_second_request_within_five_minutes_reuses_the_answer(tmp_path):
    api = FakeTheOddsApi()
    now = [NOW]
    source = make_free_source(api, tmp_path, clock=lambda: now[0])
    first = source.fetch(7)
    calls = len(api.requests)
    now[0] = NOW + timedelta(minutes=4)  # a double click
    assert source.fetch(7) == first and len(api.requests) == calls and source.spent == 0  # no credits spent
    assert source.fetched_at == NOW  # and the odds keep the time they were fetched
    now[0] = NOW + timedelta(minutes=6)
    source.fetch(7)
    assert len(api.requests) > calls and source.fetched_at == now[0]


def test_the_odds_api_missing_key(tmp_path):
    with pytest.raises(SourceError, match="THE_ODDS_API_KEY") as caught:
        make_free_source(FakeTheOddsApi(), tmp_path, key=None).fetch(7)
    assert not caught.value.retryable


@pytest.mark.parametrize(
    ("status", "message", "retryable"),
    [
        (401, "kreditter er brukt opp", False),
        (404, "ligaene", False),
        (429, "for mange", True),
        (500, "500", True),
    ],
)
def test_the_odds_api_http_errors(tmp_path, status, message, retryable):
    with pytest.raises(SourceError, match=message) as caught:
        make_free_source(FakeTheOddsApi(status), tmp_path).fetch(7)
    assert caught.value.retryable is retryable


def test_competitors_come_in_the_same_request_at_no_extra_cost(tmp_path):
    api = FakeTheOddsApi()
    source = make_free_source(api, tmp_path)
    events = source.fetch(7)
    odds_calls = [q for p, q in api.requests if p.endswith("/odds")]
    assert odds_calls[0]["bookmakers"].split(",") == ["pinnacle", "unibet_se", "betsson"]
    assert api.credits == 500 - len(odds_calls)  # still one credit per league
    assert {e.source for e in events} == {"the_odds_api"}  # the reference alone is returned
    competitors = {(c.source, c.source_event_id): c.odds for c in source.competitor_odds}
    assert competitors == {
        ("the_odds_api:unibet_se", "e1"): {"home": 1.93, "draw": 3.8, "away": 3.6},
        ("the_odds_api:betsson", "e1"): {"home": 1.91, "draw": 3.75, "away": 3.7},
    }
    source.fetch(7)  # from the cache within five minutes: the competitors are there too
    assert len(source.competitor_odds) == 2


def test_more_than_ten_bookmakers_would_cost_double_and_are_refused():
    with pytest.raises(ValueError, match="høyst 9 konkurrenter"):
        TheOddsApiConfig(competitors=[f"book{i}" for i in range(10)])
    assert TheOddsApiConfig().bookmakers[0] == "pinnacle" and len(TheOddsApiConfig().bookmakers) <= 10


def test_another_choice_of_leagues_is_fetched_even_within_five_minutes(tmp_path):
    api = FakeTheOddsApi()
    source = make_free_source(api, tmp_path)
    source.fetch(7)
    calls = len(api.requests)
    source.cfg = source.cfg.model_copy(update={"leagues": ["soccer_epl"]})
    source.fetch(7)
    assert len(api.requests) > calls


ODDSLINK = load_fixture("oddslink_sample.json")
ODDSLINK_NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


class FakeOddsLink:
    def __init__(self, status=200):
        self.status = status
        self.requests = []
        self.left = 1000

    def handle(self, request: httpx.Request) -> httpx.Response:
        params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        self.requests.append((request.url.path, params, request.headers.get("x-api-key")))
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"code": "NOPE"}})
        self.left -= 1
        headers = {"x-requests-remaining": str(self.left), "x-requests-last": "1"}
        return httpx.Response(200, json=ODDSLINK, headers=headers)


def make_oddslink(api, tmp_path, key="ok_live_test", clock=lambda: ODDSLINK_NOW):
    return OddsLink(
        OddsLinkConfig(competitors=["unibet", "betfair"]),
        key,
        "test-agent",
        cache_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(api.handle)),
        clock=clock,
    )


def test_oddslink_gets_every_league_in_one_request(tmp_path):
    api = FakeOddsLink()
    source = make_oddslink(api, tmp_path)
    events = source.fetch(2)
    [(path, params, key)] = api.requests  # one request, counted once
    assert path == "/v1/sports/soccer/odds" and key == "ok_live_test"  # the key goes in X-API-Key
    assert params["markets"] == "h2h" and params["oddsFormat"] == "decimal"
    assert params["bookmakers"] == "pinnacle,unibet,betfair" and "apiKey" not in params
    assert params["commenceTimeTo"] == "2026-11-04T12:00:00Z"
    by_home = {e.home: e for e in events}
    assert set(by_home) == {"Newcastle United", "Brann"}  # Aalesund – Kongsvinger has no Pinnacle
    newcastle = by_home["Newcastle United"]
    assert newcastle.source == "oddslink" and newcastle.league == "EPL"
    assert newcastle.odds == {"home": 2.3, "draw": 3.6, "away": 3.1}
    assert by_home["Brann"].league == "Eliteserien - Norway"
    competitors = {(c.source, c.home) for c in source.competitor_odds}
    assert ("oddslink:unibet", "Aalesund") in competitors and (
        "oddslink:betfair",
        "Newcastle United",
    ) in competitors
    assert source.remaining == 999 and source.spent == 1 and source.fetched_at == ODDSLINK_NOW


def test_oddslink_reuses_an_answer_within_five_minutes_and_keeps_only_wanted_matches(tmp_path):
    api = FakeOddsLink()
    now = [ODDSLINK_NOW]
    source = make_oddslink(api, tmp_path, clock=lambda: now[0])
    source.fetch(2)
    now[0] = ODDSLINK_NOW + timedelta(minutes=4)
    events = source.fetch(2, want=lambda home, away, kickoff: home == "Brann")
    assert len(api.requests) == 1 and source.spent == 0  # the cached answer costs nothing
    assert [e.home for e in events] == ["Brann"] and {c.home for c in source.competitor_odds} == {"Brann"}
    now[0] = ODDSLINK_NOW + timedelta(minutes=6)
    source.fetch(2)
    assert len(api.requests) == 2


@pytest.mark.parametrize(
    ("status", "message"), [(401, "avviste nøkkelen"), (403, "avviste nøkkelen"), (429, "brukt opp")]
)
def test_oddslink_errors(tmp_path, status, message):
    with pytest.raises(SourceError, match=message) as raised:
        make_oddslink(FakeOddsLink(status), tmp_path).fetch(2)
    assert not raised.value.retryable


def test_oddslink_missing_key(tmp_path):
    with pytest.raises(SourceError, match="ODDSLINK_API_KEY mangler"):
        make_oddslink(FakeOddsLink(), tmp_path, key=None).fetch(2)


class Failing:
    name = "oddslink"
    remaining = 12

    def fetch(self, days_ahead, want=None):
        raise SourceError("OddsLink svarte ikke (ConnectError)")


class Backup:
    name = "the_odds_api"

    def __init__(self):
        self.calls = 0
        self.fetched_at = ODDSLINK_NOW
        self.spent = 2
        self.competitor_odds = [RawEvent(source="the_odds_api:betsson", source_event_id="b1", home="Brann",
                                         away="Molde", league="Eliteserien", kickoff_utc=ODDSLINK_NOW,
                                         odds={"home": 2.0, "draw": 3.5, "away": 3.4})]  # fmt: skip

    def fetch(self, days_ahead, want=None):
        self.calls += 1
        return [RawEvent(source="the_odds_api", source_event_id="b1", home="Brann", away="Molde",
                         league="Eliteserien", kickoff_utc=ODDSLINK_NOW,
                         odds={"home": 2.1, "draw": 3.7, "away": 3.4})]  # fmt: skip


def test_the_fallback_answers_when_oddslink_fails_and_its_odds_are_stored_as_oddslinks():
    backup = Backup()
    reference = FallbackReference(Failing(), backup)
    [event] = reference.fetch(2)
    assert reference.name == "oddslink" and reference.used == "the_odds_api" and backup.calls == 1
    assert event.source == "oddslink" and event.odds["home"] == 2.1
    assert [c.source for c in reference.competitor_odds] == ["oddslink:betsson"]
    assert reference.spent == 2 and reference.remaining == 12  # the reserve is about OddsLink's allowance


def test_the_fallback_can_be_asked_in_oddslinks_place(tmp_path):
    """The button for when OddsLink lacks a bookmaker's odds: OddsLink is not asked, and is not spent."""
    oddslink = FakeOddsLink()
    backup = Backup()
    backup.remaining = 480
    reference = FallbackReference(make_oddslink(oddslink, tmp_path), backup, fallback_only=True)
    [event] = reference.fetch(2)
    assert oddslink.requests == [] and backup.calls == 1 and reference.used == "the_odds_api"
    assert event.source == "oddslink" and reference.remaining == 480  # The Odds API's credits, now spent


def test_the_fallbacks_unibet_is_stored_as_oddslinks_so_a_match_has_one_unibet():
    backup = Backup()
    unibet = backup.competitor_odds[0].model_copy(update={"source": "the_odds_api:unibet_se"})
    sport888 = backup.competitor_odds[0].model_copy(update={"source": "the_odds_api:sport888"})
    backup.competitor_odds += [unibet, sport888]
    reference = FallbackReference(Failing(), backup)
    reference.fetch(2)
    assert [c.source for c in reference.competitor_odds] == [
        "oddslink:betsson",
        "oddslink:unibet",
        "oddslink:888sport",
    ]


def test_the_fallback_is_not_asked_when_oddslink_answers(tmp_path):
    backup = Backup()
    reference = FallbackReference(make_oddslink(FakeOddsLink(), tmp_path), backup)
    events = reference.fetch(2)
    assert backup.calls == 0 and reference.used == "oddslink" and len(events) == 2
    assert reference.remaining == 999 and reference.spent == 1
