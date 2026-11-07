"""Check a Klar text: grammar errors, plus warnings for things that parse but are probably not what the writer
meant. ``strict`` also requires every claim to say where it comes from, which suits reports from agents."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .gloss import References, short, source_of, walk
from .lexer import KlarError
from .nodes import Complex, NounPhrase, Predicate, Sentence, Text
from .parser import parse


@dataclass(frozen=True)
class Issue:
    level: str  # error warning
    line: int
    col: int
    message: str

    def __str__(self) -> str:
        where = f"{self.line}:{self.col}" if self.line else "-"
        word = "feil" if self.level == "error" else "advarsel"
        return f"{where}: {word}: {self.message}"


def check(source: str, strict: bool = False) -> tuple[Text | None, list[Issue]]:
    try:
        text = parse(source)
    except KlarError as e:  # the text could not even be split into tokens
        return None, [Issue("error", e.line, e.col, _message(e))]
    issues = [Issue("error", e.line, e.col, _message(e)) for e in text.errors]
    refs = References(text)
    for label in sorted(set(refs.unbound_labels)):
        issues.append(Issue("warning", 0, 0, f"etiketten {label} brukes uten å være knyttet til noe først"))
    if refs.unresolved_it:
        issues.append(Issue("warning", 0, 0, "«it» står før noe den kan vise til"))
    for it, chosen, rivals in refs.ambiguous:
        names = " eller ".join(f"«{short(r)}»" for r in rivals)
        issues.append(
            Issue(
                "warning",
                it.line,
                it.col,
                f"«it» er subjekt og viser etter regelen til objektet «{short(chosen)}», ikke til {names}. "
                "Mente du subjektet, skriv det ut, bruk en etikett eller then",
            )
        )
    bound = Counter(n.label for s in text.sentences for n in walk(s) if isinstance(n, NounPhrase) and n.label)
    for label, count in sorted(bound.items()):
        if count > 1:
            issues.append(
                Issue("warning", 0, 0, f"etiketten {label} knyttes {count} ganger; bruk en ny bokstav")
            )
    for s in text.sentences:
        issues += _sentence_warnings(s, strict)
    issues.sort(key=lambda i: (i.line or 10**9, i.col))
    return text, issues


def _message(e: KlarError) -> str:
    return e.message + (f". Tips: {e.hint}" if e.hint else "")


def _sentence_warnings(s: Sentence, strict: bool) -> list[Issue]:
    out = []
    flat = " ".join(s.text.split())
    if "\n" in s.text.strip():
        out.append(
            Issue("warning", s.line, 1, f"setningen går over flere linjer; mangler det et punktum? «{flat}»")
        )
    for n in walk(s):
        if isinstance(n, Predicate) and n.modal == "may" and n.adverbs[:1] == ["not"]:
            out.append(
                Issue(
                    "warning",
                    n.line,
                    n.col,
                    "«may not» leses som forbud på engelsk, men betyr «lov å la være» i Klar; "
                    "skriv «must not» for forbud",
                )
            )
    if strict and s.kind == "statement" and not s.is_directive and s.evidential is None:
        if source_of(s) is None and not _about_self(s):
            out.append(
                Issue(
                    "warning",
                    s.line,
                    1,
                    f"påstanden sier ikke hvor den kommer fra (checked, so, suppose eller per X): «{flat}»",
                )
            )
    return out


def _about_self(s: Sentence) -> bool:
    """A sentence about what the writer did or will do ("I pa fix bug", "we fu deploy"). The writer knows that
    without a source, so strict mode does not ask for one."""
    node = s.body
    while isinstance(node, Complex):
        node = node.parts[0]
    subject = getattr(node, "subject", None)
    return isinstance(subject, NounPhrase) and subject.kind == "pronoun" and subject.ref in ("I", "we")
