"""Operations: backups, restoring one, and a pre-launch check of the configuration."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import identity, imports, navjobs, phone
from .config import Settings
from .db import MIGRATIONS, Database
from .mailer import Mail, Mailer
from .maintenance import DELETION_LOG_DAYS, SAFETY_COPIES
from .util import utcnow


def backup(settings: Settings, destination: Path, *, keep: int = 7, with_key: bool = False) -> Path:
    """Consistent copy of the database (safe while the app runs) and the images, readable only by the owner.

    The images are mirrored, so a photo deleted on the site is gone from the backup too, and only the
    `keep` newest database copies are kept. The secret key is left out unless `with_key`: with it, phone
    numbers could be recovered from their hashes, so it is kept somewhere else (FRITORG_SECRET_KEY in .env,
    and a password manager).
    """
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o700)
    target = destination / f"fritorg-{utcnow():%Y%m%d-%H%M%S}.sqlite3"
    source = sqlite3.connect(settings.db_path)
    copy = sqlite3.connect(target)
    try:
        source.backup(copy)
        copy.execute("PRAGMA journal_mode = DELETE")  # one self-contained file, also on a read-only disk
    finally:
        copy.close()
        source.close()
    target.chmod(0o600)
    for old in sorted(destination.glob("fritorg-*.sqlite3"))[:-keep]:
        old.unlink()
    uploads = destination / "uploads"
    uploads.mkdir(mode=0o700, exist_ok=True)
    wanted = set()
    if settings.uploads_dir.exists():
        for file in settings.uploads_dir.rglob("*"):  # one folder per two first letters of the name
            if not file.is_file() or file.name.startswith("."):
                continue
            relative = file.relative_to(settings.uploads_dir)
            wanted.add(relative)
            target_file = uploads / relative
            if not target_file.exists():
                target_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                shutil.copy2(file, target_file)
    for file in uploads.rglob("*"):
        if file.is_file() and file.relative_to(uploads) not in wanted:
            file.unlink()  # deleted on the site, so deleted here too
    key = Path(settings.data_dir) / "secret_key"
    if with_key and key.exists():
        shutil.copy2(key, destination / "secret_key")
        (destination / "secret_key").chmod(0o600)
    elif not with_key:
        (destination / "secret_key").unlink(missing_ok=True)
    return target


class RestoreProblem(Exception):
    """The file cannot be restored. The message says why, for the operator."""


@dataclass
class Restored:
    safety_copy: Path | None  # the database as it was, to undo the restore with (None: there was none)
    photos: int  # photo files copied back
    deleted_again: int  # accounts deleted after the backup was made, and so deleted again


def _open_read_only(path: Path) -> sqlite3.Connection:
    # immutable: nothing writes to a backup, so SQLite needs neither locks nor files next to it (it may sit
    # on a read-only disk or mount).
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def _copy_database(source: Path, target: Path) -> None:
    """SQLite's own backup: a consistent copy, also into a database the app has open."""
    reader = _open_read_only(source)
    writer = sqlite3.connect(target, timeout=30)
    try:
        reader.backup(writer)
    finally:
        writer.close()
        reader.close()


