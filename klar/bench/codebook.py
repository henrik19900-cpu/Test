"""Could a longer primer with a codebook make Klar Kort shorter? Writes bench/CODEBOOK.md.

    python bench/codebook.py

A codebook teaches the reader short codes for words and phrases, so it makes the primer longer. It can only
save tokens where a word or phrase costs more than one token, so the script splits the tokens of Kort v3
(the shortest version that keeps the content) by what they are: one token per word, numbers, names and code,
punctuation and symbols, and English words that cost more than one token. It then works out the most a
codebook could save, with an oracle that knows the test in advance: every English word one token, and every
phrase that occurs twice one token.
"""

from __future__ import annotations

import re
import statistics
import sys
from collections import Counter
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from counters import load, marginal  # noqa: E402  (bench/counters.py)

KINDS = {
    "tall": "Tall og enheter, tokens utover det første (`30s`, `3/120`, `~25%`)",
    "navn": "Navn, stier og kode, tokens utover det første (`JSON`, `src/payments/validators.py`)",
    "ord": "Engelske ord, tokens utover det første (`unconfirmed`, `penguins`)",
    "tegn": "Tegnsetting og symboler (`.` `,` `:` `→` `+`)",
}
TRAILING = ".,;:?!)"


def split_word(word: str) -> tuple[str, str]:
    """The word without the punctuation around it, and the punctuation."""
    if word.endswith("()"):
        return word, ""
    core = word.rstrip(TRAILING).lstrip("(")
    return core, word.replace(core, "", 1) if core else word


def num(x: float) -> str:
    """A whole number with a space between thousands, as in Norwegian: 6 312."""
    return f"{x:,.0f}".replace(",", " ")


def kind(core: str) -> str:
    if not core or not any(ch.isalnum() for ch in core):
        return "tegn"
    if any(ch.isdigit() for ch in core):
        return "tall"
    if re.search(r"[/_()]|\w\.\w", core) or any(ch.isupper() for ch in core):
        return "navn"
    return "ord"


