"""Housekeeping that runs in the background while the app runs: listings whose period is over
are hidden (and their owners told), old listings that nobody has touched for a long time are deleted
(after a notice), people hear about new matches for their saved searches, expired sessions, codes and
login states are deleted, and once a day the statistics SQLite uses to pick indexes are refreshed (the
right index matters more as the number of listings grows)."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from . import alerts, images, listings, messages, saved_searches
from .config import Settings
from .db import Database, analyze
from .mailer import Mail, Mailer
from .util import format_date_no, format_days_no, iso_ago, now_iso
from .views import ViewCounter

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 600
STATISTICS_SECONDS = 86_400
T = TypeVar("T")
_analyzed: dict[str, float] = {}  # database file -> when its statistics were last refreshed


@dataclass
class Report:
    expired: int = 0
    marked: int = 0  # old listings whose owners were told they will be deleted
    deleted: int = 0
    purged: int = 0
    alerts: int = 0
    price_drops: int = 0


def purge(conn: sqlite3.Connection) -> int:
    """Delete what is no longer needed. SMS codes are kept two days, for the rate limits."""
    now = now_iso()
    statements = [
        ("DELETE FROM sessions WHERE expires_at < ?", (now,)),
        ("DELETE FROM login_states WHERE created_at < ?", (iso_ago(hours=1),)),
        ("DELETE FROM pending_identities WHERE created_at < ?", (iso_ago(hours=1),)),
        ("DELETE FROM device_grants WHERE expires_at < ?", (iso_ago(days=1),)),
        ("DELETE FROM phone_codes WHERE created_at < ?", (iso_ago(days=2),)),
    ]
    return sum(conn.execute(sql, args).rowcount for sql, args in statements)


def _tell_owner(mailer: Mailer, conn: sqlite3.Connection, base: str, listing: listings.Listing) -> None:
    row = conn.execute(
        "SELECT email, name FROM users WHERE id = ? AND email_verified_at IS NOT NULL AND banned_at IS NULL",
        (listing.user_id,),
    ).fetchone()
    if row is None:
        return
    site = mailer.settings.site_name
    mailer.send_later(
        Mail(
            row["email"],
            f"Annonsen din er utløpt: «{listing.title}»",
            f"Hei {row['name']}!\n\nAnnonsen din «{listing.title}» har ligget ute i "
            f"{mailer.settings.listing_days} dager og er nå skjult. Er den fortsatt aktuell, kan du gjøre den "
            f"aktiv igjen med ett klikk:\n\n{base}/annonse/{listing.id}\n\nEr den solgt, kan du merke den som "
            f"solgt på samme side. Takk for at du bruker {site}!\n",
        )
    )


def _warn_owner(
    mailer: Mailer, conn: sqlite3.Connection, base: str, user_id: int, marked: list[listings.Listing]
) -> None:
    """One e-mail per owner about their listings that will be deleted (they share the date)."""
    row = conn.execute(
        "SELECT email, name FROM users WHERE id = ? AND email_verified_at IS NOT NULL AND banned_at IS NULL",
        (user_id,),
    ).fetchone()
    if row is None:
        return
    settings = mailer.settings
    when = format_date_no(marked[0].deletes_at)
    links = "\n".join(f"- {listing.title}: {base}/annonse/{listing.id}" for listing in marked)
    if len(marked) == 1:
        subject = f"Annonsen din slettes {when}: «{marked[0].title}»"
        these = "Denne annonsen har ikke vært aktiv eller endret på lenge. Den slettes"
    else:
        subject = f"{len(marked)} av annonsene dine slettes {when}"
        these = "Disse annonsene har ikke vært aktive eller endret på lenge. De slettes"
    mailer.send_later(
        Mail(
            row["email"],
            subject,
            f"Hei {row['name']}!\n\n{these} automatisk {when}, sammen med bildene:\n\n{links}\n\n"
            "Vil du beholde en annonse, kan du gjøre den aktiv igjen eller endre den før det. Vil du ta vare "
            f"på teksten eller bildene, kan du laste ned dataene dine på Min side:\n\n{base}/min-side\n\n"
            f"Annonser som ikke har vært aktive eller endret på {format_days_no(settings.delete_after_days)}, "
            f"slettes automatisk. Takk for at du bruker {settings.site_name}!\n",
        )
    )


def _delete_old_listings(
    conn: sqlite3.Connection,
    settings: Settings,
    mailer: Mailer | None,
    base: str,
    report: Report,
    step: Callable,
) -> None:
    if not settings.delete_after_days:
        step("cancel deletions", lambda: listings.cancel_deletions(conn))
        return
    marked = (
        step("deletion notices", lambda: listings.mark_for_deletion(conn, settings.delete_after_days)) or []
    )
    report.marked = len(marked)
    if marked and mailer is not None and mailer.enabled:
        owners: dict[int, list[listings.Listing]] = defaultdict(list)
        for listing in marked:
            owners[listing.user_id].append(listing)
        for user_id, owned in owners.items():
            step(
                "deletion e-mail",
                lambda user_id=user_id, owned=owned: _warn_owner(mailer, conn, base, user_id, owned),
            )
    deleted = step("deletion", lambda: listings.delete_marked_listings(conn))
    if deleted:
        report.deleted, filenames = deleted
        step("deleted photos", lambda: images.remove_files(settings.uploads_dir, filenames))


def run(
    db: Database,
    settings: Settings,
    mailer: Mailer | None = None,
    secret: str | None = None,
    views: ViewCounter | None = None,
) -> Report:
    report = Report()
    base = settings.base_url or "http://127.0.0.1:8000"

    def step(name: str, action: Callable[[], T]) -> T | None:
        """Each step on its own: one that fails is logged, and the others still run."""
        try:
            return action()
        except Exception:
            logger.exception("Maintenance step %r failed", name)
            return None

    with db.session() as conn:
        if views is not None:
            step("views", lambda: views.flush(conn))
        expired = step("expiry", lambda: listings.expire_listings(conn)) or []
        report.expired = len(expired)
        if mailer is not None and mailer.enabled:
            for listing in expired:
                step("expiry e-mail", lambda listing=listing: _tell_owner(mailer, conn, base, listing))
            if secret:  # signs the unsubscribe links in the alerts
                report.alerts = (
                    step("search alerts", lambda: saved_searches.send_alerts(conn, mailer, base, secret)) or 0
                )
                report.price_drops = (
                    step("price alerts", lambda: alerts.send_price_drops(conn, mailer, base, secret)) or 0
                )
        _delete_old_listings(conn, settings, mailer, base, report, step)
        report.purged = step("purge", lambda: purge(conn)) or 0
        report.purged += step("deleted conversations", lambda: messages.purge_deleted(conn)) or 0
        key = str(db.path)
        if time.monotonic() - _analyzed.get(key, -STATISTICS_SECONDS) >= STATISTICS_SECONDS:
            step("statistics", lambda: analyze(conn))
            _analyzed[key] = time.monotonic()
    return report


class Worker:
    def __init__(self, db: Database, settings: Settings, state: object):
        self.db = db
        self.settings = settings
        self.state = state  # app.state: the mailer may be replaced while running (tests)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maintenance", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        delay = 60  # the first run shortly after start, then every INTERVAL_SECONDS
        while not self._stop.wait(delay):
            delay = INTERVAL_SECONDS
            try:
                state = self.state
                report = run(
                    self.db,
                    self.settings,
                    getattr(state, "mailer", None),
                    getattr(state, "secret_key", None),
                    getattr(state, "views", None),
                )
                if report.expired:
                    logger.info("Hid %s expired listings", report.expired)
                if report.marked or report.deleted:
                    logger.info(
                        "Told owners about %s old listings; deleted %s", report.marked, report.deleted
                    )
                if report.alerts or report.price_drops:
                    logger.info("Sent %s saved-search and %s price alerts", report.alerts, report.price_drops)
            except Exception:
                logger.exception("Maintenance failed; trying again later")
