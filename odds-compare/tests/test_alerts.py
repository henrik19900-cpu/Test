import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import raw_event

from oddscompare import alerts, config, db

NOW = datetime(2026, 11, 4, 18, 30, tzinfo=UTC)
SOON = NOW + timedelta(minutes=60)  # within lead_minutes (75)
LATER = NOW + timedelta(hours=5)


class FakeNT:
    name = "norsk_tipping"

    def __init__(self, home_odds=2.30):
        self.home_odds = home_odds
        self.fetched_at = None

    def fetch(self, days_ahead):
        return [
            raw_event(source_event_id="soon", home="Wrexham", away="Middlesbrough", kickoff_utc=SOON,
                      odds={"home": self.home_odds, "draw": 3.40, "away": 3.30}),
            raw_event(source_event_id="later", home="Brann", away="Molde", kickoff_utc=LATER,
                      odds={"home": 2.30, "draw": 3.40, "away": 3.30}),
        ]  # fmt: skip


class FakeReference:
    """Pinnacle: margin 2.5 %, fair home odds 2.15, so Norsk Tipping's 2.30 is about +7 % EV."""

    name = "the_odds_api"

    def __init__(self):
        self.calls = []
        self.remaining = 400
        self.fetched_at = None
        self.competitor_odds = []

    def fetch(self, days_ahead, want=None):
        events = [
            raw_event(source="the_odds_api", source_event_id="r-soon", home="Wrexham AFC", away="Middlesbrough FC",
                      kickoff_utc=SOON, odds={"home": 2.10, "draw": 3.50, "away": 3.80}),
            raw_event(source="the_odds_api", source_event_id="r-later", home="SK Brann", away="Molde FK",
                      kickoff_utc=LATER, odds={"home": 2.10, "draw": 3.50, "away": 3.80}),
        ]  # fmt: skip
        bought = [e for e in events if want is None or want(e.home, e.away, e.kickoff_utc)]
        self.calls.append([e.home for e in bought])
        self.remaining -= 1 if bought else 0
        return bought


@pytest.fixture
def setup(tmp_path):
    (tmp_path / "config.yaml").write_text("", encoding="utf-8")
    cfg = config.load(tmp_path / "config.yaml")
    conn = db.connect(cfg.database)
    sent = []
    return cfg, conn, sent


def run(cfg, conn, sent, nt, ref, when=NOW):
    return alerts.watch(
        cfg, conn, sent.append, nt=nt, reference=ref, clock=lambda: when, sleep=lambda s: None
    )


def test_reference_odds_are_bought_only_for_matches_starting_soon_and_good_ones_are_notified(setup):
    cfg, conn, sent = setup
    ref = FakeReference()
    report = run(cfg, conn, sent, FakeNT(), ref)
    assert ref.calls == [["Wrexham AFC"]]  # not Brann – Molde, five hours away
    assert report.due == 1
    [message] = sent
    assert message["title"] == "Verdispill: Wrexham – Middlesbrough"
    assert "Hjemmeseier hos Norsk Tipping: 2,30" in message["message"] and "EV +" in message["message"]
    assert "Pinnacle-margin 2,5 %" in message["message"]
    assert "Verdispill" not in report.summary() and "Varsler sendt: 1." in report.summary()


def test_a_match_is_checked_once_and_notified_once(setup):
    cfg, conn, sent = setup
    ref = FakeReference()
    run(cfg, conn, sent, FakeNT(), ref)
    report = run(cfg, conn, sent, FakeNT(), ref, when=NOW + timedelta(minutes=15))
    assert report.due == 0 and len(ref.calls) == 1  # no second purchase
    assert len(sent) == 1  # and no second notification


def test_norsk_tipping_raising_its_odds_triggers_a_new_check_and_alert(setup):
    cfg, conn, sent = setup
    ref = FakeReference()
    run(cfg, conn, sent, FakeNT(home_odds=2.30), ref)
    report = run(cfg, conn, sent, FakeNT(home_odds=2.50), ref, when=NOW + timedelta(minutes=15))  # +8.7 %
    assert report.due == 1 and len(ref.calls) == 2
    assert len(sent) == 2 and "2,50" in sent[1]["message"]  # EV grew by more than a point: notified again


