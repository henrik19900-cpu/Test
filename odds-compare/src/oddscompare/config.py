"""Settings from config.yaml, and API keys from .env (never from code or config.yaml)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, model_validator

MarginMethod = Literal["proportional", "power", "shin"]


class NorskTippingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_interval_minutes: float = Field(5, ge=5)
    navigation_cache_hours: float = Field(6, ge=0)
    countries: list[str] = []
    base_url: str = "https://www.norsk-tipping.no/sport/oddsen/sportsbook/services"
    websocket_url: str = "wss://velnt-opr1.sport2.norsk-tipping.no/notification/listen"
    timeout_seconds: float = Field(25, gt=0)


class TheOddsApiConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = "https://api.the-odds-api.com/v4"
    bookmaker: str = "pinnacle"
    # Every league Norsk Tipping has that The Odds API covers. Each costs a credit per request, only when
    # it has matches Norsk Tipping has too; the dashboard lets you pick fewer for a request.
    leagues: list[str] = [
        "soccer_norway_eliteserien",
        "soccer_epl",
        "soccer_efl_champ",
        "soccer_england_league1",
        "soccer_england_league2",
        "soccer_uefa_champs_league",
        "soccer_uefa_europa_league",
        "soccer_uefa_europa_conference_league",
        "soccer_spain_la_liga",
        "soccer_spain_segunda_division",
        "soccer_italy_serie_a",
        "soccer_italy_serie_b",
        "soccer_germany_bundesliga",
        "soccer_germany_bundesliga2",
        "soccer_germany_liga3",
        "soccer_france_ligue_one",
        "soccer_france_ligue_two",
        "soccer_netherlands_eredivisie",
        "soccer_sweden_allsvenskan",
        "soccer_sweden_superettan",
        "soccer_denmark_superliga",
    ]
    # Norsk Tipping's competitors, fetched with the reference at no extra cost: up to 10 bookmakers
    # in one request count as one. Keys from https://the-odds-api.com/sports-odds-data/bookmaker-apis.html
    competitors: list[str] = [
        "unibet_se",
        "betsson",
        "nordicbet",
        "coolbet",
        "leovegas_se",
        "sport888",
        "betway",
    ]
    # Fetched only when asked for. A second request within this many minutes reuses the first answer,
    # so a double click does not spend credits twice.
    min_interval_minutes: float = Field(5, ge=0)
    timeout_seconds: float = Field(20, gt=0)

    @model_validator(mode="after")
    def _one_credit_per_league(self) -> TheOddsApiConfig:
        if len(self.bookmakers) > 10:
            raise ValueError(
                "høyst 9 konkurrenter ved siden av referansen: 11 bookmakere eller flere koster 2 kreditter per liga"
            )
        return self

    @property
    def bookmakers(self) -> list[str]:
        """The reference first, then the competitors, each once."""
        return list(dict.fromkeys([self.bookmaker, *self.competitors]))


class OddsLinkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = "https://oddslink.app/v1"
    bookmaker: str = "pinnacle"
    # Norsk Tipping's competitors that OddsLink has (it has no Betsson, NordicBet, Coolbet or LeoVegas).
    # Every bookmaker comes in the same request, which counts once. Keys from
    # https://oddslink.app/docs/reference/bookmaker-keys/
    competitors: list[str] = [
        "unibet",
        "888sport",
        "betway",
        "bet365",
        "bwin",
        "betano",
        "williamhill",
        "betfair",
    ]
    sport: str = "soccer"  # every soccer league in one request
    fallback: Literal["the_odds_api"] | None = "the_odds_api"  # asked instead when OddsLink fails
    # A second request within this many minutes reuses the first answer (a double click costs nothing).
    min_interval_minutes: float = Field(5, ge=0)
    timeout_seconds: float = Field(90, gt=0)  # the first call for every league can take tens of seconds

    @property
    def bookmakers(self) -> list[str]:
        """The reference first, then the competitors, each once."""
        return list(dict.fromkeys([self.bookmaker, *self.competitors]))


class OddsApiIoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = "https://api.odds-api.io/v3"
    bookmaker: str = "Betfair Exchange"
    leagues: list[str] = []
    timeout_seconds: float = Field(20, gt=0)


class ReferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["oddslink", "the_odds_api", "odds_api_io"] = "the_odds_api"
    oddslink: OddsLinkConfig = OddsLinkConfig()
    the_odds_api: TheOddsApiConfig = TheOddsApiConfig()
    odds_api_io: OddsApiIoConfig = OddsApiIoConfig()

    @property
    def bookmaker(self) -> str:
        return getattr(self, self.source).bookmaker


class AlertsConfig(BaseModel):
    """oddscompare watch: when to buy reference odds, and what is worth a notification."""

    model_config = ConfigDict(extra="forbid")

    min_ev: float = 0.02  # an outcome needs at least this EV against the reference
    max_reference_margin: float = 0.06  # and the reference's own margin at most this
    lead_minutes: float = Field(75, gt=0)  # reference odds are bought for matches starting within this
    # and once before that, this long before kick-off (0: no early check), while the day has spent less than
    # early_credit_share of max_credits_per_day, so the late check, the more precise one, always has credits
    early_lead_minutes: float = Field(180, ge=0)
    early_credit_share: float = Field(0.5, ge=0, le=1)
    # With OddsLink, one request covers every match: each purchase is for all of them, and they are checked at
    # least this often (0: only when a match is due), within early_credit_share of the day's credits
    scan_minutes: float = Field(120, ge=0)
    nt_jump: float = Field(0.05, gt=0)  # or when Norsk Tipping raises an outcome by this since the last check
    fresh_minutes: float = Field(30, gt=0)  # alerts only on reference odds at most this old
    max_credits_per_day: int = Field(20, ge=0)
    reserve_credits: int = Field(30, ge=0)  # never spend the month's last credits
    ntfy_server: str = "https://ntfy.sh"
    app_url: str = ""  # opened when the notification is tapped, e.g. the Streamlit app
    keep_days: int = Field(7, ge=1)  # how long the watcher keeps finished matches
    days_ahead: int = Field(
        2, ge=1, le=14
    )  # how far ahead the watcher reads Norsk Tipping (keeps its database small)


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_ahead: int = Field(7, ge=1, le=14)
    interval_minutes: float = Field(15, ge=5)  # never more often than every 5 minutes
    margin_method: MarginMethod = "proportional"
    match_window_minutes: float = Field(30, gt=0)
    fuzzy_accept: float = Field(90, ge=0, le=100)
    fuzzy_suggest: float = Field(80, ge=0, le=100)
    stale_after_minutes: float = Field(30, gt=0)
    # Betfair's commission on net winnings: its odds are shown, compared and used for sure bets after it.
    exchange_commission: float = Field(0.05, ge=0, lt=1)
    user_agent: str = "odds-compare/0.1 (personlig analyseverktoy)"
    database: Path = Path("data/odds.db")
    aliases: Path = Path("data/team_aliases.yaml")
    cache_dir: Path = Path("data/cache")
    norsk_tipping: NorskTippingConfig = NorskTippingConfig()
    reference: ReferenceConfig = ReferenceConfig()
    alerts: AlertsConfig = AlertsConfig()

    def resolve(self, root: Path) -> Config:
        """The same settings with relative paths taken from root (the folder of config.yaml)."""
        return self.model_copy(
            update={name: root / getattr(self, name) for name in ("database", "aliases", "cache_dir")}
        )


def load(path: str | Path | None = None) -> Config:
    """Read config.yaml (or $ODDSCOMPARE_CONFIG) and the .env next to it."""
    path = Path(path or os.environ.get("ODDSCOMPARE_CONFIG", "config.yaml")).resolve()
    load_dotenv(path.parent / ".env")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    return Config.model_validate(data or {}).resolve(path.parent)


SECRET_NAMES = (
    "ODDSLINK_API_KEY",
    "THE_ODDS_API_KEY",
    "ODDS_API_IO_KEY",
    "NTFY_TOPIC",
    "NTFY_TOKEN",
    "DATABASE_URL",
)


def apply_secrets(secrets: Mapping) -> None:
    """Keys from Streamlit's secrets into the environment, where the rest of the code reads them.

    A key under a heading such as [secrets] counts too; one at the top level, or already in the
    environment (.env), wins."""
    found = {}
    for value in secrets.values():
        if isinstance(value, Mapping):
            found.update(value)
    found.update({k: v for k, v in secrets.items() if not isinstance(v, Mapping)})
    for name in SECRET_NAMES:
        value = str(found.get(name) or "").strip()
        if value and not os.environ.get(name):
            os.environ[name] = value


def api_key(name: str) -> str | None:
    """A key or secret from the environment, without the spaces and line breaks a copy often brings along."""
    return (os.environ.get(name) or "").strip() or None
