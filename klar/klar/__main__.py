"""Command line: ``python -m klar check|gloss|json [--strict] [FILE]`` (FILE or standard input)."""

from __future__ import annotations

import argparse
import json
import sys

from .gloss import features, gloss_text, to_data
from .lint import check


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="klar", description="Sjekk, forklar og analyser tekst på Klar.")
    ap.add_argument("command", choices=["check", "gloss", "json"], help="hva som skal gjøres")
    ap.add_argument("file", nargs="?", default="-", help="fil med Klar-tekst (standard: les fra stdin)")
    ap.add_argument("--strict", action="store_true", help="krev kilde (checked/so/suppose/per) for påstander")
    args = ap.parse_args(argv)

    source = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
    text, issues = check(source, strict=args.strict)

    if args.command == "check":
        for issue in issues:
            print(issue)
        errors = sum(i.level == "error" for i in issues)
        warnings = len(issues) - errors
        sentences = len(text.sentences) if text else 0
        print(f"{sentences} setninger i orden, {errors} feil, {warnings} advarsler")
        return 1 if errors else 0

    if text is None:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1
    if args.command == "gloss":
        for s, g in zip(text.sentences, gloss_text(text), strict=True):
            print(s.text)
            print("  " + g)
    else:
        data = [{"text": s.text, "features": features(s), "tree": to_data(s)} for s in text.sentences]
        print(json.dumps(data, ensure_ascii=False, indent=2))
    for issue in issues:
        print(issue, file=sys.stderr)
    return 1 if any(i.level == "error" for i in issues) else 0


if __name__ == "__main__":
    sys.exit(main())
