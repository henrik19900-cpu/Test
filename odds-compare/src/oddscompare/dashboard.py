"""What the dashboard shows, computed from the database: one card per match, history, status.

Kept apart from app.py (which only draws) so it can be tested without Streamlit.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import calc, db
from .matching import Aliases
from .sources import OUTCOMES
from .sources.nt import NorskTipping

OSLO = ZoneInfo("Europe/Oslo")
NT = NorskTipping.name
LABELS = dict(zip(OUTCOMES, ("H", "U", "B"), strict=True))
BOOKMAKERS = {
    "pinnacle": "Pinnacle",
    "betfair_ex_eu": "Betfair Exchange",
    "betfair_ex_uk": "Betfair Exchange",
    "unibet_se": "Unibet",
    "betsson": "Betsson",
    "nordicbet": "NordicBet",
    "coolbet": "Coolbet",
    "leovegas_se": "LeoVegas",
    "sport888": "888sport",
    "betway": "Betway",
    "williamhill": "William Hill",
    "marathonbet": "Marathonbet",
    "onexbet": "1xBet",
}


# The Odds API's leagues by the names people know them by.
LEAGUE_NAMES = {
    "soccer_norway_eliteserien": "Eliteserien",
    "soccer_epl": "Premier League",
    "soccer_efl_champ": "Championship",
    "soccer_england_league1": "League One",
    "soccer_england_league2": "League Two",
    "soccer_uefa_champs_league": "Champions League",
    "soccer_uefa_europa_league": "Europa League",
    "soccer_uefa_europa_conference_league": "Conference League",
    "soccer_spain_la_liga": "LaLiga",
    "soccer_spain_segunda_division": "LaLiga 2",
    "soccer_italy_serie_a": "Serie A",
    "soccer_italy_serie_b": "Serie B",
    "soccer_germany_bundesliga": "Bundesliga",
    "soccer_germany_bundesliga2": "2. Bundesliga",
    "soccer_germany_liga3": "3. Liga",
    "soccer_france_ligue_one": "Ligue 1",
    "soccer_france_ligue_two": "Ligue 2",
    "soccer_netherlands_eredivisie": "Eredivisie",
    "soccer_sweden_allsvenskan": "Allsvenskan",
    "soccer_sweden_superettan": "Superettan",
    "soccer_denmark_superliga": "Superligaen",
}


def bookmaker_name(source: str) -> str:
    """«Betsson» for the source «the_odds_api:betsson», «Norsk Tipping» for Norsk Tipping."""
    if source == NT:
        return "Norsk Tipping"
    key = source.partition(":")[2] or source
    return BOOKMAKERS.get(key, key)


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
    competitors: dict[str, list[float]] = field(default_factory=dict)  # source -> odds, in config order
    # Where the fair odds come from: None (the reference) or "konkurrenter" (their average, when the
    # reference has not priced the match yet).
    fair_from: str | None = None
    # Norsk Tipping's odds have changed since the reference (or competitors) were last fetched, so the
    # fair odds may be out of date: the market has likely moved too.
    nt_moved: bool = False

    @property
    def nt_share_of_best(self) -> float:
        """Norsk Tipping's price as a share of the best price on the market, at its closest outcome (1 = best)."""
        return max(nt / best for nt, (best, _) in zip(self.nt_odds, self.best_prices(), strict=True))

    def position(self, i: int) -> tuple[int, int, float] | None:
        """Where Norsk Tipping's price on outcome i stands among it and its competitors.

        Returns (place, bookmakers, gap): place 1 is the best price (ties share a place), and gap is
        Norsk Tipping's price against the best one (-0.05 is 5 % lower). None without competitors."""
        if not self.competitors:
            return None
        nt = self.nt_odds[i]
        others = [odds[i] for odds in self.competitors.values()]
        return 1 + sum(o > nt for o in others), 1 + len(others), nt / max([nt, *others]) - 1

    def nt_best_outcomes(self) -> list[int]:
        """The outcomes where Norsk Tipping's price is the best (alone or shared) among its competitors."""
        return [i for i in range(len(OUTCOMES)) if (p := self.position(i)) is not None and p[0] == 1]

    def nt_worst(self, i: int) -> bool:
        """Every competitor offers at least as much on outcome i, and one offers more."""
        others = [odds[i] for odds in self.competitors.values()]
        return bool(others) and min(others) >= self.nt_odds[i] < max(others)

    def margin_place(self) -> tuple[int, int] | None:
        """How many of Norsk Tipping and its competitors have a lower margin, as (place, bookmakers)."""
        if not self.competitors:
            return None
        margins = [calc.margin(o) for o in self.competitors.values()]
        return 1 + sum(m < self.nt_margin for m in margins), 1 + len(margins)

    def best_prices(self) -> list[tuple[float, list[str]]]:
        """Per outcome: the highest price among Norsk Tipping and its competitors, and who offers it."""
        books = {NT: self.nt_odds, **self.competitors}
        best = []
        for i in range(len(OUTCOMES)):
            top = max(odds[i] for odds in books.values())
            best.append((top, [bookmaker_name(s) for s, odds in books.items() if odds[i] == top]))
        return best

    @property
    def best_ev(self) -> float | None:
        return max(self.ev) if self.ev else None

    @property
    def nt_margin(self) -> float:
        return calc.margin(self.nt_odds)

    @property
    def ref_margin(self) -> float | None:
        return calc.margin(self.ref_odds) if self.ref_odds else None

    @property
    def doubtful(self) -> bool:
        """The reference's own margin is so wide that the fair odds taken from it are unreliable."""
        return self.ref_margin is not None and self.ref_margin > DOUBTFUL_MARGIN

    def stale(self, now: datetime, after: timedelta, reference_after: timedelta | None = None) -> list[str]:
        """The sources whose odds are older than allowed. The reference is fetched only when asked
        for, so it is checked only when reference_after is given."""
        limits = {NT: (self.nt_fetched, after), "referanse": (self.ref_fetched, reference_after)}
        return [name for name, (moment, limit) in limits.items() if moment and limit and now - moment > limit]


