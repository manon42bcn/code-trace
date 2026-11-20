from concurrent.futures import ThreadPoolExecutor

import pytest

from codetrace.answering import answer_query
from codetrace.conversation import Conversation


def test_conversation_keeps_three_turns_per_repository(tmp_path):
    config = tmp_path / 'config.json'
    index = tmp_path / 'index.json'
    graph = tmp_path / 'graph.json'
    conversation = Conversation.open('new', config, index, graph)
    other = Conversation.open(conversation.identifier, config, tmp_path / 'other.json', graph)
    other.remember('other question', 'other answer')
    for number in range(4):
        conversation.remember(f'question {number}', f'answer {number}')

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda n: conversation.remember(f'parallel {n}', 'answer'), range(3)))

    reopened = Conversation.open(conversation.identifier, config, index, graph)
    assert {turn['question'] for turn in reopened.history()} == {f'parallel {n}' for n in range(3)}
    assert other.history() == [{'question': 'other question', 'answer': 'other answer'}]
    assert Conversation.open('new', config, index, graph).history() == []


def test_unknown_and_invalid_sessions_are_rejected(tmp_path):
    config = tmp_path / 'config.json'
    with pytest.raises(ValueError, match='hexadecimal'):
        Conversation.open('../other', config)
    with pytest.raises(ValueError, match='session not found'):
        Conversation.open('f' * 32, config)


def test_remote_ollama_requires_consent_before_sending_history():
    class Provider:
        provider = 'ollama'
        model = 'test'
        base_url = 'http://provider.example:11434'

        def generate(self, *_args, **_kwargs):
            pytest.fail('Remote provider called without consent')

    with pytest.raises(PermissionError, match='explicit allow_remote'):
        answer_query(
            'follow-up',
            {'items': []},
            Provider(),
            history=[{'question': 'private question', 'answer': 'private answer'}],
        )
