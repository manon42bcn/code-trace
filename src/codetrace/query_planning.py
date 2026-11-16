"""Deterministic, inspectable lexical planning without translation or generated rewrites."""

import re
import unicodedata

from .query_routing import classify_query, retrieval_sources

PLANNING_PROFILE = 'natural-v1'
STOPWORDS = set(
    """a al an and are as at con cual cuales cuando de del do does donde el en es
for from how i in is it la las lo los of on or para por que se the this to un una unas unos
was what when where which who with y como can could please would me you your""".split()
)


def words(text):
    text = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', text)
    text = ''.join(
        c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c)
    )
    return re.findall(r'[^\W_]+', text)


def variants(word):
    values = [word]
    if len(word) > 4 and word.endswith('ies'):
        values.append(word[:-3] + 'y')
    elif len(word) > 4 and word.endswith('s') and not word.endswith(('ss', 'us', 'is')):
        values.append(word[:-1])
    if len(word) > 5 and word.endswith('ed'):
        values.extend((word[:-2], word[:-1]))
    if len(word) > 5 and word.endswith('ing'):
        values.extend((word[:-3], word[:-3] + 'e'))
    return list(dict.fromkeys(values))


def plan_query(text, *, kind='any', exact=False):
    intent = classify_query(text, kind=kind)
    natural = intent == 'natural_language' and not exact and kind not in {'symbol', 'path'}
    terms = list(
        dict.fromkeys(word for word in words(text) if word not in STOPWORDS and len(word) > 1)
    )
    anchors = []
    if natural:
        anchors = [
            token
            for token in re.findall(r'`([^`\n]+)`', text)
            if all(part.isidentifier() for part in token.split('.'))
        ]
        anchors = list(dict.fromkeys(anchors))
        for token in re.findall(r'[^\W\d]\w*(?:\.\w+)*', text):
            if (
                '_' in token or '.' in token or re.search(r'[a-z][A-Z]', token)
            ) and token not in anchors:
                anchors.append(token)
    return {
        'profile': PLANNING_PROFILE,
        'input': text,
        'intent': intent,
        'lexical_mode': 'token_overlap' if natural else 'literal',
        'lexical_terms': terms[:32] if natural else [],
        'identifier_anchors': anchors[:8],
        'lexical_variants': {word: variants(word) for word in terms[:32]} if natural else {},
        'semantic_query': text,
        'structural_query': text,
        'semantic_transformed': False,
        'lexical_transformed': natural,
        'terms_truncated': natural and len(terms) > 32,
        'anchors_truncated': len(anchors) > 8,
        'limits': {'max_terms': 32, 'max_anchors': 8},
    }


def active_sources(plan, mode, *, semantic_available=False):
    sources = retrieval_sources(plan['intent'])
    if mode == 'semantic':
        if not semantic_available:
            raise ValueError('Semantic mode requires configured, prepared vectors and a provider')
        return ['semantic']
    if mode not in {'configured', 'lexical'}:
        raise ValueError('Unknown retrieval mode')
    return [
        source
        for source in sources
        if source != 'semantic' or (mode == 'configured' and semantic_available)
    ]
