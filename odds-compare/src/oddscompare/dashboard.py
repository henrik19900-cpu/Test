"""What the dashboard shows, computed from the database: one card per match, history, status.

Kept apart from app.py (which only draws) so it can be tested without Streamlit.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from . import calc, db
from .matching import Aliases
from .sources import OUTCOMES
from .sources.nt import NorskTipping

OSLO = ZoneInfo("Europe/Oslo")
NT = NorskTipping.name
LABELS = dict(zip(OUTCOMES, ("H", "U", "B"), strict=True))
WINDOWS = ("I dag", "48 t", "7 dager")


@dataclass
class Card:
    event_id: int
    league: str
    home: str
    away: str
    kickoff_utc: datetime
    nt_odds: list[float]
    nt_fetched: datetime
    ref_odds: list[float] | None = None
    ref_fetched: datetime | None = None
    fair_odds: list[float] | None = None
    ev: list[float] | None = None

    @property
    def best_ev(self) -> float | None:
        return max(self.ev) if self.ev else None

    @property
    def nt_margin(self) -> float:
        return calc.margin(self.nt_odds)

    @property
    def ref_margin(self) -> float | None:
        return calc.margin(self.ref_odds) if self.ref_odds else None

    def stale(self, now: datetime, after: timedelta, reference_after: timedelta | None = None) -> list[str]:
        """The sources whose odds are older than allowed (the reference may refresh less often)."""
        limits = {NT: (self.nt_fetched, after), "referanse": (self.ref_fetched, reference_after or after)}
        return [name for name, (moment, limit) in limits.items() if moment and now - moment > limit]


def load_cards(
    conn: sqlite3.Connection, reference: str, method: str, now: datetime, until: datetime
) -> list[Card]:
    """Every match kicking off between now and until that Norsk Tipping has odds for."""
    rows = conn.execute(
        """SELECT e.id, e.league, e.home, e.away, e.kickoff_utc, l.source, l.outcome, l.odds, l.fetched_at_utc
           FROM events e JOIN latest_odds l ON l.event_id = e.id
           WHERE e.kickoff_utc > ? AND e.kickoff_utc <= ? AND l.source IN (?, ?) AND l.market = '1X2'""",
        (db.iso(now), db.iso(until), NT, reference),
    ).fetchall()
    events: dict[int, dict] = {}
    for r in rows:
        event = events.setdefault(r["id"], {"row": r, NT: {}, reference: {}, "fetched": {}})
        event[r["source"]][r["outcome"]] = r["odds"]
        event["fetched"][r["source"]] = db.parse_iso(r["fetched_at_utc"])
    cards = []
    for event_id, event in events.items():
        r = event["row"]
        if set(event[NT]) != set(OUTCOMES):
            continue
        card = Card(
            event_id=event_id,
            league=r["league"],
            home=r["home"].strip(),
            away=r["away"].strip(),
            kickoff_utc=db.parse_iso(r["kickoff_utc"]),
            nt_odds=[event[NT][o] for o in OUTCOMES],
            nt_fetched=event["fetched"][NT],
        )
        if set(event[reference]) == set(OUTCOMES):
            card.ref_odds = [event[reference][o] for o in OUTCOMES]
            card.ref_fetched = event["fetched"][reference]
            probabilities = calc.fair_probabilities(card.ref_odds, method)
            card.fair_odds = [1 / p for p in probabilities]
            card.ev = calc.expected_value(card.nt_odds, probabilities)
        cards.append(card)
    return sort_cards(cards)


def sort_cards(cards: list[Card]) -> list[Card]:
    """Best EV first; matches without reference odds last, by kick-off."""
    return sorted(cards, key=lambda c: (c.best_ev is None, -(c.best_ev or 0), c.kickoff_utc))


def window_end(choice: str, now: datetime) -> datetime:
    if choice == "I dag":
        local = now.astimezone(OSLO)
        return datetime.combine(local.date() + timedelta(days=1), time(0), OSLO)
    if choice == "48 t":
        return now + timedelta(hours=48)
    return now + timedelta(days=7)


def filter_cards(cards: list[Card], leagues: list[str], min_ev: float, show_all: bool) -> list[Card]:
    picked = [c for c in cards if not leagues or c.league in leagues]
    if show_all:
        return picked
    return [c for c in picked if c.best_ev is not None and c.best_ev >= min_ev]


def summary(cards: list[Card]) -> dict[str, float | int | None]:
    compared = [c for c in cards if c.ev is not None]
    return {
        "matches": len(cards),
        "positive": sum(1 for c in compared if c.best_ev > 0),
        "nt_margin": sum(c.nt_margin for c in compared) / len(compared) if compared else None,
        "ref_margin": sum(c.ref_margin for c in compared) / len(compared) if compared else None,
    }


def ev_class(ev: float | None) -> str:
    """Green above 0, grey from -5 % to 0, red below -5 %."""
    if ev is None:
        return "none"
    if ev > 0:
        return "pos"
    return "neutral" if ev >= -0.05 else "neg"


def history(conn: sqlite3.Connection, event_id: int, reference: str, method: str) -> pd.DataFrame:
    """Norsk Tipping's odds and the fair odds per outcome over time, in Oslo time."""
    rows = conn.execute(
        """SELECT source, outcome, odds, fetched_at_utc FROM odds_snapshots
           WHERE event_id = ? AND source IN (?, ?) AND market = '1X2' ORDER BY fetched_at_utc""",
        (event_id, NT, reference),
    ).fetchall()
    snapshots: dict[tuple[str, str], dict[str, float]] = {}
    for r in rows:
        snapshots.setdefault((r["source"], r["fetched_at_utc"]), {})[r["outcome"]] = r["odds"]
    records = []
    for (source, fetched), odds in snapshots.items():
        if set(odds) != set(OUTCOMES):
            continue
        prices = [odds[o] for o in OUTCOMES]
        if source == reference:
            prices, kind = [1 / p for p in calc.fair_probabilities(prices, method)], "Fair"
        else:
            kind = "Norsk Tipping"
        moment = db.parse_iso(fetched).astimezone(OSLO)
        records += [
            {"tid": moment, "utfall": LABELS[o], "serie": kind, "odds": round(p, 3)}
            for o, p in zip(OUTCOMES, prices, strict=True)
        ]
    return pd.DataFrame(records, columns=["tid", "utfall", "serie", "odds"])