def load_cards(
    conn: sqlite3.Connection,
    reference: str,
    method: str,
    now: datetime,
    until: datetime,
    competitors: list[str] = (),
) -> list[Card]:
    """Every match kicking off between now and until that Norsk Tipping has odds for.

    competitors: the sources of Norsk Tipping's competitors to show (e.g. «the_odds_api:betsson»)."""
    sources = [NT, reference, *competitors]
    rows = conn.execute(
        f"""SELECT e.id, e.league, e.home, e.away, e.kickoff_utc, l.source, l.outcome, l.odds, l.fetched_at_utc
           FROM events e JOIN latest_odds l ON l.event_id = e.id
           WHERE e.kickoff_utc > ? AND e.kickoff_utc <= ? AND l.market = '1X2'
             AND l.source IN ({", ".join("?" * len(sources))})""",
        (db.iso(now), db.iso(until), *sources),
    ).fetchall()
    events: dict[int, dict] = {}
    for r in rows:
        event = events.setdefault(r["id"], {"row": r, "fetched": {}, **{s: {} for s in sources}})
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
        card.competitors = {
            s: [event[s][o] for o in OUTCOMES] for s in competitors if set(event[s]) == set(OUTCOMES)
        }
        fair_fetched = card.ref_fetched or max(
            (event["fetched"][s] for s in card.competitors if s in event["fetched"]), default=None
        )
        if fair_fetched and card.nt_fetched > fair_fetched:
            card.nt_moved = _nt_odds_at(conn, event_id, fair_fetched) not in (None, card.nt_odds)
        if card.ev is None and len(card.competitors) >= MIN_CONSENSUS:
            probabilities = consensus(list(card.competitors.values()), method)
            card.fair_odds = [1 / p for p in probabilities]
            card.ev = calc.expected_value(card.nt_odds, probabilities)
            card.fair_from = "konkurrenter"
        cards.append(card)
    return sort_cards(cards)


