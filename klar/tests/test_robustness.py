"""The parser never crashes or hangs: any input gives a tree or a KlarError."""

import random

from klar import parse
from klar.lexicon import ALL_FORMS

VOCAB = sorted(ALL_FORMS) + [
    "user",
    "file",
    "big",
    "Oslo",
    "U",
    "F",
    "5MB",
    "x.py",
    "(",
    ")",
    ",",
    ":",
    "=",
    ".",
]


def test_random_word_salad_never_crashes():
    rng = random.Random(7)
    for _ in range(3000):
        words = [rng.choice(VOCAB) for _ in range(rng.randint(1, 14))]
        text = " ".join(words) + rng.choice([".", "?", ""])
        result = parse(text)  # must not raise anything but return errors
        assert len(result.sentences) + len(result.errors) >= 1 or not text.strip(" .?")


def test_weird_characters_do_not_crash():
    for text in ["!!!", "user pa ; test.", "{a} [b].", "ø æ å.", "", "   ", "....", "((((", "`unclosed"]:
        parse(text)
