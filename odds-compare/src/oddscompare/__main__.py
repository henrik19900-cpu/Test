"""Command line: oddscompare fetch | run --interval 15 | prune --days 90."""

from __future__ import annotations

import argparse
import logging
import sys

from . import config, db, fetch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oddscompare", description="Norsk Tippings odds mot referanseodds")
    parser.add_argument(
        "--config", help="sti til config.yaml (standard: ./config.yaml eller $ODDSCOMPARE_CONFIG)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="vis hvert kall")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fetch", help="hent én runde fra alle kilder")
    run = commands.add_parser("run", help="hent i løkke")
    run.add_argument(
        "--interval", type=float, help="minutter mellom hver runde (minst 5; standard fra config.yaml)"
    )
    prune = commands.add_parser("prune", help="slett kamper med odds eldre enn så mange dager etter avspark")
    prune.add_argument("--days", type=int, default=90)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(message)s"
    )
    if not args.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = config.load(args.config)

    if args.command == "fetch":
        report = fetch.run_once(cfg)
        print(fetch.summary(report))
        return 0 if report.ok else 1
    if args.command == "run":
        interval = args.interval or cfg.interval_minutes
        if interval < 5:
            parser.error("henting oftere enn hvert 5. minutt er utenfor omfang")
        try:
            fetch.run_forever(cfg, interval)
        except KeyboardInterrupt:
            return 0
    if args.command == "prune":
        conn = db.connect(cfg.database)
        print(f"Slettet {db.prune(conn, args.days)} kamper.")
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
