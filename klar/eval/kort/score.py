"""How much meaning survives each compressed version? Writes eval/kort/RESULTS.md.

    python eval/kort/score.py

A fresh model expanded each version back to English without seeing the original (decoded/<version>.json).
Independent judges (A-D, two versions each) then graded every key fact in facts.yaml against those texts,
without knowing which version a text came from (judged/<judge>.json; the labels are in judged/labels.json).
Token counts come from bench/results.json, so run bench/run.py first.
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
    "kort_v1": "Klar Kort, versjon 1",
    "kort": "Klar Kort, versjon 2",
    "kort_v3": "Klar Kort, versjon 3",
    "kort500": "Kort-500",
    "kort200": "Kort-200",
}
COMPRESSED = ("kort", "kort_v1", "kort_v3", "kort500", "kort200")  # counted in bench/kort.yaml
BUDGET = 499  # "under 500" in every tokenizer


def pct(x: float) -> str:
    return f"{x * 100:.0f} %"


def dec(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def load_grades(facts: dict) -> tuple[dict[str, dict[str, list[float]]], dict[str, list[tuple[str, float]]]]:
    """Grades per version and text, checked against the number of facts.

    A version graded by more than one judge keeps the last judge's grades (judges are run in order A, B, C, D,
    so the last one saw the comparison that matters most); every judge's share is returned for the report.
    """
    labels = json.loads((HERE / "judged" / "labels.json").read_text(encoding="utf-8"))
    grades: dict[str, dict[str, list[float]]] = {}
    shares: dict[str, list[tuple[str, float]]] = {}
    n_facts = sum(len(fl) for fl in facts.values())
    for judge, sets in labels.items():
        path = HERE / "judged" / f"{judge}.json"
        if not path.exists():
            continue
        verdict = json.loads(path.read_text(encoding="utf-8"))
        for label, version in sets.items():
            per_text = verdict[label]
            for text_id, fl in facts.items():
                got = per_text.get(text_id)
                if got is None or len(got) != len(fl):
                    raise SystemExit(f"{judge}/{label}/{text_id}: ventet {len(fl)} karakterer, fikk {got}")
            grades[version] = {i: [float(g) for g in per_text[i]] for i in facts}
            shares.setdefault(version, []).append((judge, sum(map(sum, grades[version].values())) / n_facts))
    return grades, shares


def best_mix(
    grades: dict, bench: dict, ids: list[str], budget: int
) -> tuple[float, list[str], dict[str, int]]:
    """The measured version of each text that keeps the most facts with every tokenizer within the budget.

    Dynamic programming over the token count of the most expensive tokenizer, checked against all of them.
    """
    options = [
        v for v in ("kort_v3", "kort500", "kort200", "kort", "kort_v1") if v in grades
    ]  # ties go to the first
    names = list(bench["tokenizers"])
    worst = max(names, key=lambda n: sum(bench["compressed"][i]["kort_v3"][n] for i in ids))
    best: dict[int, tuple[float, list[str]]] = {0: (0.0, [])}
    for i in ids:
        nxt: dict[int, tuple[float, list[str]]] = {}
        for used, (kept, picks) in best.items():
            for v in options:
                t = used + bench["compressed"][i][v][worst]
                k = kept + sum(grades[v][i])
                if t <= budget and (t not in nxt or nxt[t][0] < k):
                    nxt[t] = (k, picks + [v])
        best = nxt
    _, (kept, picks) = max(best.items(), key=lambda tk: (tk[1][0], -tk[0]))  # most facts, then fewest tokens
    totals = {n: sum(bench["compressed"][i][v][n] for i, v in zip(ids, picks, strict=True)) for n in names}
    assert max(totals.values()) <= budget, totals
    return kept, picks, totals


def main() -> None:
    facts = yaml.safe_load((HERE / "facts.yaml").read_text(encoding="utf-8"))
    corpus = yaml.safe_load((ROOT / "bench" / "corpus.yaml").read_text(encoding="utf-8"))
    category = {e["id"]: e["category"] for e in corpus["items"] + corpus["passages"]}
    bench = json.loads((ROOT / "bench" / "results.json").read_text(encoding="utf-8"))
    names = list(bench["tokenizers"])
    ids = list(facts)

    def tokens(version: str) -> float:
        table = bench["compressed"] if version in COMPRESSED else bench["counts"]
        return statistics.mean(sum(table[i][version][n] for i in ids) for n in names)

    grades, shares = load_grades(facts)
    grades["en"] = {i: [1.0] * len(fl) for i, fl in facts.items()}  # the facts are written from English
    versions = {v: t for v, t in VERSIONS.items() if v in grades}
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
    for version, title in versions.items():
        t = tokens(version)
        k = kept(version)
        w(f"| {title} | {t:.0f} | {pct(k)} | {dec(t / (k * n_facts))} |")
    w("")

    w("## Per kategori\n")
    cats = sorted(set(category.values()))
    w("| Kategori | " + " | ".join(versions[v] for v in versions if v != "en") + " |")
    w("|---|" + "---:|" * (len(versions) - 1))
    for cat in cats:
        group = {i for i in ids if category[i] == cat}
        cells = [pct(kept(v, group)) for v in versions if v != "en"]
        w(f"| {cat} | " + " | ".join(cells) + " |")
    w("")

    twice = {v: s for v, s in shares.items() if len(s) > 1}
    if twice:
        w("## Samme tekst, to dommere\n")
        w(
            "En versjon som ble vurdert av to uavhengige dommere, viser hvor mye karakteren varierer mellom dommere:\n"
        )
        for version, judged in twice.items():
            w(f"- {VERSIONS[version]}: " + ", ".join(f"dommer {j} {pct(share)}" for j, share in judged))
        w("")

    if "kort_v3" in grades:
        mix_kept, picks, totals = best_mix(grades, bench, ids, BUDGET)
        w(f"## Beste blanding under {BUDGET + 1} tokens\n")
        w(
            "Hvis man for hver tekst velger den målte versjonen som gir flest fakta, slik at summen holder seg under "
            f"{BUDGET + 1} tokens i alle åtte tokenizerne, beholdes {pct(mix_kept / n_facts)} av fakta med "
            f"{statistics.mean(totals.values()):.0f} tokens i snitt (høyst {max(totals.values())}). Det er et "
            "optimistisk anslag, fordi valget er gjort med de samme karakterene som det måles med. Det viser likevel "
            "at Kort-500 kan fordele tokenene bedre: fulle tekster der fakta er billige, korte der de er dyre.\n"
        )
        chosen = sorted({v: picks.count(v) for v in set(picks)}.items(), key=lambda vc: -vc[1])
        w(
            "Valgt: "
            + "; ".join(f"{n} {'tekst' if n == 1 else 'tekster'} fra {VERSIONS[v]}" for v, n in chosen)
            + ".\n"
        )

    for version in [
        v for v in ("kort_v3", "kort", "kort500", "kort_v1", "kort200", "klar", "tele") if v in grades
    ]:
        lost = [(i, facts[i][k], g) for i in ids for k, g in enumerate(grades[version][i]) if g < 1]
        w(f"## Det {VERSIONS[version]} mistet ({len(lost)} av {n_facts} fakta under full score)\n")
        if not lost:
            w("Ingenting.\n")
            continue
        if version in ("kort200", "kort500"):
            per_text = {}
            for i, _, g in lost:
                per_text[i] = per_text.get(i, 0) + (1 - g)
            w("Tapt per tekst (summen av manglende poeng):\n")
            w(
                ", ".join(
                    f"{i} {v:g}".replace(".", ",") for i, v in sorted(per_text.items(), key=lambda kv: -kv[1])
                )
            )
            w("")
            continue
        w("| Tekst | Faktum | Karakter |")
        w("|---|---|---:|")
        for i, fact, g in lost:
            w(f"| {i} | {fact} | {g:g} |".replace("0.5", "0,5"))
        w("")

    (HERE / "RESULTS.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out[: 12 + len(versions)]))


if __name__ == "__main__":
    main()
