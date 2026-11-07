"""Split Klar text into tokens."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import lexicon


class KlarError(Exception):
    """A Klar text that does not follow the grammar. ``line`` and ``col`` are 1-based."""

    def __init__(self, message: str, line: int = 0, col: int = 0, hint: str = ""):
        self.message = message
        self.line = line
        self.col = col
        self.hint = hint
        where = f"{line}:{col}: " if line else ""
        super().__init__(f"{where}{message}" + (f" ({hint})" if hint else ""))


@dataclass(frozen=True)
class Token:
    kind: str  # WORD NAME LABEL NUM STR CODE IDENT PUNCT BAD EOF
    text: str
    line: int
    col: int
    start: int = 0  # offset in the text
    end: int = 0

    def __repr__(self) -> str:
        return f"{self.kind}:{self.text}"


_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<str>"[^"\n]*")
  | (?P<code>`[^`\n]*`)
  | (?P<num>-?\d+(?:[.:/-]\d+)*(?:%|[A-Za-z]+\b)?(?![./_]?[A-Za-z0-9_]))
  | (?P<ident>[A-Za-z0-9_-]+(?:[./][A-Za-z0-9_-]+)+(?:\(\))?|[A-Za-z0-9-]*_[A-Za-z0-9_-]*(?:\(\))?|[A-Za-z_][A-Za-z0-9_]*\(\))
  | (?P<word>[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*[+#]*)
  | (?P<punct>[.?,:=()])
  | (?P<bad>.)
    """,
    re.VERBOSE,
)

BAD_HINTS = {
    "'": "Klar har ikke apostrof: skriv «file of user», ikke «user's file», og «not», ikke «don't»",
    "!": "avslutt med . (påstand eller instruks) eller ? (spørsmål)",
    ";": "avslutt setningen med . eller bind sammen med and",
    "[": "bruk ( ) for å gruppere",
    "]": "bruk ( ) for å gruppere",
    "{": "bruk ( ) for å gruppere",
    "}": "bruk ( ) for å gruppere",
}

# Markdown that may wrap Klar text: headings, list bullets, numbered items and block quotes.
_MARKUP_LINE = re.compile(r"^(\s*)(#{1,6}\s.*|[-*+]\s|\d+[.)]\s|>\s?)", re.MULTILINE)


def strip_markup(text: str) -> str:
    """Blank out Markdown headings, bullets and quote marks, keeping every other character where it was."""

    def blank(m: re.Match[str]) -> str:
        return m.group(1) + " " * len(m.group(2))

    return _MARKUP_LINE.sub(blank, text)


def tokenize(text: str) -> list[Token]:
    text = strip_markup(text)
    tokens: list[Token] = []
    line, line_start = 1, 0
    sentence_start = True
    for m in _TOKEN.finditer(text):
        kind = m.lastgroup
        value = m.group()
        col = m.start() - line_start + 1
        if kind == "ws":
            newlines = value.count("\n")
            if newlines:
                line += newlines
                line_start = m.start() + value.rindex("\n") + 1
            continue
        if kind == "word":
            tok = _classify_word(value, line, col, sentence_start)
        else:
            tok = Token(kind.upper(), value, line, col)
        tok = Token(tok.kind, tok.text, line, col, m.start(), m.end())
        tokens.append(tok)
        sentence_start = tok.kind == "PUNCT" and tok.text in ".?:"
    tokens.append(Token("EOF", "", line, len(text) - line_start + 1, len(text), len(text)))
    return tokens


def _classify_word(value: str, line: int, col: int, sentence_start: bool) -> Token:
    if value in ("I", "i"):
        return Token("WORD", "I", line, col)
    if len(value) == 1 and value in lexicon.LABEL_LETTERS:
        return Token("LABEL", value, line, col)
    if value[0].isupper():
        lower = value.lower()
        # Models capitalize the first word of a sentence out of habit: "If file li big, ...". English
        # grammar words are lowered too, so that "The user ..." is reported as a slip, not read as a name.
        if sentence_start and (lower in lexicon.ALL_FORMS or lower in lexicon.ENGLISH_SLIPS):
            return Token("WORD", lower, line, col)
        return Token("NAME", value, line, col)
    return Token("WORD", value, line, col)
