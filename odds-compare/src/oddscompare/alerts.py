"""oddscompare watch: one round of watching for good bets, and a phone notification when one shows.

Norsk Tipping's odds are free and fetched every round. Reference odds cost credits, so they are
bought only when they matter, for the matches starting within lead_minutes (75): Pinnacle's price is
most accurate close to kick-off, and that is when a bet is worth placing. A match gets one such check,
plus another if Norsk Tipping raises an outcome by nt_jump (5 %) or more since. Each league with such
a match costs one credit (the competitors come with it for free), within max_credits_per_day and
never touching the month's last reserve_credits.

An outcome is worth a notification when its EV against Pinnacle's fair odds is at least min_ev,
Pinnacle's own margin is at most max_reference_margin (a wide margin makes the fair odds unsure), the
reference odds are fresh and Norsk Tipping has not moved since. Each outcome is notified once, and
again only if its EV has grown by a percentage point. Notifications go to ntfy (https://ntfy.sh), a
free app: the topic is a secret name only you know, set as NTFY_TOPIC.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

from . import config, dashboard, db, fetch
from .sources import OUTCOMES
from .sources.nt import NorskTipping

logger = logging.getLogger(__name__)

Notifier = Callable[[dict], None]


@dataclass
class Opportunity:
    card: dashboard.Card
    outcome: int

    @property
    def ev(self) -> float:
        return self.card.ev[self.outcome]

    @property
    def odds(self) -> float:
        return self.card.nt_odds[self.outcome]


@dataclass
class WatchReport:
    fetch: fetch.FetchReport | None = None
    due: int = 0  # matches whose reference odds were due
    reference_skipped: str | None = None  # why reference odds were not bought, when they were due
    credits_spent: int = 0
    sent: list[Opportunity] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Every source answered (a changed site or a rejected key makes the run red on GitHub)."""
        return self.fetch is None or all(s.status == "ok" for s in self.fetch.sources)

    def summary(self) -> str:
        lines = [fetch.summary(self.fetch)] if self.fetch else []
        reference_failed = self.fetch and any(s.status != "ok" for s in self.fetch.sources[1:])
        if self.due and self.reference_skipped:
            lines.append(f"{self.due} kamper skulle hatt referanseodds, men: {self.reference_skipped}")
        elif self.due and reference_failed:
            lines.append(f"Referanseodds for {self.due} kamper som starter snart feilet (se over).")
        elif self.due:
            lines.append(
                f"Referanseodds for {self.due} kamper som starter snart: {self.credits_spent} kreditter."
            )
        else:
            lines.append("Ingen kamper trengte referanseodds nå.")
        lines.append(f"Varsler sendt: {len(self.sent)}.")
        lines += [f"  {opportunity_title(o)}: {opportunity_line(o)}" for o in self.sent]
        return "\n".join(lines)


def watch(
    cfg: config.Config,
    conn: sqlite3.Connection,
    notify: Notifier,
    nt=None,
    reference=None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep=None,
) -> WatchReport:
    a = cfg.alerts
    cfg = cfg.model_copy(update={"days_ahead": a.days_ahead})  # alerts look only a little ahead
    now = clock()
    report = WatchReport()
    if nt is None or reference is None:
        built_nt, built_reference = fetch.build_sources(cfg)
        nt, reference = nt or built_nt, reference or built_reference
    extra = {"sleep": sleep} if sleep else {}

    # Norsk Tipping first (free), so the due list sees its latest odds.
    report.fetch = fetch.run_once(cfg, conn, nt, reference, clock=clock, **extra)
    due = due_matches(conn, reference.name, now, a)
    report.due = len(due)
    if due:
        report.reference_skipped = _budget_problem(conn, cfg, now)
        if report.reference_skipped is None:
            before = dashboard.credits_left(cfg.cache_dir, reference.name)
            ref_report = fetch.run_once(
                cfg,
                conn,
                nt,
                reference,
                clock=clock,
                include_reference=True,
                reference_for=lambda anchor: anchor.source_event_id in due,
                **extra,
            )
            report.fetch.sources += ref_report.sources[1:]
            report.fetch.matched, report.fetch.unmatched = ref_report.matched, ref_report.unmatched
            report.fetch.credits_left = ref_report.credits_left
            report.fetch.competitors = ref_report.competitors
            after = getattr(reference, "remaining", None)
            if before is not None and after is not None and before >= after:
                report.credits_spent = before - after
            with db.transaction(conn):
                conn.execute(
                    "INSERT INTO credits_spent (at_utc, credits, remaining) VALUES (?, ?, ?)",
                    (db.iso(now), report.credits_spent, after),
                )

    for opportunity in opportunities(conn, cfg, now):
        if _already_sent(conn, opportunity):
            continue
        try:
            notify(notification(opportunity, cfg))
        except Exception as e:  # noqa: BLE001  (a failed notification is tried again next round)
            logger.warning("the notification failed: %s", describe_failure(e))
            continue
        report.sent.append(opportunity)
        _mark_sent(conn, opportunity, now)
    db.prune(conn, a.keep_days, now=now)
    return report


