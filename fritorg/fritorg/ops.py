"""Operations: backups and a pre-launch check of the configuration."""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import identity
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


def doctor(settings: Settings, *, test_mail_to: str | None = None) -> list[Check]:
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
    if settings.bankid_mode == "oidc":
        try:
            provider = identity.OidcProvider(settings)
            issuer = provider.metadata.get("issuer")
            checks.append(Check(issuer == settings.bankid_issuer, f"BankID-leverandøren svarer ({issuer})"))
        except Exception as exc:  # noqa: BLE001 - report every kind of failure
            checks.append(Check(False, f"BankID-leverandøren svarer ikke: {exc}"))
    else:
        checks.append(
            Check(
                False,
                f"FRITORG_BANKID er «{settings.bankid_mode}». Bruk «oidc» med en BankID-leverandør i produksjon",
            )
        )
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
    return checks
