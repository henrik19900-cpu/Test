"""Make a parsed Klar text readable and checkable: a one-line gloss per sentence, references resolved, a
JSON-ready dictionary and the grammatical features of each sentence."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

from . import lexicon as L
from .nodes import (
    Clause,
    ClauseLike,
    Complex,
    Coordination,
    Embedded,
    NounPhrase,
    Phrase,
    Predicate,
    PrepPhrase,
    Sentence,
    SubClause,
    Text,
    Word,
)

EVIDENCE_TAG = {"checked": "VERIFIED", "so": "INFERRED", "suppose": "ASSUMED"}
TENSE_TAG = {"li": "NOW", "pa": "PAST", "fu": "FUT"}


def confidence_value(word: str | None) -> float | None:
    """The probability a confidence opener stands for; ``None`` when there is none (confident, >= 0.9)."""
    if word is None:
        return None
    if word in L.CONFIDENCE:
        return L.CONFIDENCE[word][1]
    try:
        return float(word.rstrip("%")) / 100
    except ValueError:
        return None


# ------------------------------------------------------------------ references


class References:
    """Resolve "it" and labels through a whole text.

    ``it`` is the nearest earlier subject or object, leaving out those inside a relative (which) clause or a
    preposition phrase, and never the subject or object of its own verb ("I pa fix bug pa add 2 test for it":
    it is the bug). A label is the phrase it was bound to.
    """

    def __init__(self, text: Text):
        self.antecedent: dict[int, Phrase] = {}
        self.labels: dict[str, Phrase] = {}
        self.claims: dict[str, Sentence] = {}  # "P: ..." names the claim of a sentence
        self.unbound_labels: list[str] = []
        self.unresolved_it = 0
        # "it" as subject that the rule gives an object, while a subject was close by: (it, chosen, rivals).
        # English readers would often take the subject there, so the checker warns.
        self.ambiguous: list[tuple[NounPhrase, Phrase, list[Phrase]]] = []
        self._core: list[tuple[int, str, Phrase]] = []  # (sentence number, "subj" or "obj", phrase)
        # Subject and object of each verb being read, innermost last.
        self._own: list[list[Phrase | None]] = []
        self._sentence_no = -1
        for s in text.sentences:
            self._sentence(s)

    def resolve(self, np: Phrase) -> Phrase | None:
        if isinstance(np, NounPhrase) and np.kind == "label":
            return self.labels.get(np.ref or "")
        return self.antecedent.get(id(np))

    def _sentence(self, s: Sentence) -> None:
        self._sentence_no += 1
        if s.label:
            self.claims[s.label] = s
        for f in s.fronted:
            self._dependent(f)
        if s.kind == "definition" and isinstance(s.left, NounPhrase) and s.left.kind == "label" and s.right:
            self._np(s.right, core=False)
            self.labels[s.left.ref or ""] = s.right
            return
        for side in (s.left, s.right):
            if side is not None:
                self._np(side, core=False)
        if s.body is not None:
            self._clause_like(s.body, core=True)

    def _clause_like(self, node: ClauseLike, core: bool) -> None:
        if isinstance(node, Complex):
            for part in node.parts:
                self._clause_like(part, core)
            return
        if node.subject is not None:
            self._np(node.subject, core, "subj")
        for p in node.predicates:
            self._predicate(p, core, node.subject)

    def _predicate(self, p: Predicate, core: bool, subject: Phrase | None) -> None:
        self._own.append([subject])
        if isinstance(p.head, (NounPhrase, Coordination)):
            self._np(p.head, core=False)
        elif isinstance(p.head, PrepPhrase):
            self._np(p.head.obj, core=False)
        elif isinstance(p.head, Word) and p.head.text == "it":
            self._it(NounPhrase("pronoun", ref="it"))
        if isinstance(p.complement, Embedded):
            self._clause_like(p.complement.body, core=True)
        elif p.complement is not None:
            self._np(p.complement, core)
            self._own[-1].append(p.complement)
        for d in p.dependents:
            self._dependent(d)
        self._own.pop()

    def _dependent(self, d: object) -> None:
        if isinstance(d, PrepPhrase):
            self._np(d.obj, core=False)
        elif isinstance(d, (SubClause, Embedded)):
            self._clause_like(d.body, core=True)
        elif isinstance(d, (NounPhrase, Coordination)):
            self._np(d, core=False)

    def _follow(self, target: Phrase) -> Phrase:
        while id(target) in self.antecedent:  # an earlier "it" stands for what it pointed to
            target = self.antecedent[id(target)]
        return target

    def _it(self, np: NounPhrase, function: str = "obj") -> None:
        own = self._own[-1] if self._own else []
        # "user can see it": it is never the subject or object of its own verb
        candidates = [(n, f, t) for n, f, t in reversed(self._core) if not any(t is o for o in own)]
        if not candidates:
            self.unresolved_it += 1
            return
        _, chosen_function, chosen = candidates[0]
        chosen = self._follow(chosen)
        self.antecedent[id(np)] = chosen
        if function == "subj" and chosen_function == "obj":
            rivals: list[Phrase] = []
            for n, f, t in candidates[1:]:
                t = self._follow(t)
                if f == "subj" and n >= self._sentence_no - 1 and short(t) != short(chosen):
                    if all(short(t) != short(r) for r in rivals):
                        rivals.append(t)
            if rivals:
                self.ambiguous.append((np, chosen, rivals))

    def _np(self, np: Phrase, core: bool, function: str = "obj") -> None:
        if isinstance(np, Coordination):
            for item in np.items:
                self._np(item, core=False)
        elif np.kind == "pronoun" and np.ref == "it":
            self._it(np, function)
        elif np.kind == "label":
            if np.ref not in self.labels and np.ref not in self.claims:
                self.unbound_labels.append(np.ref or "")
            elif core and np.ref in self.labels:
                self.antecedent[id(np)] = self.labels[np.ref or ""]
        elif np.kind == "group" and np.group is not None:
            self._np(np.group, core=False)
        for of in getattr(np, "of", []):
            self._np(of, core=False)
        for pp in getattr(np, "pps", []):
            self._np(pp.obj, core=False)
        relative = getattr(np, "relative", None)
        if relative is not None:
            self._clause_like(relative, core=False)
        label = getattr(np, "label", None)
        if label:
            self.labels[label] = np
        if core and not (
            isinstance(np, NounPhrase) and np.kind == "pronoun" and np.ref in ("I", "you", "we")
        ):
            self._core.append((self._sentence_no, function, np))


# ------------------------------------------------------------------- the gloss


def gloss_text(text: Text) -> list[str]:
    refs = References(text)
    return [gloss_sentence(s, refs) for s in text.sentences]


def gloss_sentence(s: Sentence, refs: References | None = None) -> str:
    g = _Glosser(refs)
    return g.sentence(s)


class _Glosser:
    def __init__(self, refs: References | None):
        self.refs = refs

    def sentence(self, s: Sentence) -> str:
        parts: list[str] = []
        if s.label:
            parts.append(f"{s.label}:")
        if s.discourse:
            parts.append(s.discourse.upper())
        if s.evidential:
            parts.append(f"‹{EVIDENCE_TAG[s.evidential]}›")
        if s.confidence:
            value = confidence_value(s.confidence)
            shown = f"{s.confidence} ≈{value:.0%}" if s.confidence in L.CONFIDENCE else s.confidence
            parts.append(f"‹{shown}›")
        for f in s.fronted:
            if isinstance(f, PrepPhrase) and f.prep == "per":
                parts.append(f"‹SOURCE {self.np(f.obj)}›")
            else:
                parts.append(self.dependent(f) + ",")
        if s.kind == "answer":
            parts.append((s.answer or "").upper())
        elif s.kind == "fragment" and s.right is not None:
            parts.append("ANSWER= " + self.np(s.right))
        elif s.kind == "definition" and s.left is not None and s.right is not None:
            left = (
                s.left.ref if isinstance(s.left, NounPhrase) and s.left.kind == "label" else self.np(s.left)
            )
            parts.append(f"{left} := {self.np(s.right)}")
        elif s.body is not None:
            parts.append(self.clause_like(s.body, top=True))
        return " ".join(parts) + (" ?" if s.terminator == "?" else " .")

    def clause_like(self, node: ClauseLike, top: bool = False) -> str:
        if isinstance(node, Complex):
            inner = f" {node.op.upper()} ".join(self.clause_like(p) for p in node.parts)
            return inner if top else f"({inner})"
        return self.clause(node)

    def clause(self, c: Clause) -> str:
        out = []
        if c.subject is not None:
            out.append(self.np(c.subject))
        for p in c.predicates:
            if p.link == "then":
                out.append("THEN")
            elif p.link:
                out.append(p.link.upper())
            elif p is not c.predicates[0]:
                out.append("+")
            out.append(self.predicate(p))
        return " ".join(out)

    def predicate(self, p: Predicate) -> str:
        tags = []
        if p.tense:
            tags.append(TENSE_TAG[p.tense])
        if p.modal:
            tags.append(p.modal.upper())
        if p.inherited or p.implicit:
            tags = [f"({t})" for t in tags]
        tags += [a.upper() for a in p.adverbs]
        marker = ".".join(tags)
        if p.kind == "nominal":
            body = "IS-A " + self.np(p.head) if isinstance(p.head, (NounPhrase, Coordination)) else "IS"
        elif p.kind == "locative" and isinstance(p.head, PrepPhrase):
            body = "IS " + self.pp(p.head)
        elif isinstance(p.head, Word):
            body = self.word(p.head)
        else:
            body = "_"  # gap
        out = [f"{marker}:{body}"]
        if isinstance(p.complement, Embedded):
            out.append(self.embedded(p.complement))
        elif p.complement is not None:
            out.append(self.np(p.complement))
        out += [self.dependent(d) for d in p.dependents]
        return " ".join(out)

    def word(self, w: Word) -> str:
        if w.kind == "pronoun" and w.text == "it":
            return "it"
        return w.text

    def embedded(self, e: Embedded) -> str:
        return f"«{e.word}: {self.clause_like(e.body, top=True)}»"

    def dependent(self, d: object) -> str:
        if isinstance(d, PrepPhrase):
            return self.pp(d)
        if isinstance(d, Embedded):
            return self.embedded(d)
        if isinstance(d, SubClause):
            return f"{{{d.sub}: {self.clause_like(d.body, top=True)}}}"
        if isinstance(d, Word):
            return f"{{{d.text}}}"
        return self.np(d)  # type: ignore[arg-type]

    def pp(self, pp: PrepPhrase) -> str:
        return f"{{{pp.prep} {self.np(pp.obj)}}}"

    def np(self, np: Phrase) -> str:
        if isinstance(np, Coordination):
            return f" {np.op.upper()} ".join(self.np(i) for i in np.items)
        inner: list[str] = []
        if np.focus:
            inner.append(np.focus.upper())
        if np.kind == "group" and np.group is not None:
            inner.append(self.np(np.group))
        elif np.kind in ("pronoun", "label", "wh"):
            target = self.refs.resolve(np) if self.refs else None
            claim = self.refs.claims.get(np.ref or "") if self.refs and np.kind == "label" else None
            if target is not None:
                inner.append(f"{np.ref}→{short(target)}")
            elif claim is not None:
                inner.append(f"{np.ref}→«{claim.text.split(':', 1)[1].strip().rstrip('.?')}»")
            else:
                inner.append(np.ref or "")
        else:
            if np.det:
                inner.append(np.det)
            inner += [w.text for w in np.words]
        text = " ".join(inner)
        if np.label:
            text += f"⟨{np.label}⟩"
        for of in np.of:
            text += f" of {self.np(of)}"
        for pp in np.pps:
            text += " " + self.pp(pp)
        if np.relative is not None:
            text += f" «which: {self.clause_like(np.relative, top=True)}»"
        return f"[{text}]"


def short(np: Phrase | None) -> str:
    """A few words that name a phrase: the antecedent shown after "it→"."""
    if np is None:
        return "?"
    if isinstance(np, Coordination):
        return f" {np.op} ".join(short(i) for i in np.items)
    if np.kind == "group" and np.group is not None:
        return short(np.group)
    words = [w.text for w in np.words] or [np.ref or np.det or "?"]
    text = " ".join(words)
    if np.of:
        text += " of " + short(np.of[0])
    return text


# ----------------------------------------------------------- data and features


def to_data(node: object) -> object:
    """A JSON-ready form of any syntax tree node: dictionaries with a "type", without empty fields."""
    if isinstance(node, list):
        return [to_data(x) for x in node]
    if not dataclasses.is_dataclass(node):
        return node
    out: dict[str, object] = {"type": type(node).__name__}
    for f in dataclasses.fields(node):
        value = getattr(node, f.name)
        if value in (None, [], "", False) or f.name in ("line", "col"):
            continue
        out[f.name] = to_data(value)
    if isinstance(node, Sentence):
        out["directive"] = node.is_directive
        if node.confidence:
            out["confidence_value"] = confidence_value(node.confidence)
    return out


def walk(node: object) -> Iterator[object]:
    """Every node below and including ``node``, in text order."""
    yield node
    if isinstance(node, list):
        for x in node:
            yield from walk(x)
    elif dataclasses.is_dataclass(node):
        for f in dataclasses.fields(node):
            value = getattr(node, f.name)
            if isinstance(value, list) or dataclasses.is_dataclass(value):
                yield from walk(value)


def source_of(s: Sentence) -> str | None:
    """The source a sentence names with a fronted "per X,", as text."""
    for f in s.fronted:
        if isinstance(f, PrepPhrase) and f.prep == "per":
            return short(f.obj)
    return None


def features(s: Sentence) -> dict[str, object]:
    """The grammatical choices a sentence makes, for comparing a translation with the intended meaning."""
    tenses, modals, adverbs, subs, comps, conns, links, preps, qwords = (set() for _ in range(9))
    bound, used = set(), set()
    negated = relative = grouped = False
    for n in walk(s):
        if isinstance(n, Predicate):
            if n.tense:
                tenses.add(n.tense)
            if n.modal:
                modals.add(n.modal)
            adverbs.update(n.adverbs)
            if n.link:
                links.add(n.link)
            negated |= "not" in n.adverbs or "never" in n.adverbs
        elif isinstance(n, SubClause):
            subs.add(n.sub)
        elif isinstance(n, Embedded):
            comps.add(n.word)
        elif isinstance(n, Complex):
            conns.add(n.op)
        elif isinstance(n, Coordination):
            conns.add(n.op)
        elif isinstance(n, PrepPhrase):
            preps.add(n.prep)
        elif isinstance(n, Clause):
            relative |= n.role == "relative"
        elif isinstance(n, NounPhrase):
            grouped |= n.kind == "group"
            if n.label:
                bound.add(n.label)
            if n.kind == "label":
                used.add(n.ref)
            if n.kind == "wh":
                qwords.add(n.ref)
            if n.det == "which" and s.kind == "question":
                qwords.add("which")
            negated |= n.focus == "not" or n.det == "no"
        elif isinstance(n, Word) and n.kind == "wh":
            qwords.add(n.text)
    return {
        "kind": s.kind,
        "directive": s.is_directive,
        "evidential": s.evidential,
        "confidence": s.confidence,
        "source": source_of(s),
        "tenses": sorted(tenses),
        "modals": sorted(modals),
        "adverbs": sorted(adverbs),
        "negated": negated,
        "subordinators": sorted(subs),
        "complements": sorted(comps),
        "connectives": sorted(conns),
        "links": sorted(links),
        "relative": relative,
        "grouped": grouped,
        "labels_bound": sorted(bound),
        "labels_used": sorted(used),
        "question_words": sorted(qwords),
        "label": s.label,
    }
