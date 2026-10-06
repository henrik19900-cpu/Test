"""Protection against fraud and fake listings.

Every listing is scored when it is created or changed, and every message when it is sent.
Signals are explainable rules, not a black box: each has a weight, an explanation for the
owner and moderators, and optionally a neutral warning for buyers or message recipients.

* Listings scoring REVIEW_THRESHOLD or more are held for manual review (status "review")
  and are not public until a moderator approves them.
* Messages are never blocked, but risky ones carry warnings for the recipient. The API and
  MCP expose the same warnings, so an AI agent can warn its user too.

The patterns target the most common classifieds scams in Norway: payment links ("receive
the money here"), advance payment and deposits for rentals, gift cards and crypto, BankID
codes and card numbers, "I am abroad", money-mule jobs and moving the chat to WhatsApp.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import statistics
from dataclasses import dataclass
from typing import Any

from .util import iso_ago

REVIEW_THRESHOLD = 50
NEW_ACCOUNT_DAYS = 7
AUTO_REVIEW_REPORTS = 3  # distinct logged-in reporters before a listing is hidden for review
PRICE_CHECK_CATEGORIES = {"bil", "mc", "bat", "bobil", "bolig", "fritidsbolig", "tomt"}


@dataclass(frozen=True)
class SignalInfo:
    code: str
    weight: int
    reason: str  # for the owner and moderators
    listing_warning: str | None = None  # neutral warning shown to buyers on a published listing
    message_warning: str | None = None  # warning shown to the recipient of a message


_PAYMENT_WARNING = "Avsenderen foreslår en betalingsmåte som ofte brukes i svindel. Betal aldri på forskudd til noen du ikke har møtt."

SIGNALS: dict[str, SignalInfo] = {
    s.code: s
    for s in (
        SignalInfo(
            "transfer_service",
            60,
            "Nevner betaling via pengeoverføringstjenester som Western Union eller MoneyGram.",
            message_warning=_PAYMENT_WARNING,
        ),
        SignalInfo(
            "gift_card_payment",
            60,
            "Ber om betaling med gavekort.",
            message_warning="Ingen seriøse selgere ber om betaling med gavekort. Dette er nesten alltid svindel.",
        ),
        SignalInfo(
            "crypto_payment", 50, "Ber om betaling med kryptovaluta.", message_warning=_PAYMENT_WARNING
        ),
        SignalInfo(
            "advance_payment",
            35,
            "Ber om forskuddsbetaling.",
            message_warning="Betal aldri på forskudd til noen du ikke har møtt, med mindre du bruker en trygg betalingsløsning.",
        ),
        SignalInfo(
            "deposit_before_viewing",
            50,
            "Ber om depositum før visning eller kontrakt.",
            message_warning="Betal aldri depositum før du har sett boligen og signert kontrakt. Depositum skal stå på en egen depositumskonto.",
        ),
        SignalInfo(
            "keys_by_mail",
            50,
            "Tilbyr å sende nøkler i posten (vanlig ved falske utleieannonser).",
            message_warning="Utleiere som vil sende nøklene i posten mot depositum er et kjent svindeltriks.",
        ),
        SignalInfo(
            "first_to_pay",
            50,
            "«Første som betaler får den» – et vanlig pressmiddel i svindel.",
            message_warning=_PAYMENT_WARNING,
        ),
        SignalInfo(
            "credentials_request",
            60,
            "Ber om koder, kortnummer eller personnummer.",
            message_warning="Avsenderen ber om koder, kortnummer eller personnummer. Del aldri slike opplysninger – du trenger dem aldri for å motta penger.",
        ),
        SignalInfo(
            "money_mule",
            60,
            "Ligner rekruttering til hvitvasking (motta og videresende penger eller pakker).",
            message_warning="Å motta og videresende penger eller pakker for andre kan gjøre deg til medskyldig i hvitvasking.",
        ),
        SignalInfo(
            "abroad_story",
            30,
            "Forteller at selgeren er i utlandet – et vanlig mønster i svindel.",
            message_warning="Historier om at selgeren er i utlandet og vil sende varen eller nøklene er et vanlig svindeltriks.",
        ),
        SignalInfo(
            "offsite_contact",
            25,
            "Ber om kontakt utenfor Fritorg (WhatsApp, Telegram e.l.).",
            listing_warning="Annonsen ber om kontakt utenfor Fritorg. Hold samtalen her – da er det lettere å få hjelp hvis noe går galt.",
            message_warning="Avsenderen vil fortsette samtalen utenfor Fritorg. Svindlere gjør ofte dette for å unngå sporing.",
        ),
        SignalInfo(
            "contact_email",
            15,
            "Inneholder en e-postadresse.",
            listing_warning="Annonsen inneholder en e-postadresse. Bruk gjerne meldingsfunksjonen på Fritorg i stedet.",
        ),
        SignalInfo(
            "foreign_phone",
            25,
            "Inneholder et utenlandsk telefonnummer.",
            listing_warning="Annonsen inneholder et utenlandsk telefonnummer. Vær ekstra oppmerksom.",
            message_warning="Meldingen inneholder et utenlandsk telefonnummer. Vær ekstra oppmerksom.",
        ),
        SignalInfo(
            "short_link",
            35,
            "Inneholder en forkortet lenke som skjuler hvor den fører.",
            listing_warning="Annonsen inneholder en forkortet lenke. Slike lenker skjuler hvor de fører.",
            message_warning="Meldingen inneholder en forkortet lenke. Slike lenker skjuler hvor de fører – ikke klikk på den.",
        ),
        SignalInfo(
            "external_link",
            10,
            "Inneholder en lenke til en annen nettside.",
            listing_warning="Annonsen inneholder en lenke til en annen nettside. Logg aldri inn og betal aldri via lenker.",
            message_warning="Meldingen inneholder en lenke. Logg aldri inn og oppgi aldri kort- eller BankID-opplysninger via lenker.",
        ),
        SignalInfo(
            "payment_link",
            60,
            "Inneholder en lenke om betaling eller frakt.",
            message_warning="Dette ligner en falsk betalingslenke. Fritorg sender aldri betalingslenker, og du skal aldri oppgi kortnummer eller BankID for å motta penger.",
        ),
        SignalInfo("pressure", 10, "Bruker pressende formuleringer («haster», «må selges i dag»)."),
        SignalInfo("price_far_below", 50, "Prisen er under 10 % av vanlig pris for lignende annonser."),
        SignalInfo("price_below", 30, "Prisen er langt under vanlig pris for lignende annonser."),
        SignalInfo("copied_text", 50, "Teksten er identisk med en annen selgers annonse."),
        SignalInfo("duplicate_listing", 20, "Selgeren har allerede flere annonser med samme tekst."),
        SignalInfo("reused_image", 50, "Et bilde er også brukt i en annen selgers annonse."),
        SignalInfo("new_account_high_value", 20, "Ny konto som legger ut en dyr vare."),
        SignalInfo("new_account_burst", 15, "Ny konto som legger ut mange annonser på kort tid."),
        SignalInfo("reported", 50, "Rapportert av flere brukere."),
    )
}

# Patterns run on casefolded text. Payment words must appear in a payment context, so that
# selling a gift card or a crypto mining rig is not flagged on its own.
_PAY = r"(?:betal\w*|send\w*|overfør\w*|pay\w*|transfer\w*)"
_URL = r"(?:https?://|www\.)\S+"
_TEXT_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("transfer_service", re.compile(r"\b(western ?union|money ?gram|ria money transfer|worldremit)\b")),
    (
        "gift_card_payment",
        re.compile(
            rf"\b{_PAY}\s+(?:\S+\s+){{0,4}}(?:gavekort|gift ?cards?|itunes|steam-?kort|google play-?kort)"
        ),
    ),
    (
        "crypto_payment",
        re.compile(rf"\b{_PAY}\s+(?:\S+\s+){{0,4}}(?:bitcoin|btc|krypto\w*|crypto\w*|usdt|ethereum)\b"),
    ),
    (
        "advance_payment",
        re.compile(
            r"(forskuddsbetal\w*|betale? (?:\S+ ){0,2}forskudd|\bpay (?:in advance|upfront)\b|advance payment)"
        ),
    ),
    (
        "deposit_before_viewing",
        re.compile(
            r"(depositum\w* (?:\S+ ){0,3}(?:først|før (?:visning|kontrakt|du (?:ser|får))|på forhånd)"
            r"|(?:send|overfør|betal)\w* (?:\S+ ){0,2}depositum|deposit (?:first|before)|pay (?:the|a) deposit)"
        ),
    ),
    (
        "keys_by_mail",
        re.compile(
            r"(nøkl\w* (?:\S+ ){0,2}(?:i|per|med) post\w*|send\w* (?:\S+ ){0,2}nøkl\w*|keys? (?:by|via) (?:mail|post)"
            r"|mail (?:you )?the keys)"
        ),
    ),
    ("first_to_pay", re.compile(r"(første som (?:betaler|vippser|overfører)|first (?:one )?to pay)")),
    (
        "credentials_request",
        re.compile(
            r"(bankid[- ]?(?:kode|passord|innlogging)|engangskode|kodebrikke|sms-?kode|kortnummer|kortdetaljer"
            r"|\bcvc\b|\bcvv\b|card (?:number|details)|personnummer|fødselsnummer)"
        ),
    ),
    (
        "money_mule",
        re.compile(
            r"(finans ?agent|financial agent|motta (?:penger|betaling\w*|overføring\w*) (?:på|til|via) (?:din|egen|privat)"
            r"|videresend\w* (?:penger|beløp|pakker)|money transfer agent|reshipping|pakkemottaker)"
        ),
    ),
    (
        "abroad_story",
        re.compile(
            r"((?:jeg )?(?:er|bor|jobber) (?:nå |for tiden |midlertidig )?(?:i utlandet|på (?:en )?oljeplattform|offshore)"
            r"|i'?m (?:currently )?(?:abroad|overseas|out of the country)|working (?:abroad|offshore))"
        ),
    ),
    ("offsite_contact", re.compile(r"\b(whats ?app|telegram|wechat|viber|kik messenger)\b")),
    ("contact_email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("foreign_phone", re.compile(r"(?<![\w+])(?:\+|00)(?!47)[1-9]\d{0,2}[\s-]?\d{2,4}[\s-]?\d{3,}")),
    (
        "short_link",
        re.compile(
            r"\b(bit\.ly|tinyurl\.com|t\.me|wa\.me|goo\.gl|is\.gd|ow\.ly|rb\.gy|cutt\.ly|shorturl\.at|tiny\.cc)/"
        ),
    ),
    ("external_link", re.compile(_URL)),
    ("pressure", re.compile(r"\b(haster|må selges (?:i dag|nå|raskt|fort)|urgent|asap)\b")),
]
_PAYMENT_CONTEXT = re.compile(
    r"(betal\w*|motta\w*|utbetal\w*|posten|bring|postnord|helthjem|fiks ferdig|vipps|frakt\w*|levering|kort\w*|bekreft\w*|pay\w*|deliver\w*|shipping)"
)


@dataclass
class Assessment:
    codes: list[str]

    @property
    def score(self) -> int:
        return sum(SIGNALS[c].weight for c in self.codes)

    @property
    def needs_review(self) -> bool:
        return self.score >= REVIEW_THRESHOLD


def text_codes(text: str) -> list[str]:
    folded = text.casefold()
    codes = [code for code, pattern in _TEXT_RULES if pattern.search(folded)]
    if "short_link" in codes and "external_link" in codes:
        codes.remove("external_link")
    return codes


def assess_message(text: str) -> Assessment:
    codes = [c for c in text_codes(text) if SIGNALS[c].message_warning or c == "external_link"]
    has_link = "external_link" in codes or "short_link" in codes
    if has_link and _PAYMENT_CONTEXT.search(text.casefold()):
        codes = [c for c in codes if c != "external_link"] + ["payment_link"]
    return Assessment(codes)


def text_hash(description: str) -> str | None:
    """Fingerprint of a description, ignoring case, punctuation and spacing (for copy detection)."""
    normalized = " ".join(re.sub(r"[\W_]+", " ", description.casefold()).split())
    if len(normalized) < 40:
        return None
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def _price_codes(conn: sqlite3.Connection, values: dict[str, Any], listing_id: int | None) -> list[str]:
    price = values.get("price")
    if (
        values["category"] not in PRICE_CHECK_CATEGORIES
        or values["type"] not in ("sell", "rent")
        or not price
    ):
        return []
    rows = conn.execute(
        "SELECT price FROM listings WHERE category = ? AND type = ? AND price_unit = ? AND price > 0 "
        "AND status IN ('active', 'sold') AND id != ? ORDER BY id DESC LIMIT 500",
        (values["category"], values["type"], values["price_unit"], listing_id or 0),
    ).fetchall()
    if len(rows) < 5:
        return []
    median = statistics.median(row["price"] for row in rows)
    if median < 5000:
        return []
    if price < median * 0.10:
        return ["price_far_below"]
    if price < median * 0.25:
        return ["price_below"]
    return []


def _duplicate_codes(
    conn: sqlite3.Connection, user_id: int, fingerprint: str | None, listing_id: int | None
) -> list[str]:
    if fingerprint is None:
        return []
    rows = conn.execute(
        "SELECT id, user_id FROM listings WHERE text_hash = ? AND id != ? AND status IN ('active', 'sold', 'review')",
        (fingerprint, listing_id or 0),
    ).fetchall()
    codes = []
    # Only an older listing by someone else counts: the original is never flagged because of a copy.
    if any(row["user_id"] != user_id and (listing_id is None or row["id"] < listing_id) for row in rows):
        codes.append("copied_text")
    if sum(1 for row in rows if row["user_id"] == user_id) >= 2:
        codes.append("duplicate_listing")
    return codes


def _account_codes(
    conn: sqlite3.Connection, user_id: int, values: dict[str, Any], listing_id: int | None
) -> list[str]:
    row = conn.execute("SELECT created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or row["created_at"] < iso_ago(days=1):
        return []
    codes = []
    if (values.get("price") or 0) >= 20_000:
        codes.append("new_account_high_value")
    recent = conn.execute(
        "SELECT COUNT(*) FROM listings WHERE user_id = ? AND created_at > ? AND id != ?",
        (user_id, iso_ago(days=1), listing_id or 0),
    ).fetchone()[0]
    if recent >= 3:
        codes.append("new_account_burst")
    return codes


def assess_listing(
    conn: sqlite3.Connection, user_id: int, values: dict[str, Any], listing_id: int | None = None
) -> tuple[Assessment, str | None]:
    """Score a validated listing. Returns the assessment and the description fingerprint."""
    attribute_text = " ".join(str(v) for v in values.get("attributes", {}).values())
    codes = text_codes(
        f"{values['title']}\n{values['description']}\n{values.get('location') or ''}\n{attribute_text}"
    )
    fingerprint = text_hash(values["description"])
    codes += _price_codes(conn, values, listing_id)
    codes += _duplicate_codes(conn, user_id, fingerprint, listing_id)
    codes += _account_codes(conn, user_id, values, listing_id)
    if listing_id is not None:
        # Signals that come from outside the text survive edits.
        row = conn.execute("SELECT risk_flags FROM listings WHERE id = ?", (listing_id,)).fetchone()
        for code in json.loads(row["risk_flags"]) if row else []:
            if code in ("reused_image", "reported") and code not in codes:
                codes.append(code)
    return Assessment(codes), fingerprint


def image_reused_by_other_seller(conn: sqlite3.Connection, user_id: int, digest: str) -> bool:
    """True if another seller uploaded this exact image first (so the original owner is never flagged)."""
    row = conn.execute(
        "SELECT l.user_id FROM listing_images i JOIN listings l ON l.id = i.listing_id WHERE i.sha256 = ? "
        "ORDER BY i.id LIMIT 1",
        (digest,),
    ).fetchone()
    return row is not None and row["user_id"] != user_id


def reasons(codes: list[str]) -> list[dict[str, str]]:
    return [{"code": c, "reason": SIGNALS[c].reason} for c in codes if c in SIGNALS]


def listing_warnings(codes: list[str]) -> list[str]:
    return [SIGNALS[c].listing_warning for c in codes if c in SIGNALS and SIGNALS[c].listing_warning]  # type: ignore[misc]


def message_warnings(codes: list[str]) -> list[str]:
    warnings = [SIGNALS[c].message_warning for c in codes if c in SIGNALS and SIGNALS[c].message_warning]
    return list(dict.fromkeys(w for w in warnings if w))
