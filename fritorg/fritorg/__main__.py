"""Command line: `python -m fritorg serve | seed | make-admin | backup | export-user | delete-user | import-nav |
doctor | benchmark`."""

from __future__ import annotations

import argparse
import os
import sys

from .config import Settings
from .db import Database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fritorg", description="Fritorg – gratis markedsplass for mennesker og AI-agenter"
    )
    commands = parser.add_subparsers(dest="command")

    serve = commands.add_parser("serve", help="start the web server (default)")
    serve.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    serve.add_argument("--reload", action="store_true", help="reload on code changes (development)")

    seed = commands.add_parser("seed", help="fill the database with demo users and listings")
    seed.add_argument("--force", action="store_true", help="add demo data even if the database is not empty")

    admin = commands.add_parser("make-admin", help="give an existing user moderator rights")
    admin.add_argument("email")

    # For requests that arrive by e-mail, e.g. from a closed account that cannot log in (GDPR art. 15 and 17).
    export_user = commands.add_parser("export-user", help="print everything stored about an account as JSON")
    export_user.add_argument("email")
    delete_user = commands.add_parser("delete-user", help="delete an account and everything in it")
    delete_user.add_argument("email")
    delete_user.add_argument("--yes", action="store_true", help="really delete (otherwise only show what)")

    backup = commands.add_parser("backup", help="copy the database and uploaded images to a folder")
    backup.add_argument("destination")
    backup.add_argument("--keep", type=int, default=7, help="database copies to keep (default 7)")
    backup.add_argument(
        "--with-key", action="store_true", help="also copy the secret key (store such a backup encrypted)"
    )

    nav = commands.add_parser(
        "import-nav", help="import job ads from Nav's open job feed (arbeidsplassen.no)"
    )
    nav.add_argument(
        "--until-done", action="store_true", help="keep going until every current ad is imported"
    )
    nav.add_argument("--max-fetches", type=int, default=500, help="ads to fetch per run (default 500)")

    doctor = commands.add_parser("doctor", help="check that everything is ready for launch")
    doctor.add_argument("--send-test-mail", metavar="ADDRESS", help="also send a test e-mail")
    doctor.add_argument(
        "--send-test-sms", metavar="NUMBER", help="also send a test SMS to a Norwegian mobile"
    )

    bench = commands.add_parser(
        "benchmark", help="time searches on a throwaway database with made-up listings (sizing a server)"
    )
    bench.add_argument("--listings", type=int, default=100_000, help="how many listings (default 100 000)")
    bench.add_argument("--keep", metavar="FILE", help="keep the test database in this file")

    args = parser.parse_args(argv)
    if args.command == "benchmark":
        from pathlib import Path

        from .benchmark import run as run_benchmark

        print(f"Lager {args.listings} oppdiktede annonser i en egen testdatabase …")
        run_benchmark(args.listings, Path(args.keep) if args.keep else None)
        return 0
    settings = Settings.from_env()

    if args.command == "seed":
        from .seed import seed

        db = Database(settings.db_path)
        db.init()
        created = seed(db, settings, force=args.force)
        print(
            f"La til {created} demo-annonser i {settings.db_path}"
            if created
            else "Databasen har allerede data."
        )
        return 0

    if args.command == "make-admin":
        from . import users

        db = Database(settings.db_path)
        db.init()
        with db.session() as conn:
            user = users.get_user_by_email(conn, args.email)
            if user is None:
                print(f"Fant ingen bruker med e-post {args.email}", file=sys.stderr)
                return 1
            users.set_admin(conn, user.id)
        print(f"{user.name} er nå moderator.")
        return 0

    if args.command in ("export-user", "delete-user"):
        import json

        from . import images, privacy, users

        db = Database(settings.db_path)
        db.init()
        with db.session() as conn:
            user = users.get_user_by_email(conn, args.email)
            if user is None:
                print(f"Fant ingen bruker med e-post {args.email}", file=sys.stderr)
                return 1
            if args.command == "export-user":
                data = privacy.export_user(conn, user, settings.base_url or "http://127.0.0.1:8000")
                print(json.dumps(data, ensure_ascii=False, indent=2))
                return 0
            if not args.yes:
                print(
                    f"Sletter {user.name} ({user.email}) med alle annonser, bilder og meldinger: legg til --yes."
                )
                return 1
            images.remove_files(settings.uploads_dir, users.delete_user(conn, user.id))
        print(f"Kontoen til {user.name} er slettet.")
        return 0

    if args.command == "backup":
        from pathlib import Path

        from .ops import backup as run_backup

        target = run_backup(settings, Path(args.destination), keep=max(1, args.keep), with_key=args.with_key)
        print(f"Sikkerhetskopi: {target} (+ bildene i samme mappe)")
        if not args.with_key:
            print(
                "Den hemmelige nøkkelen er ikke med. Ta vare på FRITORG_SECRET_KEY et annet sted, for eksempel"
            )
            print(
                "i en passordbehandler: uten den må alle bekrefte mobilnummeret på nytt etter en gjenoppretting."
            )
        return 0

    if args.command == "import-nav":
        from . import navjobs

        db = Database(settings.db_path)
        db.init()
        while True:
            report = navjobs.sync(db, settings, max_fetches=args.max_fetches, pause=0.1)
            if report.skipped:
                print("En annen import kjører allerede. Prøv igjen senere.")
                return 1
            print(report)
            if report.done or not args.until_done:
                return 0

    if args.command == "doctor":
        from .ops import doctor as run_doctor

        checks = run_doctor(settings, test_mail_to=args.send_test_mail, test_sms_to=args.send_test_sms)
        for check in checks:
            print(check)
        failed = [c for c in checks if c.ok is False]
        print("Klar for lansering." if not failed else f"{len(failed)} ting må fikses før lansering.")
        return 1 if failed else 0

    import uvicorn

    uvicorn.run(
        "fritorg.app:create_app",
        factory=True,
        host=getattr(args, "host", "127.0.0.1"),
        port=getattr(args, "port", 8000),
        reload=getattr(args, "reload", False),
        proxy_headers=True,
        # Behind Caddy the proxy logs each request (with secrets filtered out), so the app need not too.
        access_log=os.environ.get("FRITORG_ACCESS_LOG", "1") != "0",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
