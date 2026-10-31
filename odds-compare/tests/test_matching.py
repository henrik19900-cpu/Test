from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import load_fixture, raw_event

from oddscompare.matching import Aliases, Matcher, normalize
from oddscompare.sources.nt import parse_event_groups
from oddscompare.sources.reference import parse_odds

ALIASES = Path(__file__).parents[1] / "data" / "team_aliases.yaml"
KICKOFF = datetime(2026, 11, 1, 15, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Bodø/Glimt", "bodo glimt"),
        ("Bodo Glimt", "bodo glimt"),
        ("FK Bodø/Glimt", "bodo glimt"),
        ("Vålerenga", "valerenga"),
        ("Stabæk IF", "stabaek"),
        ("Rosenborg BK", "rosenborg"),
        ("Tromsø IL", "tromso"),
        ("FC Porto", "porto"),
        ("St. Pauli", "st pauli"),
        ("Atlético Madrid", "atletico madrid"),
        ("Malmö FF", "malmo"),
        ("Brighton & Hove Albion", "brighton and hove albion"),
        ("  Lyn ", "lyn"),
        ("FC", "fc"),  # a name that is only a club-form word is kept
    ],
)
def test_normalize(name, expected):
    assert normalize(name) == expected


def test_aliases_map_variants_to_one_name():
    aliases = Aliases({"Bodø/Glimt": ["Bodo Glimt"], "Wolverhampton Wanderers": ["Wolves"]})
    assert aliases.canonical("Wolves") == aliases.canonical("Wolverhampton Wanderers")
    assert aliases.canonical("FK Bodø/Glimt") == aliases.canonical("Bodo Glimt")
    assert aliases.canonical("Molde") == "molde"  # unknown names stay as normalised


def test_alias_file_loads(tmp_path):
    assert len(Aliases.load(ALIASES)) > 50
    assert len(Aliases.load(tmp_path / "missing.yaml")) == 0
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Aliases.load(bad)


def nt(home, away, minutes=0, sid=None):
    return raw_event(
        source_event_id=sid or f"{home}-{away}",
        home=home,
        away=away,
        kickoff_utc=KICKOFF + timedelta(minutes=minutes),
    )


def ref(home, away, minutes=0, sid=None):
    return raw_event(
        source="odds_api_io", source_event_id=sid or f"r-{home}-{away}", home=home, away=away,
        kickoff_utc=KICKOFF + timedelta(minutes=minutes),
    )  # fmt: skip


def test_same_teams_within_the_window_match():
    matcher = Matcher()
    result = matcher.match(
        [nt("Fredrikstad", "Rosenborg")], [ref("Fredrikstad FK", "Rosenborg BK", minutes=25)]
    )
    assert len(result.pairs) == 1 and result.pairs[0][2] == 100


def test_kickoff_outside_the_window_does_not_match():
    result = Matcher().match([nt("Fredrikstad", "Rosenborg")], [ref("Fredrikstad", "Rosenborg", minutes=31)])
    assert result.pairs == []
    assert result.unmatched[0].best is None


def test_home_and_away_swapped_is_not_a_match():
    result = Matcher().match([nt("GAIS", "AIK")], [ref("AIK", "GAIS")])
    assert result.pairs == []
    assert result.unmatched[0].swapped


def test_the_right_direction_wins_over_a_swapped_twin():
    result = Matcher().match(
        [nt("GAIS", "AIK")], [ref("AIK", "GAIS", sid="swapped"), ref("GAIS", "AIK", sid="right")]
    )
    assert [other.source_event_id for _, other, _ in result.pairs] == ["right"]


def test_fuzzy_match_from_90():
    matcher = Matcher()
    score = matcher.team_score("Djurgården IF", "Djurgardens IF")
    assert 90 <= score < 100
    assert (
        len(matcher.match([nt("Djurgården IF", "Degerfors IF")], [ref("Djurgardens IF", "Degerfors")]).pairs)
        == 1
    )


def test_near_miss_between_80_and_90_is_logged_not_used():
    matcher = Matcher()
    assert 80 <= matcher.team_score("Odd", "Odds BK") < 90
    result = matcher.match([nt("Odd", "Sandnes Ulf")], [ref("Odds BK", "Sandnes Ulf")])
    assert result.pairs == []
    assert result.unmatched[0].best.home == "Odds BK"
    assert 80 <= result.unmatched[0].score < 90
    # With the alias it is a match.
    with_alias = Matcher(Aliases({"Odd": ["Odds BK"]}))
    assert len(with_alias.match([nt("Odd", "Sandnes Ulf")], [ref("Odds BK", "Sandnes Ulf")]).pairs) == 1


def test_different_clubs_from_one_city_do_not_match():
    matcher = Matcher()
    assert matcher.team_score("Manchester United", "Manchester City") < 80
    assert Matcher().match([nt("Manchester United", "Roma")], [ref("Manchester City", "Roma")]).pairs == []


def test_each_reference_match_is_used_once():
    result = Matcher().match(
        [nt("Molde", "Brann", sid="a"), nt("Molde", "Brann", minutes=5, sid="b")], [ref("Molde", "Brann")]
    )
    assert len(result.pairs) == 1 and len(result.unmatched) == 1


def test_worth_fetching_keeps_matches_and_near_misses_only():
    want = Matcher().worth_fetching([nt("Odd", "Sandnes Ulf"), nt("Fredrikstad", "Rosenborg")])
    assert want("Fredrikstad FK", "Rosenborg BK", KICKOFF)
    assert want("Odds BK", "Sandnes Ulf", KICKOFF)  # near miss: its name is needed for the suggestion
    assert not want("Hamburger SV", "Werder Bremen", KICKOFF)
    assert not want("Fredrikstad", "Rosenborg", KICKOFF + timedelta(hours=1))


def fixture_events():
    nt_sample = load_fixture("nt_sample.json")
    ref_sample = load_fixture("odds_api_io_sample.json")
    now = datetime.fromisoformat(nt_sample["fetched_at_utc"])
    return parse_event_groups(nt_sample["event_groups"], now, 14), parse_odds(
        ref_sample["odds"], ref_sample["bookmaker"]
    )


def test_at_least_95_percent_of_the_fixture_matches():
    """Acceptance criterion: matching finds at least 95 % of Norsk Tipping's matches in the fixtures."""
    nt_events, ref_events = fixture_events()
    assert len(nt_events) == 88
    result = Matcher(Aliases.load(ALIASES)).match(nt_events, ref_events)
    assert result.rate >= 0.95, [f"{u.event.home} - {u.event.away}" for u in result.unmatched]
    for anchor, other, _ in result.pairs:  # and every pair is right: same kick-off give or take 30 minutes
        assert abs(anchor.kickoff_utc - other.kickoff_utc) <= timedelta(minutes=30)
    names = {(a.home.strip(), o.home) for a, o, _ in result.pairs}
    assert ("GAIS", "GAIS") in names and ("IK Sirius", "IK Sirius") in names  # not the swapped twins
