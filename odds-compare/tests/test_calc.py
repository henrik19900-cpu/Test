import pytest

from oddscompare import calc

ODDS_TOLERANCE = 0.005
PERCENT_TOLERANCE = 0.1  # percentage points

# The two cases from the specification: reference odds, Norsk Tipping's odds, and what they give.
CASES = [
    pytest.param(
        (2.10, 3.40, 3.70),
        (2.05, 3.10, 3.30),
        (2.19, 3.54, 3.85),
        11.3,
        (-6.2, -12.4, -14.3),
        id="home-favourite",
    ),
    pytest.param(
        (1.80, 3.80, 4.60), (1.70, 3.70, 4.90), (1.86, 3.94, 4.77), 6.3, (-8.8, -6.0, 2.8), id="value-on-away"
    ),
]


@pytest.mark.parametrize(("reference", "nt", "fair", "nt_margin", "ev"), CASES)
def test_specification_cases(reference, nt, fair, nt_margin, ev):
    assert calc.fair_odds(reference) == pytest.approx(fair, abs=ODDS_TOLERANCE)
    assert calc.margin(nt) * 100 == pytest.approx(nt_margin, abs=PERCENT_TOLERANCE)
    probabilities = calc.fair_probabilities(reference)
    assert [e * 100 for e in calc.expected_value(nt, probabilities)] == pytest.approx(
        ev, abs=PERCENT_TOLERANCE
    )


@pytest.mark.parametrize("method", calc.METHODS)
@pytest.mark.parametrize("odds", [(2.10, 3.40, 3.70), (1.25, 6.0, 12.0), (1.91, 1.91), (3.1, 3.2, 2.6)])
def test_fair_probabilities_sum_to_one(method, odds):
    probabilities = calc.fair_probabilities(odds, method)
    assert sum(probabilities) == pytest.approx(1.0, abs=1e-9)
    assert all(0 < p < 1 for p in probabilities)
    # The order of the outcomes is kept: the shortest price stays the most likely.
    assert sorted(range(len(odds)), key=lambda i: odds[i]) == sorted(
        range(len(odds)), key=lambda i: -probabilities[i]
    )


def test_power_solves_its_equation():
    odds = (1.25, 6.0, 12.0)
    implied = calc.implied_probabilities(odds)
    probabilities = calc.fair_probabilities(odds, "power")
    # p_i = q_i ** k with one k for every outcome.
    import math

    ks = [math.log(p) / math.log(q) for p, q in zip(probabilities, implied, strict=True)]
    assert max(ks) - min(ks) < 1e-9
    assert ks[0] > 1  # with a margin, k is above 1


@pytest.mark.parametrize("method", ["power", "shin"])
def test_power_and_shin_take_more_off_long_shots(method):
    odds = (1.25, 6.0, 12.0)
    proportional = calc.fair_probabilities(odds)
    other = calc.fair_probabilities(odds, method)
    assert other[0] > proportional[0]  # the favourite keeps more of its probability
    assert other[2] < proportional[2]  # the long shot loses more


def test_equal_odds_give_equal_probabilities_with_every_method():
    for method in calc.METHODS:
        assert calc.fair_probabilities((1.90, 1.90), method) == pytest.approx([0.5, 0.5])


def test_shin_without_margin_falls_back_to_proportional():
    odds = (2.10, 3.60, 4.20)  # sums to under 1, as on an exchange
    assert calc.margin(odds) < 0
    assert calc.fair_probabilities(odds, "shin") == pytest.approx(calc.fair_probabilities(odds))


def test_margin_of_a_fair_book_is_zero():
    assert calc.margin((2.0, 2.0)) == pytest.approx(0.0)


@pytest.mark.parametrize("odds", [(1.0, 3.0), (0.5, 2.0), (2.0,), (float("nan"), 2.0)])
def test_invalid_odds_are_refused(odds):
    with pytest.raises(ValueError):
        calc.fair_probabilities(odds)


def test_unknown_method_is_refused():
    with pytest.raises(ValueError, match="unknown margin method"):
        calc.fair_probabilities((2.0, 2.0), "magic")


def test_expected_value_needs_matching_lengths():
    with pytest.raises(ValueError):
        calc.expected_value((2.0, 2.0), (0.5,))
