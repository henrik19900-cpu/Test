"""Reference odds: OddsLink (free plan, the default), The Odds API (free plan, its fallback) or
Odds-API.io (paid).

OddsLink (https://oddslink.app) has Pinnacle, Betfair Exchange and the big European bookmakers on its
free plan: 1,000 requests a month, no card. One request to the soccer key returns every league with
every bookmaker asked for, and counts once however many matches come back, so one request covers
what costs a credit per league at The Odds API. When OddsLink fails, FallbackReference asks The
Odds API instead and stores its odds as OddsLink's, so the dashboard and the alerts carry on.

Pinnacle closed its public API in July 2025. The Odds API (https://the-odds-api.com) carries
Pinnacle's prices, taken from Pinnacle's public website, on its free plan: 500 credits a month, no
card. /sports and /sports/{league}/events are free; /sports/{league}/odds costs 1 credit per league
for one market and one bookmaker, however many matches it returns, and nothing when it returns
none. So each request lists the matches for free, keeps those that can match a Norsk Tipping match
(the filter fetch.py passes), and spends a credit only on leagues that have one.

Reference odds are fetched only when the user asks (`oddscompare reference` or the dashboard's
button), never in the regular rounds. A second request within min_interval_minutes reuses the
first answer.

Norsk Tipping's competitors (config: competitors) are asked for in the same request: up to 10
bookmakers cost the same single credit per league. Their odds are kept in competitor_odds.

Odds-API.io (https://docs.odds-api.io) is kept as an option for a paid key. It does not carry
Pinnacle; Betfair Exchange is its default there.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from ..config import OddsApiIoConfig, OddsLinkConfig, TheOddsApiConfig
from . import OUTCOMES, EventFilter, RawEvent, SourceError

logger = logging.getLogger(__name__)

MARKET = "ML"  # Odds-API.io's name for the full-time three-way result in football
BATCH = 10  # the most event ids /odds/multi takes
DRAW = "Draw"  # The Odds API's name for the draw in a soccer h2h market


class TheOddsApi:
    name = "the_odds_api"

    def __init__(
        self,
        cfg: TheOddsApiConfig,
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
        self.fetched_at: datetime | None = None  # when the odds of the last fetch() were read from the API
        self.remaining: int | None = None  # credits left this month, as the API last reported
        self.spent = 0  # credits the last fetch() cost, as the API reported per call (0 for a cached answer)
        # The competitors' odds from the last fetch(), one RawEvent per bookmaker and match, with the
        # reference's event ids (the same match) and source "the_odds_api:<bookmaker>".
        self.competitor_odds: list[RawEvent] = []

    def fetch(self, days_ahead: int, want: EventFilter | None = None) -> list[RawEvent]:
        if not self.api_key:
            raise SourceError(
                "THE_ODDS_API_KEY mangler: legg den i .env, eller under «Secrets» på Streamlit Cloud "
                '(THE_ODDS_API_KEY = "nøkkelen"). Gratis nøkkel: the-odds-api.com',
                retryable=False,
            )
        now = self.clock()
        self.spent = 0
        cached = self._cached(now)
        if cached is None:
            window = {
                "commenceTimeFrom": _rfc3339(now),
                "commenceTimeTo": _rfc3339(now + timedelta(days=days_ahead)),
            }
            events: list[dict[str, Any]] = []
            for league in self.cfg.leagues:
                listed = self._get(f"/sports/{league}/events", **window) or []  # free
                ids = [
                    e["id"]
                    for e in listed
                    if want is None or want(e["home_team"], e["away_team"], _commence(e))
                ]
                if ids:
                    events += (
                        self._get(
                            f"/sports/{league}/odds",
                            **window,
                            bookmakers=",".join(self.cfg.bookmakers),  # up to 10 cost the same as one
                            markets="h2h",
                            oddsFormat="decimal",
                            dateFormat="iso",
                            eventIds=",".join(ids),
                        )
                        or []
                    )
            cached = {
                "fetched_at_utc": now.isoformat(),
                "remaining": self.remaining,
                "leagues": self.cfg.leagues,
                "bookmakers": self.cfg.bookmakers,
                "events": events,
            }
            self._save(cached)
            logger.info("The Odds API: %s credits left this month", self.remaining)
        self.fetched_at = datetime.fromisoformat(cached["fetched_at_utc"])
        self.competitor_odds = [
            raw
            for key in self.cfg.competitors
            for raw in parse_h2h(cached["events"], key, f"{self.name}:{key}")
        ]
        return parse_h2h(cached["events"], self.cfg.bookmaker, self.name)

    def _get(self, path: str, **params: Any) -> Any:
        try:
            response = self.client.get(
                self.cfg.base_url + path, params={**params, "apiKey": self.api_key}, headers=self.headers
            )
        except httpx.HTTPError as e:
            raise SourceError(f"The Odds API svarte ikke ({type(e).__name__})") from e
        try:
            if "x-requests-remaining" in response.headers:
                self.remaining = int(float(response.headers["x-requests-remaining"]))
            if "x-requests-last" in response.headers:
                self.spent += int(float(response.headers["x-requests-last"]))
        except ValueError:
            pass
        if response.status_code == 401:
            raise SourceError(
                "The Odds API avviste nøkkelen, eller månedens kreditter er brukt opp (sjekk THE_ODDS_API_KEY)",
                retryable=False,
            )
        if response.status_code == 429:
            raise SourceError("The Odds API: for mange forespørsler, prøv igjen om litt")
        if response.status_code == 404:
            raise SourceError(
                f"The Odds API kjenner ikke {path} (sjekk ligaene i config.yaml)", retryable=False
            )
        if response.status_code >= 400:
            raise SourceError(f"The Odds API svarte {response.status_code} på {path}: {response.text[:200]}")
        try:
            return response.json()
        except ValueError as e:
            raise SourceError(f"The Odds API sendte ikke JSON på {path}") from e

    def _cached(self, now: datetime) -> dict[str, Any] | None:
        if not self.cache_file or not self.cache_file.exists():
            return None
        try:
            payload = json.loads(self.cache_file.read_text(encoding="utf-8"))
            age = now - datetime.fromisoformat(payload["fetched_at_utc"])
        except (OSError, ValueError, KeyError):
            return None
        same_request = (
            payload.get("leagues") == self.cfg.leagues and payload.get("bookmakers") == self.cfg.bookmakers
        )
        fresh = timedelta(0) <= age < timedelta(minutes=self.cfg.min_interval_minutes)
        return payload if same_request and fresh else None

    def _save(self, payload: dict[str, Any]) -> None:
        if self.cache_file:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def parse_h2h(
    events: list[dict[str, Any]], bookmaker: str, source: str = TheOddsApi.name, label: str = "The Odds API"
) -> list[RawEvent]:
    """The 1X2 odds from an /odds answer of The Odds API or OddsLink (the same format). Events without the
    bookmaker's h2h market are skipped."""
    if not isinstance(events, list):
        raise SourceError(f"{label}: uventet format på oddssvaret (forventet en liste)", retryable=False)
    parsed = []
    for event in events:
        try:
            book = next((b for b in event.get("bookmakers") or [] if b.get("key") == bookmaker), None)
            market = next((m for m in (book or {}).get("markets") or [] if m.get("key") == "h2h"), None)
            if not market:
                continue
            prices = {o["name"]: float(o["price"]) for o in market.get("outcomes") or []}
            names = {"home": event["home_team"], "draw": DRAW, "away": event["away_team"]}
            if any(name not in prices for name in names.values()):
                continue
            parsed.append(
                RawEvent(
                    source=source,
                    source_event_id=str(event["id"]),
                    home=event["home_team"],
                    away=event["away_team"],
                    league=_league(event),
                    kickoff_utc=_commence(event),
                    odds={outcome: prices[name] for outcome, name in names.items()},
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            raise SourceError(
                f"{label}: uventet format på kamp {event.get('id')!r}: {e}", retryable=False
            ) from e
    return parsed


def _league(event: dict[str, Any]) -> str:
    """OddsLink names the league in league.title; The Odds API in sport_title."""
    league = event.get("league")
    if isinstance(league, dict) and league.get("title"):
        return str(league["title"])
    return event.get("sport_title") or event.get("sport_key", "")


def _commence(event: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(event["commence_time"]).replace("Z", "+00:00")).astimezone(UTC)


class OddsLink:
    """OddsLink's /sports/soccer/odds: every soccer league, the reference and the competitors in one
    request (it counts once). A second request within min_interval_minutes reuses the first answer."""

    name = "oddslink"

    def __init__(
        self,
        cfg: OddsLinkConfig,
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
        self.fetched_at: datetime | None = None
        self.remaining: int | None = None  # requests left this month, as OddsLink last reported
        self.spent = 0  # requests the last fetch() counted (0 for a cached answer)
        self.competitor_odds: list[RawEvent] = []

    def fetch(self, days_ahead: int, want: EventFilter | None = None) -> list[RawEvent]:
        if not self.api_key:
            raise SourceError(
                "ODDSLINK_API_KEY mangler: legg den i .env, eller under «Secrets» på Streamlit Cloud "
                "(gratis nøkkel: oddslink.app)",
                retryable=False,
            )
        now = self.clock()
        self.spent = 0
        cached = self._cached(now)
        if cached is None:
            events = self._get(
                f"/sports/{self.cfg.sport}/odds",
                markets="h2h",
                bookmakers=",".join(self.cfg.bookmakers),
                oddsFormat="decimal",
                dateFormat="iso",
                commenceTimeFrom=_rfc3339(now),
                commenceTimeTo=_rfc3339(now + timedelta(days=days_ahead)),
            )
            cached = {
                "fetched_at_utc": now.isoformat(),
                "remaining": self.remaining,
                "bookmakers": self.cfg.bookmakers,
                "events": events if events is not None else [],
            }
            self._save(cached)
            logger.info("OddsLink: %s requests left this month", self.remaining)
        self.fetched_at = datetime.fromisoformat(cached["fetched_at_utc"])
        events = cached["events"]
        if want is not None and isinstance(events, list):
            events = [e for e in events if _wanted(e, want)]
        self.competitor_odds = [
            raw
            for key in self.cfg.competitors
            for raw in parse_h2h(events, key, f"{self.name}:{key}", "OddsLink")
        ]
        return parse_h2h(events, self.cfg.bookmaker, self.name, "OddsLink")

    def _get(self, path: str, **params: Any) -> Any:
        try:
            response = self.client.get(
                self.cfg.base_url + path, params=params, headers={**self.headers, "X-API-Key": self.api_key}
            )
        except httpx.HTTPError as e:
            raise SourceError(f"OddsLink svarte ikke ({type(e).__name__})") from e
        try:
            if "x-requests-remaining" in response.headers:
                self.remaining = int(float(response.headers["x-requests-remaining"]))
            if "x-requests-last" in response.headers:
                self.spent += int(float(response.headers["x-requests-last"]))
        except ValueError:
            pass
        if response.status_code in (401, 403):
            raise SourceError(
                f"OddsLink avviste nøkkelen ({response.status_code}, sjekk ODDSLINK_API_KEY)", retryable=False
            )
        if response.status_code == 429:
            raise SourceError(
                "OddsLink: månedens forespørsler er brukt opp, eller for mange på en gang", retryable=False
            )
        if response.status_code >= 400:
            raise SourceError(f"OddsLink svarte {response.status_code} på {path}: {response.text[:200]}")
        try:
            return response.json()
        except ValueError as e:
            raise SourceError(f"OddsLink sendte ikke JSON på {path}") from e

    def _cached(self, now: datetime) -> dict[str, Any] | None:
        if not self.cache_file or not self.cache_file.exists():
            return None
        try:
            payload = json.loads(self.cache_file.read_text(encoding="utf-8"))
            age = now - datetime.fromisoformat(payload["fetched_at_utc"])
        except (OSError, ValueError, KeyError):
            return None
        fresh = timedelta(0) <= age < timedelta(minutes=self.cfg.min_interval_minutes)
        return payload if payload.get("bookmakers") == self.cfg.bookmakers and fresh else None

    def _save(self, payload: dict[str, Any]) -> None:
        if self.cache_file:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _wanted(event: dict[str, Any], want: EventFilter) -> bool:
    try:
        return bool(want(event["home_team"], event["away_team"], _commence(event)))
    except (KeyError, TypeError, ValueError):
        return True  # parse_h2h reports a malformed event


# The Odds API's keys for bookmakers OddsLink has under another key: stored under OddsLink's, so a match
# has one Unibet (the newest odds, from either) rather than two rows both called Unibet.
SAME_BOOKMAKER = {"unibet_se": "unibet", "sport888": "888sport"}


def same_bookmaker(key: str) -> str:
    return SAME_BOOKMAKER.get(key, key)


class FallbackReference:
    """A reference source with a second one for when it fails. The second one's odds are stored under the
    first one's name (both are the same bookmaker's prices), so the dashboard and the alerts carry on.

    fallback_only asks the second one straight away, e.g. when the first one lacks a bookmaker's odds."""

    def __init__(self, primary, fallback, fallback_only: bool = False):
        self.primary = primary
        self.fallback = fallback
        self.fallback_only = fallback_only
        self.name = primary.name
        self.used = primary.name  # which one answered the last fetch()
        self.fetched_at: datetime | None = None
        self.spent = 0
        self.competitor_odds: list[RawEvent] = []

    @property
    def remaining(self) -> int | None:
        """The primary's allowance left, which the watcher's reserve is about (the fallback's when only it
        is asked)."""
        return (self.fallback if self.fallback_only else self.primary).remaining

    def fetch(self, days_ahead: int, want: EventFilter | None = None) -> list[RawEvent]:
        if self.fallback_only:
            events = self.fallback.fetch(days_ahead, want)
            source = self.fallback
        else:
            try:
                events = self.primary.fetch(days_ahead, want)
                source = self.primary
            except Exception as e:  # noqa: BLE001  (any failure: the fallback has the same prices)
                logger.warning("%s failed (%s); asking %s instead", self.primary.name, e, self.fallback.name)
                events = self.fallback.fetch(days_ahead, want)
                source = self.fallback
        self.used = source.name
        self.fetched_at = getattr(source, "fetched_at", None)
        self.spent = getattr(source, "spent", 0) or 0
        prefix = f"{source.name}:"
        self.competitor_odds = [
            raw.model_copy(
                update={"source": f"{self.name}:{same_bookmaker(raw.source.removeprefix(prefix))}"}
            )
            for raw in getattr(source, "competitor_odds", None) or []
        ]
        return [raw.model_copy(update={"source": self.name}) for raw in events]


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
