"""Runtime settings, read from FRITORG_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(f"FRITORG_{name}")
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value is not None else default


def _env_bool(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "ja", "on"}


@dataclass
class Settings:
    data_dir: Path = Path("data")
    # Public base URL, e.g. "https://fritorg.no". When unset it is derived from each request.
    base_url: str | None = None
    site_name: str = "Fritorg"
    # None = secure cookies only when base_url is https.
    secure_cookies: bool | None = None
    seed_demo: bool = False

    # Generous limits: agents are welcome, but the service must survive abuse.
    rate_limit_read_per_minute: int = 600
    rate_limit_write_per_minute: int = 60
    rate_limit_auth_per_10min: int = 30
    max_registrations_per_hour: int = 20
    max_listings_per_day: int = 50
    max_messages_per_day: int = 200
    # Stricter quotas during an account's first day make throwaway scam accounts less useful.
    new_account_max_listings_per_day: int = 5
    new_account_max_messages_per_day: int = 20

    max_image_bytes: int = 8 * 1024 * 1024
    max_images_per_listing: int = 12
    max_request_bytes: int = 64 * 1024 * 1024

    @property
    def db_path(self) -> Path:
        return self.data_dir / "fritorg.sqlite3"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def cookies_secure(self) -> bool:
        if self.secure_cookies is not None:
            return self.secure_cookies
        return bool(self.base_url and self.base_url.startswith("https://"))

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        secure = _env("SECURE_COOKIES")
        return cls(
            data_dir=Path(_env("DATA_DIR", str(defaults.data_dir))),
            base_url=(_env("BASE_URL") or "").rstrip("/") or None,
            site_name=_env("SITE_NAME", defaults.site_name),
            secure_cookies=None if secure is None else _env_bool("SECURE_COOKIES", False),
            seed_demo=_env_bool("SEED_DEMO", defaults.seed_demo),
            rate_limit_read_per_minute=_env_int("RATE_LIMIT_READ", defaults.rate_limit_read_per_minute),
            rate_limit_write_per_minute=_env_int("RATE_LIMIT_WRITE", defaults.rate_limit_write_per_minute),
            rate_limit_auth_per_10min=_env_int("RATE_LIMIT_AUTH", defaults.rate_limit_auth_per_10min),
            max_registrations_per_hour=_env_int(
                "MAX_REGISTRATIONS_PER_HOUR", defaults.max_registrations_per_hour
            ),
            max_listings_per_day=_env_int("MAX_LISTINGS_PER_DAY", defaults.max_listings_per_day),
            max_messages_per_day=_env_int("MAX_MESSAGES_PER_DAY", defaults.max_messages_per_day),
            new_account_max_listings_per_day=_env_int(
                "NEW_ACCOUNT_MAX_LISTINGS_PER_DAY", defaults.new_account_max_listings_per_day
            ),
            new_account_max_messages_per_day=_env_int(
                "NEW_ACCOUNT_MAX_MESSAGES_PER_DAY", defaults.new_account_max_messages_per_day
            ),
            max_image_bytes=_env_int("MAX_IMAGE_BYTES", defaults.max_image_bytes),
            max_images_per_listing=_env_int("MAX_IMAGES_PER_LISTING", defaults.max_images_per_listing),
        )
