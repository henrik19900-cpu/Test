"""Housekeeping that runs in the background while the app runs: listings whose period is over
are hidden (and their owners told), people hear about new matches for their saved searches, and
expired sessions, codes and login states are deleted."""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass

from . import listings, saved_searches
from .config import Settings
from .db import Database
from .mailer import Mail, Mailer
from .util import iso_ago, now_iso

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 600


@dataclass
class Report:
    expired: int = 0
    purged: int = 0
    alerts: int = 0


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


def run(db: Database, settings: Settings, mailer: Mailer | None = None, secret: str | None = None) -> Report:
    report = Report()
    base = settings.base_url or "http://127.0.0.1:8000"
    with db.session() as conn:
        expired = listings.expire_listings(conn)
        report.expired = len(expired)
        if mailer is not None and mailer.enabled:
            for listing in expired:
                _tell_owner(mailer, conn, base, listing)
            if secret:  # signs the unsubscribe links in the alerts
                report.alerts = saved_searches.send_alerts(conn, mailer, base, secret)
        report.purged = purge(conn)
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
                    self.db, self.settings, getattr(state, "mailer", None), getattr(state, "secret_key", None)
                )
                if report.expired:
                    logger.info("Hid %s expired listings", report.expired)
                if report.alerts:
                    logger.info("Sent %s saved-search alerts", report.alerts)
            except Exception:
                logger.exception("Maintenance failed; trying again later")
