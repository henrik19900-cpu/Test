"""Every Klar text in the benchmark corpus is valid, and the compressed versions cover it."""

import json
from pathlib import Path

import pytest
import yaml

from klar.lint import check

ROOT = Path(__file__).resolve().parents[1]
CORPUS = yaml.safe_load((ROOT / "bench" / "corpus.yaml").read_text(encoding="utf-8"))
ENTRIES = CORPUS["items"] + CORPUS["passages"]


@pytest.mark.parametrize("entry", ENTRIES, ids=[e["id"] for e in ENTRIES])
def test_corpus_entry_is_clean_klar(entry):
    text, issues = check(entry["klar"])
    assert issues == [], [str(i) for i in issues]
    assert {"en", "tele", "nb", "klar", "category"} <= set(entry)


def test_corpus_ids_are_unique():
    ids = [e["id"] for e in ENTRIES]
    assert len(ids) == len(set(ids))


EXAMPLES = sorted((ROOT / "eksempler").glob("*.klar"))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_are_clean(path):
    strict = path.name == "agentrapport.klar"
    _, issues = check(path.read_text(encoding="utf-8"), strict=strict)
    assert issues == [], [str(i) for i in issues]


def test_kort_covers_the_corpus():
    kort = yaml.safe_load((ROOT / "bench" / "kort.yaml").read_text(encoding="utf-8"))
    facts = yaml.safe_load((ROOT / "eval" / "kort" / "facts.yaml").read_text(encoding="utf-8"))
    ids = {e["id"] for e in ENTRIES}
    assert set(kort) == ids and set(facts) == ids
    versions = ("kort", "kort_v3", "kort500", "kort200")
    assert all(all(v[name] for name in versions) for v in kort.values())


@pytest.mark.parametrize(
    "path", sorted((ROOT / "eval" / "kort" / "decoded").glob("*.json")), ids=lambda p: p.stem
)
def test_every_decoded_version_covers_the_corpus(path):
    decoded = json.loads(path.read_text(encoding="utf-8"))
    assert set(decoded) == {e["id"] for e in ENTRIES}
    assert all(isinstance(t, str) and t.strip() for t in decoded.values())


@pytest.mark.parametrize(("version", "most"), [("kort500", 499), ("kort200", 200)])
def test_budget_versions_hold_in_every_tokenizer(version, most):
    # Kort-500 is under 500 tokens and Kort-200 at most 200, in each of the eight tokenizers.
    # bench/run.py writes the counts; rerun it after changing bench/kort.yaml.
    results = json.loads((ROOT / "bench" / "results.json").read_text(encoding="utf-8"))
    ids = [e["id"] for e in ENTRIES]
    for name in results["tokenizers"]:
        total = sum(results["compressed"][i][version][name] for i in ids)
        assert total <= most, f"{version} in {name}: {total} tokens"
