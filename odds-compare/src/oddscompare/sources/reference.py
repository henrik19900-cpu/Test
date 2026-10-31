"""Reference odds from Odds-API.io (https://docs.odds-api.io).

Pinnacle closed its public API in July 2025, and Odds-API.io does not carry Pinnacle. Betfair
Exchange is the default bookmaker: an exchange's prices are set by the market, with next to no
margin. Any bookmaker name from GET /bookmakers works (config: reference.odds_api_io.bookmaker).

Two kinds of requests: /events lists the upcoming matches the bookmaker has odds for, and
/odds/multi fetches the 1X2 market ("ML") for up to 10 events per request. Every request counts
against the key's quota (100 an hour on the old free keys, 5 000 on paid plans), so fetch.py passes
a filter that keeps only the events that can match a Norsk Tipping match.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from ..config import OddsApiIoConfig
from . import OUTCOMES, EventFilter, RawEvent, SourceError

MARKET = "ML"  # Odds-API.io's name for the full-time three-way result in football
BATCH = 10  # the most event ids /odds/multi takes


class OddsApiIo:
    name = "odds_api_io"

    def __init__(
        self,
        cfg: OddsApiIoConfig,
        api_key: str | None,
        user_agent: str,
        cache_dir: Path | None = None,
        client: httpx.Client | None = None,
        clock=lambda: datetime.now(UTC),
    ):
        self.cfg = cfg
        self.api_key = api_key
        self.cache_file = cache_dir / f"{self.name}.json" if cache_dir else None
        self.client = client or httpx.Client(timeout=cfg.timeout_seconds)
        self.headers = {"user-agent": user_agent, "accept": "application/json"}
        self.clock = clock

    def fetch(self, days_ahead: int, want: EventFilter | None = None) -> list[RawEvent]:
        if not self.api_key:
            raise SourceError("ODDS_API_IO_KEY mangler i .env", retryable=False)
        now = self.clock()
        events = self._events(now, now + timedelta(days=days_ahead))
        if want is not None:
            events = [e for e in events if want(e["home"], e["away"], _kickoff(e))]
        odds = []
        for start in range(0, len(events), BATCH):
            ids = ",".join(str(e["id"]) for e in events[start : start + BATCH])
            odds.extend(
                self._get("/odds/multi", eventIds=ids, bookmakers=self.cfg.bookmaker, markets=MARKET) or []
            )
        self._save({"fetched_at_utc": now.isoformat(), "bookmaker": self.cfg.bookmaker, "odds": odds})
        return parse_odds(odds, self.cfg.bookmaker, self.name)

    def _events(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        params = {
            "sport": "football",
            "bookmaker": self.cfg.bookmaker,
            "status": "pending",
            "from": _rfc3339(start),
            "to": _rfc3339(end),
            "limit": 5000,
        }
        if not self.cfg.leagues:
            return self._get("/events", **params) or []
        events = []
        for league in self.cfg.leagues:
            events.extend(self._get("/events", **params, league=league) or [])
        return events

    def _get(self, path: str, **params: Any) -> Any:
        try:
            response = self.client.get(
                self.cfg.base_url + path, params={**params, "apiKey": self.api_key}, headers=self.headers
            )
        except httpx.HTTPError as e:
            raise SourceError(f"Odds-API.io svarte ikke ({type(e).__name__})") from e
        if response.status_code in (401, 403):
            raise SourceError("Odds-API.io avviste API-nøkkelen (sjekk ODDS_API_IO_KEY)", retryable=False)
        if response.status_code == 429:
            raise SourceError(
                "Odds-API.io: kvoten for API-nøkkelen er brukt opp, prøv igjen senere", retryable=False
            )
        if response.status_code >= 400:
            raise SourceError(f"Odds-API.io svarte {response.status_code} på {path}: {response.text[:200]}")
        try:
            return response.json()
        except ValueError as e:
            raise SourceError(f"Odds-API.io sendte ikke JSON på {path}") from e

    def _save(self, payload: dict[str, Any]) -> None:
        if self.cache_file:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def parse_odds(events: list[dict[str, Any]], bookmaker: str, source: str = OddsApiIo.name) -> list[RawEvent]:
    """The 1X2 odds from /odds or /odds/multi responses. Events without the bookmaker's ML market are skipped."""
    if not isinstance(events, list):
        raise SourceError("Odds-API.io: uventet format på oddssvaret (forventet en liste)", retryable=False)
    parsed = []
    for event in events:
        try:
            markets = (event.get("bookmakers") or {}).get(bookmaker) or []
            market = next((m for m in markets if str(m.get("name", "")).upper() == MARKET), None)
            if not market or not market.get("odds"):
                continue
            line = market["odds"][0]
            if any(line.get(o) in (None, "") for o in OUTCOMES):
                continue
            parsed.append(
                RawEvent(
                    source=source,
                    source_event_id=str(event["id"]),
                    home=event["home"],
                    away=event["away"],
                    league=(event.get("league") or {}).get("name", ""),
                    kickoff_utc=_kickoff(event),
                    odds={o: float(line[o]) for o in OUTCOMES},
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            raise SourceError(
                f"Odds-API.io: uventet format på kamp {event.get('id')!r}: {e}", retryable=False
            ) from e
    return parsed


def _kickoff(event: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(event["date"]).replace("Z", "+00:00")).astimezone(UTC)


def _rfc3339(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
