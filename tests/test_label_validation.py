from coderag.label_validation import validate_labels


def test_labels_validate_against_graph_edges():
    queries = [
        {
            'term': 'key',
            'relevant_writers': ['w'],
            'relevant_readers': ['r'],
            'relevant_accesses': ['w', 'r'],
        }
    ]
    assert validate_labels(queries, {'w', 'r'}, {('w', 'writes'), ('r', 'reads')}) == []


def test_labels_report_invalid_union_and_edges():
    queries = [
        {'term': 'key', 'relevant_writers': ['w'], 'relevant_readers': [], 'relevant_accesses': []}
    ]
    errors = validate_labels(queries, {'w'}, set())
    assert len(errors) == 2
