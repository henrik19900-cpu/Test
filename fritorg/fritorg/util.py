"""Small helpers shared across the app: timestamps and Norwegian formatting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo

try:  # Show dates in Norwegian local time when tz data is available.
    from zoneinfo import ZoneInfo

    LOCAL_TZ: tzinfo = ZoneInfo("Europe/Oslo")
except Exception:  # pragma: no cover - depends on the host's tz database
    LOCAL_TZ = UTC

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

MONTHS_NO = ["jan.", "feb.", "mars", "apr.", "mai", "juni", "juli", "aug.", "sep.", "okt.", "nov.", "des."]


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def to_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(ISO_FORMAT)


def now_iso() -> str:
    return to_iso(utcnow())


def iso_in(**delta: float) -> str:
    return to_iso(utcnow() + timedelta(**delta))


def iso_ago(**delta: float) -> str:
    return to_iso(utcnow() - timedelta(**delta))


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (date or datetime). Naive values are treated as UTC."""
    text = value.strip()
    if len(text) == 10:
        text += "T00:00:00"
    moment = datetime.fromisoformat(text.replace("z", "Z"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment


def format_number(value: int, sep: str = " ") -> str:
    return f"{value:,}".replace(",", sep)


def format_date_no(iso: str | None) -> str:
    if not iso:
        return ""
    moment = parse_iso(iso).astimezone(LOCAL_TZ)
    return f"{moment.day}. {MONTHS_NO[moment.month - 1]} {moment.year}"


def format_ago_no(iso: str | None) -> str:
    """How old something is, in Norwegian days: "i dag", "i går", "3 dager siden", then the date."""
    if not iso:
        return ""
    day = parse_iso(iso).astimezone(LOCAL_TZ).date()
    today = utcnow().astimezone(LOCAL_TZ).date()
    days = (today - day).days
    if days <= 0:
        return "i dag"
    if days == 1:
        return "i går"
    if days < 7:
        return f"{days} dager siden"
    text = f"{day.day}. {MONTHS_NO[day.month - 1]}"
    return text if day.year == today.year else f"{text} {day.year}"


def format_datetime_no(iso: str | None) -> str:
    if not iso:
        return ""
    moment = parse_iso(iso).astimezone(LOCAL_TZ)
    return f"{format_date_no(iso)} kl. {moment:%H:%M}"


def truncate(text: str, length: int) -> str:
    text = " ".join(text.split())
    if len(text) <= length:
        return text
    cut = text[: length - 1].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:-") + "…"
