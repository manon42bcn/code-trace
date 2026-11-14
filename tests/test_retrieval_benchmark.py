from coderag.retrieval_benchmark import benchmark_retrievers


def test_benchmark_compares_named_strategies():
    queries = [{'term': 'order', 'relevant_chunk_ids': {'a'}}]
    report = benchmark_retrievers(
        queries,
        {
            'lexical': lambda _query: [{'chunk_id': 'a'}],
            'semantic': lambda _query: [{'chunk_id': 'b'}],
        },
        k_values=(1,),
    )
    assert report['queries'] == 1
    assert report['strategies']['lexical']['metrics']['mrr'] == 1.0
    assert report['strategies']['semantic']['metrics']['mrr'] == 0.0
    assert report['strategies']['lexical']['elapsed_seconds'] >= 0
