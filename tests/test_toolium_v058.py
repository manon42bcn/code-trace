from coderag.toolium_analysis import analyze_toolium


def _setup(tmp_path, *, mode='enabled'):
    root = tmp_path / 'repo'
    (root / 'acceptance/settings').mkdir(parents=True)
    (root / 'acceptance/resources/language').mkdir(parents=True)
    (root / 'acceptance/settings/toolium.cfg').write_text('[TestExecution]\nlanguage: pt-br\n')
    (root / 'acceptance/resources/language/pix.yaml').write_text(
        'pix:\n  common:\n    deep_link:\n      pt-br: "Translated link"\n'
    )
    config = {'repositories': {'r': {'path': 'repo'}}, 'analysis': {'toolium': mode}}
    return root, config


def test_lang_resolved_and_other_markers_dynamic(tmp_path):
    _, config = _setup(tmp_path)
    index = {
        'chunks': [
            {
                'id': 'fn',
                'path': 'features/steps/a.py',
                'language': 'python',
                'symbol': 'fn',
                'content': 'def fn(context):\n  return context.map_param(value)',
            }
        ]
    }
    rel = [
        {
            'chunk_id': 's',
            'feature_path': 'features/x.feature',
            'scenario': 'scenario: x',
            'resolved_text': '[LANG:pix.common.deep_link] [CONF:a.b] [CONTEXT:x]',
        }
    ]
    result = analyze_toolium(config, tmp_path / 'config.json', 'r', index, rel)
    assert [r['status'] for r in result['references']] == ['resolved', 'dynamic', 'dynamic']
    assert result['references'][0]['value'] == 'Translated link'
    assert result['references'][0]['resource_path'] == 'acceptance/resources/language/pix.yaml'
    assert result['summary']['map_param_calls'] == 1


def test_missing_key_no_guess(tmp_path):
    _, config = _setup(tmp_path)
    rel = [{'resolved_text': '[LANG:not.exists]'}]
    result = analyze_toolium(config, tmp_path / 'config.json', 'r', {'chunks': []}, rel)
    assert result['references'][0]['status'] == 'language_key_not_found'


def test_auto_detection_and_disabled(tmp_path):
    _, config = _setup(tmp_path, mode='auto')
    rel = [{'resolved_text': '[LANG:pix.common.deep_link]'}]
    index = {'chunks': []}
    assert not analyze_toolium(config, tmp_path / 'c.json', 'r', index, rel)['enabled']
    config['relationships'] = {'r': {'dependencies': ['toolium']}}
    assert analyze_toolium(config, tmp_path / 'c.json', 'r', index, rel)['enabled']
    config['analysis']['toolium'] = 'disabled'
    assert not analyze_toolium(config, tmp_path / 'c.json', 'r', index, rel)['enabled']


def test_examples_resolved_text_used(tmp_path):
    _, config = _setup(tmp_path)
    rel = [
        {'text': '[LANG:<key>]', 'resolved_text': '[LANG:pix.common.deep_link]', 'example_row': 2}
    ]
    result = analyze_toolium(config, tmp_path / 'c.json', 'r', {'chunks': []}, rel)
    assert result['references'][0]['status'] == 'resolved'
    assert result['references'][0]['example_row'] == 2


def test_unavailable_sources_are_reported(tmp_path):
    config = {'repositories': {'r': {'path': 'missing'}}, 'analysis': {'toolium': 'enabled'}}
    result = analyze_toolium(
        config, tmp_path / 'c.json', 'r', {'chunks': []}, [{'resolved_text': '[LANG:x]'}]
    )
    assert result['references'][0]['status'] == 'source_unavailable'