def main() -> None:
    kort = yaml.safe_load((HERE / "kort.yaml").read_text(encoding="utf-8"))
    corpus = yaml.safe_load((HERE / "corpus.yaml").read_text(encoding="utf-8"))
    english = [e["en"].strip() for e in corpus["items"] + corpus["passages"]]
    texts = [kort[i]["kort_v3"].strip() for i in kort]
    counters = load()
    names = list(counters)

    def cost(s: str) -> float:
        """Tokens for s in running text, after a space, averaged over the tokenizers."""
        return statistics.mean(marginal(counters[n], s) for n in names)

    total = statistics.mean(sum(counters[n](t) for t in texts) for n in names)

    def pct(part: float, whole: float | None = None, decimals: int = 0) -> str:
        return f"{part / (whole or total) * 100:.{decimals}f} %".replace(".", ",")

    english_total = statistics.mean(sum(counters[n](t) for t in english) for n in names)

    words = [w for t in texts for w in t.split()]
    freq = Counter(words)
    parts = Counter()  # tokens by kind; the first token of every word is counted as "one per word"
    excess_words: Counter[str] = Counter()
    for w, n in freq.items():
        core, punct = split_word(w)
        c_core = cost(core) if core else 0.0
        c_all = cost(w)
        k = kind(core)
        if k == "tegn":
            parts["tegn"] += c_all * n
            continue
        parts["per_word"] += n
        parts[k] += (c_core - 1) * n
        parts["tegn"] += (c_all - c_core) * n
        if k == "ord" and c_core > 1:
            excess_words[core] += (c_core - 1) * n
    rest = total - sum(parts.values())  # merges across word boundaries and the first word of each text

    # Oracle 1: every English word costs one token.
    word_saving = sum(excess_words.values())
    # Oracle 2: every phrase of 2-4 plain words that occurs at least twice becomes one token (no overlaps).
    plain = [
        [split_word(w)[0] if kind(split_word(w)[0]) == "ord" else None for w in t.split()] for t in texts
    ]
    phrases: Counter[tuple[str, ...]] = Counter()
    for ws in plain:
        for size in (4, 3, 2):
            for k in range(len(ws) - size + 1):
                gram = ws[k : k + size]
                if all(gram):
                    phrases[tuple(gram)] += 1
    chosen = []
    used: set[tuple[int, int]] = set()
    for gram, n in sorted(phrases.items(), key=lambda gn: -(len(gn[0]) - 1) * gn[1]):
        if n < 2:
            continue
        spots = []
        for ti, ws in enumerate(plain):
            for k in range(len(ws) - len(gram) + 1):
                cells = {(ti, j) for j in range(k, k + len(gram))}
                if tuple(ws[k : k + len(gram)]) == gram and not cells & used:
                    spots.append(cells)
        if len(spots) >= 2:
            for cells in spots:
                used |= cells
            chosen.append((" ".join(gram), len(spots)))
    phrase_saving = sum((len(g.split()) - 1) * n for g, n in chosen)

    # What the codebook itself would cost in the primer: one line per entry, like "`uc` unconfirmed".
    entries = list(excess_words) + [g for g, _ in chosen]
    primer_extra = sum(cost(f"`x{i}` {e}") for i, e in enumerate(entries)) + len(entries)  # + line breaks
    saving = word_saving + phrase_saving
    per_english_token = saving / english_total

    out: list[str] = []
    w = out.append
    w("# Kan en kodebok gjøre Klar Kort kortere?\n")
    w(
        "Generert av `python bench/codebook.py`. En kodebok lærer leseren korte koder for ord og uttrykk, og gjør "
        "derfor primeren lengre. Den kan bare spare tokens der et ord eller uttrykk koster mer enn ett token. "
        "Tabellen deler tokenene i Kort v3 (den korteste versjonen som beholder innholdet, "
        f"{len(texts)} tekster) etter hva de er. Snitt over {len(names)} tokenizere.\n"
    )
    w("| Del av teksten | Tokens | Andel |")
    w("|---|---:|---:|")
    w(
        f"| Første token i hvert ord ({parts['per_word']:.0f} ord) | {parts['per_word']:.0f} | {pct(parts['per_word'])} |"
    )
    for k, title in KINDS.items():
        w(f"| {title} | {parts[k]:.0f} | {pct(parts[k])} |")
    w(f"| Sammenslåing over ordgrenser, og første ord i hver tekst | {rest:.0f} | {pct(rest)} |")
    w(f"| **Kort v3 i alt** | **{total:.0f}** | |")
    w("")
    w("## Det meste en kodebok kan spare\n")
    w(
        "Tallene under er en øvre grense. Kodeboken er laget med fasit: den kjenner testen på forhånd. "
        "I ny tekst står mange av ordene ikke i kodeboken.\n"
    )
    w("| Kodebok | Sparer | Kort v3 blir |")
    w("|---|---:|---:|")
    w(
        f"| Hvert engelske ord koster ett token ({len(excess_words)} oppføringer) | {word_saving:.0f} "
        f"| {total - word_saving:.0f} |"
    )
    w(
        f"| + hvert uttrykk som står minst to ganger blir ett token ({len(chosen)} oppføringer) "
        f"| {saving:.0f} | {total - saving:.0f} |"
    )
    w("")
    w(
        f"Kodeboken selv koster omtrent {primer_extra:.0f} tokens i primeren, mer enn den sparer på hele testen. "
        f"Den sparer tokens tilsvarende {pct(saving, english_total, 1)} av den engelske originalen, så den lønner "
        f"seg først etter omtrent {num(primer_extra / per_english_token)} tokens med tekst, eller "
        f"{num(primer_extra / 10 / per_english_token)} med prompt caching (en lagret primer koster omtrent en "
        "tidel). Det forutsetter at akkurat ordene i kodeboken kommer igjen i den teksten.\n"
    )
    w("Uttrykkene som står minst to ganger:\n")
    w(", ".join(f"`{g}` ({n})" for g, n in chosen) or "Ingen.")
    w("")
    w("De dyreste engelske ordene:\n")
    w(", ".join(f"`{word}` (+{x:.1f})" for word, x in excess_words.most_common(12)))
    w("")
    (HERE / "CODEBOOK.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
