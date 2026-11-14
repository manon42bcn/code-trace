"""Provider-neutral lexical retrieval baseline with labeled synthetic queries."""

from coderag.evaluation import mrr, precision_at_k, recall_at_k

QUERIES = [
    {'term': 'save_order', 'kind': 'symbol', 'relevant': {'order'}},
    {'term': 'src/orders.py', 'kind': 'path', 'relevant': {'order', 'reader'}},
    {'term': 'order_id', 'kind': 'content', 'relevant': {'order', 'reader'}},
]


def index():
    return {
        'chunks': [
            {
                'id': 'order',
                'path': 'src/orders.py',
                'symbol': 'save_order',
                'content': "storage['order_id'] = value",
                'start_line': 1,
            },
            {
                'id': 'reader',
                'path': 'src/orders.py',
                'symbol': 'read_order',
                'content': "return storage['order_id']",
                'start_line': 8,
            },
            {
                'id': 'user',
                'path': 'src/users.py',
                'symbol': 'save_user',
                'content': "storage['user_id'] = value",
                'start_line': 1,
            },
        ],
        'lexical_index': {},
    }


def retrieve(data, query):
    return {
        chunk['id'] for chunk in data['chunks'] if query['term'] in (chunk.get(query['kind']) or '')
    }


def test_labeled_generic_queries_have_expected_recall():
    data = index()
    recalls = []
    for query in QUERIES:
        found = retrieve(data, query)
        recalls.append(len(found & query['relevant']) / len(query['relevant']))
    assert recalls == [1.0, 1.0, 1.0]


def test_retrieval_metrics():
    results = [{'chunk_id': 'order'}, {'chunk_id': 'user'}]
    assert recall_at_k(results, {'order'}, 1) == 1.0
    assert precision_at_k(results, {'order'}, 2) == 0.5
    assert mrr(results, {'order'}) == 1.0


def test_baseline_reports_zero_false_positives_for_exact_symbol():
    query = QUERIES[0]
    assert retrieve(index(), query) == query['relevant']
