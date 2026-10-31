"""One fetch round: both sources, matching, and a new snapshot in SQLite.

Norsk Tipping is fetched first; its matches are the canonical events. The reference source is then
asked only for the matches that can pair with one of them (each request counts against its quota).
A source that fails is tried three times with exponential backoff, logged in fetch_log, and the
round goes on with the other source.

The reference costs credits, so it is fetched only when the user asks for it (include_reference);
the regular rounds (`oddscompare fetch` and `run`) read Norsk Tipping alone.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from . import config, db
from .matching import Aliases, Matcher
from .sources import RawEvent, ReferenceSource, SourceError
from .sources.nt import NorskTipping
from .sources.reference import OddsApiIo, TheOddsApi

logger = logging.getLogger(__name__)

ATTEMPTS = 3
BACKOFF_SECONDS = 2.0  # 2 s, then 4 s


@dataclass
class SourceReport:
    name: str
    status: str = "ok"
    n_events: int = 0
    error: str | None = None
    seconds: float = 0.0


@dataclass
class FetchReport:
    started_at: datetime
    sources: list[SourceReport] = field(default_factory=list)
    matched: int = 0
    unmatched: int = 0
    seconds: float = 0.0
    credits_left: int | None = None  # the reference API's credits left this month, when it says
    competitors: dict[str, int] = field(default_factory=dict)  # bookmaker -> matches with its odds

    @property
    def ok(self) -> bool:
        return any(s.status == "ok" for s in self.sources)


@dataclass
class _Anchor:
    """A Norsk Tipping match known from the database (when Norsk Tipping itself failed this round)."""

    source_event_id: str
    home: str
    away: str
    kickoff_utc: datetime


def build_sources(cfg: config.Config) -> tuple[NorskTipping, ReferenceSource]:
    nt = NorskTipping(cfg.norsk_tipping, cfg.user_agent, cache_dir=cfg.cache_dir)
    if cfg.reference.source == "odds_api_io":
        reference = OddsApiIo(
            cfg.reference.odds_api_io,
            config.api_key("ODDS_API_IO_KEY"),
            cfg.user_agent,
            cache_dir=cfg.cache_dir,
        )
    else:
        reference = TheOddsApi(
            cfg.reference.the_odds_api,
            config.api_key("THE_ODDS_API_KEY"),
            cfg.user_agent,
            cache_dir=cfg.cache_dir,
        )
    return nt, reference


def run_once(
    cfg: config.Config,
    conn: sqlite3.Connection | None = None,
    nt: NorskTipping | None = None,
    reference: ReferenceSource | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    include_reference: bool = False,
) -> FetchReport:
    """Fetch Norsk Tipping, and the reference too when include_reference (it costs credits)."""
    t0 = time.monotonic()
    own_conn = conn is None
    conn = conn or db.connect(cfg.database)
    if nt is None or reference is None:
        built_nt, built_reference = build_sources(cfg)
        nt, reference = nt or built_nt, reference or built_reference
    started = clock()
    report = FetchReport(started_at=started)
    matcher = Matcher(
        Aliases.load(cfg.aliases),
        window=timedelta(minutes=cfg.match_window_minutes),
        accept=cfg.fuzzy_accept,
        suggest=cfg.fuzzy_suggest,
    )
    try:
        nt_events = _attempt(conn, nt.name, lambda: nt.fetch(cfg.days_ahead), report, sleep, clock)
        if nt_events is not None:
            with db.transaction(conn):  # a cached answer keeps the time it was fetched
                anchors = _store_anchors(conn, nt_events, getattr(nt, "fetched_at", None) or started)
        else:
            anchors = _stored_anchors(conn, started)

        if not include_reference:
            return report
        ref_events = _attempt(
            conn,
            reference.name,
            lambda: reference.fetch(cfg.days_ahead, want=matcher.worth_fetching([a for a, _ in anchors])),
            report,
            sleep,
            clock,
        )
        report.credits_left = getattr(reference, "remaining", None)
        if ref_events is not None:
            with db.transaction(conn):  # cached reference odds keep the time they were fetched, too
                fetched_at = getattr(reference, "fetched_at", None) or started
                _store_reference(
                    conn,
                    ref_events,
                    anchors,
                    matcher,
                    fetched_at,
                    report,
                    getattr(reference, "competitor_odds", None) or [],
                    reference.name,
                )
                _store_competitors(conn, reference, fetched_at, report)
    finally:
        report.seconds = time.monotonic() - t0
        if own_conn:
            conn.close()
    return report


def _attempt(conn, name: str, call: Callable[[], list[RawEvent]], report: FetchReport, sleep, clock):
    """Run a source's fetch with retries; log the outcome. None when it failed."""
    entry = SourceReport(name)
    report.sources.append(entry)
    started, t0 = clock(), time.monotonic()
    for attempt in range(1, ATTEMPTS + 1):
        try:
            events = call()
        except SourceError as e:
            entry.error = str(e)
            retry = e.retryable
        except Exception as e:  # a bug in one source must not stop the other
            logger.exception("%s failed", name)
            entry.error = f"{type(e).__name__}: {e}"
            retry = True
        else:
            entry.n_events, entry.error = len(events), None
            entry.seconds = time.monotonic() - t0
            db.log_fetch(conn, name, started, "ok", len(events))
            return events
        if not retry or attempt == ATTEMPTS:
            break
        logger.warning("%s failed (attempt %d of %d): %s", name, attempt, ATTEMPTS, entry.error)
        sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
    entry.status, entry.seconds = "error", time.monotonic() - t0
    db.log_fetch(conn, name, started, "error", 0, entry.error)
    return None


