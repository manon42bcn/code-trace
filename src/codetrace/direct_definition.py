"""Conservative, repository-independent handling of definition-location questions."""

from __future__ import annotations

import re

from .context_api import build_context
from .evidence_context import chunk_lookup
from .generation import Claim, GenerationResult
from .grounded_prompt import response_language_instruction
from .lexical_search import search_index

DIRECT_DEFINITION = 'direct_definition'
_LOCATION = re.compile(
    r'\s*¿?(?:'
    r'(?:d[óo]nde|en qu[ée] (?:archivo|fichero|m[óo]dulo|l[íi]nea))\s+'
    r'(?:se define|est[áa] definid[oa])\s+(?P<es>.+?)'
    r'|(?:where|in which (?:file|module))\s+(?:is|are)\s+(?P<en>.+?)\s+defined'
    r')\s*[?.]?\s*',
    re.IGNORECASE,
)
_REFERENCE = re.compile(
    r'(?:ese|esa|este|esta|aquel|aquella|that|this)\s+'
    r'(?:step|paso|funci[óo]n|clase|s[íi]mbolo|function|class|symbol)|it',
    re.IGNORECASE,
)
_ARTICLE = re.compile(r'^(?:el|la|the)\s+', re.IGNORECASE)
_KIND = re.compile(r'^(step|paso|funci[óo]n|clase|s[íi]mbolo|function|class|symbol)\s+', re.I)
_QUOTED = re.compile(r'`([^`\n]+)`')
_GHERKIN = re.compile(r'^(given|when|then)\s+(.+)$', re.IGNORECASE)


def _symbol(text):
    return all(part.isidentifier() for part in text.split('.'))


def _target(question, history):
    match = _LOCATION.fullmatch(question)
    if match is None:
        return None
    text = _ARTICLE.sub('', match['es'] or match['en'])
    if _REFERENCE.fullmatch(text):
        references = list(dict.fromkeys(_QUOTED.findall(history[-1]['answer']))) if history else []
        return references[0] if len(references) == 1 else None
    text = _KIND.sub('', text)
    quoted = _QUOTED.fullmatch(text)
    if quoted:
        return quoted[1]
    return text if _symbol(text) else None


def _definitions(index, target):
    matches = (
        search_index(index, target, kind='symbol', exact=True, limit=2) if _symbol(target) else []
    )
    symbols = [row for row in matches if row['ranking']['role'] == 'definition']
    step = _GHERKIN.fullmatch(target)
    keyword, pattern = (step[1].lower(), step[2]) if step else (None, target)
    definitions = index.get('step_definitions')
    if definitions is None:
        definitions = index.get('behave_relations', {}).get('step_definitions', [])
    steps = [
        {'chunk_id': definition['chunk_id'], 'score': 1.0}
        for definition in definitions
        if definition.get('pattern') == pattern
        and (keyword is None or definition.get('keyword') in (keyword, 'step'))
    ]
    return [*symbols, *steps]


def direct_definition(query, index, graph, *, history=None, limits=None, relevant_chunk_ids=None):
    """Resolve a uniquely indexed definition and assemble its existing evidence."""
    target = _target(query, history)
    if target is None:
        return None
    definitions = _definitions(index, target)
    if len(definitions) != 1:
        return None
    chunk_id = definitions[0]['chunk_id']
    chunk = chunk_lookup(index).get(chunk_id)
    if (
        chunk is None
        or not chunk.get('path')
        or not chunk.get('start_line')
        or not chunk.get('end_line')
    ):
        return None
    context = build_context(
        index,
        graph,
        query,
        [{**definitions[0], 'source': DIRECT_DEFINITION}],
        intent='exact_symbol',
        relevant_chunk_ids=relevant_chunk_ids,
        **{**(limits or {}), 'expansion_depth': 0},
    )
    if not context['items']:
        return None
    item = context['items'][0]
    citation = item['citation']
    location = f'{citation["path"]}:{citation["start_line"]}-{citation["end_line"]}'
    spanish = response_language_instruction(query).startswith('Response language: Spanish')
    text = (
        f'`{target}` se define en {location}.'
        if spanish
        else f'`{target}` is defined in {location}.'
    )
    answer = GenerationResult(
        text,
        'codetrace',
        'static-index',
        claims=[Claim(text, 'static_candidate', [chunk_id])],
        citations=[citation],
    )
    return {
        'answer': answer,
        'context': context,
        'generated': False,
        'answer_mode': DIRECT_DEFINITION,
    }
