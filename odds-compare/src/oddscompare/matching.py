"""Which Norsk Tipping match is which reference match.

Two matches are the same when both team names match after normalisation and the kick-off times
are within ± match_window_minutes. A name matches when:

1. its normalised form is the same (lower case, ø → o, å → a, æ → ae, other accents dropped,
   full stops removed, & read as «and», other punctuation as a space, and club-form words such as
   «FK», «IL», «FC», «BK» removed: see STRIP_WORDS), or
2. the alias table (data/team_aliases.yaml) maps both to the same canonical name, or
3. one is the other with words added («Oviedo» / «Real Oviedo», «Olympiakos» / «Olympiakos
   Piraeus»), scored 95, unless the added words mark another side of the club (II, U21, women), or
4. as a fall-back, rapidfuzz scores the two at fuzzy_accept (90) or more. Matches that score
   from fuzzy_suggest (80) up to that are not used, but logged as suggestions for the alias table.

Home and away must line up: a match with the teams the other way round is not the same match.
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

import yaml
from rapidfuzz import fuzz

from .sources import EventFilter

# Words for the club's legal form, which feeds use or leave out at will. The specification names the
# first four; the others are their Swedish, Danish, English, Spanish, Italian and German counterparts,
# without which most Swedish clubs would need an alias («Hammarby» / «Hammarby IF»).
STRIP_WORDS = frozenset(
    {"fk", "il", "fc", "bk"}
    | {"if", "ik", "ifk", "ff", "aif", "sk", "is", "fotball", "afc", "cf", "ud", "cd", "ca"}
    | {"sc", "ac", "as", "ssc", "rc", "osc", "sv", "vfb", "vfl"}
)
# Letters that Unicode does not split into a base letter and an accent.
_LETTERS = str.maketrans(
    {"ø": "o", "Ø": "o", "å": "a", "Å": "a", "æ": "ae", "Æ": "ae", "ß": "ss", "ł": "l", "Ł": "l"}
    | {"đ": "d", "Đ": "d", "ð": "d", "Ð": "d", "ı": "i", "œ": "oe", "Œ": "oe", "þ": "th", "Þ": "th"}
)
_YEAR = re.compile(r"\b(18|19|20)\d\d\b")  # founding years in names: «VfL 1899 Osnabrück», «Como 1907»
# Words that make a name another side of the club, so «Hoffenheim II» never matches «Hoffenheim».
OTHER_SIDES = frozenset(
    {"ii", "iii", "b", "w", "women", "woman", "ladies", "fem", "femenino", "feminine", "dff", "dam", "damer"}
    | {"kvinner", "u17", "u18", "u19", "u20", "u21", "u23", "reserves", "res", "youth", "jong"}
)
SUBSET_SCORE = 95.0


class Fixture(Protocol):
    """What matching needs to know about a match; RawEvent has it."""

    source_event_id: str
    home: str
    away: str
    kickoff_utc: datetime


def normalize(name: str) -> str:
    text = unicodedata.normalize("NFKD", name.translate(_LETTERS).lower())
    text = "".join(c for c in text if not unicodedata.combining(c)).replace(".", "").replace("&", " and ")
    words = re.sub(r"[^a-z0-9]+", " ", _YEAR.sub(" ", text)).split()
    kept = [w for w in words if w not in STRIP_WORDS]
    return " ".join(kept or words)  # a name that is only «FC» stays «fc»


class Aliases:
    """Variants mapped to one canonical name, from YAML: {canonical name: [variant, ...]}."""

    def __init__(self, table: dict[str, list[str]] | None = None):
        self._canonical: dict[str, str] = {}
        for canonical, variants in (table or {}).items():
            target = normalize(canonical)
            for name in [canonical, *(variants or [])]:
                self._canonical[normalize(name)] = target

    @classmethod
    def load(cls, path: str | Path) -> Aliases:
        path = Path(path)
        if not path.exists():
            return cls()
        table = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(table, dict):
            raise ValueError(f"{path}: expected a mapping of canonical name to a list of variants")
        return cls({str(k): [str(v) for v in (vs or [])] for k, vs in table.items()})

    def canonical(self, name: str) -> str:
        normalized = normalize(name)
        return self._canonical.get(normalized, normalized)

    def __len__(self) -> int:
        return len(self._canonical)


@dataclass
class Unmatched:
    event: Fixture
    best: Fixture | None = None
    score: float | None = None
    swapped: bool = False  # the best candidate has the same teams, but home and away the other way round


@dataclass
class MatchResult:
    pairs: list[tuple[Fixture, Fixture, float]] = field(default_factory=list)  # (anchor, other, score)
    unmatched: list[Unmatched] = field(default_factory=list)

    @property
    def rate(self) -> float:
        total = len(self.pairs) + len(self.unmatched)
        return len(self.pairs) / total if total else 1.0


class Matcher:
    def __init__(
        self,
        aliases: Aliases | None = None,
        window: timedelta = timedelta(minutes=30),
        accept: float = 90,
        suggest: float = 80,
    ):
        self.aliases = aliases or Aliases()
        self.window = window
        self.accept = accept
        self.suggest = suggest
        self._names: dict[str, str] = {}

    def team_score(self, a: str, b: str) -> float:
        ca, cb = self._canonical(a), self._canonical(b)
        if ca == cb:
            return 100.0
        score = fuzz.token_sort_ratio(ca, cb)
        wa, wb = set(ca.split()), set(cb.split())
        if (wa ^ wb) & OTHER_SIDES:
            return min(score, 50.0)  # «Rosenborg» and «Rosenborg W» are alike as text, but not the same team
        if (wa <= wb or wb <= wa) and len(min(ca, cb, key=len)) >= 4:
            return max(score, SUBSET_SCORE)
        return score

    def pair_score(self, anchor: Fixture, other: Fixture) -> tuple[float, bool]:
        """How alike two matches' teams are (the lower of the two names), and whether they are swapped."""
        straight = min(self.team_score(anchor.home, other.home), self.team_score(anchor.away, other.away))
        if straight >= self.accept:
            return straight, False
        crossed = min(self.team_score(anchor.home, other.away), self.team_score(anchor.away, other.home))
        return straight, crossed >= self.accept

    def match(self, anchors: list[Fixture], others: list[Fixture]) -> MatchResult:
        """Pair every anchor with at most one other match, best scores first."""
        index = _TimeIndex(others)
        scored = []
        best: dict[int, tuple[float, int, bool]] = {}
        for a, anchor in enumerate(anchors):
            for o in index.near(anchor.kickoff_utc, self.window):
                score, swapped = self.pair_score(anchor, others[o])
                scored.append((score, a, o))
                if a not in best or score > best[a][0] or (swapped and not best[a][2]):
                    best[a] = (score, o, swapped)
        result = MatchResult()
        taken_anchors, taken_others = set(), set()
        for score, a, o in sorted(scored, key=lambda s: -s[0]):
            if score < self.accept:
                break
            if a in taken_anchors or o in taken_others:
                continue
            taken_anchors.add(a)
            taken_others.add(o)
            result.pairs.append((anchors[a], others[o], score))
        for a, anchor in enumerate(anchors):
            if a in taken_anchors:
                continue
            if a in best:
                score, o, swapped = best[a]
                result.unmatched.append(Unmatched(anchor, others[o], score, swapped))
            else:
                result.unmatched.append(Unmatched(anchor))
        return result

    def worth_fetching(self, anchors: list[Fixture]) -> EventFilter:
        """A filter for the reference source: keep matches that may match an anchor, near misses included."""
        index = _TimeIndex(anchors)

        class _Probe:
            def __init__(self, home: str, away: str, kickoff: datetime):
                self.source_event_id, self.home, self.away, self.kickoff_utc = "", home, away, kickoff

        def want(home: str, away: str, kickoff: datetime) -> bool:
            probe = _Probe(home, away, kickoff)
            return any(
                self.pair_score(anchors[a], probe)[0] >= self.suggest
                for a in index.near(kickoff, self.window)
            )

        return want

    def _canonical(self, name: str) -> str:
        if name not in self._names:
            self._names[name] = self.aliases.canonical(name)
        return self._names[name]


class _TimeIndex:
    """Positions of matches by kick-off, to find those within a window quickly."""

    def __init__(self, fixtures: list[Fixture]):
        order = sorted(range(len(fixtures)), key=lambda i: fixtures[i].kickoff_utc)
        self._times = [fixtures[i].kickoff_utc for i in order]
        self._order = order

    def near(self, moment: datetime, window: timedelta) -> list[int]:
        start = bisect.bisect_left(self._times, moment - window)
        end = bisect.bisect_right(self._times, moment + window)
        return self._order[start:end]
