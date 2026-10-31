"""Margin, fair probabilities and expected value. Pure functions without I/O.

All functions take decimal odds for every outcome of one market, in the same order, and return
lists in that order. Three ways to take the bookmaker's margin out are supported:

- proportional: every implied probability is scaled down by the same factor (the default).
- power: p_i = (1/o_i)^k, with k chosen so the probabilities sum to 1.
- shin: Shin's model, which assumes part of the margin protects against insiders.

Power and Shin take relatively more off long shots than off favourites, which matches the
favourite/long-shot bias in betting markets better than the proportional method.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

METHODS = ("proportional", "power", "shin")

_TOLERANCE = 1e-12
_MAX_ITERATIONS = 200


def implied_probabilities(odds: Sequence[float]) -> list[float]:
    """1/o for every outcome, margin included."""
    if len(odds) < 2:
        raise ValueError("a market needs at least two outcomes")
    for o in odds:
        if not math.isfinite(o) or o <= 1.0:
            raise ValueError(f"decimal odds must be above 1, got {o!r}")
    return [1.0 / o for o in odds]


def margin(odds: Sequence[float]) -> float:
    """The overround: the implied probabilities' sum minus 1 (0.113 is 11.3 %)."""
    return sum(implied_probabilities(odds)) - 1.0


def fair_probabilities(odds: Sequence[float], method: str = "proportional") -> list[float]:
    """The probabilities with the margin taken out; they sum to 1."""
    try:
        remove = _METHODS[method]
    except KeyError:
        raise ValueError(f"unknown margin method {method!r}, choose one of {', '.join(METHODS)}") from None
    return remove(implied_probabilities(odds))


def fair_odds(odds: Sequence[float], method: str = "proportional") -> list[float]:
    return [1.0 / p for p in fair_probabilities(odds, method)]


def expected_value(offered_odds: Sequence[float], probabilities: Sequence[float]) -> list[float]:
    """Expected profit per unit staked at the offered odds: o * p - 1 (0.028 is +2.8 %)."""
    if len(offered_odds) != len(probabilities):
        raise ValueError("odds and probabilities must cover the same outcomes")
    return [o * p - 1.0 for o, p in zip(offered_odds, probabilities, strict=True)]


def _proportional(implied: list[float]) -> list[float]:
    total = sum(implied)
    return [q / total for q in implied]


def _power(implied: list[float]) -> list[float]:
    # sum(q_i ** k) falls as k rises (every q_i is below 1), and is n - 1 > 0 above the root at k = 0.
    def excess(k: float) -> float:
        return sum(q**k for q in implied) - 1.0

    high = 2.0
    while excess(high) > 0:
        high *= 2
    k = _bisect(excess, 0.0, high)
    return [q**k for q in implied]


def _shin(implied: list[float]) -> list[float]:
    total = sum(implied)
    if total <= 1.0:
        # No margin to explain (it happens on exchanges), so Shin's insider share would be negative.
        return _proportional(implied)

    def probabilities(z: float) -> list[float]:
        return [(math.sqrt(z * z + 4 * (1 - z) * q * q / total) - z) / (2 * (1 - z)) for q in implied]

    # The sum is sqrt(total) > 1 at z = 0 and falls as z rises.
    z = _bisect(lambda z: sum(probabilities(z)) - 1.0, 0.0, 0.999)
    return probabilities(z)


def _bisect(f: Callable[[float], float], low: float, high: float) -> float:
    """The root of a falling function between low (f > 0) and high (f < 0)."""
    for _ in range(_MAX_ITERATIONS):
        middle = (low + high) / 2
        if f(middle) > 0:
            low = middle
        else:
            high = middle
        if high - low < _TOLERANCE:
            break
    return (low + high) / 2


_METHODS: dict[str, Callable[[list[float]], list[float]]] = {
    "proportional": _proportional,
    "power": _power,
    "shin": _shin,
}
