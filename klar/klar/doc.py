"""Write the word list in docs/spesifikasjon.md from the lexicon: ``python -m klar.doc``.

The list lives between two marker comments in the document, so the spec can never drift from what the parser
accepts (tests/test_docs.py checks that it is up to date).
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import lexicon as L

SPEC = Path(__file__).resolve().parents[1] / "docs" / "spesifikasjon.md"
START = "<!-- ORDLISTE START (generert av python -m klar.doc, ikke rediger for hånd) -->"
END = "<!-- ORDLISTE SLUTT -->"

SECTIONS = [
    ("Markører: tid", L.TENSES),
    ("Markører: modalitet", L.MODALS),
    ("Adverb (mellom markør og hovedord)", L.ADVERBS),
    ("Substantivfrase som predikat", L.PREDICATE_NOMINAL),
    ("Kilde (først i setningen)", L.EVIDENTIALS),
    ("Sikkerhet (først i setningen)", {form: p for form, (p, _) in L.CONFIDENCE.items()}),
    ("Diskursord (først i setningen)", L.DISCOURSE),
    ("Bindeord mellom setninger", L.CONNECTIVES),
    ("Underordnere (leddsetninger)", L.SUBORDINATORS),
    ("Objektsetninger", L.COMPLEMENTIZERS),
    ("Relativsetninger", L.RELATIVIZER),
    ("Spørreord", L.QUESTION_WORDS),
    ("Pronomen", L.PRONOUNS),
    ("Eiendomsord", L.POSSESSIVES),
    ("Bestemmerord og kvantorer", L.DETERMINERS),
    ("Preposisjoner", L.PREPOSITIONS),
    ("Tids- og stedsord", L.ADVERBIAL_WORDS),
    ("Svar", L.ANSWERS),
]


def word_list() -> str:
    out = [START, ""]
    for title, table in SECTIONS:
        out.append(f"**{title}**\n")
        out.append("| Ord | Betydning | Meaning |")
        out.append("|---|---|---|")
        out += [f"| `{p.form}` | {p.no} | {p.en} |" for p in table.values()]
        out.append("")
    out.append("**Tegn**\n")
    out.append("| Tegn | Betydning | Meaning |")
    out.append("|---|---|---|")
    out += [f"| `{sign}` | {no} | {en} |" for sign, (en, no) in L.PUNCTUATION.items()]
    out += ["", f"Etiketter: én stor bokstav, {' '.join(sorted(L.LABEL_LETTERS))}.", "", END]
    return "\n".join(out)


def updated(text: str) -> str:
    before, rest = text.split(START, 1)
    _, after = rest.split(END, 1)
    return before + word_list() + after


def main() -> int:
    SPEC.write_text(updated(SPEC.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"skrev ordlisten i {SPEC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