def _nt_odds_at(conn: sqlite3.Connection, event_id: int, moment: datetime) -> list[float] | None:
    """Norsk Tipping's odds for the match as they were at moment (its last snapshot up to then)."""
    rows = conn.execute(
        """SELECT outcome, odds FROM odds_snapshots WHERE event_id = ? AND source = ? AND market = '1X2'
           AND fetched_at_utc = (SELECT MAX(fetched_at_utc) FROM odds_snapshots
                                 WHERE event_id = ? AND source = ? AND fetched_at_utc <= ?)""",
        (event_id, NT, event_id, NT, db.iso(moment + timedelta(minutes=1))),
    ).fetchall()
    odds = dict(rows)
    return [odds[o] for o in OUTCOMES] if set(odds) == set(OUTCOMES) else None


MIN_CONSENSUS = 3  # competitors needed for fair odds from their average
# Pinnacle's 1X2 margin is usually 3-6 %. Far above that, the line is early or stale, and fair odds taken
# from it are unreliable (31.10.2026: median 4.6 %, 2 of 201 matches above 8 %, one of them at 11.7 %).
DOUBTFUL_MARGIN = 0.08


def consensus(books: list[list[float]], method: str) -> list[float]:
    """The average of several bookmakers' fair probabilities, each with its own margin taken out."""
    fair = [calc.fair_probabilities(odds, method) for odds in books]
    average = [sum(p[i] for p in fair) / len(fair) for i in range(len(OUTCOMES))]
    total = sum(average)
    return [p / total for p in average]


# How the cards can be ordered, the first being the default.
SORTS = {
    # Best EV first; matches without reference odds last, by kick-off.
    "Beste EV": lambda c: (c.best_ev is None, -(c.best_ev or 0), c.kickoff_utc),
    "Avsparkstid": lambda c: (c.kickoff_utc, c.league, c.home),
    "Liga": lambda c: (c.league, c.kickoff_utc, c.home),
    "Lavest NT-margin": lambda c: (c.nt_margin, c.kickoff_utc),
    # Where Norsk Tipping's price is closest to (or is) the best on the market, for the outcome where it is closest.
    "NT nærmest beste odds": lambda c: (-c.nt_share_of_best, c.kickoff_utc),
}


def sort_cards(cards: list[Card], order: str = "Beste EV") -> list[Card]:
    return sorted(cards, key=SORTS[order])


def window_end(choice: str, now: datetime) -> datetime:
    if choice == "I dag":
        local = now.astimezone(OSLO)
        return datetime.combine(local.date() + timedelta(days=1), time(0), OSLO)
    if choice == "48 t":
        return now + timedelta(hours=48)
    return now + timedelta(days=7)


def filter_cards(
    cards: list[Card], leagues: list[str], min_ev: float, show_all: bool, nt_best_only: bool = False
) -> list[Card]:
    """The cards in the leagues picked; with nt_best_only, only matches where Norsk Tipping has the best
    price on at least one outcome (whatever the EV)."""
    picked = [c for c in cards if not leagues or c.league in leagues]
    if nt_best_only:
        return [c for c in picked if c.nt_best_outcomes()]
    if show_all:
        return picked
    return [c for c in picked if c.best_ev is not None and c.best_ev >= min_ev]


@dataclass
class NtBest:
    """An outcome where Norsk Tipping has the best price among its competitors."""

    card: Card
    outcome: int
    odds: float
    runner_up: str  # the next best bookmaker(s), or those sharing the best price
    runner_up_odds: float
    shared: bool
    lead: float  # Norsk Tipping's price over the next best (0 when shared)

    @property
    def ev(self) -> float | None:
        return self.card.ev[self.outcome] if self.card.ev else None


def nt_best(cards: list[Card]) -> list[NtBest]:
    """Every outcome where Norsk Tipping has the best price, the biggest lead first."""
    found = []
    for card in cards:
        for i in card.nt_best_outcomes():
            others = {bookmaker_name(s): odds[i] for s, odds in card.competitors.items()}
            nt = card.nt_odds[i]
            equal = [name for name, o in others.items() if o == nt]
            if equal:
                found.append(NtBest(card, i, nt, ", ".join(equal), nt, True, 0.0))
            else:
                second = max(others.values())
                names = ", ".join(name for name, o in others.items() if o == second)
                found.append(NtBest(card, i, nt, names, second, False, nt / second - 1))
    return sorted(found, key=lambda b: (-b.lead, b.card.kickoff_utc))


