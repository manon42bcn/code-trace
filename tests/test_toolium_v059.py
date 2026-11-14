from test_toolium_v058 import _setup

from coderag.toolium_analysis import _references, analyze_toolium


def test_nested_context_inside_lang(tmp_path):
    _, config = _setup(tmp_path)
    text = '[LANG:months.[CONTEXT:month_end]]'
    result = analyze_toolium(
        config, tmp_path / 'config.json', 'r', {'chunks': []}, [{'resolved_text': text}]
    )
    refs = result['references']
    assert len(refs) == 2
    assert refs[0]['reference'] == text
    assert refs[0]['status'] == 'runtime_dependent'
    assert refs[0]['dependencies'] == [
        {'kind': 'context', 'key': 'month_end', 'reference': '[CONTEXT:month_end]'}
    ]
    assert refs[1]['kind'] == 'context'
    assert refs[1]['status'] == 'dynamic'


def test_nested_multiple_levels_and_siblings():
    refs = _references('x [LANG:a.[CONF:key.[CONTEXT:x]]] and [LANG:b]')
    assert len(refs) == 4
    assert refs[0]['kind'] == 'lang'
    assert refs[0]['dependencies'][0]['kind'] == 'conf'
    assert refs[1]['kind'] == 'conf'
    assert refs[2]['kind'] == 'context'
    assert refs[3]['key'] == 'b'


def test_custom_language_exact_and_override(tmp_path):
    root, config = _setup(tmp_path)
    (root / 'acceptance/settings/toolium.cfg').write_text('[TestExecution]\nlanguage: eng-uk\n')
    (root / 'acceptance/resources/language/pix.yaml').write_text(
        'pix:\n  common:\n    deep_link:\n      eng-uk: British value\n      de-de: German value\n'
    )
    rel = [{'resolved_text': '[LANG:pix.common.deep_link] and [LANG:pix.common.deep_link::de-de]'}]
    refs = analyze_toolium(config, tmp_path / 'config.json', 'r', {'chunks': []}, rel)['references']
    assert [(r['language'], r['value']) for r in refs] == [
        ('eng-uk', 'British value'),
        ('de-de', 'German value'),
    ]


def test_unclosed_marker_ignored():
    assert _references('test [LANG:unfinished') == []