def _backup_time(source: Path) -> datetime:
    """When `backup` made the copy (its name says so), or else when the file was last changed."""
    found = re.fullmatch(r"fritorg-(\d{8}-\d{6})\.sqlite3", source.name)
    if found:
        return datetime.strptime(found[1], "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
    return datetime.fromtimestamp(source.stat().st_mtime, UTC)


def _check_backup(source: Path) -> None:
    try:
        if not source.is_file():
            raise RestoreProblem(f"Fant ikke {source}.")
        source.open("rb").close()
    except PermissionError:
        raise RestoreProblem(
            f"Har ikke lov til å lese {source} som bruker {os.getuid()}. I Docker kjører appen som bruker "
            "10001: gi den mappen med sikkerhetskopien først (sudo chown -R 10001 MAPPEN)."
        ) from None
    try:
        copy = _open_read_only(source)
        try:
            healthy = copy.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            version = copy.execute("PRAGMA user_version").fetchone()[0]
            tables = {row[0] for row in copy.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            copy.close()
    except sqlite3.DatabaseError as exc:
        raise RestoreProblem(f"{source} er ikke en database fra Fritorg ({exc}).") from None
    if not {"users", "listings"} <= tables:
        raise RestoreProblem(f"{source} er ikke en database fra Fritorg.")
    if not healthy:
        raise RestoreProblem(f"{source} er skadet. Prøv en annen sikkerhetskopi.")
    if version > len(MIGRATIONS):
        raise RestoreProblem(
            f"{source} er laget av en nyere versjon av Fritorg. Oppdater koden før du gjenoppretter den."
        )
    if _backup_time(source) < utcnow() - timedelta(days=DELETION_LOG_DAYS):
        raise RestoreProblem(
            f"{source} er eldre enn {DELETION_LOG_DAYS} dager. Kontoer som er slettet før det, ville kommet "
            "tilbake, så den kan ikke brukes. Bruk en nyere sikkerhetskopi."
        )


def _set_aside(settings: Settings, safety_copy: Path) -> list[tuple]:
    """Save the database as it is now, and read which accounts were deleted. A damaged database is moved
    aside as it is (then the list is lost, and the accounts deleted since the backup must be deleted by hand)."""
    path = settings.db_path
    if not path.exists():
        return []
    safety_copy.parent.mkdir(parents=True, exist_ok=True)
    safety_copy.parent.chmod(0o700)
    try:
        _copy_database(path, safety_copy)
        safety_copy.chmod(0o600)
        with closing(_open_read_only(safety_copy)) as conn:
            return conn.execute("SELECT user_id, created_at, deleted_at FROM deleted_accounts").fetchall()
    except sqlite3.DatabaseError:
        safety_copy.unlink(missing_ok=True)
        for suffix in ("", "-wal", "-shm"):
            part = path.with_name(path.name + suffix)
            if part.exists():
                moved = part.rename(safety_copy.with_name(safety_copy.name + suffix))
                os.utime(moved)  # kept BACKUP_DAYS from now, like a copy
        return []


def restore(settings: Settings, source: Path) -> Restored:
    """Put a database copy made by `backup` back in place, with the photos saved next to it.

    The database as it is now is saved first, so the restore can be undone the same way. Accounts deleted
    after the copy was made are deleted again: a restore never brings back someone who had their account
    deleted (GDPR art. 17). Everyone is logged out. Photos are only added; the maintenance job deletes the ones
    no listing uses. Stop the app first, and start it again afterwards.
    """
    from . import images, users

    _check_backup(source)
    safety_copy = Path(settings.data_dir) / SAFETY_COPIES / f"fritorg-{utcnow():%Y%m%d-%H%M%S}.sqlite3"
    deleted = _set_aside(settings, safety_copy)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    _copy_database(source, settings.db_path)
    db = Database(settings.db_path)
    db.init()  # a copy from an older version gets the newer tables

    photos = 0
    saved = source.parent / "uploads"
    for file in saved.rglob("*.webp") if saved.is_dir() else ():
        target = settings.uploads_dir / file.relative_to(saved)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)
            photos += 1

    with db.session() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO deleted_accounts (user_id, created_at, deleted_at) VALUES (?, ?, ?)",
            deleted,
        )
        again = [
            user_id
            for user_id, created_at, _ in deleted
            if conn.execute(
                "SELECT 1 FROM users WHERE id = ? AND created_at = ?", (user_id, created_at)
            ).fetchone()
        ]
        for user_id in again:
            images.remove_files(settings.uploads_dir, users.delete_user(conn, user_id))
        conn.execute("DELETE FROM sessions")  # also those that were logged out after the backup
    return Restored(safety_copy if safety_copy.exists() else None, photos, len(again))


@dataclass
class Check:
    ok: bool | None  # None = warning
    text: str

    def __str__(self) -> str:
        mark = {True: "OK  ", False: "FEIL", None: "OBS "}[self.ok]
        return f"[{mark}] {self.text}"


def doctor(
    settings: Settings, *, test_mail_to: str | None = None, test_sms_to: str | None = None
) -> list[Check]:
    """Everything that should be in place before the site opens to the public."""
    checks: list[Check] = []
    base = settings.base_url or ""
    checks.append(
        Check(
            base.startswith("https://"),
            f"FRITORG_BASE_URL er {base or '(ikke satt)'} – må være en https-adresse",
        )
    )
    if settings.secret_key:
        checks.append(Check(True, "FRITORG_SECRET_KEY er satt"))
    else:
        checks.append(
            Check(
                None, "FRITORG_SECRET_KEY mangler: nøkkelen i datamappen brukes, så ta vare på den i backup"
            )
        )
    checks += _verification_checks(settings, test_sms_to)
    if settings.smtp_host:
        checks.append(Check(True, f"E-post sendes via {settings.smtp_host}:{settings.smtp_port}"))
        if test_mail_to:
            try:
                Mailer(settings).send_now(
                    Mail(test_mail_to, f"Test fra {settings.site_name}", "E-post virker.")
                )
                checks.append(Check(True, f"Test-e-post sendt til {test_mail_to}"))
            except Exception as exc:  # noqa: BLE001
                checks.append(Check(False, f"Kunne ikke sende e-post: {exc}"))
    else:
        checks.append(Check(None, "E-post (FRITORG_SMTP_HOST) er ikke satt opp: brukerne får ikke varsler"))
    checks.append(
        Check(bool(settings.contact_email), "Kontaktadresse for personvern (FRITORG_CONTACT_EMAIL)")
    )
    checks.append(
        Check(
            bool(settings.operator), "Behandlingsansvarlig (FRITORG_OPERATOR) for vilkårene og personvernet"
        )
    )
    db = Database(settings.db_path)
    db.init()
    with db.session() as conn:
        moderators = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0]
        listings = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    checks.append(
        Check(moderators > 0, f"{moderators} moderator(er). Lag en med: python -m fritorg make-admin E-POST")
    )
    checks.append(Check(True, f"Databasen svarer ({listings} annonser) i {settings.db_path}"))
    checks += _import_checks(settings, db)
    return checks


