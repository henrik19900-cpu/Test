"""How much meaning survives each compressed version? Writes eval/kort/RESULTS.md.

    python eval/kort/score.py

A fresh model expanded each version back to English without seeing the original (decoded/<version>.json).
Two independent judges then graded every key fact in facts.yaml against those texts, without knowing which
version a text came from (judged/A.json, judged/B.json; the labels are in judged/labels.json). Token counts
come from bench/results.json, so run bench/run.py first.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

VERSIONS = {
    "en": "Engelsk (originalen)",
    "klar": "Klar",
    "tele": "Telegramengelsk",
    "kort": "Klar Kort",
    "kort200": "Kort-200",
}


def load_grades(facts: dict) -> dict[str, dict[str, list[float]]]:
    """Grades per version and text, checked against the number of facts."""
    labels = json.loads((HERE / "judged" / "labels.json").read_text(encoding="utf-8"))
    grades: dict[str, dict[str, list[float]]] = {}
    for judge, sets in labels.items():
        verdict = json.loads((HERE / "judged" / f"{judge}.json").read_text(encoding="utf-8"))
        for label, version in sets.items():
            per_text = verdict[label]
            for text_id, fl in facts.items():
                got = per_text.get(text_id)
                if got is None or len(got) != len(fl):
                    raise SystemExit(f"{judge}/{label}/{text_id}: ventet {len(fl)} karakterer, fikk {got}")
            grades[version] = {i: [float(g) for g in per_text[i]] for i in facts}
    return grades


def main() -> None:
    facts = yaml.safe_load((HERE / "facts.yaml").read_text(encoding="utf-8"))
    corpus = yaml.safe_load((ROOT / "bench" / "corpus.yaml").read_text(encoding="utf-8"))
    category = {e["id"]: e["category"] for e in corpus["items"] + corpus["passages"]}
    bench = json.loads((ROOT / "bench" / "results.json").read_text(encoding="utf-8"))
    names = list(bench["tokenizers"])
    ids = list(facts)

    def tokens(version: str) -> float:
        if version in ("kort", "kort200"):
            return statistics.mean(sum(bench["compressed"][i][version][n] for i in ids) for n in names)
        return statistics.mean(sum(bench["counts"][i][version][n] for i in ids) for n in names)

    grades = load_grades(facts)
    grades["en"] = {i: [1.0] * len(fl) for i, fl in facts.items()}  # the facts are written from English
    n_facts = sum(len(fl) for fl in facts.values())

    def kept(version: str, only: set[str] | None = None) -> float:
        chosen = [i for i in ids if only is None or i in only]
        total = sum(len(facts[i]) for i in chosen)
        return sum(sum(grades[version][i]) for i in chosen) / total

    out: list[str] = []
    w = out.append
    w("# Hvor mye mening overlever komprimeringen?\n")
    w(
        "Generert av `python eval/kort/score.py`. Metoden står i [README.md](README.md). "
        f"Korpuset har {len(ids)} tekster med til sammen {n_facts} nøkkelfakta "
        "([facts.yaml](facts.yaml)).\n"
    )
    w("## Resultat\n")
    w("| Versjon | Tokens (snitt, 8 tokenizere) | Fakta som overlevde | Tokens per bevart faktum |")
    w("|---|---:|---:|---:|")
    for version, title in VERSIONS.items():
        t = tokens(version)
        k = kept(version)
        w(f"| {title} | {t:.0f} | {k:.0%} | {t / (k * n_facts):.1f} |")
    w("")

    w("## Per kategori\n")
    cats = sorted(set(category.values()))
    w("| Kategori | " + " | ".join(VERSIONS[v] for v in VERSIONS if v != "en") + " |")
    w("|---|" + "---:|" * (len(VERSIONS) - 1))
    for cat in cats:
        group = {i for i in ids if category[i] == cat}
        cells = [f"{kept(v, group):.0%}" for v in VERSIONS if v != "en"]
        w(f"| {cat} | " + " | ".join(cells) + " |")
    w("")

    for version in ("kort", "kort200", "klar", "tele"):
        lost = [(i, facts[i][k], g) for i in ids for k, g in enumerate(grades[version][i]) if g < 1]
        w(f"## Det {VERSIONS[version]} mistet ({len(lost)} av {n_facts} fakta under full score)\n")
        if not lost:
            w("Ingenting.\n")
            continue
        if version == "kort200":
            per_text = {}
            for i, _, g in lost:
                per_text[i] = per_text.get(i, 0) + (1 - g)
            w("Tapt per tekst (summen av manglende poeng):\n")
            w(", ".join(f"{i} {v:g}" for i, v in sorted(per_text.items(), key=lambda kv: -kv[1])))
            w("")
            continue
        w("| Tekst | Faktum | Karakter |")
        w("|---|---|---:|")
        for i, fact, g in lost:
            w(f"| {i} | {fact} | {g:g} |")
        w("")

    (HERE / "RESULTS.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out[: 12 + len(VERSIONS)]))


if __name__ == "__main__":
    main()
