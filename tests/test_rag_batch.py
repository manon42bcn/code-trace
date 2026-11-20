from codetrace.generation import Claim, GenerationResult
from codetrace.rag_batch import evaluate_rag_dataset


def test_batch_rag_evaluation_aggregates_metrics():
    dataset = [{'query': 'What?', 'relevant_citations': ['a'], 'required_claims': 1}]

    def run(_):
        return {
            'answer': GenerationResult(
                'ok',
                'fake',
                'model',
                claims=[Claim('fact', 'static_candidate', ['a'])],
                citations=[{'chunk_id': 'a'}],
            )
        }

    report = evaluate_rag_dataset(dataset, run)
    assert report['queries'] == 1
    assert report['citation_recall'] == 1.0
    assert report['claim_coverage'] == 1.0


def test_evaluate_rag_writes_local_report_after_timeout(tmp_path, monkeypatch, capsys):
    import json
    from types import SimpleNamespace

    from codetrace import generation_config, generation_factory
    from codetrace.__main__ import main

    class Provider:
        provider = 'ollama'
        model = 'benchmark-test'

        def generate(self, prompt, **_kwargs):
            if 'private question b' in prompt:
                raise TimeoutError('private error detail')
            return GenerationResult('test answer', self.provider, self.model)

    monkeypatch.chdir(tmp_path)
    provider = Provider()
    config = SimpleNamespace(provider=provider.provider, model=provider.model)
    monkeypatch.setattr(generation_config, 'load_generation_config', lambda: config)
    monkeypatch.setattr(generation_factory, 'build_generation_provider', lambda _: provider)
    (tmp_path / 'index.json').write_text('{"chunks": []}', encoding='utf-8')
    (tmp_path / 'relationships.json').write_text('{}', encoding='utf-8')
    dataset = [
        {'query': query, 'relevant_citations': []}
        for query in ('private question a', 'private question b')
    ]
    (tmp_path / 'dataset.json').write_text(json.dumps(dataset), encoding='utf-8')

    code = main(
        [
            'evaluate-rag',
            '--dataset',
            'dataset.json',
            '--index',
            'index.json',
            '--relationships',
            'relationships.json',
        ]
    )

    (output,) = (tmp_path / 'indexes/reports').glob('evaluate-rag-*.json')
    payload = output.read_text(encoding='utf-8')
    report = json.loads(payload)
    assert code == 1
    assert report['error_rate'] == 0.5
    assert report['model'] == provider.model
    assert set(report['rows'][0]['timings']) == {
        'total_seconds',
        'retrieval_seconds',
        'context_seconds',
        'generation_seconds',
        'validation_seconds',
    }
    assert report['rows'][1]['error_type'] == 'TimeoutError'
    assert report['latency']['generation_seconds']['p95'] is None
    assert 'private' not in payload
    assert 'test answer' not in payload
    assert json.loads(capsys.readouterr().out) == report

    events = [
        json.loads(line)
        for line in (tmp_path / 'indexes/reports/requests.jsonl').read_text().splitlines()
    ]
    assert [event['source'] for event in events] == ['evaluate_rag', 'evaluate_rag']
    assert [event['status'] for event in events] == ['ok', 'error']
    assert events[1]['error_type'] == 'TimeoutError'
    assert 'generation_seconds' in events[1]['timings']
