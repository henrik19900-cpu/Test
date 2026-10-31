"""The user's own bets: a log with closing line value (CLV), result, and how sure the numbers are.

CLV compares the odds taken with the fair odds just before kick-off (the reference's last odds
before the match, with the margin taken out). Beating the closing line regularly is the best sign
of a real edge, and it shows long before profit does: profit swings with every result, CLV hardly.

Closing odds are only as late as the last reference fetch before kick-off, and reference odds are
fetched only when the user asks. A bet's CLV is therefore shown once reference odds have been
fetched after the bet was placed.
"""

from __future__ import annotations

import csv
import io
import math
import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from . import calc, db
from .sources import OUTCOMES

RESULTS = ("won", "lost", "void")
MIN_FOR_STATS = 10  # bets needed before an average and its uncertainty mean anything
Z_ONE_SIDED_5 = 1.6449
Z_POWER_80 = 0.8416
COLUMNS = (
    "id",
    "placed_at_utc",
    "nt_event_id",
    "league",
    "home",
    "away",
    "kickoff_utc",
    "outcome",
    "odds",
    "stake",
    "fair_at_bet",
    "fair_source_at_bet",
    "closing_fair",
    "closing_at_utc",
    "closing_source",
    "result",
    "note",
)


def add(
    conn: sqlite3.Connection,
    *,
    nt_event_id: str,
    league: str,
    home: str,
    away: str,
    kickoff_utc: datetime,
    outcome: str,
    odds: float,
    stake: float,
    fair_at_bet: float | None = None,
    fair_source_at_bet: str | None = None,
    note: str = "",
    placed_at: datetime | None = None,
) -> str:
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(OUTCOMES)}")
    bet_id = uuid.uuid4().hex[:12]
    with db.transaction(conn):
        conn.execute(
            f"INSERT INTO bets ({', '.join(COLUMNS[:12])}, note) VALUES ({', '.join('?' * 13)})",
            (
                bet_id,
                db.iso(placed_at or datetime.now(UTC)),
                nt_event_id,
                league,
                home,
                away,
                db.iso(kickoff_utc),
                outcome,
                odds,
                stake,
                fair_at_bet,
                fair_source_at_bet,
                note,
            ),
        )
    return bet_id


def nt_event_id(conn: sqlite3.Connection, event_id: int) -> str:
    row = conn.execute(
        "SELECT source_event_id FROM source_events WHERE event_id = ? AND source = 'norsk_tipping'",
        (event_id,),
    ).fetchone()
    return row[0] if row else ""


def all_bets(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT {', '.join(COLUMNS)} FROM bets ORDER BY kickoff_utc DESC, placed_at_utc DESC"
    ).fetchall()


def set_result(conn: sqlite3.Connection, bet_id: str, result: str | None) -> None:
    if result is not None and result not in RESULTS:
        raise ValueError(f"result must be one of {', '.join(RESULTS)}")
    with db.transaction(conn):
        conn.execute("UPDATE bets SET result = ? WHERE id = ?", (result, bet_id))


def update(conn: sqlite3.Connection, bet_id: str, *, odds: float, stake: float, note: str) -> None:
    if odds <= 1 or stake <= 0:
        raise ValueError("odds must be above 1 and the stake above 0")
    with db.transaction(conn):
        conn.execute(
            "UPDATE bets SET odds = ?, stake = ?, note = ? WHERE id = ?", (odds, stake, note, bet_id)
        )


def delete(conn: sqlite3.Connection, bet_ids: Iterable[str]) -> None:
    with db.transaction(conn):
        conn.executemany("DELETE FROM bets WHERE id = ?", [(i,) for i in bet_ids])


def update_closing(
    conn: sqlite3.Connection,
    reference: str,
    competitors: list[str],
    method: str = "proportional",
    reference_name: str = "Pinnacle",
    min_consensus: int = 3,
) -> int:
    """Set each bet's closing fair odds from the last odds before kick-off. Returns how many changed.

    The reference's last odds before kick-off come first; without them, the average of at least
    min_consensus competitors' last odds before kick-off (each with its margin taken out)."""
    changed = 0
    for bet in conn.execute(
        "SELECT id, nt_event_id, kickoff_utc, outcome, closing_at_utc FROM bets"
    ).fetchall():
        event_id = db.linked_event(conn, "norsk_tipping", bet["nt_event_id"]) if bet["nt_event_id"] else None
        if event_id is None:
            continue
        closing = _closing(conn, event_id, bet["kickoff_utc"], reference, competitors, method, min_consensus)
        if closing is None:
            continue
        fair, at, source = closing
        if bet["closing_at_utc"] and bet["closing_at_utc"] >= at:
            continue
        index = OUTCOMES.index(bet["outcome"])
        with db.transaction(conn):
            conn.execute(
                "UPDATE bets SET closing_fair = ?, closing_at_utc = ?, closing_source = ? WHERE id = ?",
                (fair[index], at, reference_name if source == reference else "konkurrenter", bet["id"]),
            )
        changed += 1
    return changed


