from coderag.evaluation import evaluate_retrieval, relevant_for


def test_evaluate_separates_writer_and_reader_labels():
    query = {'term': 'order_id', 'relevant_writers': {'writer'}, 'relevant_readers': {'reader'}}

    def retriever(_):
        return [{'chunk_id': 'writer'}, {'chunk_id': 'reader'}]

    assert relevant_for(query, edge_type='writes') == {'writer'}
    assert relevant_for(query, edge_type='reads') == {'reader'}
    assert (
        evaluate_retrieval([query], retriever, k_values=(1,), edge_type='writes')['metrics']['mrr']
        == 1.0
    )
    assert (
        evaluate_retrieval([query], retriever, k_values=(1,), edge_type='reads')['metrics']['mrr']
        == 0.5
    )


def test_evaluation_accepts_multiple_sources():
    queries = [{'term': 'order', 'relevant_chunk_ids': {'target'}}]
    report = evaluate_retrieval(queries, lambda _: [{'chunk_id': 'target'}], k_values=(1,))
    assert report['metrics']['precision'][1] == 1.0
