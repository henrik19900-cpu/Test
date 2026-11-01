"""Command line: oddscompare fetch | run --interval 15 | reference | watch | notify-test | prune --days 90."""

from __future__ import annotations

import argparse
import logging
import sys

from . import alerts, config, db, fetch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oddscompare", description="Norsk Tippings odds mot referanseodds")
    parser.add_argument(
        "--config", help="sti til config.yaml (standard: ./config.yaml eller $ODDSCOMPARE_CONFIG)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="vis hvert kall")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fetch", help="hent én runde fra Norsk Tipping")
    run = commands.add_parser("run", help="hent fra Norsk Tipping i løkke")
    run.add_argument(
        "--interval", type=float, help="minutter mellom hver runde (minst 5; standard fra config.yaml)"
    )
    commands.add_parser(
        "reference", help="hent referanseodds nå (bruker kreditter), sammen med Norsk Tipping"
    )
    watch = commands.add_parser(
        "watch",
        help="én varslingsrunde: Norsk Tipping, referanseodds for kamper som starter snart, varsel ved verdispill",
    )
    watch.add_argument(
        "--test", action="store_true", help="send også ett testvarsel for beste utfall nå, uansett terskel"
    )
    commands.add_parser("notify-test", help="send et testvarsel til ntfy-emnet i NTFY_TOPIC")
    prune = commands.add_parser("prune", help="slett kamper med odds eldre enn så mange dager etter avspark")
    prune.add_argument("--days", type=int, default=90)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(message)s"
    )
    if not args.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = config.load(args.config)

    if args.command in ("fetch", "reference"):
        report = fetch.run_once(cfg, include_reference=args.command == "reference")
        print(fetch.summary(report))
        return 0 if report.ok else 1
    if args.command in ("watch", "notify-test"):
        topic = config.api_key("NTFY_TOPIC")
        if topic:
            notify = alerts.ntfy(topic, cfg.alerts.ntfy_server, config.api_key("NTFY_TOKEN"))
        elif args.command == "notify-test":
            print("NTFY_TOPIC mangler: sett det i .env, eller som hemmelighet i GitHub.")
            return 1
        else:
            print("NTFY_TOPIC mangler: varslene skrives bare her.")

            def notify(message: dict) -> None:
                print(f"[varsel] {message['title']}\n{message['message']}")

        if args.command == "notify-test":
            try:
                notify(alerts.test_message(cfg))
            except Exception as e:  # noqa: BLE001
                print(alerts.describe_failure(e))
                return 1
            print("Testvarsel sendt. Det skal dukke opp i ntfy-appen om noen sekunder.")
            return 0
        conn = db.connect(cfg.database)
        report = alerts.watch(cfg, conn, notify, test=args.test)
        conn.close()
        print(report.summary())
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
