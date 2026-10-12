from __future__ import annotations

import asyncio
import os
import re
import shutil
import sqlite3
import time
from contextlib import closing
from pathlib import Path

import pytest
from conftest import PHOTO, make_listing, web_login
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from fritorg import images, maintenance, ops, users
from fritorg.__main__ import main
from fritorg.app import create_app
from fritorg.config import Settings
from fritorg.db import MIGRATIONS, Database


def test_backup_copies_database_and_images_for_the_owner_only(app, client, auth, settings, tmp_path):
    listing = make_listing(client, auth)
    client.post(
        f"/api/v1/listings/{listing['id']}/images",
        files={"file": ("p.png", PHOTO, "image/png")},
        headers=auth,
    )
    folder = tmp_path / "backup"
    target = ops.backup(settings, folder)
    copy = sqlite3.connect(target)
    assert copy.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1
    assert len(list((folder / "uploads").rglob("*.webp"))) == 2  # image and thumbnail
    assert target.stat().st_mode & 0o777 == 0o600 and folder.stat().st_mode & 0o777 == 0o700
    # Without the key a stolen backup does not give away phone numbers (they are hashed with it).
    assert not (folder / "secret_key").exists()
    ops.backup(settings, folder, with_key=True)
    assert (folder / "secret_key").read_text() == app.state.secret_key

    # A photo deleted on the site goes from the backup too, and old copies are pruned.
    client.delete(f"/api/v1/listings/{listing['id']}", headers=auth)
    for _ in range(3):
        ops.backup(settings, folder, keep=2)
    assert list((folder / "uploads").rglob("*.webp")) == []
    assert len(list(folder.glob("fritorg-*.sqlite3"))) <= 2
    assert not (folder / "secret_key").exists()


def test_doctor_lists_what_is_missing(tmp_path):
    too_long = Settings(
        data_dir=tmp_path,
        sms_provider="twilio",
        twilio_account_sid="AC1",
        twilio_auth_token="t",
        twilio_from="Gratistorget",
    )
    assert any(
        "for langt" in c.text for c in ops.doctor(too_long) if c.ok is False
    )  # SMS senders: 11 at most
    checks = ops.doctor(Settings(data_dir=tmp_path, bankid_mode="simulated"))
    failed = " ".join(c.text for c in checks if c.ok is False)
    assert "https" in failed and "oidc" in failed and "moderator" in failed

    ready = Settings(
        data_dir=tmp_path,
        base_url="https://fritorg.example",
        bankid_mode="off",
        smtp_host="smtp.example",
        contact_email="post@fritorg.example",
        operator="Fritorg AS",
        secret_key="x" * 64,
    )
    texts = {c.text: c.ok for c in ops.doctor(ready)}
    assert texts["FRITORG_SECRET_KEY er satt"] is True
    assert any("smtp.example" in text for text in texts)


def test_security_headers(tmp_path):
    secure = create_app(
        Settings(
            data_dir=tmp_path,
            bankid_mode="off",
            verification="none",
            base_url="https://fritorg.example",
            contact_email="sikkerhet@fritorg.example",
        )
    )
    with TestClient(secure) as client:
        page = client.get("/")
        assert page.headers["strict-transport-security"] == "max-age=31536000"
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert page.headers["x-frame-options"] == "DENY"
        assert client.get("/static/style.css").headers["cache-control"] == "public, max-age=86400"
        security_txt = client.get("/.well-known/security.txt")
        assert "Contact: mailto:sikkerhet@fritorg.example" in security_txt.text
        assert "Drives av" not in page.text  # no operator configured


def test_no_hsts_or_security_txt_without_configuration(client):
    assert "strict-transport-security" not in client.get("/").headers
    assert client.get("/.well-known/security.txt").status_code == 404


def test_prohibited_items_go_to_review(client, auth):
    listing = make_listing(
        client,
        auth,
        category="annet",
        title="Selger hasj",
        description="Selger hasj, ta kontakt.",
        attributes={},
    )
    assert listing["status"] == "review"
    assert "prohibited_item" in {r["code"] for r in listing["moderation"]["reasons"]}


def test_the_image_trusts_forwarded_addresses_only_from_private_networks():
    """Rate limits count per address, so only the proxy in front of the app may say who the visitor is."""
    trusted = re.search(r"FORWARDED_ALLOW_IPS=(\S+)", (Path(__file__).parents[1] / "Dockerfile").read_text())

    def client_seen(peer: str, forwarded: str) -> str:
        seen = {}

        async def app(scope, receive, send):
            seen["host"] = scope["client"][0]

        scope = {
            "type": "http",
            "client": (peer, 4321),
            "headers": [(b"x-forwarded-for", forwarded.encode())],
        }
        asyncio.run(ProxyHeadersMiddleware(app, trusted_hosts=trusted.group(1))(scope, None, None))
        return seen["host"]

    assert client_seen("172.18.0.3", "203.0.113.7") == "203.0.113.7"  # Caddy on the compose network
    assert client_seen("172.18.0.3", "10.9.9.9, 203.0.113.7") == "203.0.113.7"  # the nearest untrusted
    assert client_seen("198.51.100.9", "203.0.113.7") == "198.51.100.9"  # straight to the port: ignored


