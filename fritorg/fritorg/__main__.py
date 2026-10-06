"""Command line: `python -m fritorg serve | seed | make-admin | backup | import-nav | doctor`."""

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

    backup = commands.add_parser(
        "backup", help="copy the database, uploaded images and secret key to a folder"
    )
    backup.add_argument("destination")

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

    args = parser.parse_args(argv)
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

    if args.command == "backup":
        from pathlib import Path

        from .ops import backup as run_backup

        target = run_backup(settings, Path(args.destination))
        print(f"Sikkerhetskopi: {target} (+ bilder og hemmelig nøkkel i samme mappe)")
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
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
