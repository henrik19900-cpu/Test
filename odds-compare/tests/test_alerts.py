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


def run(cfg, conn, sent, nt, ref, when=NOW, test=False):
    return alerts.watch(
        cfg, conn, sent.append, nt=nt, reference=ref, clock=lambda: when, sleep=lambda s: None, test=test
    )


def test_reference_odds_are_bought_only_for_matches_starting_soon_and_good_ones_are_notified(setup):
    cfg, conn, sent = setup
    ref = FakeReference()
    report = run(cfg, conn, sent, FakeNT(), ref)
    assert ref.calls == [["Wrexham AFC"]]  # not Brann – Molde, five hours away
    assert report.due == 1
    assert (report.fetch.matched, report.fetch.unmatched) == (1, 0)  # Brann – Molde was not asked for
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


def test_credits_spent_come_from_what_the_api_said_each_call_cost(setup):
    cfg, conn, sent = setup

    class Counting(FakeReference):
        def fetch(self, days_ahead, want=None):
            bought = super().fetch(days_ahead, want)
            self.spent = 7 if bought else 0
            return bought

    report = run(cfg, conn, sent, FakeNT(), Counting())  # no credits left on record yet: the first run
    assert report.credits_spent == 7 and "7 kreditter" in report.summary()
    assert (
        conn.execute("SELECT SUM(credits) FROM credits_spent").fetchone()[0] == 7
    )  # counts for the daily cap


def test_a_test_alert_sends_the_best_outcome_whatever_the_threshold(setup):
    cfg, conn, sent = setup
    cfg = cfg.model_copy(
        update={"alerts": cfg.alerts.model_copy(update={"min_ev": 0.5})}
    )  # nothing qualifies
    report = run(cfg, conn, sent, FakeNT(), FakeReference(), test=True)
    [message] = sent  # exactly one, and only the test
    assert message["title"] == "TEST – Verdispill: Wrexham – Middlesbrough"
    assert "Hjemmeseier hos Norsk Tipping: 2,30" in message["message"]
    assert "uansett terskel" in message["message"] and "minst 50,0 %" in message["message"]
    assert report.ok and "Testvarsel sendt: TEST – Verdispill" in report.summary()
    assert conn.execute("SELECT COUNT(*) FROM alerts_sent").fetchone()[0] == 0  # the real alert still comes


def test_a_test_alert_without_reference_odds_is_the_plain_test_message(setup):
    cfg, conn, sent = setup

    class Empty(FakeReference):
        def fetch(self, days_ahead, want=None):
            return []

    run(cfg, conn, sent, FakeNT(), Empty(), test=True)
    assert [m["title"] for m in sent] == [alerts.test_message(cfg)["title"]]


def test_a_test_alert_that_fails_makes_the_run_red(setup):
    cfg, conn, _ = setup

    def refuse(message):
        request = httpx.Request("POST", "https://ntfy.sh/")
        raise httpx.HTTPStatusError("x", request=request, response=httpx.Response(429, request=request))

    report = alerts.watch(
        cfg,
        conn,
        refuse,
        nt=FakeNT(),
        reference=FakeReference(),
        clock=lambda: NOW,
        sleep=lambda s: None,
        test=True,
    )
    assert not report.ok and "Testvarselet feilet: ntfy.sh avviste" in report.summary()


def test_alerts_link_to_the_odds_page(setup):
    cfg, conn, sent = setup
    url = "https://claude.ai/artifact/example"
    cfg = cfg.model_copy(update={"alerts": cfg.alerts.model_copy(update={"app_url": url})})
    run(cfg, conn, sent, FakeNT(), FakeReference(), test=True)
    assert len(sent) == 2  # the real alert and the test alert
    for message in [*sent, alerts.test_message(cfg)]:
        assert message["click"] == url
        assert message["actions"] == [{"action": "view", "label": "Åpne odds-siden", "url": url}]
    cfg = cfg.model_copy(update={"alerts": cfg.alerts.model_copy(update={"app_url": ""})})
    assert "click" not in alerts.test_message(cfg) and "actions" not in alerts.test_message(cfg)


