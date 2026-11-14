from coderag.generation import Claim, GenerationResult
from coderag.rag_batch import evaluate_rag_dataset


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
