"""Parse Klar into a syntax tree.

The grammar is deterministic: at every point the next one or two tokens, or a tentative parse of the next
noun phrase, decide what comes next. There is never a choice between two complete parses, so every sentence
has at most one tree. Where English would be ambiguous, Klar makes the writer choose with a word, a label or
brackets; the docs (docs/spesifikasjon.md) list each rule.
"""

from __future__ import annotations

from . import lexicon as L
from .lexer import BAD_HINTS, KlarError, Token, strip_markup, tokenize
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

TERMINATORS = {".", "?"}
# Subordinators that may open a sentence. "because" only links clauses in the middle of a sentence.
PREPOSED_SUBS = set(L.SUBORDINATORS) | {"because"}
# Connectives that may join two predicates of the same subject: "user pa try but pa fail".
PREDICATE_LINKS = {"and", "or", "xor", "but", "so"}
LEVELS = [L.LOW_LEVEL, L.OR_LEVEL, L.AND_LEVEL]


def parse(text: str) -> Text:
    """Parse a whole text. A sentence that does not parse is skipped and its error kept in ``Text.errors``."""
    source = strip_markup(text)
    tokens = tokenize(source)
    sentences: list[Sentence] = []
    errors: list[KlarError] = []
    i = 0
    while tokens[i].kind != "EOF":
        p = _Parser(tokens, i, source)
        try:
            sentences.append(p.sentence())
            i = p.i
        except KlarError as e:
            errors.append(e)
            i = _after_sentence(tokens, max(p.i, i))
    return Text(sentences, errors)


def parse_sentence(text: str) -> Sentence:
    """Parse exactly one sentence, raising ``KlarError`` if it is not valid Klar."""
    result = parse(text)
    if result.errors:
        raise result.errors[0]
    if len(result.sentences) != 1:
        raise KlarError(f"ventet én setning, fant {len(result.sentences)}")
    return result.sentences[0]


def _after_sentence(tokens: list[Token], i: int) -> int:
    """Where to go on after a sentence with an error: past its end, "!" and ";" included."""

    def ends(tok: Token) -> bool:
        return (tok.kind == "PUNCT" and tok.text in TERMINATORS) or (tok.kind == "BAD" and tok.text in "!;")

    while tokens[i].kind != "EOF" and not ends(tokens[i]):
        i += 1
    return i + 1 if tokens[i].kind != "EOF" else i


