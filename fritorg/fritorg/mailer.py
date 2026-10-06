"""E-mail: verified addresses and notifications (new messages, moderation decisions).

Mail goes out through any SMTP server (FRITORG_SMTP_*). Without SMTP settings nothing is
sent and nothing breaks. Messages are sent from a background thread so a slow mail server
never delays a page. Notifications only go to verified addresses, so nobody can make
Fritorg send mail to a stranger by typing their address.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import smtplib
import sqlite3
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from .config import Settings
from .util import now_iso

logger = logging.getLogger(__name__)
VERIFY_HOURS = 72


@dataclass
class Mail:
    to: str
    subject: str
    body: str


class Mailer:
    """Sends mail through SMTP in a background thread. Does nothing when SMTP is not configured."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mail") if self.enabled else None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.smtp_host)

    def send_later(self, mail: Mail) -> None:
        if self._pool is not None:
            self._pool.submit(self._send_safely, mail)

    def _send_safely(self, mail: Mail) -> None:
        try:
            self.send_now(mail)
        except Exception:
            logger.exception("Could not send e-mail to %s", mail.to)

    def send_now(self, mail: Mail) -> None:
        s = self.settings
        message = EmailMessage()
        message["From"] = s.smtp_from or formataddr(
            (s.site_name, f"noreply@{(s.base_url or 'localhost').split('//')[-1]}")
        )
        message["To"] = mail.to
        message["Subject"] = mail.subject
        message["Message-ID"] = make_msgid(domain="fritorg")
        message.set_content(mail.body)
        context = ssl.create_default_context()
        if s.smtp_security == "ssl":
            with smtplib.SMTP_SSL(s.smtp_host or "", s.smtp_port, context=context, timeout=20) as smtp:
                self._deliver(smtp, message)
        else:
            with smtplib.SMTP(s.smtp_host or "", s.smtp_port, timeout=20) as smtp:
                if s.smtp_security == "starttls":
                    smtp.starttls(context=context)
                self._deliver(smtp, message)

    def _deliver(self, smtp: smtplib.SMTP, message: EmailMessage) -> None:
        if self.settings.smtp_username:
            smtp.login(self.settings.smtp_username, self.settings.smtp_password or "")
        smtp.send_message(message)


class MemoryMailer(Mailer):
    """Collects mail instead of sending it (tests and local development)."""

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.outbox: list[Mail] = []

    @property
    def enabled(self) -> bool:
        return True

    def send_later(self, mail: Mail) -> None:
        self.outbox.append(mail)


# --- Verification links ---------------------------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def verification_token(secret: str, user_id: int, email: str) -> str:
    payload = _b64(
        json.dumps(
            {"u": user_id, "e": email.casefold(), "x": int(time.time()) + VERIFY_HOURS * 3600}
        ).encode()
    )
    signature = _b64(hmac.new(secret.encode(), f"verify:{payload}".encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def check_verification_token(secret: str, token: str) -> tuple[int, str] | None:
    payload, _, signature = token.partition(".")
    expected = _b64(hmac.new(secret.encode(), f"verify:{payload}".encode(), hashlib.sha256).digest())
    if not signature or not hmac.compare_digest(signature, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except ValueError:
        return None
    if data.get("x", 0) < time.time():
        return None
    return int(data["u"]), str(data["e"])


def verify_email(conn: sqlite3.Connection, secret: str, token: str) -> bool:
    checked = check_verification_token(secret, token)
    if checked is None:
        return False
    user_id, email = checked
    cursor = conn.execute(
        "UPDATE users SET email_verified_at = COALESCE(email_verified_at, ?) WHERE id = ? AND casefold(email) = ?",
        (now_iso(), user_id, email),
    )
    return cursor.rowcount == 1


def send_verification(mailer: Mailer, secret: str, base: str, user_id: int, name: str, email: str) -> None:
    if not mailer.enabled:
        return
    link = f"{base}/bekreft-epost?token={verification_token(secret, user_id, email)}"
    site = mailer.settings.site_name
    mailer.send_later(
        Mail(
            email,
            f"Bekreft e-postadressen din på {site}",
            f"Hei {name}!\n\nBekreft e-postadressen din, så får du beskjed når noen sender deg en melding:\n\n"
            f"{link}\n\nLenken virker i {VERIFY_HOURS} timer. Har du ikke laget en konto på {site}, kan du se bort "
            "fra denne e-posten.\n",
        )
    )


# --- Notifications -------------------------------------------------------------------------------


def _verified_address(conn: sqlite3.Connection, user_id: int) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT email, name FROM users WHERE id = ? AND email_verified_at IS NOT NULL AND banned_at IS NULL",
        (user_id,),
    ).fetchone()
    return (row["email"], row["name"]) if row else None


def notify_new_message(
    mailer: Mailer, base: str, conn: sqlite3.Connection, conversation_id: int, sender_id: int
) -> None:
    """Mail the recipient about a new message, once until they have read the conversation."""
    if not mailer.enabled:
        return
    conversation = conn.execute(
        "SELECT c.*, u.name AS sender_name FROM conversations c JOIN users u ON u.id = ? WHERE c.id = ?",
        (sender_id, conversation_id),
    ).fetchone()
    if conversation is None:
        return
    recipient_id = (
        conversation["seller_id"] if sender_id == conversation["buyer_id"] else conversation["buyer_id"]
    )
    unread = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND sender_id != ? AND read_at IS NULL",
        (conversation_id, recipient_id),
    ).fetchone()[0]
    address = _verified_address(conn, recipient_id)
    if unread != 1 or address is None:  # already told about earlier unread messages
        return
    email, name = address
    site = mailer.settings.site_name
    mailer.send_later(
        Mail(
            email,
            f"Ny melding om «{conversation['listing_title']}»",
            f"Hei {name}!\n\n{conversation['sender_name']} har sendt deg en melding om «{conversation['listing_title']}» "
            f"på {site}.\n\nLes og svar her: {base}/meldinger/{conversation_id}\n\n"
            f"Husk: {site} sender aldri betalingslenker, og du skal aldri oppgi kortnummer eller BankID for å motta "
            "penger.\n",
        )
    )


def notify_moderation(
    mailer: Mailer,
    base: str,
    conn: sqlite3.Connection,
    listing_id: int,
    approved: bool,
    note: str | None = None,
) -> None:
    if not mailer.enabled:
        return
    row = conn.execute("SELECT user_id, title FROM listings WHERE id = ?", (listing_id,)).fetchone()
    address = _verified_address(conn, row["user_id"]) if row else None
    if address is None:
        return
    email, name = address
    if approved:
        subject = f"Annonsen din er publisert: «{row['title']}»"
        text = f"Hei {name}!\n\nAnnonsen din er kontrollert og publisert: {base}/annonse/{listing_id}\n"
    else:
        subject = f"Annonsen din er fjernet: «{row['title']}»"
        text = (
            f"Hei {name}!\n\nEn moderator har fjernet annonsen din «{row['title']}».\n\nBegrunnelse: {note}\n"
        )
    mailer.send_later(Mail(email, subject, text))
