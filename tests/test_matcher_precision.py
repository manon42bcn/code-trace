from coderag.behave_links import _pattern_regex


def test_typed_number_rejects_non_number():
    rx = _pattern_regex('response code {code:d}')
    assert rx.fullmatch('response code 200')
    assert not rx.fullmatch('response code nope')


def test_unknown_field_type_is_not_generic_wildcard():
    assert _pattern_regex('something {value:customType}') is None


def test_multiple_decorators_string_patterns():
    assert _pattern_regex('hello "{name}"').fullmatch('hello "world"')