def due_matches(conn: sqlite3.Connection, reference: str, now: datetime, a: config.AlertsConfig) -> set[str]:
    """Norsk Tipping's matches (by its id) that need reference odds now: starting within lead_minutes and
    not checked since then, or Norsk Tipping has raised an outcome by nt_jump since the last check."""
    rows = conn.execute(
        """SELECT se.source_event_id, e.id, e.kickoff_utc FROM source_events se JOIN events e ON e.id = se.event_id
           WHERE se.source = ? AND e.kickoff_utc > ? AND e.kickoff_utc <= ?""",
        (NorskTipping.name, db.iso(now), db.iso(now + timedelta(minutes=a.lead_minutes))),
    ).fetchall()
    due = set()
    for nt_id, event_id, kickoff in rows:
        last = conn.execute(
            "SELECT MAX(fetched_at_utc) FROM odds_snapshots WHERE event_id = ? AND source = ?",
            (event_id, reference),
        ).fetchone()[0]
        window_start = db.parse_iso(kickoff) - timedelta(minutes=a.lead_minutes)
        if last is None or db.parse_iso(last) < window_start:
            due.add(nt_id)
            continue
        then = dashboard._nt_odds_at(conn, event_id, db.parse_iso(last))
        current = dashboard._nt_odds_at(conn, event_id, now)
        if then and current and any(c / t - 1 >= a.nt_jump for c, t in zip(current, then, strict=True)):
            due.add(nt_id)
    return due


def _budget_problem(conn: sqlite3.Connection, cfg: config.Config, now: datetime) -> str | None:
    a = cfg.alerts
    day_start = datetime.combine(now.astimezone(dashboard.OSLO).date(), datetime.min.time(), dashboard.OSLO)
    spent = conn.execute(
        "SELECT COALESCE(SUM(credits), 0) FROM credits_spent WHERE at_utc >= ?", (db.iso(day_start),)
    ).fetchone()[0]
    if spent >= a.max_credits_per_day:
        return f"dagens tak på {a.max_credits_per_day} kreditter er nådd"
    left = dashboard.credits_left(cfg.cache_dir, cfg.reference.source)
    if left is not None and left <= a.reserve_credits:
        return f"bare {left} kreditter igjen denne måneden (reserven er {a.reserve_credits})"
    return None


def opportunities(conn: sqlite3.Connection, cfg: config.Config, now: datetime) -> list[Opportunity]:
    """Outcomes worth a notification now, best EV first."""
    a = cfg.alerts
    reference = cfg.reference.source
    cards = dashboard.load_cards(
        conn,
        reference,
        cfg.margin_method,
        now,
        now + timedelta(days=cfg.days_ahead),
        fetch.competitor_sources(cfg),
    )
    found = []
    for card in cards:
        if (
            not card.ref_odds
            or card.ev is None
            or card.nt_moved
            or card.ref_margin > a.max_reference_margin
            or now - card.ref_fetched > timedelta(minutes=a.fresh_minutes)
        ):
            continue
        found += [Opportunity(card, i) for i in range(len(OUTCOMES)) if card.ev[i] >= a.min_ev]
    return sorted(found, key=lambda o: -o.ev)


def _already_sent(conn: sqlite3.Connection, o: Opportunity) -> bool:
    row = conn.execute(
        "SELECT ev FROM alerts_sent WHERE nt_event_id = ? AND outcome = ?",
        (_nt_id(conn, o), OUTCOMES[o.outcome]),
    ).fetchone()
    return row is not None and o.ev < row[0] + 0.01