def _import_checks(settings: Settings, db: Database) -> list[Check]:
    checks = _nav_checks(settings, db)
    for slug, enabled, name, variable in (
        (
            "jobtech",
            settings.jobtech_import,
            "Svenske stillinger for Norge (Platsbanken)",
            "FRITORG_JOBTECH_IMPORT",
        ),
    ):
        if not enabled:
            checks.append(Check(None, f"{name} hentes ikke inn. {variable}=1 slår det på"))
            continue
        with db.session() as conn:
            state = imports.status(conn, slug)
        if state["last_error"]:
            checks.append(Check(False, f"{name}: siste import feilet: {state['last_error']}"))
        elif state["last_run_at"]:
            checks.append(
                Check(
                    True,
                    f"{name}: {state['active_listings']} annonser, sist oppdatert {state['last_run_at']}",
                )
            )
        else:
            checks.append(Check(None, f"{name}: importen har ikke kjørt ennå (den starter med appen)"))
    return checks


def _nav_checks(settings: Settings, db: Database) -> list[Check]:
    if not settings.nav_import:
        return [
            Check(
                None,
                "Ledige stillinger fra Nav (arbeidsplassen.no) hentes ikke inn. FRITORG_NAV_IMPORT=1 slår det på",
            )
        ]
    with db.session() as conn:
        state = navjobs.status(conn)
    checks = [
        Check(
            True if settings.nav_token else None,
            "Eget token for Navs stillingsfeed (FRITORG_NAV_TOKEN)"
            if settings.nav_token
            else "Bruker Navs offentlige testtoken. Be om et eget token fra nav.team.arbeidsplassen@nav.no (se README)",
        )
    ]
    if state["last_error"]:
        checks.append(Check(False, f"Siste import fra Nav feilet: {state['last_error']}"))
    elif state["last_run_at"]:
        checks.append(
            Check(
                True, f"{state['active_listings']} stillinger fra Nav, sist oppdatert {state['last_run_at']}"
            )
        )
    else:
        checks.append(Check(None, "Importen fra Nav har ikke kjørt ennå (den starter med appen)"))
    return checks


def _verification_checks(settings: Settings, test_sms_to: str | None) -> list[Check]:
    """Every seller must be a verified person: by SMS code (default) or BankID."""
    if settings.bankid_mode == "oidc":
        try:
            provider = identity.OidcProvider(settings)
            issuer = provider.metadata.get("issuer")
            return [Check(issuer == settings.bankid_issuer, f"BankID-leverandøren svarer ({issuer})")]
        except Exception as exc:  # noqa: BLE001 - report every kind of failure
            return [Check(False, f"BankID-leverandøren svarer ikke: {exc}")]
    if settings.bankid_required:
        return [
            Check(
                False,
                f"FRITORG_BANKID er «{settings.bankid_mode}» (bare for utvikling). Bruk «oidc» med en "
                "BankID-avtale, eller «off» og bekreftelse med SMS",
            )
        ]
    if settings.verification != "sms":
        return [
            Check(
                False,
                f"FRITORG_VERIFICATION er «{settings.verification}»: hvem som helst kan legge ut annonser uten å "
                "bekrefte hvem de er. Bruk «sms»",
            )
        ]
    if settings.sms_provider == "console":
        return [
            Check(
                False,
                "SMS-koder sendes ikke, de vises på skjermen (FRITORG_SMS_PROVIDER=console). Koble til en "
                "SMS-leverandør med «twilio» eller «http» (se deploy/.env.example)",
            )
        ]
    try:
        sender = phone.create_sender(settings)
    except RuntimeError as exc:
        return [Check(False, str(exc))]
    checks = [
        Check(True, f"Brukerne bekrefter mobilnummeret med SMS via {settings.sms_provider}"),
        Check(
            None if settings.sms_daily_limit > 20_000 else True,
            f"Maks {settings.sms_daily_limit} SMS-koder per døgn (FRITORG_SMS_DAILY_LIMIT) og "
            f"{settings.sms_per_ip_per_hour} per IP-adresse per time",
        ),
    ]
    if test_sms_to and sender is not None:
        try:
            number = phone.normalize_mobile(test_sms_to)
            sender.send(number, f"Test fra {settings.site_name}: SMS virker.")
            checks.append(Check(True, f"Test-SMS sendt til {phone.phone_hint(number)}"))
        except Exception as exc:  # noqa: BLE001
            checks.append(Check(False, f"Kunne ikke sende SMS: {getattr(exc, 'message', exc)}"))
    return checks