def test_secrets_pasted_with_spaces_or_a_line_break_still_work(monkeypatch):
    monkeypatch.setenv("THE_ODDS_API_KEY", " fake-key-123 \n")
    assert config.api_key("THE_ODDS_API_KEY") == "fake-key-123"
    monkeypatch.setenv("NTFY_TOPIC", "  ")
    assert config.api_key("NTFY_TOPIC") is None


def test_an_early_check_hours_before_and_the_late_check_again_near_kick_off(setup):
    cfg, conn, sent = setup
    ref = FakeReference()
    report = run(cfg, conn, sent, FakeNT(), ref, when=LATER - timedelta(hours=2))  # Brann – Molde in 2 hours
    assert ref.calls == [["SK Brann"]] and (report.due, report.due_early) == (0, 1)
    assert "Referanseodds for 1 kamper med tidlig sjekk:" in report.summary()
    run(cfg, conn, sent, FakeNT(), ref, when=LATER - timedelta(minutes=105))
    assert len(ref.calls) == 1  # checked early already: nothing bought
    report = run(cfg, conn, sent, FakeNT(), ref, when=LATER - timedelta(minutes=70))
    assert ref.calls[-1] == ["SK Brann"] and report.due == 1  # and again within 75 minutes


def test_early_checks_stop_at_half_the_days_credits_but_the_late_ones_go_on(setup):
    cfg, conn, sent = setup
    with db.transaction(conn):  # 10 of the day's 20 credits spent
        conn.execute(
            "INSERT INTO credits_spent (at_utc, credits, remaining) VALUES (?, 10, 300)", (db.iso(NOW),)
        )
    early_cfg = cfg.model_copy(update={"alerts": cfg.alerts.model_copy(update={"early_lead_minutes": 330})})
    ref = FakeReference()
    report = run(early_cfg, conn, sent, FakeNT(), ref)  # Wrexham in 1 hour, Brann – Molde in 5
    assert ref.calls == [["Wrexham AFC"]] and (report.due, report.due_early, report.early_skipped) == (
        1,
        0,
        1,
    )
    assert "Tidlig sjekk av 1 kamper venter" in report.summary()


def test_no_early_check_when_it_is_off(setup):
    cfg, conn, sent = setup
    cfg = cfg.model_copy(update={"alerts": cfg.alerts.model_copy(update={"early_lead_minutes": 0})})
    ref = FakeReference()
    report = run(cfg, conn, sent, FakeNT(), ref, when=LATER - timedelta(hours=2))
    assert (
        ref.calls == [] and report.due_early == 0 and "Ingen kamper trengte referanseodds" in report.summary()
    )


# With OddsLink one request covers every match, so every match is checked, not only those starting soon.


class FakeOddsLink(FakeReference):
    name = "oddslink"

    def fetch(self, days_ahead, want=None):
        self.spent = 1  # one request, however many matches
        return [e.model_copy(update={"source": "oddslink"}) for e in super().fetch(days_ahead, want)]


class BrokenOddsLink:
    name = "oddslink"
    remaining = 900

    def __init__(self):
        self.calls = 0

    def fetch(self, days_ahead, want=None):
        self.calls += 1
        from oddscompare.sources import SourceError

        raise SourceError("OddsLink svarte ikke (ConnectError)")


@pytest.fixture
def oddslink(tmp_path):
    (tmp_path / "config.yaml").write_text("reference:\n  source: oddslink\n", encoding="utf-8")
    cfg = config.load(tmp_path / "config.yaml")
    return cfg, db.connect(cfg.database), []