def _closing(conn, event_id, kickoff, reference, competitors, method, min_consensus):
    def last_before(source: str) -> tuple[list[float], str] | None:
        row = conn.execute(
            """SELECT MAX(fetched_at_utc) FROM odds_snapshots
               WHERE event_id = ? AND source = ? AND market = '1X2' AND fetched_at_utc < ?""",
            (event_id, source, kickoff),
        ).fetchone()
        if not row or not row[0]:
            return None
        odds = dict(
            conn.execute(
                """SELECT outcome, odds FROM odds_snapshots
                   WHERE event_id = ? AND source = ? AND market = '1X2' AND fetched_at_utc = ?""",
                (event_id, source, row[0]),
            ).fetchall()
        )
        return ([odds[o] for o in OUTCOMES], row[0]) if set(odds) == set(OUTCOMES) else None

    ref = last_before(reference)
    if ref:
        return [1 / p for p in calc.fair_probabilities(ref[0], method)], ref[1], reference
    books = [b for b in (last_before(s) for s in competitors) if b]
    if len(books) < min_consensus:
        return None
    fair = [calc.fair_probabilities(odds, method) for odds, _ in books]
    average = [sum(p[i] for p in fair) / len(fair) for i in range(len(OUTCOMES))]
    total = sum(average)
    return [total / p for p in average], max(at for _, at in books), "competitors"


# Numbers per bet


def profit(bet) -> float | None:
    """Kroner won or lost; None while the result is not set."""
    if bet["result"] == "won":
        return bet["stake"] * (bet["odds"] - 1)
    if bet["result"] == "lost":
        return -bet["stake"]
    if bet["result"] == "void":
        return 0.0
    return None


def clv(bet) -> float | None:
    """The odds taken against the closing fair odds (0.03 is 3 % better), once they came after the bet."""
    if not bet["closing_fair"] or not bet["closing_at_utc"] or bet["closing_at_utc"] <= bet["placed_at_utc"]:
        return None
    return bet["odds"] / bet["closing_fair"] - 1


def ev_at_bet(bet) -> float | None:
    return bet["odds"] / bet["fair_at_bet"] - 1 if bet["fair_at_bet"] else None


@dataclass
class Estimate:
    """An average over the bets, with how sure it is."""

    n: int
    mean: float | None = None
    low: float | None = None  # 95 % interval
    high: float | None = None
    p: float | None = None  # one-sided: the chance of an average this good without any edge
    bets_needed: int | None = None  # in all, to show an edge this size (5 % level, 80 % power)

    @property
    def enough(self) -> bool:
        return self.n >= MIN_FOR_STATS


def estimate(values: list[float]) -> Estimate:
    n = len(values)
    if n == 0:
        return Estimate(0)
    mean = sum(values) / n
    if n < MIN_FOR_STATS:
        return Estimate(n, mean)
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    if sd == 0:
        return Estimate(n, mean, mean, mean, 0.0 if mean > 0 else 1.0)
    se = sd / math.sqrt(n)
    p = 0.5 * math.erfc((mean / se) / math.sqrt(2))
    needed = math.ceil((Z_ONE_SIDED_5 + Z_POWER_80) ** 2 * sd**2 / mean**2) if mean > 0 else None
    return Estimate(n, mean, mean - 1.96 * se, mean + 1.96 * se, p, needed)


@dataclass
class Summary:
    bets: int
    open: int
    staked: float  # on settled bets
    profit: float
    roi: float | None
    expected_profit: float  # what the EV at the time of the bets says, on settled bets
    clv: Estimate
    returns: Estimate  # profit per krone staked, per bet


def summarize(rows: list) -> Summary:
    settled = [b for b in rows if b["result"] in ("won", "lost")]
    staked = sum(b["stake"] for b in settled)
    total = sum(profit(b) for b in rows if profit(b) is not None)
    expected = sum(b["stake"] * ev_at_bet(b) for b in settled if ev_at_bet(b) is not None)
    return Summary(
        bets=len(rows),
        open=sum(1 for b in rows if b["result"] is None),
        staked=staked,
        profit=total,
        roi=total / staked if staked else None,
        expected_profit=expected,
        clv=estimate([c for c in (clv(b) for b in rows) if c is not None]),
        returns=estimate([profit(b) / b["stake"] for b in settled]),
    )


# CSV, to keep the log when the database starts over (Streamlit Cloud) and to move it between places


def to_csv(rows: list) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow(["" if row[c] is None else row[c] for c in COLUMNS])
    return out.getvalue()


def from_csv(conn: sqlite3.Connection, text: str) -> int:
    """Add or update the bets in a CSV made by to_csv. Returns how many rows were read."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    missing = set(COLUMNS) - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"CSV-filen mangler kolonnene {', '.join(sorted(missing))}")
    count = 0
    with db.transaction(conn):
        for row in reader:
            values = {c: (row[c] if row[c] != "" else None) for c in COLUMNS}
            for number in ("odds", "stake", "fair_at_bet", "closing_fair"):
                values[number] = float(values[number]) if values[number] is not None else None
            values["note"] = values["note"] or ""
            values["nt_event_id"] = values["nt_event_id"] or ""
            conn.execute(
                f"INSERT OR REPLACE INTO bets ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                [values[c] for c in COLUMNS],
            )
            count += 1
    return count