class _Parser:
    def __init__(self, tokens: list[Token], i: int, source: str):
        self.t = tokens
        self.i = i
        self.source = source
        self.sentence_start = i

    # ---------------------------------------------------------------- tokens

    def tok(self, k: int = 0) -> Token:
        return self.t[min(self.i + k, len(self.t) - 1)]

    def word(self, k: int = 0) -> str | None:
        tok = self.tok(k)
        return tok.text if tok.kind == "WORD" else None

    def punct(self, k: int = 0) -> str | None:
        tok = self.tok(k)
        return tok.text if tok.kind == "PUNCT" else None

    def advance(self) -> Token:
        tok = self.tok()
        if tok.kind == "BAD":
            raise self.error(f"tegnet {tok.text!r} finnes ikke i Klar")
        self.i += 1
        return tok

    def expect(self, text: str, message: str) -> Token:
        if self.tok().text != text or self.tok().kind not in ("PUNCT", "WORD"):
            raise self.error(message)
        return self.advance()

    def error(self, message: str, tok: Token | None = None) -> KlarError:
        tok = tok or self.tok()
        return KlarError(message, tok.line, tok.col, self._hint(tok))

    def _hint(self, tok: Token) -> str:
        if tok.kind == "BAD":
            return BAD_HINTS.get(tok.text, "")
        if tok.kind == "WORD" and tok.text in L.ENGLISH_SLIPS:
            return f"«{tok.text}»: {L.ENGLISH_SLIPS[tok.text]}"
        j = self.sentence_start
        while self.t[j].kind != "EOF" and not (self.t[j].kind == "PUNCT" and self.t[j].text in TERMINATORS):
            if self.t[j].kind == "WORD" and self.t[j].text in L.ENGLISH_SLIPS:
                return f"«{self.t[j].text}»: {L.ENGLISH_SLIPS[self.t[j].text]}"
            if self.t[j].kind == "BAD":
                return BAD_HINTS.get(self.t[j].text, "")
            j += 1
        return ""

    # ----------------------------------------------------------- word classes

    def is_pmark(self, k: int = 0) -> bool:
        return self.word(k) in L.PMARKS

    def is_content(self, k: int = 0) -> bool:
        tok = self.tok(k)
        if tok.kind in ("NAME", "NUM", "STR", "CODE", "IDENT"):
            return True
        return tok.kind == "WORD" and tok.text not in L.ALL_FORMS and tok.text not in L.ENGLISH_SLIPS

    def np_start(self, k: int = 0) -> bool:
        tok = self.tok(k)
        if tok.kind in ("NAME", "NUM", "STR", "CODE", "IDENT", "LABEL"):
            return True
        if tok.kind == "PUNCT":
            return tok.text == "("
        if tok.kind != "WORD":
            return False
        w = tok.text
        if w not in L.ALL_FORMS:
            return w not in L.ENGLISH_SLIPS
        return (
            w in L.PRONOUNS
            or w in L.WH_PRONOUNS
            or w in L.DETERMINERS
            or w in L.POSSESSIVES
            or w in L.NP_FOCUS
            or w in L.ADVERBIAL_WORDS
        )

    def is_head_word(self) -> bool:
        tok = self.tok()
        if self.is_content() or tok.kind == "LABEL":
            return True
        w = self.word()
        return w in L.PRONOUNS or w in L.WH_PRONOUNS or w in L.ADVERBIAL_WORDS or w in L.CONFIDENCE

    def _tentative(self, k: int, attempt) -> bool:
        save = self.i
        self.i += k
        try:
            return bool(attempt())
        except KlarError:
            return False
        finally:
            self.i = save

    def np_then_pmark(self, k: int = 0) -> bool:
        """Is there a clause with a subject at k: a noun phrase, then a marker (or an implied li)?"""
        if not self.np_start(k):
            return False

        def attempt() -> bool:
            subject = self.np(in_subject=True, allow_pp=True)
            return self.is_pmark() or (self.is_bare_subject(subject) and self.implicit_start())

        return self._tentative(k, attempt)

    @staticmethod
    def is_bare_subject(np: Phrase) -> bool:
        """A pronoun or a label standing alone: after it, li may be left out ("it valid", "U want F")."""
        if not isinstance(np, NounPhrase) or np.of or np.pps or np.relative or np.focus or np.label:
            return False
        return (np.kind == "pronoun" and np.ref in ("I", "you", "we", "it")) or np.kind == "label"

    def implicit_start(self) -> bool:
        """Can a predicate with an implied li start here? Only an adverb, "a" or a content word."""
        return self.word() in L.ADVERBS or self.word() == "a" or self.is_content()

    def np_then(self, punct: str) -> bool:
        if not self.np_start():
            return False
        return self._tentative(0, lambda: (self.np(in_subject=True, allow_pp=True), self.punct() == punct)[1])

    def clause_follows(self, k: int = 0) -> bool:
        if self.is_pmark(k) or self.np_then_pmark(k):
            return True
        return self.punct(k) == "(" and self.bracket_is_clause(k)

    def matching_paren(self, k: int = 0) -> int:
        depth = 0
        j = self.i + k
        while True:
            tok = self.t[j]
            if tok.kind == "EOF" or (tok.kind == "PUNCT" and tok.text in TERMINATORS):
                raise self.error("parentesen lukkes ikke før setningen slutter", self.t[self.i + k])
            if tok.kind == "PUNCT" and tok.text == "(":
                depth += 1
            elif tok.kind == "PUNCT" and tok.text == ")":
                depth -= 1
                if depth == 0:
                    return j
            j += 1

    def bracket_is_clause(self, k: int = 0) -> bool:
        def attempt() -> bool:
            end = self.matching_paren()
            self.advance()
            self.complex(depth=0)
            return self.i == end

        return self._tentative(k, attempt)

    # -------------------------------------------------------------- sentence

    def sentence(self) -> Sentence:
        first = self.tok()
        self.sentence_start = self.i
        s = Sentence(kind="statement", terminator=".", text="", line=first.line)
        if first.kind == "LABEL" and self.punct(1) == ":":
            s.label = self.advance().text
            self.advance()
        if self.word() in L.ANSWERS and self.punct(1) in TERMINATORS:
            s.kind = "answer"
            s.answer = self.advance().text
            return self.finish(s, first)
        if self.punct() == "=":
            self.advance()
            s.kind = "fragment"
            if not self.np_start():
                raise self.error("«=» som svar trenger en frase etter seg: = F.")
            s.right = self.np(in_subject=True, allow_pp=True)
            return self.finish(s, first)
        if self.np_start() and self.np_then("="):
            s.kind = "definition"
            s.left = self.np(in_subject=True, allow_pp=True)
            self.advance()
            if not self.np_start():
                raise self.error("en definisjon trenger en frase etter «=»")
            s.right = self.np(in_subject=True, allow_pp=True)
            return self.finish(s, first)
        self.openers(s)
        s.body = self.complex(depth=0)
        return self.finish(s, first)

    def finish(self, s: Sentence, first: Token) -> Sentence:
        tok = self.tok()
        if not (tok.kind == "PUNCT" and tok.text in TERMINATORS):
            if tok.kind == "EOF":
                raise self.error("setningen mangler punktum eller spørsmålstegn på slutten")
            if tok.text == ",":
                raise self.error(
                    "komma brukes bare etter noe som står først (if ..., / in 2024,); "
                    "skriv «but»/«and» uten komma, eller avslutt setningen med punktum"
                )
            raise self.error(f"ventet slutten på setningen (. eller ?), fant «{tok.text}»")
        self.advance()
        s.terminator = tok.text
        if s.terminator == "?" and s.kind == "statement":
            s.kind = "question"
        s.text = self.source[first.start : tok.end]
        return s

    def openers(self, s: Sentence) -> None:
        while True:
            w = self.word()
            tok = self.tok()
            if w in L.DISCOURSE and s.discourse is None and s.evidential is None and s.confidence is None:
                if w == "also" and self.is_pmark(1):
                    break
                s.discourse = self.advance().text
            elif w in L.EVIDENTIALS and s.evidential is None:
                s.evidential = self.advance().text
            elif w in L.CONFIDENCE and s.confidence is None:
                s.confidence = self.advance().text
            elif (
                tok.kind == "NUM" and tok.text.endswith("%") and self.word(1) != "of" and s.confidence is None
            ):
                s.confidence = self.advance().text
            else:
                break
        while True:
            w = self.word()
            if w in PREPOSED_SUBS and (w not in L.PREPOSITIONS or self.clause_follows(1)):
                s.fronted.append(self.preposed_sub())
            elif w in L.PREPOSITIONS and w != "because" or (w == "because" and self.word(1) == "of"):
                s.fronted.append(self.pp(in_subject=True, allow_pp=True))
                self.expect(",", "en preposisjonsfrase foran i setningen slutter med komma: in 2024, ...")
            elif self.np_start() and self.np_then(","):
                s.fronted.append(self.np(in_subject=True, allow_pp=True))
                self.advance()
            else:
                break

    def preposed_sub(self) -> SubClause:
        sub = self.advance().text
        body = self.complex(depth=0, stop_then=True, role="adverbial")
        if self.punct() == "," or self.word() == "then":
            self.advance()
        else:
            raise self.error(f"«{sub} ...» foran hovedsetningen slutter med komma eller then: {sub} X, Y.")
        return SubClause(sub, body, preposed=True)

    # --------------------------------------------------------------- clauses

    def complex(self, depth: int, stop_then: bool = False, role: str = "main", level: int = 0) -> ClauseLike:
        """Clauses joined by connectives: and binds tighter than or/xor, which bind tighter than the rest."""
        if level == len(LEVELS):
            return self.unit(depth, stop_then, role)
        ops = LEVELS[level]
        node = self.complex(depth, stop_then, role, level + 1)
        while self.word() in ops and self.clause_follows(1):
            op = self.advance().text
            right = self.complex(depth, stop_then, role, level + 1)
            if isinstance(node, Complex) and node.op == op:
                node.parts.append(right)
            else:
                node = Complex(op, [node, right])
        return node

    def unit(self, depth: int, stop_then: bool = False, role: str = "main") -> ClauseLike:
        if self.punct() == "(" and self.bracket_is_clause():
            self.advance()
            inner = self.complex(depth=0)
            self.expect(")", "parentesen lukkes ikke: mangler «)»")
            return inner
        return self.clause(depth, stop_then, role)

    def clause(self, depth: int, stop_then: bool = False, role: str = "main") -> Clause:
        subject: Phrase | None = None
        if not self.is_pmark():
            if not self.np_start():
                tok = self.tok()
                found = tok.text or "slutten"
                raise self.error(f"ventet et subjekt eller en markør (li, pa, fu, must ...), fant «{found}»")
            subject = self.np(in_subject=True, allow_pp=True)
            if not self.is_pmark():
                if self.is_bare_subject(subject) and self.implicit_start():
                    first = self.predicate_rest("li", None, None, False, self.tok())
                    first.implicit = True
                    return self.chain(Clause(subject, [first], role), depth, stop_then)
                tok = self.tok()
                found = tok.text or "slutten"
                if self.word() in L.ADVERBS and (self.is_pmark(1) or self.is_pmark(2)):
                    raise self.error(
                        f"«{found}» står mellom markøren og hovedordet: li {found} ..., ikke {found} li ..."
                    )
                raise self.error(
                    f"subjektet trenger en markør etter seg: li (nå), pa (fortid), fu (fremtid) "
                    f"eller must/should/may/can/would. Fant «{found}»"
                )
        return self.chain(Clause(subject, [self.predicate(link=None)], role), depth, stop_then)

    def chain(self, clause: Clause, depth: int, stop_then: bool) -> Clause:
        """More predicates for the same subject: a bare marker, and/or/but/so + marker, or then."""
        predicates = clause.predicates
        while True:
            w = self.word()
            if self.is_pmark():
                if depth > 0:
                    break  # a bare marker closes an embedded clause; the next predicate belongs outside
                predicates.append(self.predicate(link=None))
            elif w in PREDICATE_LINKS and self.is_pmark(1):
                self.advance()
                predicates.append(self.predicate(link=w))
            elif w == "and" and self.word(1) == "then" and not stop_then:
                self.advance()
                self.advance()
                predicates.append(self.then_predicate(predicates[-1]))
            elif w == "then" and not stop_then:
                self.advance()
                predicates.append(self.then_predicate(predicates[-1]))
            else:
                break
        return clause

    def pmark(self) -> tuple[str | None, str | None]:
        tense = modal = None
        if self.word() in L.TENSES:
            tense = self.advance().text
            if self.word() in L.MODALS:
                modal = self.advance().text
        elif self.word() in L.MODALS:
            modal = self.advance().text
        else:
            raise self.error("ventet en markør: li, pa, fu, must, should, may, can eller would")
        if self.is_pmark():
            raise self.error("to markører etter hverandre; bare tid foran modal er lov: pa can")
        return tense, modal

    def predicate(self, link: str | None) -> Predicate:
        tok = self.tok()
        tense, modal = self.pmark()
        return self.predicate_rest(tense, modal, link, False, tok)

    def then_predicate(self, previous: Predicate) -> Predicate:
        tok = self.tok()
        if self.is_pmark():
            tense, modal = self.pmark()
            return self.predicate_rest(tense, modal, "then", False, tok)
        return self.predicate_rest(previous.tense, previous.modal, "then", True, tok)

    def predicate_rest(
        self, tense: str | None, modal: str | None, link: str | None, inherited: bool, tok: Token
    ) -> Predicate:
        adverbs = []
        while self.word() in L.ADVERBS:
            adverbs.append(self.advance().text)
        p = Predicate(tense, modal, link, inherited, adverbs, "verbal", None, line=tok.line, col=tok.col)
        w = self.word()
        if w == "a":
            self.advance()
            p.kind = "nominal"
            if not self.np_start():
                raise self.error("«a» trenger en substantivfrase etter seg: li a programming language")
            p.head = self.np(in_subject=False, allow_pp=False)
        elif w in L.DETERMINERS or w in L.POSSESSIVES:
            p.kind = "nominal"
            p.head = self.np(in_subject=False, allow_pp=False)
        elif w in L.PREPOSITIONS and not (w in L.SUBORDINATORS and self.clause_follows(1)):
            p.kind = "locative"
            p.head = self.pp(in_subject=False)
        elif self.tok().kind == "NUM" and self.is_content(1):
            p.kind = "nominal"  # "li 100 request per minute": a number starts a noun phrase
            p.head = self.np(in_subject=False, allow_pp=False)
        elif self.is_head_word():
            p.head = self.head_word()
            p.complement = self.complement()
        elif self._gap_allowed():
            p.head = None  # the gap of an embedded question: "must ask when meeting li"
        else:
            tok = self.tok()
            found = tok.text or "slutten"
            raise self.error(
                f"etter markøren kommer et hovedord (verb, adjektiv, substantiv), fant «{found}»"
            )
        p.dependents = self.dependents()
        return p

    def _gap_allowed(self) -> bool:
        tok = self.tok()
        ends = tok.kind == "EOF" or (tok.kind == "PUNCT" and tok.text in TERMINATORS | {",", ")"})
        return ends or self.word() in L.CONNECTIVES or self.is_pmark()

    def head_word(self) -> Word:
        tok = self.advance()
        kinds = {
            "NAME": "name",
            "NUM": "num",
            "STR": "str",
            "CODE": "code",
            "IDENT": "code",
            "LABEL": "label",
        }
        if tok.kind in kinds:
            return Word(tok.text, kinds[tok.kind], tok.line, tok.col)
        w = tok.text
        if w in L.PRONOUNS:
            kind = "pronoun"
        elif w in L.WH_PRONOUNS:
            kind = "wh"
        elif w in L.ADVERBIAL_WORDS:
            kind = "adverbial"
        else:
            kind = "word"
        return Word(w, kind, tok.line, tok.col)

    def complement(self) -> Phrase | Embedded | None:
        w = self.word()
        if w == "that":
            self.advance()
            return Embedded("that", "that", self.embedded_body())
        if w == "whether":
            self.advance()
            return Embedded("whether", "whether", self.embedded_body())
        how_many = w == "how" and self.word(1) in ("many", "much")
        if w in L.WH_PRONOUNS and not how_many and self.clause_follows(1):
            self.advance()
            return Embedded("wh", w, self.embedded_body())
        if (w == "which" or how_many) and self.np_then_pmark(0):
            word = "which" if w == "which" else f"how {self.word(1)}"
            return Embedded("which", word, self.clause(depth=1, role="complement"))
        if self.np_start() and w not in L.ADVERBIAL_WORDS:
            return self.np(in_subject=False, allow_pp=False)
        return None

    def embedded_body(self) -> ClauseLike:
        if self.punct() == "(" and self.bracket_is_clause():
            return self.unit(depth=0)
        return self.clause(depth=1, role="complement")  # its errors say what is missing

    def dependents(self) -> list[PrepPhrase | SubClause | Embedded | Word]:
        deps: list[PrepPhrase | SubClause | Embedded | Word] = []
        while True:
            w = self.word()
            if w in ("because", "instead") and self.word(1) == "of":
                deps.append(self.pp(in_subject=False))
            elif w in L.SUBORDINATORS:
                if w in L.PREPOSITIONS and not self.clause_follows(1):
                    deps.append(self.pp(in_subject=False))
                elif not self.clause_follows(1):
                    if w not in L.WH_PRONOUNS:
                        raise self.error(f"«{w}» trenger en setning etter seg")
                    tok = self.advance()
                    deps.append(Word(w, "wh", tok.line, tok.col))  # question word in place: pa leave when?
                else:
                    self.advance()
                    body = self.unit(depth=1, role="adverbial")
                    deps.append(SubClause(w, body, preposed=False))
            elif w in L.PREPOSITIONS and w not in ("because", "instead"):
                deps.append(self.pp(in_subject=False))
            elif w in ("that", "whether"):
                self.advance()  # a clause after the object: "must ask user whether file li ready"
                deps.append(Embedded(w, w, self.embedded_body()))
            elif w in ("what", "who", "why", "how") and self.clause_follows(1):
                self.advance()
                deps.append(Embedded("wh", w, self.embedded_body()))
            elif w in L.ADVERBIAL_WORDS:
                tok = self.advance()
                deps.append(Word(w, "adverbial", tok.line, tok.col))
            elif w in L.WH_PRONOUNS and not self.clause_follows(1):
                tok = self.advance()
                deps.append(Word(w, "wh", tok.line, tok.col))
            else:
                return deps

    def pp(self, in_subject: bool, allow_pp: bool = False) -> PrepPhrase:
        prep = self.advance().text
        if prep in ("because", "instead"):
            self.expect("of", f"«{prep}» brukes bare som «{prep} of»")
            prep += " of"
        if not self.np_start():
            raise self.error(f"«{prep}» trenger en frase etter seg")
        return PrepPhrase(prep, self.np(in_subject=in_subject, allow_pp=allow_pp))

    # ----------------------------------------------------------- noun phrases

    def np(self, in_subject: bool, allow_pp: bool, level: int = 0) -> Phrase:
        """Noun phrases joined by and (tighter) and or/xor."""
        if level == 2:
            return self.np_unit(in_subject, allow_pp)
        ops = ("or", "xor") if level == 0 else ("and",)
        first = self.np(in_subject, allow_pp, level + 1)
        items = [first]
        op = None
        while self.word() in ops and self._coordination_continues(in_subject):
            w = self.advance().text
            if op and w != op:
                raise self.error("bland ikke or og xor i samme liste; grupper med ( )")
            op = w
            items.append(self.np(in_subject, allow_pp, level + 1))
        return first if len(items) == 1 else Coordination(op, items)

    def _coordination_continues(self, in_subject: bool) -> bool:
        """After and/or/xor: does a noun phrase follow that belongs to the same list?

        Before the predicate (in a subject) it always does. After it, "and X li ..." starts a new clause.
        """
        if not self.np_start(1) or self.is_pmark(1) or self.word(1) == "then":
            return False
        return in_subject or not self.np_then_pmark(1)

    def _words_np(self, det: str | None) -> NounPhrase:
        words: list[Word] = []
        if det is None and self.word() in L.ADVERBIAL_WORDS:
            t = self.advance()
            words.append(Word(t.text, "adverbial", t.line, t.col))
        else:
            while self.is_content():
                t = self.advance()
                kind = {"NAME": "name", "NUM": "num", "STR": "str", "CODE": "code", "IDENT": "code"}.get(
                    t.kind, "word"
                )
                words.append(Word(t.text, kind, t.line, t.col))
        if not words and det is None:
            found = self.tok().text or "slutten"
            raise self.error(f"ventet en substantivfrase, fant «{found}»")
        return NounPhrase("words" if words else "det", words=words, det=det)

    def np_unit(self, in_subject: bool, allow_pp: bool) -> NounPhrase:
        tok = self.tok()
        focus = None
        if self.word() in L.NP_FOCUS and self.np_start(1) and self.word(1) not in L.NP_FOCUS:
            focus = self.advance().text
        w = self.word()
        if self.punct() == "(":
            self.advance()
            inner = self.np(in_subject=True, allow_pp=True)
            self.expect(")", "parentesen lukkes ikke: mangler «)»")
            np = NounPhrase("group", group=inner)
        elif w in L.PRONOUNS:
            self.advance()
            np = NounPhrase("pronoun", ref=w)
        elif self.tok().kind == "LABEL":
            np = NounPhrase("label", ref=self.advance().text)
        elif w in L.WH_PRONOUNS and not (w == "how" and self.word(1) in ("many", "much")):
            self.advance()
            np = NounPhrase("wh", ref=w)
        elif w == "how" and self.word(1) in ("many", "much"):
            self.advance()
            det = "how " + self.advance().text
            np = self._words_np(det)
        else:
            det = None
            if w in L.DETERMINERS or w in L.POSSESSIVES:
                det = self.advance().text
            np = self._words_np(det)
        np.focus = focus
        np.line, np.col = tok.line, tok.col
        if np.kind in ("words", "group") and self.tok().kind == "LABEL" and self.punct(1) != ":":
            np.label = self.advance().text
        while self.word() == "of" and self.np_start(1):
            self.advance()
            np.of.append(self.np_unit(in_subject, allow_pp=False))
        if self.word() == "which" and self.clause_follows(1):
            self.advance()
            np.relative = self.clause(depth=1, role="relative")
        if allow_pp:
            while True:
                w = self.word()
                if w in ("because", "instead") and self.word(1) == "of":
                    np.pps.append(self.pp(in_subject))
                elif w in L.PREPOSITIONS and w not in ("because", "instead"):
                    if w in L.SUBORDINATORS and self.clause_follows(1):
                        break
                    np.pps.append(self.pp(in_subject))
                else:
                    break
        return np
