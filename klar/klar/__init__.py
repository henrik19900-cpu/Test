"""Klar: a compact, unambiguous written language for AI messages. See README.md."""

from .gloss import References, features, gloss_sentence, gloss_text, to_data
from .lexer import KlarError, tokenize
from .parser import parse, parse_sentence

__version__ = "1.0.0"
__all__ = [
    "KlarError",
    "References",
    "features",
    "gloss_sentence",
    "gloss_text",
    "parse",
    "parse_sentence",
    "to_data",
    "tokenize",
]
