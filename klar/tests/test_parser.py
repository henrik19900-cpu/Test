import pytest

from klar import KlarError, parse, parse_sentence, tokenize
from klar.nodes import Clause, Complex, Coordination, Embedded, NounPhrase, PrepPhrase, SubClause, Word


def clause(text: str) -> Clause:
    body = parse_sentence(text).body
    assert isinstance(body, Clause), body
    return body


# ------------------------------------------------------------------------------- tokens


def test_tokens_kinds():
    kinds = [(t.kind, t.text) for t in tokenize('user U pa send `x` "hi" config.yaml 5MB to GitHub.')][:-1]
    assert kinds == [
        ("WORD", "user"),
        ("LABEL", "U"),
        ("WORD", "pa"),
        ("WORD", "send"),
        ("CODE", "`x`"),
        ("STR", '"hi"'),
        ("IDENT", "config.yaml"),
        ("NUM", "5MB"),
        ("WORD", "to"),
        ("NAME", "GitHub"),
        ("PUNCT", "."),
    ]


def test_tokens_pronoun_i_is_not_a_label():
    assert [t.kind for t in tokenize("I li ready. i li ready.")][:-1] == ["WORD", "WORD", "WORD", "PUNCT"] * 2


def test_tokens_paths_numbers_and_times():
    text = "pa run src/app/main.py and find_order() at 14:30 on 2026-11-07 v2.0 3.5."
    texts = [t.text for t in tokenize(text)][:-1]  # without the end-of-text token
    assert "src/app/main.py" in texts and "find_order()" in texts
    assert "14:30" in texts and "2026-11-07" in texts and "v2.0" in texts and "3.5" in texts
    assert texts[-1] == "."


def test_first_word_capitalized_by_habit():
    s = parse_sentence("If file li big, must compress it.")
    assert s.fronted and isinstance(s.fronted[0], SubClause)


def test_markdown_bullets_and_headings_are_ignored():
    text = parse("# Regler\n\n- must answer short.\n- must not guess.\n1. should cite source.\n")
    assert not text.errors
    assert [s.is_directive for s in text.sentences] == [True, True, True]


# ------------------------------------------------------------------------------ clauses


@pytest.mark.parametrize(
    "text,tense,modal",
    [
        ("user li test system.", "li", None),
        ("user pa test system.", "pa", None),
        ("user fu test system.", "fu", None),
        ("user must test system.", None, "must"),
        ("user pa can test system.", "pa", "can"),
    ],
)
def test_markers(text, tense, modal):
    p = clause(text).predicates[0]
    assert (p.tense, p.modal) == (tense, modal)
    assert p.head.text == "test"
    assert p.complement.head == "system"


def test_predicate_kinds():
    assert clause("sky li blue.").predicates[0].kind == "verbal"
    nominal = clause("Python li a programming language.").predicates[0]
    assert nominal.kind == "nominal" and nominal.head.head == "language"
    loc = clause("user li in Oslo.").predicates[0]
    assert loc.kind == "locative" and loc.head.prep == "in"
    assert clause("rate limit li 100 request per minute.").predicates[0].kind == "nominal"


def test_li_implied_after_pronoun_or_label():
    p = clause("it not valid.").predicates[0]
    assert p.implicit and p.tense == "li" and p.adverbs == ["not"] and p.head.text == "valid"
    assert clause("U want copy of F.").predicates[0].implicit


def test_li_is_never_implied_after_a_content_word():
    with pytest.raises(KlarError, match="markør"):
        parse_sentence("user test system.")


def test_subjectless_clauses():
    directive = parse_sentence("must not use jargon.")
    assert directive.is_directive
    passive = parse_sentence("pa delete file.")
    assert not passive.is_directive and passive.body.subject is None


def test_adverbs_between_marker_and_head():
    assert clause("I pa not yet confirm this.").predicates[0].adverbs == ["not", "yet"]


# ---------------------------------------------------------------------- attachment rules


def test_preposition_after_object_attaches_to_verb():
    p = clause("I pa see man with telescope.").predicates[0]
    assert p.complement.head == "man" and isinstance(p.dependents[0], PrepPhrase)


def test_brackets_attach_preposition_to_noun():
    p = clause("I pa see (man with telescope).").predicates[0]
    group = p.complement
    assert group.kind == "group" and group.group.pps[0].prep == "with" and not p.dependents


def test_preposition_in_subject_attaches_to_subject():
    c = clause("user from Norway pa buy car.")
    assert c.subject.pps[0].obj.head == "Norway"


def test_of_binds_inside_noun_phrase_to_the_right():
    np = clause("name of file of user li long.").subject
    assert np.head == "name" and np.of[0].head == "file" and np.of[0].of[0].head == "user"


def test_relative_clause_ends_at_bare_marker():
    c = clause("file which user pa upload li big.")
    assert c.subject.relative.subject.head == "user"
    assert [p.tense for p in c.predicates] == ["li"] and c.predicates[0].head.text == "big"


def test_relative_clause_without_subject_and_chain_inside():
    c = clause("user which pa log-in and pa log-out pa see error.")
    rel = c.subject.relative
    assert rel.subject is None and len(rel.predicates) == 2
    assert c.predicates[0].head.text == "see"


# ---------------------------------------------------------------------- joining things


def test_chain_shares_subject():
    c = clause("user pa open file pa edit it.")
    assert len(c.predicates) == 2 and c.predicates[1].link is None


