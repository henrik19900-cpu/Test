"""The documentation matches the language: every example parses, and the word lists are complete."""

import re
from pathlib import Path

import pytest

from klar import doc, lexicon
from klar.lint import check

DOCS = Path(__file__).resolve().parents[1] / "docs"
PRIMERS = sorted(DOCS.glob("primer.*.md"))


def klar_blocks(path: Path) -> list[str]:
    return re.findall(r"```klar\n(.*?)```", path.read_text(encoding="utf-8"), flags=re.S)


ALL_DOCS = sorted(DOCS.glob("*.md")) + [DOCS.parent / "README.md", DOCS.parent / "eval" / "README.md"]


@pytest.mark.parametrize("path", ALL_DOCS, ids=lambda p: p.name)
def test_klar_code_blocks_parse(path):
    for block in klar_blocks(path):
        errors = [str(i) for i in check(block)[1] if i.level == "error"]
        assert errors == [], block


def test_spec_has_klar_examples():
    assert len(klar_blocks(DOCS / "spesifikasjon.md")) >= 10


def test_spec_word_list_is_up_to_date():
    text = (DOCS / "spesifikasjon.md").read_text(encoding="utf-8")
    assert doc.updated(text) == text, "kjør python -m klar.doc"


@pytest.mark.parametrize("path", PRIMERS, ids=lambda p: p.name)
def test_primer_examples_parse(path):
    text = path.read_text(encoding="utf-8")
    examples = [s for s in re.findall(r"`([^`]+)`", text) if len(s.split()) > 1 and s.rstrip()[-1] in ".?"]
    assert len(examples) > 30
    for example in examples:
        errors = [str(i) for i in check(example)[1] if i.level == "error"]
        assert errors == [], example


@pytest.mark.parametrize("path", PRIMERS, ids=lambda p: p.name)
def test_primer_mentions_every_grammar_word(path):
    words = set(re.findall(r"[A-Za-z]+", path.read_text(encoding="utf-8")))
    assert sorted(f for f in lexicon.ALL_FORMS if f not in words) == []


MARKDOWN = sorted(
    p
    for p in DOCS.parent.rglob("*.md")
    if not any(part.startswith(".") for part in p.relative_to(DOCS.parent).parts)
)


def slug(heading: str) -> str:
    """The anchor GitHub gives a heading: lower case, punctuation removed, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


@pytest.mark.parametrize("path", MARKDOWN, ids=lambda p: str(p.relative_to(DOCS.parent)))
def test_links_between_documents_resolve(path):
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"[a-z]+:", target):
            continue
        file, _, anchor = target.partition("#")
        linked = (path.parent / file).resolve() if file else path
        assert linked.exists(), f"{target}: finnes ikke"
        if anchor and linked.suffix == ".md":
            headings = re.findall(r"^#+ (.+)$", linked.read_text(encoding="utf-8"), flags=re.M)
            assert anchor in {slug(h) for h in headings}, f"{target}: ingen overskrift med det ankeret"
