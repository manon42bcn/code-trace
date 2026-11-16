from test_toolium_v058 import _setup

from coderag.context_flow import context_flow, context_inventory
from coderag.toolium_analysis import analyze_toolium


def _chunk(content, identifier, symbol='my_step'):
    return {
        'id': identifier,
        'path': 'steps/test.py',
        'language': 'python',
        'strategy': 'python_ast',
        'symbol': symbol,
        'start_line': 10,
        'content': content,
    }


def test_context_assignment_and_reads():
    index = {
        'chunks': [
            _chunk(
                (
                    'def my_step(context):\n    context.month_end = 31\n    '
                    'context["month_start"] = "first"\n    z = context.month_end\n'
                ),
                'a',
            )
        ]
    }
    writes, reads, _ = context_inventory(index, 'repo')
    assert {(p['key'], p['literal_value']) for p in writes} == {
        ('month_end', 31),
        ('month_start', 'first'),
    }
    assert any(r['key'] == 'month_end' for r in reads)


def test_context_flow_candidates_never_runtime_verified():
    index = {'chunks': [_chunk('def f(context):\n    context.month_end = 31', 'a')]}
    refs = [{'kind': 'context', 'key': 'month_end'}, {'kind': 'context', 'key': 'unknown'}]
    result = context_flow({'repo': index}, refs, [])
    assert result['reference_producer_links'][0]['status'] == 'candidate_producers'
    assert result['reference_producer_links'][0]['runtime_verified'] is False
    assert result['reference_producer_links'][1]['status'] == 'no_static_producer_found'


def test_step_map_param_is_linked_to_matched_definition():
    index = {'chunks': [_chunk('def f(context, x):\n    return context.map_param(x)', 'a')]}
    rel = [{'definitions': [{'repository': 'repo', 'chunk_id': 'a'}]}]
    result = context_flow({'repo': index}, [], rel)
    assert result['step_map_param_links'] == [
        {'relation_index': 0, 'map_param_call_ids': [0], 'runtime_verified': False}
    ]


def test_does_not_confuse_arbitrary_objects_with_context():
    index = {
        'chunks': [
            _chunk(
                'def f(context, other):\n    other.month_end = 1\n    context[variable] = 2', 'a'
            )
        ]
    }
    p, _, _ = context_inventory(index, 'repo')
    assert p == []


def test_toolium_off_keeps_behave_independent(tmp_path):
    _, config = _setup(tmp_path)
    config['analysis'] = {'toolium': 'disabled'}
    result = analyze_toolium(config, tmp_path / 'config.json', 'r', {'chunks': []}, [])
    assert result['enabled'] is False