def fetch_status(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The newest fetch_log row per source."""
    return conn.execute(
        """SELECT f.source, f.started_at_utc, f.status, f.n_events, f.error FROM fetch_log f
           JOIN (SELECT source, MAX(id) AS id FROM fetch_log GROUP BY source) newest ON newest.id = f.id
           ORDER BY f.source"""
    ).fetchall()


def last_success(conn: sqlite3.Connection, source: str) -> datetime | None:
    row = conn.execute(
        "SELECT MAX(started_at_utc) FROM fetch_log WHERE source = ? AND status = 'ok'", (source,)
    ).fetchone()
    return db.parse_iso(row[0]) if row and row[0] else None


def unmatched(conn: sqlite3.Connection, now: datetime) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT raw_home, raw_away, kickoff_utc, league, best_candidate, score FROM unmatched
           WHERE source = ? AND kickoff_utc > ? ORDER BY score IS NULL, score DESC, kickoff_utc""",
        (NT, db.iso(now)),
    ).fetchall()


def alias_suggestions(rows: list[sqlite3.Row], aliases: Aliases, minimum: float = 80) -> dict[str, list[str]]:
    """For near misses: the reference's spelling of each team that is not already recognised, by Norsk Tipping's name."""
    suggestions: dict[str, list[str]] = {}
    for r in rows:
        candidate = r["best_candidate"]
        if not candidate or r["score"] is None or r["score"] < minimum or candidate.endswith(")"):
            continue  # nothing close, or the same teams with home and away swapped (no alias fixes that)
        other_home, _, other_away = candidate.partition(" - ")
        for ours, theirs in ((r["raw_home"].strip(), other_home), (r["raw_away"].strip(), other_away)):
            if theirs and aliases.canonical(ours) != aliases.canonical(theirs):
                variants = suggestions.setdefault(ours, [])
                if theirs not in variants:
                    variants.append(theirs)
    return suggestions
