"""The odds sources. Each one sits behind the same interface, so one can be swapped without
touching the rest of the code."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, field_validator

MARKET_1X2 = "1X2"
OUTCOMES = ("home", "draw", "away")

# Whether an event (home, away, kick-off in UTC) is worth fetching odds for.
EventFilter = Callable[[str, str, datetime], bool]


class RawEvent(BaseModel):
    """One match as a source reports it, with decimal odds per outcome of the 1X2 market."""

    source: str
    source_event_id: str
    home: str
    away: str
    league: str
    kickoff_utc: datetime
    odds: dict[str, float]
    market: str = MARKET_1X2

    @field_validator("kickoff_utc")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("kickoff_utc must carry a time zone")
        return value

    @field_validator("odds")
    @classmethod
    def _complete(cls, value: dict[str, float]) -> dict[str, float]:
        if set(value) != set(OUTCOMES) or any(o <= 1.0 for o in value.values()):
            raise ValueError(f"odds must be above 1 for exactly {', '.join(OUTCOMES)}")
        return value

    def prices(self) -> list[float]:
        return [self.odds[o] for o in OUTCOMES]


class SourceError(RuntimeError):
    """A source could not deliver. The message says why, in words a person can act on.

    retryable=False for problems another attempt will not fix (a rejected API key, a changed format).
    """

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class OddsSource(Protocol):
    name: str

    def fetch(self, days_ahead: int) -> list[RawEvent]: ...


class ReferenceSource(OddsSource, Protocol):
    def fetch(self, days_ahead: int, want: EventFilter | None = None) -> list[RawEvent]:
        """With want, odds are only fetched for the events it accepts (each request counts against a quota)."""
        ...
