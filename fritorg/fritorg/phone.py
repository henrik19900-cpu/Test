"""Verification of Norwegian mobile numbers by SMS code.

The default way to verify people, because it needs no special agreement (BankID does):
just an account with an SMS provider. Norwegian mobile subscriptions are registered to a
person, so a confirmed number makes anonymous fraud much harder, and each number can
belong to one account only. The number itself is never stored, only a keyed hash and a
short hint for display ("+47 •••••567").

Providers: "twilio", "http" (a URL template that fits most simple SMS APIs, for example
Norwegian ones) and "console" for development, which shows the code instead of sending it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .config import Settings
from .db import transaction
from .errors import AppError, Conflict, RateLimited, ValidationProblem
from .ratelimit import RateLimiter
from .util import iso_ago, iso_in, now_iso

logger = logging.getLogger(__name__)

CODE_MINUTES = 10
MAX_ATTEMPTS = 5
CODES_PER_HOUR_PER_USER = 3
CODES_PER_DAY_PER_NUMBER = 5


class SmsError(AppError):
    status = 502
    code = "sms_failed"
    title = "SMS could not be sent"


class VerificationRequired(AppError):
    status = 403
    code = "verification_required"
    title = "Verification required"


def normalize_mobile(raw: str) -> str:
    """'912 34 567', '+47 91234567' or '0047 912 34 567' -> '+4791234567' (Norwegian mobiles only)."""
    digits = re.sub(r"[\s\-().]", "", raw or "")
    if digits.startswith("+47"):
        digits = digits[3:]
    elif digits.startswith("0047"):
        digits = digits[4:]
    elif len(digits) == 10 and digits.startswith("47"):
        digits = digits[2:]
    if not re.fullmatch(r"[49]\d{7}", digits):
        raise ValidationProblem.field(
            "phone",
            "Skriv et norsk mobilnummer med 8 siffer (som begynner på 4 eller 9).",
            hint="Only Norwegian mobile numbers (+47, 8 digits starting with 4 or 9) can be verified.",
        )
    return f"+47{digits}"


def phone_hash(secret: str, e164: str) -> str:
    return hmac.new(secret.encode(), f"phone|{e164}".encode(), hashlib.sha256).hexdigest()


def phone_hint(e164: str) -> str:
    return f"+47 •••••{e164[-3:]}"


def _code_hash(secret: str, user_id: int, code: str, purpose: str = "verify") -> str:
    message = f"code|{purpose}|{user_id}|{code}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


# --- Senders ------------------------------------------------------------------------------------


class SmsSender:
    def send(self, to: str, message: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass
class ConsoleSms(SmsSender):
    """Development: logs the message instead of sending it, and remembers it for the web page."""

    outbox: list[tuple[str, str]] = field(default_factory=list)

    def send(self, to: str, message: str) -> None:
        logger.warning("SMS to %s (not sent, development mode): %s", phone_hint(to), message)
        self.outbox = [*self.outbox[-49:], (to, message)]


def _request(url: str, data: bytes | None, headers: dict[str, str]) -> None:
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - configured provider URL
            response.read()
    except urllib.error.HTTPError as exc:
        logger.warning("SMS provider answered %s: %s", exc.code, exc.read()[:300])
        raise SmsError("SMS-en kunne ikke sendes. Prøv igjen om litt.") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        logger.warning("SMS provider unreachable: %s", exc)
        raise SmsError("SMS-en kunne ikke sendes. Prøv igjen om litt.") from None


@dataclass
class TwilioSms(SmsSender):
    account_sid: str
    auth_token: str
    sender: str

    def send(self, to: str, message: str) -> None:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        body = urllib.parse.urlencode({"To": to, "From": self.sender, "Body": message}).encode()
        basic = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode()).decode()
        _request(url, body, {"Authorization": f"Basic {basic}"})


@dataclass
class HttpSms(SmsSender):
    """Any provider with a simple HTTP API. The URL template may use {to} (+4791234567),
    {to_digits} (4791234567), {to_local} (91234567) and {message}; values are URL-encoded.
    With method POST the query string is sent as a form body instead."""

    url_template: str
    method: str = "GET"

    def send(self, to: str, message: str) -> None:
        values = {
            "to": to,
            "to_digits": to.lstrip("+"),
            "to_local": to[3:],
            "message": message,
        }
        url = self.url_template.format(**{k: urllib.parse.quote(v, safe="") for k, v in values.items()})
        if self.method.upper() == "POST":
            base, _, query = url.partition("?")
            _request(base, query.encode(), {"Content-Type": "application/x-www-form-urlencoded"})
        else:
            _request(url, None, {})


def create_sender(settings: Settings) -> SmsSender | None:
    if not settings.phone_verification_required:
        return None
    provider = settings.sms_provider
    if provider == "console":
        if settings.base_url and settings.base_url.startswith("https://") and not settings.allow_console_sms:
            raise RuntimeError(
                "FRITORG_SMS_PROVIDER=console shows codes on screen and must not run in production. Configure "
                "twilio or http, or set FRITORG_ALLOW_CONSOLE_SMS=1 for a demo site."
            )
        return ConsoleSms()
    if provider == "twilio":
        if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from):
            raise RuntimeError(
                "FRITORG_SMS_PROVIDER=twilio needs FRITORG_TWILIO_ACCOUNT_SID, _AUTH_TOKEN and _FROM."
            )
        return TwilioSms(settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_from)
    if provider == "http":
        if not settings.sms_url:
            raise RuntimeError("FRITORG_SMS_PROVIDER=http needs FRITORG_SMS_URL (see deploy/.env.example).")
        return HttpSms(settings.sms_url, settings.sms_method)
    raise RuntimeError(f"Unknown FRITORG_SMS_PROVIDER {provider!r}: use console, twilio or http.")


# --- Flow ---------------------------------------------------------------------------------------


@dataclass
class CodeSent:
    phone_hint: str
    expires_in: int
    test_code: str | None = None  # only with the console provider, so development needs no phone


def verification_needed(settings: Settings, user) -> bool:
    """True while the account must confirm a mobile number before posting or messaging."""
    return settings.phone_verification_required and not user.is_verified and not user.is_admin


def ensure_verified(settings: Settings, user, base: str) -> None:
    """Writing (listings, messages) needs a verified person when verification is turned on."""
    if verification_needed(settings, user):
        raise VerificationRequired(
            "Bekreft mobilnummeret ditt før du legger ut annonser eller sender meldinger.",
            hint=f"Ask the user for their Norwegian mobile number and POST {base}/api/v1/me/phone with "
            f'{{"phone": "..."}} (or MCP tool verify_phone); then POST {base}/api/v1/me/phone/verify with the '
            f'6-digit code from the SMS: {{"code": "..."}}. On the web: {base}/verifiser-telefon',
        )


def start(
    conn: sqlite3.Connection,
    sender: SmsSender,
    secret: str,
    settings: Settings,
    user_id: int,
    raw_phone: str,
    *,
    limiter: RateLimiter | None = None,
    client_ip: str = "unknown",
    purpose: str = "verify",
) -> CodeSent | None:
    """Send a code to the number. Returns the hint to show ("+47 •••••567").

    With purpose "reset" (forgotten password) the number must be the one the account confirmed;
    otherwise nothing is sent and None is returned, without telling the caller why.
    """
    e164 = normalize_mobile(raw_phone)
    hashed = phone_hash(secret, e164)
    if purpose == "reset":
        row = conn.execute("SELECT phone_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None or not row["phone_hash"] or not hmac.compare_digest(row["phone_hash"], hashed):
            return None
    recent_user = conn.execute(
        "SELECT COUNT(*) FROM phone_codes WHERE user_id = ? AND created_at > ?", (user_id, iso_ago(hours=1))
    ).fetchone()[0]
    # Per purpose: others trying to verify an account with the number must not use up its owner's reset codes.
    recent_number = conn.execute(
        "SELECT COUNT(*) FROM phone_codes WHERE phone_hash = ? AND purpose = ? AND created_at > ?",
        (hashed, purpose, iso_ago(days=1)),
    ).fetchone()[0]
    if recent_user >= CODES_PER_HOUR_PER_USER or recent_number >= CODES_PER_DAY_PER_NUMBER:
        raise RateLimited("Du har bedt om mange koder. Vent litt før du prøver igjen.", retry_after=3600)
    today = conn.execute(
        "SELECT COUNT(*) FROM phone_codes WHERE created_at > ?", (iso_ago(days=1),)
    ).fetchone()[0]
    if today >= settings.sms_daily_limit:
        logger.error("Daily SMS limit (%s) reached; no more codes are sent today", settings.sms_daily_limit)
        raise RateLimited("Vi kan ikke sende flere SMS-er akkurat nå. Prøv igjen senere.", retry_after=3600)
    if limiter is not None:
        decision = limiter.hit("sms", client_ip, settings.sms_per_ip_per_hour, 3600)
        if not decision.allowed:
            raise RateLimited(
                "For mange SMS-koder fra denne adressen. Prøv igjen senere.", retry_after=decision.reset_in
            )
    # A number already on another account gets an explanation instead of a code, and the caller gets the
    # same answer as for any number, so nobody can test which numbers have accounts. It counts against the
    # same limits (the row below), and the code stored for it is never sent.
    taken = (
        purpose == "verify"
        and conn.execute("SELECT 1 FROM users WHERE phone_hash = ? AND id != ?", (hashed, user_id)).fetchone()
        is not None
    )
    code = f"{secrets.randbelow(10**6):06d}"
    with transaction(conn):
        conn.execute(
            "INSERT INTO phone_codes (user_id, phone_hash, phone_hint, code_hash, purpose, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                hashed,
                phone_hint(e164),
                _code_hash(secret, user_id, code, purpose),
                purpose,
                now_iso(),
                iso_in(minutes=CODE_MINUTES),
            ),
        )
    site = settings.site_name
    if taken:
        sender.send(
            e164,
            f"Noen prøvde å bekrefte en ny konto hos {site} med dette nummeret, men det er allerede knyttet til "
            "en konto. Var det deg, logger du inn med den kontoen (velg «Glemt passordet?» om du trenger det). "
            "Var det ikke deg, kan du se bort fra denne meldingen.",
        )
        return CodeSent(phone_hint(e164), CODE_MINUTES * 60)
    what = "koden for å lage nytt passord" if purpose == "reset" else "koden din"
    sender.send(
        e164,
        f"{code} er {what} hos {site}. Den gjelder i {CODE_MINUTES} minutter. Ikke del den med noen – "
        f"{site} spør aldri om den på telefon.",
    )
    return CodeSent(
        phone_hint(e164), CODE_MINUTES * 60, test_code=code if isinstance(sender, ConsoleSms) else None
    )


def pending_hint(conn: sqlite3.Connection, user_id: int, purpose: str = "verify") -> str | None:
    row = conn.execute(
        "SELECT phone_hint FROM phone_codes WHERE user_id = ? AND purpose = ? AND used_at IS NULL "
        "AND expires_at > ? ORDER BY id DESC LIMIT 1",
        (user_id, purpose, now_iso()),
    ).fetchone()
    return row["phone_hint"] if row else None


def _check_code(conn: sqlite3.Connection, secret: str, user_id: int, code: str, purpose: str) -> sqlite3.Row:
    """The latest unused code for the purpose, if `code` matches it. Every attempt counts."""
    code = re.sub(r"\D", "", code or "")
    row = conn.execute(
        "SELECT * FROM phone_codes WHERE user_id = ? AND purpose = ? AND used_at IS NULL AND expires_at > ? "
        "ORDER BY id DESC LIMIT 1",
        (user_id, purpose, now_iso()),
    ).fetchone()
    if row is None:
        raise ValidationProblem.field("code", "Koden er utløpt eller brukt. Be om en ny kode.")
    # Count the attempt before comparing, atomically, so parallel guesses cannot exceed the limit.
    counted = conn.execute(
        "UPDATE phone_codes SET attempts = attempts + 1 WHERE id = ? AND attempts < ?",
        (row["id"], MAX_ATTEMPTS),
    )
    if counted.rowcount == 0:
        raise ValidationProblem.field("code", "For mange feil forsøk. Be om en ny kode.")
    if not hmac.compare_digest(row["code_hash"], _code_hash(secret, user_id, code, purpose)):
        left = MAX_ATTEMPTS - row["attempts"] - 1
        raise ValidationProblem.field(
            "code", f"Feil kode. Du har {left} forsøk igjen." if left > 0 else "Feil kode. Be om en ny kode."
        )
    return row


def confirm_reset(conn: sqlite3.Connection, secret: str, user_id: int, code: str) -> None:
    """Check a code for resetting a forgotten password (sent to the account's confirmed number)."""
    _check_code(conn, secret, user_id, code, "reset")
    conn.execute(
        "UPDATE phone_codes SET used_at = ? WHERE user_id = ? AND purpose = 'reset' AND used_at IS NULL",
        (now_iso(), user_id),
    )


def confirm(conn: sqlite3.Connection, secret: str, user_id: int, code: str) -> None:
    row = _check_code(conn, secret, user_id, code, "verify")
    with transaction(conn):
        if conn.execute(
            "SELECT 1 FROM users WHERE phone_hash = ? AND id != ?", (row["phone_hash"], user_id)
        ).fetchone():
            raise Conflict("Nummeret er allerede knyttet til en annen konto.")
        now = now_iso()
        conn.execute(
            "UPDATE users SET phone_hash = ?, phone_hint = ?, phone_verified_at = ?, "
            "verified_at = COALESCE(verified_at, ?), verified_via = COALESCE(verified_via, 'sms') WHERE id = ?",
            (row["phone_hash"], row["phone_hint"], now, now, user_id),
        )
        conn.execute(
            "UPDATE phone_codes SET used_at = ? WHERE user_id = ? AND purpose = 'verify' AND used_at IS NULL",
            (now, user_id),
        )
