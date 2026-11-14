"""YAML/JSON indexing preserves source evidence and never executes configuration."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from coderag import core
from coderag.core import build_chunks, detect_language, index_repository
from coderag.lexical_search import search_index

CFG = {
    'languages': ['yaml', 'json', 'lock'],
    'isolate_parsers': False,
    'chunking': {
        'strategy': 'structural',
        'max_tokens': 100,
        'overlap_tokens': 5,
        'preserve_symbols': True,
        'include_parent_context': True,
        'on_missing_parser': 'error',
        'on_syntax_error': 'error',
    },
}
YAML = (
    'agent:\n'
    '  tools:\n'
    '    - tool_name: alpha\n'
    '      description: |\n'
    '        A multiline description.\n'
    '        Keep the original text.\n'
    '    - tool_name: beta\n'
    '      enabled: true\n'
)


@pytest.mark.parametrize(
    ('name', 'language'),
    [
        ('a.yaml', 'yaml'),
        ('a.yml', 'yaml'),
        ('a.json', 'json'),
        ('package-lock.json', 'lock'),
        ('pnpm-lock.yaml', 'lock'),
    ],
)
def test_configuration_detection_preserves_lock_special_cases(name, language):
    assert detect_language(Path(name), {}) == language


def test_yaml_entries_keep_their_names_properties_and_exact_lines():
    chunks = build_chunks('agent.yaml', 'yaml', YAML, CFG)
    entry = next(chunk for chunk in chunks if chunk['symbol'] == '$/agent/tools/0')
    assert entry['start_line'] == 3
    assert entry['end_line'] == 6
    assert 'tool_name: alpha' in entry['content']
    assert 'A multiline description.' in entry['content']
    assert entry['parent_symbol'] == '$/agent/tools'
    assert entry['data_path'] == '$/agent/tools/0'
    assert entry['strategy'] == 'yaml_structure'
    for chunk in chunks:
        expected = '\n'.join(YAML.splitlines()[chunk['start_line'] - 1 : chunk['end_line']])
        assert chunk['content'] == expected
    assert search_index({'chunks': chunks}, 'alpha', kind='content')[0]['chunk_id'] == entry['id']


def test_yaml_aliases_are_preserved_at_their_occurrence_without_expansion():
    source = 'defaults: &base\n  retries: 3\ncopy: *base\nrecursive: &self [*self]\n'
    chunks = build_chunks('config.yml', 'yaml', source, CFG)
    alias = next(chunk for chunk in chunks if chunk['symbol'] == '$/copy')
    assert alias['start_line'] == alias['end_line'] == 3
    assert alias['content'] == 'copy: *base'
    assert len(chunks) < 10


def test_yaml_multiple_documents_have_distinct_paths():
    chunks = build_chunks('multi.yml', 'yaml', '---\nname: one\n---\nname: two\n', CFG)
    paths = {chunk['symbol'] for chunk in chunks}
    assert '$doc/0/name' in paths
    assert '$doc/1/name' in paths


def test_yaml_tags_cannot_execute_constructors(monkeypatch):
    def forbidden(_command):
        pytest.fail('YAML configuration must never execute commands')

    monkeypatch.setattr(os, 'system', forbidden)
    source = 'action: !!python/object/apply:os.system ["ignored"]\n'
    chunks = build_chunks('tagged.yaml', 'yaml', source, CFG)
    assert any('python/object/apply' in chunk['content'] for chunk in chunks)


@pytest.mark.parametrize(
    'source', ['{"a":1,"b":[true,null]}', '{\n\t"a":1,\n\t"b":2\n}', '[1,2,3]', '"scalar"']
)
def test_json_compact_tab_indented_and_scalar_documents_are_preserved(source):
    chunks = build_chunks('data.json', 'json', source, CFG)
    assert chunks
    assert all(chunk['language'] == 'json' for chunk in chunks)
    assert all(chunk['estimated_tokens'] <= 100 for chunk in chunks)
    if '\n' not in source:
        assert chunks[0]['content'] == source
        assert chunks[0]['symbol'] == '$'


def test_json_pretty_structure_and_escaped_keys():
    source = json.dumps(
        {'a/b': {'x~y': 42}, 'tools': [{'name': 'alpha', 'enabled': True}]}, indent=2
    )
    chunks = build_chunks('data.json', 'json', source, CFG)
    assert '$/a~1b/x~0y' in {chunk['symbol'] for chunk in chunks}
    entry = next(chunk for chunk in chunks if chunk['symbol'] == '$/tools/0')
    assert '"name": "alpha"' in entry['content']
    assert '"enabled": true' in entry['content']


@pytest.mark.parametrize(
    ('language', 'source'),
    [
        ('json', '{"bad":}'),
        ('json', '{"a":1,"a":2}'),
        ('json', '{"n":NaN}'),
        ('yaml', 'bad: [unterminated'),
        ('yaml', 'a: 1\na: 2\n'),
    ],
)
def test_strict_errors_and_explicit_raw_recovery(language, source):
    with pytest.raises(ValueError, match='fragmentación estructural'):
        build_chunks('bad.' + language, language, source, CFG)
    recovery = {**CFG, 'chunking': {**CFG['chunking'], 'on_syntax_error': 'recover'}}
    diagnostics = []
    chunks = build_chunks('bad.' + language, language, source, recovery, diagnostics)
    assert chunks
    assert all(chunk['strategy'] == f'{language}_document' for chunk in chunks)
    assert diagnostics[0]['recovery'] == 'raw_document'


def test_large_list_entry_is_split_to_budget_without_changing_its_path():
    source = 'tools:\n  - name: alpha\n    description: "' + 'word ' * 300 + '"\n'
    chunks = build_chunks('big.yaml', 'yaml', source, CFG)
    entries = [chunk for chunk in chunks if chunk['symbol'] == '$/tools/0']
    assert len(entries) > 1
    assert all(chunk['estimated_tokens'] <= 100 for chunk in entries)


def test_configuration_files_are_indexed_incrementally_and_sensitive_names_are_excluded(
    tmp_path, monkeypatch
):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'agent.yaml').write_text(YAML)
    (repo / 'config.json').write_text('{"enabled":true}')
    (repo / 'credentials.json').write_text('{"token":"do-not-index"}')
    output = tmp_path / 'index.json'
    first = index_repository(repo, output, {'indexing': CFG})
    assert first['files_discovered'] == 2
    assert not any(chunk['path'] == 'credentials.json' for chunk in first['chunks'])
    assert {'path': 'credentials.json', 'kind': 'file'} in first['excluded_paths']
    original = core.build_chunks
    parsed = []

    def record(path, *args, **kwargs):
        parsed.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(core, 'build_chunks', record)
    second = index_repository(repo, output, {'indexing': CFG}, incremental=True)
    assert not parsed
    assert [chunk['id'] for chunk in first['chunks']] == [chunk['id'] for chunk in second['chunks']]
    for chunk in second['chunks']:
        if chunk['path'] == 'config.json':
            chunk.pop('configuration_chunking_version')
    output.write_text(json.dumps(second))
    index_repository(repo, output, {'indexing': CFG}, incremental=True)
    assert parsed == ['config.json']


def test_worker_supports_configuration_structures():
    request = {'path': 'agent.yaml', 'language': 'yaml', 'source': YAML, 'config': CFG}
    process = subprocess.run(
        [sys.executable, '-m', 'coderag.worker'],
        input=json.dumps(request),
        text=True,
        capture_output=True,
    )
    assert process.returncode == 0, process.stderr
    assert '$/agent/tools/0' in {chunk['symbol'] for chunk in json.loads(process.stdout)['chunks']}


def test_configuration_paths_are_available_to_structural_graph_search():
    from coderag.evidence_graph import build_evidence_graph
    from coderag.structural_search import search_graph

    chunks = build_chunks('agent.yaml', 'yaml', YAML, CFG)
    graph = build_evidence_graph(
        {'demo': {'chunks': chunks}}, {'source_repository': 'demo', 'relations': []}
    )
    matches = search_graph(graph, '$/agent/tools/0', kind='symbol')
    assert matches
    assert matches[0]['chunk_id'] in {chunk['id'] for chunk in chunks}


@pytest.mark.parametrize('language', ['json', 'yaml'])
def test_deep_configuration_respects_nesting_limits(monkeypatch, language):
    from coderag import configuration_chunks

    monkeypatch.setattr(configuration_chunks, 'MAX_DEPTH', 2)
    with pytest.raises(ValueError, match='nesting exceeds'):
        build_chunks('nested.' + language, language, '[[[[0]]]]', CFG)


@pytest.mark.parametrize('language', ['json', 'yaml'])
def test_configuration_respects_node_limits(monkeypatch, language):
    from coderag import configuration_chunks

    monkeypatch.setattr(configuration_chunks, 'MAX_NODES', 2)
    with pytest.raises(ValueError, match='node limit'):
        build_chunks('many.' + language, language, '[1, 2, 3]', CFG)


def test_many_json_keys_keep_exact_line_coverage():
    source = json.dumps({f'key_{number}': number for number in range(2000)}, indent=2)
    chunks = build_chunks('many.json', 'json', source, CFG)
    covered = [
        line for chunk in chunks for line in range(chunk['start_line'], chunk['end_line'] + 1)
    ]
    assert covered == list(range(1, len(source.splitlines()) + 1))
    assert '$/key_1999' in {chunk['symbol'] for chunk in chunks}


def test_partition_sweep_preserves_leaf_selection_and_tie_breaking():
    import random

    from coderag.core import partition

    generator = random.Random(17)
    lines = ['line'] * 30
    for _ in range(100):
        units = []
        for number in range(20):
            start = generator.randint(1, 30)
            units.append((start, generator.randint(start, 32), str(number), 'structure'))
        expected = []
        for line in range(1, len(lines) + 1):
            covering = [unit for unit in units if unit[0] <= line <= unit[1]]
            unit = (
                min(covering, key=lambda item: (item[1] - item[0], -item[0])) if covering else None
            )
            if expected and expected[-1][2] == unit:
                expected[-1] = (expected[-1][0], line, unit)
            else:
                expected.append((line, line, unit))
        assert partition(lines, units) == expected