def summary(cards: list[Card]) -> dict[str, float | int | None]:
    """The counts, and the average margins over the matches the reference itself has priced."""
    compared = [c for c in cards if c.ev is not None]
    priced = [c for c in cards if c.ref_odds]
    return {
        "matches": len(cards),
        "positive": sum(1 for c in compared if c.best_ev > 0),
        "nt_margin": sum(c.nt_margin for c in priced) / len(priced) if priced else None,
        "ref_margin": sum(c.ref_margin for c in priced) / len(priced) if priced else None,
    }


@dataclass
class HeadToHead:
    """Norsk Tipping against one competitor, over the outcomes both price."""

    name: str
    outcomes: int
    nt_higher: int
    equal: int
    nt_lower: int
    mean_gap: float  # Norsk Tipping's odds against the competitor's (-0.03 is 3 % lower)
    margin: float  # the competitor's average margin on these matches
    nt_margin: float  # Norsk Tipping's average margin on the same matches


@dataclass
class Market:
    """How Norsk Tipping's prices compare with its competitors' and the reference's."""

    matches: int  # with competitors' odds
    outcomes: int
    best_share: float | None  # outcomes where Norsk Tipping has the best price (alone or shared)
    worst_share: float | None  # outcomes where it has the lowest price
    mean_gap: float | None  # its price against the best price, on average
    margins: list[tuple[str, float, int]]  # (bookmaker, average margin, matches), lowest margin first
    head_to_head: list[HeadToHead]


def market(cards: list[Card], reference_name: str = "Pinnacle") -> Market:
    compared = [c for c in cards if c.competitors]
    places = [(c, i) for c in compared for i in range(len(OUTCOMES))]
    margins: dict[str, list[float]] = {"Norsk Tipping": [c.nt_margin for c in compared]}
    if any(c.ref_odds for c in compared):
        margins[reference_name] = [c.ref_margin for c in compared if c.ref_odds]
    pairs: dict[str, list[tuple[list[float], list[float]]]] = {}
    for c in compared:
        for source, odds in c.competitors.items():
            name = bookmaker_name(source)
            margins.setdefault(name, []).append(calc.margin(odds))
            pairs.setdefault(name, []).append((c.nt_odds, odds))
    head_to_head = []
    for name, matches in pairs.items():
        diffs = [nt[i] / theirs[i] - 1 for nt, theirs in matches for i in range(len(OUTCOMES))]
        head_to_head.append(
            HeadToHead(
                name=name,
                outcomes=len(diffs),
                nt_higher=sum(d > 0 for d in diffs),
                equal=sum(d == 0 for d in diffs),
                nt_lower=sum(d < 0 for d in diffs),
                mean_gap=sum(diffs) / len(diffs),
                margin=sum(calc.margin(theirs) for _, theirs in matches) / len(matches),
                nt_margin=sum(calc.margin(nt) for nt, _ in matches) / len(matches),
            )
        )
    head_to_head.sort(key=lambda h: h.mean_gap)
    return Market(
        matches=len(compared),
        outcomes=len(places),
        best_share=sum(c.position(i)[0] == 1 for c, i in places) / len(places) if places else None,
        worst_share=sum(c.nt_worst(i) for c, i in places) / len(places) if places else None,
        mean_gap=sum(c.position(i)[2] for c, i in places) / len(places) if places else None,
        margins=sorted(((n, sum(v) / len(v), len(v)) for n, v in margins.items() if v), key=lambda m: m[1]),
        head_to_head=head_to_head,
    )


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


def credits_left(cache_dir: Path, source: str) -> int | None:
    """The reference API's credits left this month, as its last answer (cached on disk) said."""
    try:
        return json.loads((cache_dir / f"{source}.json").read_text(encoding="utf-8")).get("remaining")
    except (OSError, ValueError, AttributeError):
        return None


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