def test_with_oddslink_every_match_is_checked_and_notified_not_only_those_starting_soon(oddslink):
    cfg, conn, sent = oddslink
    ref = FakeOddsLink()
    report = run(cfg, conn, sent, FakeNT(), ref)
    assert ref.calls == [["Wrexham AFC", "SK Brann"]]  # Brann – Molde too, five hours away
    assert report.every_match and (report.fetch.matched, report.fetch.unmatched) == (2, 0)
    assert {m["title"] for m in sent} == {"Verdispill: Wrexham – Middlesbrough", "Verdispill: Brann – Molde"}
    assert (
        "Referanseodds for alle kampene de neste 2 døgnene (blant dem 1 kamper som starter snart): "
        "1 forespørsel." in report.summary()
    )


def test_with_oddslink_every_match_is_checked_once_an_hour(oddslink):
    cfg, conn, sent = oddslink
    ref = FakeOddsLink()
    start = NOW - timedelta(hours=3)  # Wrexham in 4 hours, Brann – Molde in 8
    report = run(cfg, conn, sent, FakeNT(), ref, when=start)
    assert ref.calls == [["Wrexham AFC", "SK Brann"]] and report.due == 0 and len(sent) == 2
    assert "Referanseodds for alle kampene de neste 2 døgnene: 1 forespørsel." in report.summary()
    report = run(cfg, conn, sent, FakeNT(), ref, when=start + timedelta(minutes=30))
    assert (
        len(ref.calls) == 1
        and "Neste sjekk av alle kampene de neste 2 døgnene om 30 min." in report.summary()
    )
    run(cfg, conn, sent, FakeNT(), ref, when=start + timedelta(minutes=60))
    assert len(ref.calls) == 2 and len(sent) == 2  # checked again, but nothing new to notify


def test_with_oddslink_a_match_starting_soon_waits_for_the_hourly_check(oddslink):
    cfg, conn, sent = oddslink
    ref = FakeOddsLink()
    run(cfg, conn, sent, FakeNT(), ref, when=NOW - timedelta(minutes=30))  # Wrexham in 90 minutes
    report = run(cfg, conn, sent, FakeNT(home_odds=2.50), ref)  # in 60, and Norsk Tipping raised its odds
    assert len(ref.calls) == 1 and report.due == 1  # due, but once an hour is the limit
    assert "om 30 min" in report.summary()


def test_with_oddslink_the_daily_cap_stops_the_hourly_check(oddslink):
    cfg, conn, sent = oddslink
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO credits_spent (at_utc, credits, remaining) VALUES (?, 20, 900)", (db.iso(NOW),)
        )
    ref = FakeOddsLink()
    report = run(cfg, conn, sent, FakeNT(), ref)
    assert ref.calls == [] and "dagens tak" in report.reference_skipped
    assert "Alle kampene de neste 2 døgnene skulle hatt referanseodds, men: dagens tak" in report.summary()


def test_when_oddslink_fails_its_fallback_is_asked_only_for_the_matches_starting_soon(oddslink):
    from oddscompare.sources.reference import FallbackReference

    cfg, conn, sent = oddslink
    broken, backup = BrokenOddsLink(), FakeReference()
    report = run(cfg, conn, sent, FakeNT(), FallbackReference(broken, backup))
    assert broken.calls >= 1 and backup.calls == [["Wrexham AFC"]]  # a credit per league: only what is due
    assert (
        report.ok
        and not report.every_match
        and [m["title"] for m in sent] == ["Verdispill: Wrexham – Middlesbrough"]
    )
    assert "OddsLink feilet" in report.summary() and "fra the_odds_api i stedet" in report.summary()


def test_the_regular_check_of_every_match_does_not_spend_the_fallbacks_credits(oddslink):
    from oddscompare.sources.reference import FallbackReference

    cfg, conn, sent = oddslink
    backup = FakeReference()
    report = run(
        cfg, conn, sent, FakeNT(), FallbackReference(BrokenOddsLink(), backup), when=NOW - timedelta(hours=3)
    )
    assert backup.calls == [] and not report.ok  # red on GitHub: OddsLink failed
    assert "Referanseodds for alle kampene de neste 2 døgnene feilet" in report.summary()
