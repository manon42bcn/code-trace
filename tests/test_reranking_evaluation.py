from coderag.evaluation import evaluate_retrieval
from coderag.reranking import reciprocal_rank_fusion


def test_rrf_improves_disagreement_case():
    queries = [{'term': 'order', 'relevant_chunk_ids': {'target'}}]
    sources = {
        'lexical': [{'chunk_id': 'noise'}, {'chunk_id': 'target'}],
        'structural': [{'chunk_id': 'target'}, {'chunk_id': 'other'}],
        'semantic': [{'chunk_id': 'noise'}, {'chunk_id': 'target'}],
    }

    def fused(_query):
        return reciprocal_rank_fusion(sources, k=1, limit=3)

    report = evaluate_retrieval(queries, fused, k_values=(1, 3))
    assert report['metrics']['recall'][1] == 1.0
    assert report['metrics']['mrr'] == 1.0


def test_evaluation_accepts_multiple_sources():
    queries = [{'term': 'order', 'relevant_chunk_ids': {'target'}}]
    report = evaluate_retrieval(
        queries,
        lambda _: [{'chunk_id': 'target'}],
        k_values=(1,),
    )
    assert report['metrics']['precision'][1] == 1.0
