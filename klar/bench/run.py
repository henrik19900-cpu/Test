"""Count tokens for every text in the corpus, in every tokenizer, and write bench/RESULTS.md.

    pip install -e ".[bench]"
    python bench/run.py

The first run downloads the tokenizers (about 60 MB). Every number in RESULTS.md comes from this script.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from counters import TOKENIZERS, load, marginal  # noqa: E402  (bench/counters.py)

from klar import lexicon, parse, tokenize  # noqa: E402

VARIANTS = {"en": "Engelsk", "tele": "Telegramengelsk", "nb": "Norsk", "klar": "Klar"}
CATEGORIES = {
    "instruks": "Instrukser til en AI",
    "rapport": "Rapporter fra agenter",
    "resonnement": "Resonnement",
    "fakta": "Fakta",
    "dialog": "Spørsmål og svar",
}
# Symbols that "AI languages" often use, next to the Klar word for the same thing.
SYMBOLS = [
    ("∀", "all"),
    ("∃", "some"),
    ("¬", "not"),
    ("∧", "and"),
    ("∨", "or"),
    ("⊕", "xor"),
    ("→", "if"),
    ("⇔", "iff"),
    ("∴", "so"),
    ("≈", "approx"),
    ("✓", "checked"),
    ("❓", "maybe"),
    ("🔒", "must"),
]
PRIMERS = {
    "en": ROOT / "docs" / "primer.en.md",
    "no": ROOT / "docs" / "primer.no.md",
    "kort": ROOT / "docs" / "kort.en.md",
}
CONSONANTS = "ptkmnslvbdgfj"
VOWELS = "aeiou"


def invented(word: str) -> str:
    """A made-up word for an English one, the way a language with its own vocabulary (Esperanto, Toki Pona)
    would have it: syllables of consonant + vowel, more of them for longer words. Deterministic."""
    digest = hashlib.sha256(word.encode()).digest()
    syllables = max(2, min(4, (len(word) + 2) // 3))
    return "".join(
        CONSONANTS[digest[2 * i] % len(CONSONANTS)] + VOWELS[digest[2 * i + 1] % 5] for i in range(syllables)
    )


def content_words(text: str) -> str:
    """Only the content words, names, numbers and code of a Klar text: what is left with no grammar at all."""
    kinds = ("NAME", "NUM", "IDENT", "CODE", "STR", "LABEL")
    words = [
        t.text
        for t in tokenize(text)
        if t.kind in kinds or (t.kind == "WORD" and t.text not in lexicon.ALL_FORMS)
    ]
    return " ".join(words)


def with_invented_words(text: str) -> str:
    """The same Klar text with every English content word swapped for an invented word. Grammar words, names,
    numbers, labels and code stay as they are."""
    out, last = [], 0
    for tok in tokenize(text):
        if tok.kind == "WORD" and tok.text not in lexicon.ALL_FORMS:
            out.append(text[last : tok.start] + invented(tok.text))
            last = tok.end
    out.append(text[last:])
    return "".join(out)


def main() -> None:
    corpus = yaml.safe_load((HERE / "corpus.yaml").read_text(encoding="utf-8"))
    entries = corpus["items"] + corpus["passages"]
    for entry in entries:
        result = parse(entry["klar"])
        if result.errors:
            raise SystemExit(f"{entry['id']}: Klar-teksten er ugyldig: {result.errors[0]}")

    counters = load()
    names = list(counters)
    counts = {e["id"]: {v: {n: counters[n](e[v].strip()) for n in names} for v in VARIANTS} for e in entries}
    chars = {e["id"]: {v: len(e[v].strip()) for v in VARIANTS} for e in entries}

    particles = sorted(lexicon.ALL_FORMS) + sorted(lexicon.LABEL_LETTERS)
    particle_cost = {p: {n: marginal(counters[n], p) for n in names} for p in particles}
    symbol_cost = {
        f"{sym} / {word}": {
            "symbol": statistics.mean(marginal(counters[n], sym) for n in names),
            "word": statistics.mean(marginal(counters[n], word) for n in names),
        }
        for sym, word in SYMBOLS
    }
    apriori = {
        e["id"]: {n: counters[n](with_invented_words(e["klar"].strip())) for n in names} for e in entries
    }
    kort = yaml.safe_load((HERE / "kort.yaml").read_text(encoding="utf-8"))
    compressed = {
        e["id"]: {
            "kort": {n: counters[n](kort[e["id"]]["kort"].strip()) for n in names},
            "kort_v1": {
                n: counters[n](kort[e["id"]].get("kort_v1", kort[e["id"]]["kort"]).strip()) for n in names
            },
            "kort200": {n: counters[n](kort[e["id"]]["kort200"].strip()) for n in names},
            "content": {n: counters[n](content_words(e["klar"])) for n in names},
        }
        for e in entries
    }
    primer_cost = {
        lang: {n: counters[n](path.read_text(encoding="utf-8")) for n in names}
        for lang, path in PRIMERS.items()
        if path.exists()
    }

    data = {
        "tokenizers": {n: TOKENIZERS[n][0] for n in names},
        "counts": counts,
        "chars": chars,
        "particles": particle_cost,
        "symbols": symbol_cost,
        "apriori": apriori,
        "compressed": compressed,
        "apriori_example": with_invented_words(entries[0]["klar"]),
        "primer": primer_cost,
    }
    (HERE / "results.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "RESULTS.md").write_text(report(corpus, data), encoding="utf-8")
    print((HERE / "RESULTS.md").read_text(encoding="utf-8"))


def pct(a: float, b: float) -> str:
    """How much smaller a is than b, as a signed percentage: -31 % means a is 31 % smaller."""
    return f"{(a / b - 1) * 100:+.0f} %".replace("-", "−")


def report(corpus: dict, data: dict) -> str:
    names = list(data["tokenizers"])
    counts = data["counts"]
    items = corpus["items"]
    passages = corpus["passages"]
    everything = items + passages
    out: list[str] = []
    w = out.append

    def total(ids: list[str], variant: str, name: str) -> int:
        return sum(counts[i][variant][name] for i in ids)

    def mean_total(ids: list[str], variant: str) -> float:
        return statistics.mean(total(ids, variant, n) for n in names)

    all_ids = [e["id"] for e in everything]
    w("# Målinger: hvor mange tokens koster det samme innholdet?\n")
    w(
        "Generert av `python bench/run.py` fra `bench/corpus.yaml`: "
        f"{len(items)} setninger og {len(passages)} lengre tekster, hver skrevet på engelsk, "
        "telegramengelsk, norsk og Klar med samme informasjon. Tallene er tokens slik hver modells egen "
        "tokenizer teller dem.\n"
    )

    w("## Hovedresultat (alle tekster)\n")
    w("| Tokenizer | Engelsk | Telegramengelsk | Norsk | Klar | Klar mot engelsk | Klar mot norsk |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for n in names:
        t = {v: total(all_ids, v, n) for v in VARIANTS}
        label = data["tokenizers"][n]
        w(
            f"| {label} (`{n}`) | {t['en']} | {t['tele']} | {t['nb']} | {t['klar']} "
            f"| {pct(t['klar'], t['en'])} | {pct(t['klar'], t['nb'])} |"
        )
    m = {v: mean_total(all_ids, v) for v in VARIANTS}
    w(
        f"| **Snitt** | **{m['en']:.0f}** | **{m['tele']:.0f}** | **{m['nb']:.0f}** | **{m['klar']:.0f}** "
        f"| **{pct(m['klar'], m['en'])}** | **{pct(m['klar'], m['nb'])}** |"
    )
    ch = {v: sum(data["chars"][i][v] for i in all_ids) for v in VARIANTS}
    w(
        f"\nTegn (ikke tokens): engelsk {ch['en']}, telegramengelsk {ch['tele']}, norsk {ch['nb']}, "
        f"Klar {ch['klar']} ({pct(ch['klar'], ch['en'])} mot engelsk).\n"
    )

    w("## Per kategori (snitt over de åtte tokenizerne)\n")
    w("| Kategori | Engelsk | Telegramengelsk | Norsk | Klar | Klar mot engelsk | Klar mot telegram |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for cat, title in CATEGORIES.items():
        ids = [e["id"] for e in everything if e["category"] == cat]
        cm = {v: mean_total(ids, v) for v in VARIANTS}
        w(
            f"| {title} ({len(ids)}) | {cm['en']:.0f} | {cm['tele']:.0f} | {cm['nb']:.0f} | {cm['klar']:.0f} "
            f"| {pct(cm['klar'], cm['en'])} | {pct(cm['klar'], cm['tele'])} |"
        )
    pids = [p["id"] for p in passages]
    pm = {v: mean_total(pids, v) for v in VARIANTS}
    w(
        f"| *Bare de {len(pids)} lengre tekstene* | {pm['en']:.0f} | {pm['tele']:.0f} | {pm['nb']:.0f} "
        f"| {pm['klar']:.0f} | {pct(pm['klar'], pm['en'])} | {pct(pm['klar'], pm['tele'])} |"
    )

    ratios = [statistics.mean(counts[i]["klar"][n] / counts[i]["en"][n] for n in names) for i in all_ids]
    better = sum(r < 1 for r in ratios)
    w(
        f"\nKlar er kortere enn engelsk i {better} av {len(all_ids)} tekster. Median for Klar/engelsk per "
        f"tekst: {statistics.median(ratios):.2f}; spredning fra {min(ratios):.2f} til {max(ratios):.2f}.\n"
    )

    w("## Hver tekst (snitt over tokenizerne)\n")
    w("| Tekst | Engelsk | Telegram | Norsk | Klar | Klar mot engelsk |")
    w("|---|---:|---:|---:|---:|---:|")
    for e in everything:
        c = {v: statistics.mean(counts[e["id"]][v][n] for n in names) for v in VARIANTS}
        w(
            f"| {e['id']} | {c['en']:.1f} | {c['tele']:.1f} | {c['nb']:.1f} | {c['klar']:.1f} "
            f"| {pct(c['klar'], c['en'])} |"
        )

    w("\n## Grammatikkordene: ett token hver?\n")
    particles = data["particles"]
    single = [p for p, c in particles.items() if all(v == 1 for v in c.values())]
    w(
        f"{len(single)} av {len(particles)} grammatikkord og etiketter koster nøyaktig ett token (med "
        "mellomrom foran) i alle åtte tokenizerne."
    )
    others = {p: c for p, c in particles.items() if p not in single}
    if others:
        w("Unntak:\n")
        for p, c in others.items():
            costs = ", ".join(f"{n}: {v}" for n, v in c.items() if v != 1)
            w(f"- `{p}` ({costs})")
    w("")

    w("## Symboler mot ord\n")
    w("Mange «AI-språk» bruker logiske symboler og emoji. De ser korte ut, men koster mer:\n")
    w("| Symbol / Klar-ord | Tokens for symbolet | Tokens for ordet |")
    w("|---|---:|---:|")
    for key, c in data["symbols"].items():
        w(f"| {key} | {c['symbol']:.2f} | {c['word']:.2f} |")
    w("")

    w("## Hvorfor ikke helt nye ord?\n")
    w(
        "Et språk med eget ordforråd (som esperanto eller toki pona) måtte bytte ut de engelske innholdsordene. "
        "For å måle hva det ville koste, er hvert innholdsord i Klar-tekstene byttet mot et oppdiktet ord med "
        "samme lengde i stavelser, mens grammatikken er den samme. Eksempel: "
        f"`{corpus['items'][0]['klar']}` blir `{data['apriori_example']}`.\n"
    )
    w("| Tokenizer | Klar | Klar med oppdiktede ord | Forskjell |")
    w("|---|---:|---:|---:|")
    for n in names:
        k = total(all_ids, "klar", n)
        a = sum(data["apriori"][i][n] for i in all_ids)
        w(f"| {data['tokenizers'][n]} | {k} | {a} | {pct(a, k)} |")
    w(
        "\nOrdene modellen allerede kjenner, er de billigste den har. Nye ord koster flere tokens, og modellen "
        "må i tillegg lære hva de betyr.\n"
    )

    w("## Klar Kort: så få tokens som mulig\n")
    w(
        "[Klar Kort](../docs/kort.en.md) dropper alt leseren kan gjette seg til, men beholder hvert faktum. "
        "Kort-200 er hele korpuset presset ned til maks 200 tokens, og der overlever bare hovedpoenget i hver "
        "tekst. «Bare innholdsord» er innholdsordene i Klar-tekstene uten et eneste grammatikkord, ikke engang "
        "«not». Det er omtrent gulvet for hva samme innhold kan koste i tokens. Hvor mange av fakta som "
        "overlever i hver versjon, står i [eval/kort/RESULTS.md](../eval/kort/RESULTS.md).\n"
    )
    w("| Tokenizer | Engelsk | Klar | Telegramengelsk | Klar Kort | Kort-200 | Bare innholdsord |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    comp = data["compressed"]
    for n in names:
        k = sum(comp[i]["kort"][n] for i in all_ids)
        k2 = sum(comp[i]["kort200"][n] for i in all_ids)
        cw = sum(comp[i]["content"][n] for i in all_ids)
        w(
            f"| {data['tokenizers'][n]} | {total(all_ids, 'en', n)} | {total(all_ids, 'klar', n)} "
            f"| {total(all_ids, 'tele', n)} | {k} | {k2} | {cw} |"
        )
    mk = statistics.mean(sum(comp[i]["kort"][n] for i in all_ids) for n in names)
    mk2 = statistics.mean(sum(comp[i]["kort200"][n] for i in all_ids) for n in names)
    mcw = statistics.mean(sum(comp[i]["content"][n] for i in all_ids) for n in names)
    w(
        f"| **Snitt** | **{m['en']:.0f}** | **{m['klar']:.0f}** | **{m['tele']:.0f}** | **{mk:.0f}** "
        f"| **{mk2:.0f}** | **{mcw:.0f}** |"
    )
    w(
        f"\nKlar Kort er {pct(mk, m['en'])} mot engelsk, {pct(mk, m['klar'])} mot Klar og {pct(mk, m['tele'])} "
        f"mot telegramengelsk. Kort-200 er {pct(mk2, m['en'])} mot engelsk.\n"
    )

    if data["primer"]:
        w("## Primeren: hva det koster å lære en modell Klar\n")
        rate = 1 - m["klar"] / m["en"]
        labels = {"en": "Klar, engelsk", "no": "Klar, norsk", "kort": "Klar Kort"}
        files = {"en": "primer.en.md", "no": "primer.no.md", "kort": "kort.en.md"}
        for lang, c in data["primer"].items():
            pm_ = statistics.mean(c.values())
            w(
                f"- `docs/{files[lang]}` ({labels[lang]}): {pm_:.0f} tokens i snitt "
                f"({min(c.values())}–{max(c.values())})."
            )
        p_en = statistics.mean(data["primer"]["en"].values()) if "en" in data["primer"] else None
        if p_en:
            breakeven = f"{p_en / rate:,.0f}".replace(",", " ")
            cached = f"{p_en * 0.1 / rate:,.0f}".replace(",", " ")
            rate_nb = 1 - m["klar"] / m["nb"]
            breakeven_nb = f"{p_en / rate_nb:,.0f}".replace(",", " ")
            cached_nb = f"{p_en * 0.1 / rate_nb:,.0f}".replace(",", " ")
            w(
                f"\nKlar sparer {rate:.0%} av tokenene mot engelsk i korpuset. Primeren på {p_en:.0f} tokens "
                f"lønner seg derfor etter omtrent **{breakeven} tokens** med engelsk tekst som ellers ville blitt "
                "skrevet eller lest i samme samtale. Med prompt caching koster en lagret primer omtrent en tidel "
                f"per gjenbruk, og da er grensen nær **{cached} tokens**. Mot norsk tekst sparer Klar "
                f"{rate_nb:.0%}, og grensen er omtrent **{breakeven_nb} tokens** ({cached_nb} med caching). Når "
                "modellen *skriver* Klar, teller besparelsen mer, fordi output-tokens er dyrere og tregere enn "
                "input-tokens.\n"
            )
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    main()
