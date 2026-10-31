"""Settings from config.yaml, and API keys from .env (never from code or config.yaml)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

MarginMethod = Literal["proportional", "power", "shin"]


class NorskTippingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_interval_minutes: float = Field(5, ge=5)
    navigation_cache_hours: float = Field(6, ge=0)
    countries: list[str] = []
    base_url: str = "https://www.norsk-tipping.no/sport/oddsen/sportsbook/services"
    websocket_url: str = "wss://velnt-opr1.sport2.norsk-tipping.no/notification/listen"
    timeout_seconds: float = Field(25, gt=0)


class OddsApiIoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = "https://api.odds-api.io/v3"
    bookmaker: str = "Betfair Exchange"
    leagues: list[str] = []
    timeout_seconds: float = Field(20, gt=0)


class ReferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["odds_api_io"] = "odds_api_io"
    odds_api_io: OddsApiIoConfig = OddsApiIoConfig()


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_ahead: int = Field(7, ge=1, le=14)
    interval_minutes: float = Field(15, ge=5)  # never more often than every 5 minutes
    margin_method: MarginMethod = "proportional"
    match_window_minutes: float = Field(30, gt=0)
    fuzzy_accept: float = Field(90, ge=0, le=100)
    fuzzy_suggest: float = Field(80, ge=0, le=100)
    stale_after_minutes: float = Field(30, gt=0)
    user_agent: str = "odds-compare/0.1 (personlig analyseverktoy)"
    database: Path = Path("data/odds.db")
    aliases: Path = Path("data/team_aliases.yaml")
    cache_dir: Path = Path("data/cache")
    norsk_tipping: NorskTippingConfig = NorskTippingConfig()
    reference: ReferenceConfig = ReferenceConfig()

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


def api_key(name: str) -> str | None:
    return os.environ.get(name) or None
