"""The syntax tree of a Klar text."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Word:
    text: str
    kind: str  # word name num str code adverbial wh
    line: int = 0
    col: int = 0


@dataclass
class NounPhrase:
    """A noun phrase: modifiers before the head, the head last.

    ``kind`` is ``words`` (content words), ``pronoun``, ``label`` (a reference to a label), ``wh`` (a question
    word), ``det`` (a determiner standing alone: "this", "all") or ``group`` (a phrase in brackets).
    """

    kind: str
    words: list[Word] = field(default_factory=list)
    det: str | None = None
    focus: str | None = None
    label: str | None = None  # label bound here: "file F"
    ref: str | None = None  # the pronoun, label or question word
    group: Phrase | None = None
    of: list[Phrase] = field(default_factory=list)
    pps: list[PrepPhrase] = field(default_factory=list)
    relative: Clause | None = None
    line: int = 0
    col: int = 0

    @property
    def head(self) -> str | None:
        if self.words:
            return self.words[-1].text
        if self.group is not None and isinstance(self.group, NounPhrase):
            return self.group.head
        return self.ref or self.det


@dataclass
class Coordination:
    op: str  # and or xor
    items: list[Phrase]


Phrase = NounPhrase | Coordination


@dataclass
class PrepPhrase:
    prep: str
    obj: Phrase


@dataclass
class SubClause:
    sub: str  # if when unless until while before after since where because
    body: ClauseLike
    preposed: bool


@dataclass
class Embedded:
    """A clause used as an object: "that ...", "whether ...", "why ...", "which test pa fail"."""

    kind: str  # that whether wh which
    word: str
    body: ClauseLike


@dataclass
class Predicate:
    tense: str | None
    modal: str | None
    # How it joins the previous predicate: None (first, or a bare marker), and or xor but so then.
    link: str | None
    inherited: bool  # marker inherited through "then"
    adverbs: list[str]
    kind: str  # verbal nominal locative
    head: Word | Phrase | PrepPhrase | None
    complement: Phrase | Embedded | None = None
    dependents: list[PrepPhrase | SubClause | Embedded | Word] = field(default_factory=list)
    implicit: bool = False  # "li" left out after a pronoun or label: "it valid", "I recommend B"
    line: int = 0
    col: int = 0


@dataclass
class Clause:
    subject: Phrase | None
    predicates: list[Predicate]
    role: str = "main"  # main relative complement adverbial


@dataclass
class Complex:
    op: str  # and or xor but so because iff
    parts: list[ClauseLike]


ClauseLike = Clause | Complex


@dataclass
class Sentence:
    kind: str  # statement question definition answer fragment
    terminator: str
    text: str
    line: int
    label: str | None = None  # "P: ..."
    discourse: str | None = None
    evidential: str | None = None
    confidence: str | None = None
    fronted: list[PrepPhrase | SubClause | Phrase] = field(default_factory=list)
    body: ClauseLike | None = None
    left: Phrase | None = None  # definition: left = right
    right: Phrase | None = None
    answer: str | None = None  # yes / no

    @property
    def is_directive(self) -> bool:
        return self.kind == "statement" and _first_clause_is_directive(self.body)


def _first_clause_is_directive(node: ClauseLike | None) -> bool:
    while isinstance(node, Complex):
        node = node.parts[0]
    if not isinstance(node, Clause) or not node.predicates:
        return False
    first = node.predicates[0]
    subject_is_you = isinstance(node.subject, NounPhrase) and node.subject.ref == "you"
    return first.modal in ("must", "should", "may") and (node.subject is None or subject_is_you)


@dataclass
class Text:
    sentences: list[Sentence]
    errors: list = field(default_factory=list)  # KlarError for each sentence that did not parse