def _store_anchors(conn: sqlite3.Connection, events: list[RawEvent], fetched_at: datetime) -> list[tuple]:
    """Norsk Tipping's matches as canonical events, with this round's odds. Returns (anchor, event id) pairs."""
    anchors = []
    for raw in events:
        event_id = db.linked_event(conn, raw.source, raw.source_event_id)
        if event_id is None:
            event_id = db.create_event(conn, raw)
        else:
            db.update_event(conn, event_id, raw)
        db.link(conn, raw, event_id)
        db.add_snapshot(conn, event_id, raw, fetched_at)
        anchors.append((raw, event_id))
    return anchors


def _stored_anchors(conn: sqlite3.Connection, now: datetime) -> list[tuple]:
    return [
        (
            _Anchor(r["source_event_id"], r["raw_home"], r["raw_away"], db.parse_iso(r["kickoff_utc"])),
            r["event_id"],
        )
        for r in db.source_events_since(conn, NorskTipping.name, now)
    ]


def _store_reference(
    conn,
    events: list[RawEvent],
    anchors: list[tuple],
    matcher: Matcher,
    fetched_at,
    report,
    competitor_odds: list[RawEvent] = (),
    source: str = "",
) -> None:
    """Pair the reference's matches with Norsk Tipping's and store their odds.

    Matches only the competitors have priced so far (the reference often prices midweek matches
    late) are paired too, so their odds show; they get the reference's odds once it has them."""
    priced = {raw.source_event_id for raw in events}
    only_competitors = {
        raw.source_event_id: raw.model_copy(update={"source": source})
        for raw in competitor_odds
        if raw.source_event_id not in priced
    }
    taken = set()
    fresh = []
    for raw in [*events, *only_competitors.values()]:  # matches paired in an earlier round keep their pairing
        event_id = db.linked_event(conn, raw.source, raw.source_event_id)
        if event_id is not None:
            if raw.source_event_id in priced:
                db.add_snapshot(conn, event_id, raw, fetched_at)
            taken.add(event_id)
        else:
            fresh.append(raw)
    event_of = {id(anchor): event_id for anchor, event_id in anchors}
    result = matcher.match([a for a, event_id in anchors if event_id not in taken], fresh)
    for anchor, raw, _ in result.pairs:
        db.link(conn, raw, event_of[id(anchor)])
        if raw.source_event_id in priced:
            db.add_snapshot(conn, event_of[id(anchor)], raw, fetched_at)
    missing = {id(u.event) for u in result.unmatched}
    db.clear_unmatched(
        conn, NorskTipping.name, [(a.home, a.away, a.kickoff_utc) for a, _ in anchors if id(a) not in missing]
    )
    for miss in result.unmatched:
        if isinstance(miss.event, RawEvent):
            best = f"{miss.best.home} - {miss.best.away}" if miss.best else None
            if miss.swapped:
                best = f"{best} (hjemme og borte byttet)"
            db.record_unmatched(conn, miss.event, best, miss.score, fetched_at)
    report.matched = len(taken) + len(result.pairs)
    report.unmatched = len(result.unmatched)


def _store_competitors(conn, reference, fetched_at: datetime, report: FetchReport) -> None:
    """The competitors' odds go on the events their reference match was paired with."""
    for raw in getattr(reference, "competitor_odds", None) or []:
        event_id = db.linked_event(conn, reference.name, raw.source_event_id)
        if event_id is not None:
            db.add_snapshot(conn, event_id, raw, fetched_at)
            bookmaker = raw.source.partition(":")[2]
            report.competitors[bookmaker] = report.competitors.get(bookmaker, 0) + 1


def run_forever(
    cfg: config.Config, interval_minutes: float, sleep: Callable[[float], None] = time.sleep
) -> None:
    if interval_minutes < 5:
        raise ValueError("henting oftere enn hvert 5. minutt er utenfor omfang")
    nt, reference = build_sources(cfg)
    while True:
        started = time.monotonic()
        try:
            logger.info(summary(run_once(cfg, nt=nt, reference=reference)))
        except Exception:  # e.g. the database locked for too long: try again next round
            logger.exception("the fetch round failed")
        sleep(max(0.0, interval_minutes * 60 - (time.monotonic() - started)))


def summary(report: FetchReport) -> str:
    lines = []
    for s in report.sources:
        if s.status == "ok":
            lines.append(f"{s.name}: {s.n_events} kamper ({s.seconds:.1f} s)")
        else:
            lines.append(f"{s.name}: FEIL – {s.error}")
    if len(report.sources) > 1:
        lines.append(f"Matchet: {report.matched}, uten match: {report.unmatched}.")
    if report.competitors:
        counts = ", ".join(f"{name} {n}" for name, n in sorted(report.competitors.items()))
        lines.append(f"Konkurrenter (kamper med odds): {counts}.")
    if report.credits_left is not None:
        lines.append(f"Kreditter igjen denne måneden: {report.credits_left}.")
    lines.append(f"Ferdig på {report.seconds:.1f} s.")
    return "\n".join(lines)
