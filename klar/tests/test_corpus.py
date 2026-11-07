"""Every Klar text in the benchmark corpus is valid."""

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
