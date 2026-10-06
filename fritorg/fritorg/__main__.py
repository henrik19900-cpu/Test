"""Command line: `python -m fritorg serve | seed | make-admin`."""

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

    args = parser.parse_args(argv)
    settings = Settings.from_env()

    if args.command == "seed":
        from .seed import seed

        db = Database(settings.db_path)
        db.init()
        created = seed(db, force=args.force)
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
