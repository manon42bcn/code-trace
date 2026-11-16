from coderag.error_analysis import analyze_retrieval_errors


def test_error_analysis_reports_hits_misses_and_false_positives():
    queries = [{'term': 'order', 'relevant_accesses': ['a', 'b']}]
    report = analyze_retrieval_errors(
        queries, lambda _: [{'chunk_id': 'a'}, {'chunk_id': 'noise'}], k=2
    )
    assert report[0]['hits'] == ['a']
    assert report[0]['misses'] == ['b']
    assert report[0]['false_positives'] == ['noise']