def test_access_logs_leave_out_keys_and_photo_links():
    import logging

    from fritorg.app import RedactTokens

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4", "GET", "/annonse/5/bilder?t=1760000000.0123456789abcdef0123456789abcdef", "1.1", 200),
        None,
    )
    RedactTokens().filter(record)
    assert "0123456789abcdef" not in record.getMessage() and "bilder?t=***" in record.getMessage()
    from fritorg.app import redact

    assert redact("/mcp/ft_abcdefghijklmnopqrstuvwxyz0123") == "/mcp/ft_***"
    assert redact("/nytt-passord?token=abc.def&x=1") == "/nytt-passord?token=***&x=1"
    assert redact("/glemt-passord/kode?epost=kari%40example.no") == "/glemt-passord/kode?epost=***"


def test_pages_with_personal_data_are_not_cached(client, auth):
    from conftest import web_login

    assert "no-store" not in client.get("/").headers.get("cache-control", "")
    web_login(client)
    assert client.get("/min-side").headers["cache-control"] == "private, no-store"


def test_a_restore_brings_the_site_back_but_not_deleted_accounts(
    app, client, auth, other_auth, settings, tmp_path
):
    listing = make_listing(client, auth)
    client.post(
        f"/api/v1/listings/{listing['id']}/images",
        files={"file": ("p.png", PHOTO, "image/png")},
        headers=auth,
    )
    web_login(client)
    target = ops.backup(settings, tmp_path / "backup")
    # After the backup: Ola deletes the account, and the photos are lost.
    with app.state.db.session() as conn:
        users.delete_user(conn, 2)
    for file in settings.uploads_dir.rglob("*.webp"):
        file.unlink()

    restored = ops.restore(settings, target)
    assert restored.photos == 2 and restored.deleted_again == 1 and restored.safety_copy.exists()
    photo = client.get(f"/api/v1/listings/{listing['id']}").json()["images"][0]["url"]
    assert client.get(photo.removeprefix("http://testserver")).status_code == 200
    assert client.get("/api/v1/me", headers=other_auth).status_code == 401  # still deleted
    assert client.get("/min-side", follow_redirects=False).status_code == 303  # everyone logs in again
    assert ops.restore(settings, target).deleted_again == 1  # the restored database remembers it too
    # The copy of what was replaced is deleted like other backups.
    month_ago = time.time() - (maintenance.BACKUP_DAYS + 1) * 86_400
    os.utime(restored.safety_copy, (month_ago, month_ago))
    assert maintenance.remove_old_safety_copies(settings) == 1 and not restored.safety_copy.exists()


def test_only_sound_backups_are_restored(settings, tmp_path, monkeypatch, capsys):
    Database(settings.db_path).init()
    folder = tmp_path / "backup"
    target = ops.backup(settings, folder)
    junk = folder / "junk.sqlite3"
    junk.write_bytes(b"not a database" * 400)
    newer = folder / "newer.sqlite3"
    shutil.copy(target, newer)
    with closing(sqlite3.connect(newer)) as conn:
        conn.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
    old = folder / "fritorg-20200101-030000.sqlite3"
    shutil.copy(target, old)
    for source, problem in (
        (folder / "missing.sqlite3", "Fant ikke"),
        (junk, "ikke en sikkerhetskopi"),
        (newer, "nyere versjon"),
        (old, "eldre enn 60 dager"),
    ):
        with pytest.raises(ops.RestoreProblem, match=problem):
            ops.restore(settings, source)

    # A damaged database is moved aside as it is, and the backup takes its place.
    settings.db_path.write_bytes(b"\0" * 4096)
    restored = ops.restore(settings, target)
    assert restored.safety_copy.read_bytes() == b"\0" * 4096
    with Database(settings.db_path).session() as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"

    monkeypatch.setenv("FRITORG_DATA_DIR", str(settings.data_dir))
    assert main(["restore", str(target)]) == 1  # not without --yes
    assert main(["restore", str(target), "--yes"]) == 0
    assert "Alle må logge inn på nytt" in capsys.readouterr().out


def test_photos_no_listing_uses_are_cleared_out(app, client, auth, settings):
    listing = make_listing(client, auth)
    client.post(
        f"/api/v1/listings/{listing['id']}/images",
        files={"file": ("p.png", PHOTO, "image/png")},
        headers=auth,
    )
    used = sorted(settings.uploads_dir.rglob("*.webp"))
    stray = settings.uploads_dir / "ab" / ("ab" + "0" * 30 + ".webp")
    stray.parent.mkdir(exist_ok=True)
    for file in (stray, stray.with_name(stray.stem + "-t.webp")):
        file.write_bytes(b"x")
    with app.state.db.session() as conn:
        assert images.remove_unused_files(conn, settings.uploads_dir) == 0  # a new file gets a day
        day_ago = time.time() - images.UNUSED_FILE_HOURS * 3600 - 60
        for file in settings.uploads_dir.rglob("*.webp"):
            os.utime(file, (day_ago, day_ago))
        assert images.remove_unused_files(conn, settings.uploads_dir) == 2
    assert sorted(settings.uploads_dir.rglob("*.webp")) == used


def test_the_health_check_says_which_version_runs(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, verification="none", commit="5237e24"))) as client:
        assert client.get("/healthz").json() == {"status": "ok", "commit": "5237e24"}
