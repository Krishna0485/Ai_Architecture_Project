from regintel.text import (
    bigrams,
    count_tokens,
    coverage,
    normalize_term,
    sentences,
    slugify,
    terms,
    token_f1,
)


def test_terms_keep_section_numbers_and_drop_stopwords() -> None:
    assert terms("Under § 825.110 the employees shall") == ["825.110", "employe"]
    assert terms("entitled entitlement") == ["entitl", "entitl"]


def test_normalize_term() -> None:
    assert normalize_term("policies") == "policy"
    assert normalize_term("notifications") == "notific"
    assert normalize_term("run") == "run"
    assert normalize_term("2024") == "2024"


def test_sentences_split_on_regulation_boundaries() -> None:
    s = sentences("(a) First rule applies. (b) Second rule; (c) Third.")
    assert len(s) == 3


def test_coverage_and_f1() -> None:
    assert coverage("encryption at rest", "data is encrypted at rest") == 0.5
    assert coverage("the of", "x") == 0.0
    assert token_f1("12 workweeks of leave", "12 workweeks leave") == 1.0
    assert token_f1("", "x") == 0.0
    assert token_f1("apple", "pear") == 0.0


def test_misc() -> None:
    assert count_tokens("one two three") >= 3
    assert slugify("Hello, World!") == "hello_world"
    assert slugify("!!!") == "item"
    assert bigrams(["a", "b", "c"]) == {("a", "b"), ("b", "c")}