def test_and_with_marker_is_chain_and_with_subject_is_new_clause():
    assert len(clause("user pa open file and pa close it.").predicates) == 2
    body = parse_sentence("user pa open file and admin pa close it.").body
    assert isinstance(body, Complex) and body.op == "and" and len(body.parts) == 2


def test_and_alone_joins_nouns():
    obj = clause("user pa open file and folder.").predicates[0].complement
    assert isinstance(obj, Coordination) and obj.op == "and"
    subj = clause("file and folder li big.").subject
    assert isinstance(subj, Coordination)


def test_then_repeats_marker():
    preds = clause("must read file then summarize it then save summary.").predicates
    assert [p.modal for p in preds] == ["must"] * 3
    assert [p.inherited for p in preds] == [False, True, True]


def test_and_binds_tighter_than_or():
    body = parse_sentence("A li x and B li y or C li z.").body
    assert body.op == "or" and body.parts[0].op == "and"


def test_bracketed_clauses():
    body = parse_sentence("(file li big or user li admin) and must compress file.").body
    assert body.op == "and" and isinstance(body.parts[0], Complex) and body.parts[0].op == "or"


def test_mixing_or_and_xor_in_a_noun_list_is_an_error():
    with pytest.raises(KlarError, match="xor"):
        parse_sentence("must pick red or green xor blue.")


def test_subordinate_clauses_front_and_back():
    front = parse_sentence("if file li big, must compress it.")
    assert front.fronted[0].sub == "if" and front.fronted[0].preposed
    then = parse_sentence("if file li big then must compress it.")
    assert then.fronted[0].sub == "if"
    back = clause("must compress file if it li big.")
    assert back.predicates[0].dependents[0].sub == "if"


def test_preposition_or_subordinator():
    s = parse_sentence("before 2024, price pa low.")
    assert isinstance(s.fronted[0], PrepPhrase)
    s = parse_sentence("before test pa run, must build code.")
    assert isinstance(s.fronted[0], SubClause)


def test_object_clauses():
    for text, kind in [
        ("user pa say that file li big.", "that"),
        ("must check whether test pa pass.", "whether"),
        ("must explain why test pa fail.", "wh"),
        ("must check which test pa fail.", "which"),
        ("must count how many user pa register.", "which"),
    ]:
        assert clause(text).predicates[0].complement.kind == kind, text


def test_object_clause_after_object():
    p = clause("must ask user whether file li ready.").predicates[0]
    assert p.complement.head == "user" and isinstance(p.dependents[0], Embedded)


# ---------------------------------------------------------------------- sentence level


def test_source_and_certainty():
    s = parse_sentence("so likely cache li old.")
    assert (s.evidential, s.confidence) == ("so", "likely")
    s = parse_sentence("checked 90% test li pass.")
    assert (s.evidential, s.confidence) == ("checked", "90%")


def test_percent_of_is_a_quantity():
    s = parse_sentence("80% of user pa agree.")
    assert s.confidence is None and s.body.subject.head == "80%"


def test_per_first_is_source_elsewhere_rate():
    s = parse_sentence("per docs, limit li 100 request per minute.")
    assert s.fronted[0].prep == "per" and s.fronted[0].obj.head == "docs"
    assert s.body.predicates[0].dependents[0].prep == "per"


def test_questions_and_answers():
    assert parse_sentence("file li exist?").kind == "question"
    assert parse_sentence("user pa want what?").body.predicates[0].complement.kind == "wh"
    assert parse_sentence("how many user pa register?").body.subject.det == "how many"
    assert parse_sentence("yes.").kind == "answer"
    frag = parse_sentence("= F.")
    assert frag.kind == "fragment" and frag.right.ref == "F"


def test_definitions_and_claim_labels():
    d = parse_sentence("K = customer support ticket.")
    assert d.kind == "definition" and d.left.ref == "K"
    c = parse_sentence("P: all bird li fly.")
    assert c.label == "P" and c.body.subject.det == "all"


def test_fronted_noun_and_preposition_phrases():
    s = parse_sentence("yesterday, in Oslo, server pa crash.")
    assert isinstance(s.fronted[0], NounPhrase) and isinstance(s.fronted[1], PrepPhrase)


def test_time_words_attach_to_the_verb():
    p = clause("pa run test now.").predicates[0]
    assert p.complement.head == "test" and isinstance(p.dependents[0], Word)


# ------------------------------------------------------------------------------ errors


@pytest.mark.parametrize(
    "text,hint",
    [
        ("The user pa test system.", "artikler"),
        ("user is ready.", "li"),
        ("user will test system.", "fu"),
        ("user's file li big.", "apostrof"),
        ("user pa test system!", "spørsmål"),
    ],
)
def test_english_slips_get_hints(text, hint):
    with pytest.raises(KlarError) as e:
        parse_sentence(text)
    assert hint in str(e.value)


@pytest.mark.parametrize(
    "text,message",
    [
        ("user pa test system", "punktum"),
        ("user pa li test.", "to markører"),
        ("must see (man with telescope.", "parentesen"),
        ("must write a summary.", "slutten"),
    ],
)
def test_errors(text, message):
    with pytest.raises(KlarError, match=message):
        parse_sentence(text)


def test_one_bad_sentence_does_not_stop_the_rest():
    text = parse("user pa test system! user pa fix bug. the end. must stop.")
    assert len(text.errors) == 2
    assert [s.text for s in text.sentences] == ["user pa fix bug.", "must stop."]
