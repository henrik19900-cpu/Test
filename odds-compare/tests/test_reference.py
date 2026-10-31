from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest
from conftest import load_fixture

from oddscompare.config import OddsApiIoConfig
from oddscompare.sources import SourceError
from oddscompare.sources.reference import OddsApiIo, parse_odds

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
