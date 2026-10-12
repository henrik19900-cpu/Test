"""Sellers who sell as a business: the organisation number and name that buyers see.

Buyers must be told whether a seller is a business, since consumer law (forbrukerkjøpsloven, and the right to
cancel when buying at a distance) applies only then, and who the business is. A seller declares it on Min side
or with the API. The number is checked against Enhetsregisteret, the official register of Norwegian entities
(open data from Brønnøysundregistrene), and the name registered there is the one shown. The declaration is the
seller's own: pages say so, and link to the register so buyers can check.
"""

from __future__ import annotations

import json
import re
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Callable

from .errors import ServiceUnavailable, ValidationProblem
from .users import User
from .util import now_iso

REGISTRY_API = "https://data.brreg.no/enhetsregisteret/api/enheter/{}"
REGISTRY_PAGE = "https://virksomhet.brreg.no/nb/oppslag/enheter/{}"
_WEIGHTS = (3, 2, 7, 6, 5, 4, 3, 2)  # modulus 11 check digit of Norwegian organisation numbers

Lookup = Callable[[str], str]


def clean_org_number(value: str) -> str:
    """The nine digits of an organisation number ("974 760 673" -> "974760673"), if the check digit fits."""
    digits = re.sub(r"[\s.-]", "", value or "")
    if not re.fullmatch(r"\d{9}", digits):
        raise ValidationProblem.field("org_number", "Organisasjonsnummeret har 9 sifre.")
    check = 11 - sum(int(digit) * weight for digit, weight in zip(digits[:8], _WEIGHTS, strict=True)) % 11
    if check % 11 != int(digits[8]) or check == 10:
        raise ValidationProblem.field("org_number", "Organisasjonsnummeret er ikke gyldig. Sjekk sifrene.")
    return digits


def format_org_number(number: str, space: str = " ") -> str:
    return space.join((number[:3], number[3:6], number[6:]))


def registry_name(org_number: str) -> str:
    """The name Enhetsregisteret has for the number. Refused when it is not registered or has been deleted."""
    request = urllib.request.Request(REGISTRY_API.format(org_number), headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            raise ValidationProblem.field(
                "org_number",
                "Organisasjonsnummeret finnes ikke i Enhetsregisteret, eller enheten er slettet.",
            ) from None
        raise ServiceUnavailable("Enhetsregisteret svarer ikke akkurat nå. Prøv igjen om litt.") from None
    except (OSError, ValueError):
        raise ServiceUnavailable("Enhetsregisteret svarer ikke akkurat nå. Prøv igjen om litt.") from None
    if data.get("slettedato") or not data.get("navn"):
        raise ValidationProblem.field("org_number", "Enheten er slettet i Enhetsregisteret.")
    return " ".join(str(data["navn"]).split())[:200]


def lookup_for(registry: str) -> Lookup | None:
    """How names are found: in Enhetsregisteret, or not at all (registry "off", for development)."""
    return registry_name if registry == "brreg" else None


def declare(
    conn: sqlite3.Connection, user: User, org_number: str, lookup: Lookup | None, name: str | None = None
) -> tuple[str, str]:
    """Mark the account as a business. Returns the number and the name shown (from the register, or, when the
    register is not used, the one given)."""
    number = clean_org_number(org_number)
    if lookup is not None:
        shown = lookup(number)
        checked = now_iso()
    else:
        shown = " ".join((name or user.name).split())[:200]
        checked = None
    conn.execute(
        "UPDATE users SET org_number = ?, business_name = ?, business_checked_at = ? WHERE id = ?",
        (number, shown, checked, user.id),
    )
    return number, shown


def remove(conn: sqlite3.Connection, user: User) -> None:
    conn.execute(
        "UPDATE users SET org_number = NULL, business_name = NULL, business_checked_at = NULL WHERE id = ?",
        (user.id,),
    )


def as_dict(org_number: str | None, name: str | None) -> dict[str, str] | None:
    """For the API: who the business is, and where to check it."""
    if org_number is None:
        return None
    return {
        "name": name or "",
        "org_number": org_number,
        "registry_url": REGISTRY_PAGE.format(org_number),
        "declared_by": "seller",
    }
