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
    # Shown in the footer, terms and security.txt: who runs the site and how to reach them.
    contact_email: str | None = None
    operator: str | None = None
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
    # Listings are active this many days; then they are hidden until the owner renews them (0 = never).
    listing_days: int = 60
    # Businesses that sync their inventory (PUT /api/v1/me/feeds/{feed}) may keep this many listings.
    max_synced_listings: int = 2000
    # Stricter quotas during an account's first day make throwaway scam accounts less useful.
    new_account_max_listings_per_day: int = 5
    new_account_max_messages_per_day: int = 20

    # How people are verified before they can post listings or send messages:
    # "sms" (default): email + password, plus a Norwegian mobile number confirmed by SMS code.
    #   Needs no special agreement, only an account with an SMS provider.
    # "none": no verification (local experiments and tests).
    verification: str = "sms"
    sms_provider: str = "console"  # "console" (development: the code is shown on screen), "twilio" or "http"
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from: str | None = None
    # Template for "http": e.g. https://provider.example/send?to={to}&text={message}
    sms_url: str | None = None
    sms_method: str = "GET"
    allow_console_sms: bool = False
    # Caps on SMS costs (and on abuse such as SMS pumping): codes per IP address per hour and per day in total.
    sms_per_ip_per_hour: int = 10
    sms_daily_limit: int = 2000

    # BankID (optional, needs an agreement with BankID or a broker): "oidc" (real BankID through an
    # OpenID Connect provider such as BankID, Signicat or Idura/Criipto), "simulated" (development)
    # or "off". When on, accounts are created and logged into with BankID instead.
    bankid_mode: str = "off"
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

    # Job ads from Nav's open job feed (arbeidsplassen.no). Nav's terms allow republishing; ask
    # nav.team.arbeidsplassen@nav.no for a production token (without one the public test token is used).
    nav_import: bool = False
    nav_token: str | None = None
    nav_feed_url: str = "https://pam-stilling-feed.nav.no"
    nav_import_interval: int = 120  # seconds between polls of the feed
    # Venues and facilities Stavanger kommune rents out (open data, NLOD), updated daily.
    stavanger_import: bool = False
    # Swedish job ads (Platsbanken, CC0) located in Norway or asking for Norwegian.
    jobtech_import: bool = False

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
    def phone_verification_required(self) -> bool:
        return not self.bankid_required and self.verification == "sms"

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
            contact_email=_env("CONTACT_EMAIL"),
            operator=_env("OPERATOR"),
            secure_cookies=None if secure is None else _env_bool("SECURE_COOKIES", False),
            seed_demo=_env_bool("SEED_DEMO", defaults.seed_demo),
            rate_limit_read_per_minute=_env_int("RATE_LIMIT_READ", defaults.rate_limit_read_per_minute),
            rate_limit_write_per_minute=_env_int("RATE_LIMIT_WRITE", defaults.rate_limit_write_per_minute),
            rate_limit_auth_per_10min=_env_int("RATE_LIMIT_AUTH", defaults.rate_limit_auth_per_10min),
            max_registrations_per_hour=_env_int(
                "MAX_REGISTRATIONS_PER_HOUR", defaults.max_registrations_per_hour
            ),
            max_listings_per_day=_env_int("MAX_LISTINGS_PER_DAY", defaults.max_listings_per_day),
            listing_days=_env_int("LISTING_DAYS", defaults.listing_days),
            max_synced_listings=_env_int("MAX_SYNCED_LISTINGS", defaults.max_synced_listings),
            max_messages_per_day=_env_int("MAX_MESSAGES_PER_DAY", defaults.max_messages_per_day),
            new_account_max_listings_per_day=_env_int(
                "NEW_ACCOUNT_MAX_LISTINGS_PER_DAY", defaults.new_account_max_listings_per_day
            ),
            new_account_max_messages_per_day=_env_int(
                "NEW_ACCOUNT_MAX_MESSAGES_PER_DAY", defaults.new_account_max_messages_per_day
            ),
            verification=(_env("VERIFICATION", defaults.verification) or "sms").lower(),
            sms_provider=(_env("SMS_PROVIDER", defaults.sms_provider) or "console").lower(),
            twilio_account_sid=_env("TWILIO_ACCOUNT_SID"),
            twilio_auth_token=_env("TWILIO_AUTH_TOKEN"),
            twilio_from=_env("TWILIO_FROM"),
            sms_url=_env("SMS_URL"),
            sms_method=(_env("SMS_METHOD", defaults.sms_method) or "GET").upper(),
            allow_console_sms=_env_bool("ALLOW_CONSOLE_SMS", False),
            sms_per_ip_per_hour=_env_int("SMS_PER_IP_PER_HOUR", defaults.sms_per_ip_per_hour),
            sms_daily_limit=_env_int("SMS_DAILY_LIMIT", defaults.sms_daily_limit),
            bankid_mode=(_env("BANKID", defaults.bankid_mode) or "off").lower(),
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
            nav_import=_env_bool("NAV_IMPORT", defaults.nav_import),
            nav_token=_env("NAV_TOKEN"),
            nav_feed_url=(_env("NAV_FEED_URL", defaults.nav_feed_url) or defaults.nav_feed_url).rstrip("/"),
            nav_import_interval=_env_int("NAV_IMPORT_INTERVAL", defaults.nav_import_interval),
            stavanger_import=_env_bool("STAVANGER_IMPORT", defaults.stavanger_import),
            jobtech_import=_env_bool("JOBTECH_IMPORT", defaults.jobtech_import),
            max_image_bytes=_env_int("MAX_IMAGE_BYTES", defaults.max_image_bytes),
            max_images_per_listing=_env_int("MAX_IMAGES_PER_LISTING", defaults.max_images_per_listing),
        )
