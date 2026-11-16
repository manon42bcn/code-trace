from coderag.evidence_graph import build_evidence_graph


def _index():
    return {
        'chunks': [
            {
                'id': 'a',
                'path': 'pkg/mod.py',
                'language': 'python',
                'strategy': 'python_ast',
                'symbol': 'first',
                'content': 'def first():\n    second()',
            },
            {
                'id': 'b',
                'path': 'pkg/mod.py',
                'language': 'python',
                'strategy': 'python_ast',
                'symbol': 'second',
                'content': 'def second():\n    return 1',
            },
        ]
    }


def test_deterministic_graph_and_calls():
    report = {'source_repository': 'demo', 'relations': []}
    g = build_evidence_graph({'demo': _index()}, report)
    assert g == build_evidence_graph({'demo': _index()}, report)
    assert g['summary']['edge_types']['calls'] == 1
    assert all(not e['runtime_verified'] for e in g['edges'])


def test_gherkin_and_accesses():
    report = {
        'source_repository': 'demo',
        'relations': [
            {
                'source_repository': 'demo',
                'feature_path': 'features/a.feature',
                'scenario': 's',
                'line_approx': 3,
                'resolved_text': 'hello',
                'definitions': [{'repository': 'demo', 'chunk_id': 'a'}],
                'resolution_tier': 'local_scope',
            }
        ],
        'toolium': {
            'context_flow': {
                'producers': [
                    {
                        'repository': 'demo',
                        'chunk_id': 'a',
                        'namespace': 'toolium.storage',
                        'key': 'token',
                        'line_approx': 5,
                    }
                ],
                'consumers': [
                    {
                        'repository': 'demo',
                        'chunk_id': 'b',
                        'namespace': 'toolium.storage',
                        'key': 'token',
                        'line_approx': 7,
                    }
                ],
            }
        },
    }
    g = build_evidence_graph({'demo': _index()}, report)
    assert all(g['summary']['edge_types'][k] == 1 for k in ('implements_step', 'writes', 'reads'))
    assert len([n for n in g['nodes'] if n['kind'] == 'data_key']) == 1


def test_no_behave_or_storage():
    g = build_evidence_graph({'demo': _index()}, {'source_repository': 'demo', 'relations': []})
    assert not any(e['type'] in ('implements_step', 'reads', 'writes') for e in g['edges'])
