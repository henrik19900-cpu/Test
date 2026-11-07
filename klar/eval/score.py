"""Score the learnability test and write eval/RESULTS.md.

    python eval/score.py

Each round directory holds items.yaml (the test with the intended answers), prompt.txt (exactly what each
model was given), answers/<model>.json (each model's raw reply) and grading.yaml (the human grading of
meaning, with a note for everything below full marks). Whether a Klar answer is valid, and which grammatical
features it has, is decided by the parser, not by hand.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from klar import features, parse  # noqa: E402
from klar.gloss import walk  # noqa: E402
from klar.lint import check  # noqa: E402
from klar.nodes import Predicate  # noqa: E402

MODELS = ["haiku", "sonnet", "opus"]
ROUNDS = {
    "round1": "Runde 1: primeren slik den først ble skrevet",
    "round2": "Runde 2: nye setninger, primeren rettet etter feilene i runde 1",
}
LIST_KEYS = {"tenses", "modals", "adverbs", "subordinators", "complements"}


def text_features(text: str) -> dict:
    """Features of a whole Klar answer: lists merged over its sentences, flags true if any sentence has it."""
    merged: dict = {"min_predicates": 0}
    for s in parse(text).sentences:
        merged["min_predicates"] += sum(isinstance(n, Predicate) for n in walk(s))
        for key, value in features(s).items():
            if isinstance(value, list):
                merged[key] = sorted(set(merged.get(key, [])) | set(value))
            elif isinstance(value, bool):
                merged[key] = merged.get(key, False) or value
            elif value is not None and merged.get(key) is None:
                merged[key] = value
            elif key == "kind" and value == "question":
                merged[key] = value  # a text with a question in it counts as a question
    return merged


def feature_misses(answer: str, wanted: dict) -> list[str]:
    got = text_features(answer)
    misses = []
    for key, value in wanted.items():
        have = got.get(key)
        if key == "min_predicates":
            ok = (have or 0) >= value
        elif key in LIST_KEYS:
            ok = set(value) <= set(have or [])
        elif isinstance(value, list):
            ok = have in value  # one of several right answers
        else:
            ok = have == value
        if not ok:
            misses.append(f"{key}: ville ha {value}, fikk {have}")
    return misses


def score_round(name: str) -> tuple[list[tuple], list[str]]:
    folder = HERE / name
    items = yaml.safe_load((folder / "items.yaml").read_text(encoding="utf-8"))
    grading = yaml.safe_load((folder / "grading.yaml").read_text(encoding="utf-8"))
    models = [m for m in MODELS if (folder / "answers" / f"{m}.json").exists()]
    answers = {m: json.loads((folder / "answers" / f"{m}.json").read_text(encoding="utf-8")) for m in models}

    rows, out = [], []
    w = out.append
    w(f"## {ROUNDS[name]}\n")
    w(
        f"Oppgavene og fasit: [{name}/items.yaml]({name}/items.yaml). Prompt: [{name}/prompt.txt]({name}/prompt.txt).\n"
    )
    w("### Klar → engelsk (poeng satt for hånd)\n")
    w("| Oppgave | Klar | " + " | ".join(models) + " |")
    w("|---|---|" + "---|" * len(models))
    for it in items["comprehension"]:
        cells = []
        for m in models:
            g = grading["comprehension"][m][it["id"]]
            cells.append(f"{g['score']}" + (f": {g['note']}" if g.get("note") else ""))
        w(f"| {it['id']} | `{it['klar']}` | " + " | ".join(cells) + " |")
    w("")
    w("### Engelsk → Klar\n")
    w("Gyldig og trekk: sjekket av parseren. Betydning: satt for hånd.\n")
    for m in models:
        valid = feats = 0
        meaning = 0.0
        w(f"**{m}**\n")
        w("| Oppgave | Engelsk | Svar | Gyldig? | Trekk | Betydning |")
        w("|---|---|---|---|---|---|")
        for it in items["production"]:
            answer = answers[m]["B"].get(it["id"], "")
            _, issues = check(answer)
            errors = [str(i).split(": ", 2)[-1] for i in issues if i.level == "error"]
            misses = feature_misses(answer, it["check"]) if not errors else []
            graded = grading["production"][m][it["id"]]
            valid += not errors
            feats += not errors and not misses
            meaning += float(graded["score"])
            status = "ja" if not errors else "**nei**: " + "; ".join(errors)
            feat = "–" if errors else ("OK" if not misses else "; ".join(misses))
            mean = f"{graded['score']}" + (f": {graded['note']}" if graded.get("note") else "")
            w(f"| {it['id']} | {it['en']} | `{answer}` | {status} | {feat} | {mean} |")
        w("")
        a_total = sum(float(v["score"]) for v in grading["comprehension"][m].values())
        rows.append(
            (name, m, a_total, len(items["comprehension"]), valid, feats, meaning, len(items["production"]))
        )
    return rows, out


def main() -> None:
    rows, sections = [], []
    for name in ROUNDS:
        if (HERE / name / "grading.yaml").exists():
            r, s = score_round(name)
            rows += r
            sections += s
    out = [
        "# Læringstest: kan en modell lære Klar av primeren alene?\n",
        "Generert av `python eval/score.py`. Metode og vurdering står i [README.md](README.md). Hver modell fikk "
        "bare primeren og oppgavene, uten verktøy og uten tilgang til repoet. Råsvarene ligger i "
        "`round*/answers/`.\n",
        "## Oppsummering\n",
        "| Runde | Modell | Forstå Klar | Skrive gyldig Klar | Riktige grammatiske trekk | Riktig betydning |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for name, m, a_total, n_a, valid, feats, meaning, n_b in rows:
        out.append(
            f"| {name[-1]} | {m} | {a_total:g} av {n_a} | {valid} av {n_b} | {feats} av {n_b} | {meaning:g} av {n_b} |"
        )
    out.append("")
    out += sections
    (HERE / "RESULTS.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out[: 12 + len(rows)]))


if __name__ == "__main__":
    main()
