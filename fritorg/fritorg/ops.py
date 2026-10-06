"""Operations: backups and a pre-launch check of the configuration."""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import identity, navjobs, phone
from .config import Settings
from .db import Database
from .mailer import Mail, Mailer
from .util import utcnow


def backup(settings: Settings, destination: Path) -> Path:
    """Consistent copy of the database (safe while the app runs), new uploads and the secret key."""
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"fritorg-{utcnow():%Y%m%d-%H%M%S}.sqlite3"
    source = sqlite3.connect(settings.db_path)
    copy = sqlite3.connect(target)
    try:
        source.backup(copy)
    finally:
        copy.close()
        source.close()
    uploads = destination / "uploads"
    uploads.mkdir(exist_ok=True)
    if settings.uploads_dir.exists():
        for file in settings.uploads_dir.iterdir():
            if file.is_file() and not file.name.startswith(".") and not (uploads / file.name).exists():
                shutil.copy2(file, uploads / file.name)
    key = Path(settings.data_dir) / "secret_key"
    if key.exists():
        shutil.copy2(key, destination / "secret_key")
        (destination / "secret_key").chmod(0o600)
    return target


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
        Check(None if not settings.contact_email else True, "Kontaktadresse (FRITORG_CONTACT_EMAIL)")
    )
    checks.append(
        Check(None if not settings.operator else True, "Driftsansvarlig (FRITORG_OPERATOR) for vilkårene")
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
