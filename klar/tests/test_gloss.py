import json

from klar import References, features, gloss_text, parse, parse_sentence, to_data
from klar.gloss import confidence_value, short, walk
from klar.nodes import NounPhrase


def resolve_all(text: str) -> list[str]:
    """What each "it" in the text points to, in order."""
    t = parse(text)
    refs = References(t)
    out = []
    for s in t.sentences:
        for n in walk(s):
            if isinstance(n, NounPhrase) and n.kind == "pronoun" and n.ref == "it":
                out.append(short(refs.resolve(n)))
    return out


def test_it_is_the_nearest_subject_or_object():
    assert resolve_all("user pa open file pa edit it.") == ["file"]
    assert resolve_all("cat pa chase mouse. it li fast.") == ["mouse"]
    assert resolve_all("file pa crash. it pa restart. it li ok.") == ["file", "file"]


def test_it_skips_its_own_verb():
    assert resolve_all("I pa fix bug in login form pa add 2 test for it.") == ["bug"]
    assert resolve_all("must save file where user can see it.") == ["file"]
    assert resolve_all("user pa open file and admin pa close it.") == ["file"]


def test_it_skips_preposition_phrases_and_relative_clauses():
    assert resolve_all("user pa send report to admin. it li long.") == ["report"]
    assert resolve_all("user pa open file which admin pa create. it li big.") == ["file"]


def test_it_sees_into_that_and_whether_clauses():
    assert resolve_all("must check whether input li valid. if it not valid, must stop.") == ["input"]


def test_labels_and_claims():
    t = parse("user U pa send file F to admin. U want copy of F. P: all bird li fly. so P li false.")
    glosses = gloss_text(t)
    assert "[U→user]" in glosses[1] and "[F→file]" in glosses[1]
    assert "P→«all bird li fly»" in glosses[3]


def test_definition_binds_label():
    glosses = gloss_text(parse("K = customer support ticket. user pa open K."))
    assert glosses[0] == "K := [customer support ticket] ."
    assert "[K→customer support ticket]" in glosses[1]


def test_gloss_shows_markers_source_and_certainty():
    g = gloss_text(parse("checked likely test pa not pass."))[0]
    assert g == "‹VERIFIED› ‹likely ≈75%› [test] PAST.NOT:pass ."
    g = gloss_text(parse("per docs, limit li 5MB."))[0]
    assert g.startswith("‹SOURCE [docs]›")


def test_features():
    f = features(parse_sentence("if build li fail, must notify team and must not deploy."))
    assert f["subordinators"] == ["if"] and f["modals"] == ["must"] and f["negated"] and f["directive"]
    f = features(parse_sentence("per manual, limit li 10GB per user."))
    assert f["source"] == "manual"
    f = features(parse_sentence("user which pa report bug li from Oslo."))
    assert f["relative"]
    f = features(parse_sentence("I pa see (man with binoculars)."))
    assert f["grouped"]


def test_confidence_values():
    assert confidence_value("likely") == 0.75
    assert confidence_value("90%") == 0.9
    assert confidence_value(None) is None


def test_data_is_json():
    data = to_data(parse_sentence("checked 41 test pa pass and 1 pa fail."))
    text = json.dumps(data)
    assert '"evidential": "checked"' in text and data["type"] == "Sentence"