def _mark_sent(conn: sqlite3.Connection, o: Opportunity, now: datetime) -> None:
    with db.transaction(conn):
        conn.execute(
            """INSERT INTO alerts_sent (nt_event_id, outcome, sent_at_utc, odds, ev) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (nt_event_id, outcome) DO UPDATE SET
                 sent_at_utc = excluded.sent_at_utc, odds = excluded.odds, ev = excluded.ev""",
            (_nt_id(conn, o), OUTCOMES[o.outcome], db.iso(now), o.odds, o.ev),
        )


def _nt_id(conn: sqlite3.Connection, o: Opportunity) -> str:
    row = conn.execute(
        "SELECT source_event_id FROM source_events WHERE event_id = ? AND source = ?",
        (o.card.event_id, NorskTipping.name),
    ).fetchone()
    return row[0] if row else str(o.card.event_id)


# The notification


def _pct(value: float, signed: bool = False) -> str:
    text = f"{value * 100:+.1f} %" if signed else f"{value * 100:.1f} %"
    return text.replace(".", ",").replace("-", "−")


def _odds(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def opportunity_title(o: Opportunity) -> str:
    return f"{o.card.home} – {o.card.away}: {('H', 'U', 'B')[o.outcome]} {_odds(o.odds)} ({_pct(o.ev, signed=True)})"


def opportunity_line(o: Opportunity) -> str:
    return f"fair {_odds(o.card.fair_odds[o.outcome])}, {o.card.league}"


def notification(o: Opportunity, cfg: config.Config) -> dict:
    card, i = o.card, o.outcome
    outcome = ("hjemmeseier", "uavgjort", "borteseier")[i]
    place = card.position(i)
    kickoff = card.kickoff_utc.astimezone(dashboard.OSLO).strftime("%d.%m kl. %H:%M")
    lines = [
        f"{outcome.capitalize()} hos Norsk Tipping: {_odds(o.odds)}",
        f"Fair odds (Pinnacle): {_odds(card.fair_odds[i])} · EV {_pct(o.ev, signed=True)}",
        f"Avspark {kickoff} · {card.league}",
        f"Pinnacle-margin {_pct(card.ref_margin)}"
        + (f" · NT {'best' if place[0] == 1 else f'nr. {place[0]}'} av {place[1]}" if place else ""),
    ]
    message = {
        "title": f"Verdispill: {card.home} – {card.away}",
        "message": "\n".join(lines),
        "tags": ["soccer", "chart_with_upwards_trend"],
        "priority": 4,
    }
    if cfg.alerts.app_url:
        message["click"] = cfg.alerts.app_url
    return message


def ntfy(
    topic: str, server: str = "https://ntfy.sh", token: str | None = None, client: httpx.Client | None = None
) -> Notifier:
    """A notifier that publishes to an ntfy topic as JSON (https://docs.ntfy.sh/publish/#publish-as-json)."""
    client = client or httpx.Client(timeout=20)
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    def send(message: dict) -> None:
        response = client.post(server.rstrip("/") + "/", json={"topic": topic, **message}, headers=headers)
        response.raise_for_status()

    return send


def describe_failure(error: Exception) -> str:
    """Why ntfy did not take a notification, in words a person can act on."""
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status == 429:
            # ntfy.sh counts the free plan per IP address, with an account too («basis: ip» in /v1/account).
            return (
                "ntfy.sh avviste varselet: denne IP-adressen har nådd grensen på gratisplanen (429), som deles "
                "med alle på samme adresse. Overvåkeren prøver igjen ved neste kjøring, fra en ny adresse."
            )
        if status in (401, 403):
            return f"ntfy.sh avviste tilgangsnøkkelen eller emnet ({status}). Sjekk NTFY_TOKEN og NTFY_TOPIC."
        return f"ntfy.sh svarte {status}."
    return f"ntfy.sh svarte ikke ({type(error).__name__})."


def test_message(cfg: config.Config) -> dict:
    message = {
        "title": "Odds-sammenligner: varsler virker",
        "message": "Dette er en test. Du får et varsel som dette når det dukker opp et verdispill.",
        "tags": ["white_check_mark"],
        "priority": 3,
    }
    if cfg.alerts.app_url:
        message["click"] = cfg.alerts.app_url
    return message