def test_no_alert_on_a_wide_reference_margin_or_small_ev(setup):
    cfg, conn, sent = setup
    run(cfg, conn, sent, FakeNT(home_odds=2.16), FakeReference())  # EV under 2 %
    assert sent == []
    cfg = cfg.model_copy(update={"alerts": cfg.alerts.model_copy(update={"max_reference_margin": 0.02})})
    run(cfg, conn, sent, FakeNT(home_odds=2.60), FakeReference(), when=NOW + timedelta(minutes=15))
    assert sent == []  # Pinnacle's 2.5 % margin is above the 2 % limit set here


def test_the_daily_cap_and_the_reserve_stop_purchases(setup):
    cfg, conn, sent = setup
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO credits_spent (at_utc, credits, remaining) VALUES (?, 20, 300)", (db.iso(NOW),)
        )
    ref = FakeReference()
    report = run(cfg, conn, sent, FakeNT(), ref)
    assert ref.calls == [] and "dagens tak" in report.reference_skipped
    assert "skulle hatt referanseodds" in report.summary()


def test_the_reserve(setup):
    cfg, conn, sent = setup
    cfg.cache_dir.mkdir(parents=True)
    (cfg.cache_dir / "the_odds_api.json").write_text(
        json.dumps({"fetched_at_utc": NOW.isoformat(), "remaining": 25})
    )
    ref = FakeReference()
    report = run(cfg, conn, sent, FakeNT(), ref)
    assert ref.calls == [] and "bare 25 kreditter" in report.reference_skipped


def test_a_failed_notification_does_not_stop_the_round(setup):
    cfg, conn, _ = setup

    def broken(message):
        raise httpx.ConnectError("no network")

    report = alerts.watch(
        cfg, conn, broken, nt=FakeNT(), reference=FakeReference(), clock=lambda: NOW, sleep=lambda s: None
    )
    assert report.sent == []  # and it is tried again next round
    assert conn.execute("SELECT COUNT(*) FROM alerts_sent").fetchone()[0] == 0


def test_ntfy_publishes_json_to_the_root_url():
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("authorization"), json.loads(request.content)))
        return httpx.Response(200, json={"id": "x"})

    send = alerts.ntfy(
        "my-secret-topic",
        "https://ntfy.sh",
        token="tk_1",
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    send({"title": "Verdispill: Wrexham – Middlesbrough", "message": "Hjemmeseier …", "priority": 4})
    [(url, auth, body)] = seen
    assert url == "https://ntfy.sh/" and auth == "Bearer tk_1"
    assert body["topic"] == "my-secret-topic" and body["title"].startswith("Verdispill")


def test_notify_test_needs_a_topic(tmp_path, monkeypatch, capsys):
    from oddscompare import __main__ as cli

    (tmp_path / "config.yaml").write_text("", encoding="utf-8")
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    assert cli.main(["--config", str(tmp_path / "config.yaml"), "notify-test"]) == 1
    assert "NTFY_TOPIC mangler" in capsys.readouterr().out


def test_ntfy_failures_are_explained():
    def status(code):
        request = httpx.Request("POST", "https://ntfy.sh/")
        return httpx.HTTPStatusError("x", request=request, response=httpx.Response(code, request=request))

    assert "neste kjøring" in alerts.describe_failure(status(429))
    assert "Sjekk NTFY_TOKEN og NTFY_TOPIC" in alerts.describe_failure(status(403))
    assert "svarte ikke" in alerts.describe_failure(httpx.ConnectError("down"))


def test_the_summary_says_when_the_reference_failed(setup):
    cfg, conn, sent = setup

    class Down(FakeReference):
        def fetch(self, days_ahead, want=None):
            from oddscompare.sources import SourceError

            raise SourceError("THE_ODDS_API_KEY mangler", retryable=False)

    report = run(cfg, conn, sent, FakeNT(), Down())
    assert "feilet (se over)" in report.summary() and sent == []
    assert not report.ok  # a rejected key makes the run red on GitHub
    assert run(cfg, conn, sent, FakeNT(), FakeReference()).ok


def test_secrets_pasted_with_spaces_or_a_line_break_still_work(monkeypatch):
    monkeypatch.setenv("THE_ODDS_API_KEY", " fake-key-123 \n")
    assert config.api_key("THE_ODDS_API_KEY") == "fake-key-123"
    monkeypatch.setenv("NTFY_TOPIC", "  ")
    assert config.api_key("NTFY_TOPIC") is None
