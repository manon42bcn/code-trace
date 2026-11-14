from coderag.generation import Claim, GenerationResult
from coderag.rag_evaluation import evaluate_answer


def test_rag_evaluation_measures_citations_and_claims():
    result = GenerationResult(
        'answer',
        'fake',
        'model',
        claims=[Claim('fact', 'static_candidate', ['a'])],
        citations=[{'chunk_id': 'a'}],
        limitations=['static'],
    )
    metrics = evaluate_answer(result, relevant_citations={'a', 'b'}, required_claims=1)
    assert metrics['citation_recall'] == 0.5
    assert metrics['invalid_citations'] == 0
    assert metrics['claims_requirement_met'] is True
