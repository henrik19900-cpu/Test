from klar.lint import check


def messages(text: str, strict: bool = False) -> list[str]:
    return [str(i) for i in check(text, strict)[1]]


def test_clean_text_has_no_issues():
    assert messages("checked test li pass. must fix bug.", strict=True) == []


def test_parse_errors_are_reported_with_hints():
    out = messages("the user pa test system.")
    assert len(out) == 1 and "feil" in out[0] and "artikler" in out[0]


def test_may_not_warns():
    out = messages("you may not delete log.")
    assert any("may not" in m and "must not" in m for m in out)


def test_strict_wants_a_source():
    assert messages("file li big.") == []
    out = messages("file li big.", strict=True)
    assert len(out) == 1 and "kilde" not in out[0] and "checked" in out[0]
    assert messages("per docs, file li big.", strict=True) == []
    assert messages("so file li big. suppose file li big. checked file li big.", strict=True) == []
    assert messages("must check file. file li big?", strict=True) == []


def test_missing_period_between_lines_warns():
    out = messages("user pa test system\nU li big.")
    assert any("flere linjer" in m for m in out)


def test_labels():
    assert any("brukes uten" in m for m in messages("U li big."))
    assert any("knyttes 2 ganger" in m for m in messages("user U pa leave. admin U pa stay."))


def test_it_without_antecedent_warns():
    assert any("«it»" in m for m in messages("it li big."))


def test_subject_it_pointing_at_an_object_warns():
    out = messages("script pa delete file and it pa crash.")
    assert any("«file»" in m and "«script»" in m for m in out)
    assert messages("script pa delete file then crash.") == []
    assert messages("user pa open file pa edit it.") == []
    assert messages("file pa crash. it pa restart.") == []


def test_strict_lets_the_writer_report_on_itself():
    assert messages("I pa not yet confirm this. we fu deploy tomorrow.", strict=True) == []
