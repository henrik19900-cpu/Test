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

    # Identity: "simulated" (development: a fake BankID page), "oidc" (real BankID through an
    # OpenID Connect provider such as BankID, Signicat or Idura/Criipto) or "off" (email + password).
    bankid_mode: str = "simulated"
    bankid_issuer: str | None = None
    bankid_client_id: str | None = None
    bankid_client_secret: str | None = None
    bankid_scope: str = "openid profile"
    bankid_acr_values: str | None = None
    # Claim that identifies the person; it is only ever stored as a keyed hash.
    bankid_id_claim: str = "sub"
    allow_simulated_bankid: bool = False
    # Keys the identity hashes and signed codes. Keep it stable and secret (see README).
    secret_key: str | None = None

    # Outgoing mail (optional). Without smtp_host no mail is sent.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_security: str = "starttls"  # "starttls", "ssl" or "none"

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
    def bankid_required(self) -> bool:
        return self.bankid_mode != "off"

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
            bankid_mode=(_env("BANKID", defaults.bankid_mode) or "simulated").lower(),
            bankid_issuer=(_env("BANKID_ISSUER") or "").rstrip("/") or None,
            bankid_client_id=_env("BANKID_CLIENT_ID"),
            bankid_client_secret=_env("BANKID_CLIENT_SECRET"),
            bankid_scope=_env("BANKID_SCOPE", defaults.bankid_scope),
            bankid_acr_values=_env("BANKID_ACR_VALUES"),
            bankid_id_claim=_env("BANKID_ID_CLAIM", defaults.bankid_id_claim),
            allow_simulated_bankid=_env_bool("ALLOW_SIMULATED_BANKID", False),
            secret_key=_env("SECRET_KEY"),
            smtp_host=_env("SMTP_HOST"),
            smtp_port=_env_int("SMTP_PORT", defaults.smtp_port),
            smtp_username=_env("SMTP_USERNAME"),
            smtp_password=_env("SMTP_PASSWORD"),
            smtp_from=_env("SMTP_FROM"),
            smtp_security=(_env("SMTP_SECURITY", defaults.smtp_security) or "starttls").lower(),
            max_image_bytes=_env_int("MAX_IMAGE_BYTES", defaults.max_image_bytes),
            max_images_per_listing=_env_int("MAX_IMAGES_PER_LISTING", defaults.max_images_per_listing),
        )
