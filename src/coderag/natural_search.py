"""Bounded term-overlap retrieval with identifier anchors and explicit scoring signals."""

import math
from collections import Counter

from .match_ranking import describe_match, rank_key
from .query_planning import variants, words


def natural_signal(chunk, plan, matched=None, anchors=None):
    """Use the same literal coverage signal for lexical and hybrid candidates."""
    if matched is None:
        tokens = {
            form
            for field in ('symbol', 'path', 'content')
            for word in words(str(chunk.get(field) or ''))
            for form in variants(word)
        }
        matched = {term for term, forms in plan['lexical_variants'].items() if set(forms) & tokens}
    if anchors is None:
        anchors = [
            anchor
            for anchor in plan['identifier_anchors']
            if any(anchor in str(chunk.get(field) or '') for field in ('symbol', 'path', 'content'))
        ]
    signal = describe_match(chunk, plan['input'])
    for anchor in anchors:
        candidate = describe_match(chunk, anchor)
        if candidate['priority'] < signal['priority']:
            signal = {**candidate, 'anchor': anchor}
    return {
        **signal,
        'matched_terms': sorted(matched),
        'matched_anchors': anchors,
        'lexical_mode': 'token_overlap',
        'term_coverage': len(matched) / max(len(plan['lexical_terms']), 1),
    }


def search_natural(index, plan, *, kind='any', limit=50):
    terms = {term: set(forms) for term, forms in plan['lexical_variants'].items()}
    fields = ('symbol', 'path', 'content') if kind == 'any' else (kind,)
    documents = []
    frequencies = Counter()
    for chunk in index.get('chunks', []):
        tokens = {
            field: {form for word in words(str(chunk.get(field) or '')) for form in variants(word)}
            for field in fields
        }
        all_tokens = set().union(*tokens.values())
        matched = {term for term, forms in terms.items() if forms & all_tokens}
        anchors = [
            anchor
            for anchor in plan['identifier_anchors']
            if any(anchor in str(chunk.get(field) or '') for field in fields)
        ]
        if matched or anchors:
            frequencies.update(matched)
            documents.append((chunk, tokens, matched, anchors))
    count = len(index.get('chunks', []))
    weights = {'symbol': 3.0, 'path': 2.0, 'content': 1.0}
    results = []
    for chunk, tokens, matched, anchors in documents:
        score = sum(
            math.log1p((count + 1) / (frequencies[term] + 1))
            * max(weights[field] for field in fields if terms[term] & tokens[field])
            for term in matched
        )
        score += sum(
            max(weights[field] for field in fields if anchor in str(chunk.get(field) or ''))
            for anchor in anchors
        )
        signal = natural_signal(chunk, plan, matched, anchors)
        results.append(
            {
                'chunk_id': chunk['id'],
                'score': score / (1 + score),
                'path': chunk.get('path'),
                'symbol': chunk.get('symbol'),
                'start_line': chunk.get('start_line'),
                'match_kinds': [
                    field
                    for field in fields
                    if (
                        any(forms & tokens[field] for forms in terms.values())
                        or any(anchor in str(chunk.get(field) or '') for anchor in anchors)
                    )
                ],
                'ranking': signal,
            }
        )
    return sorted(results, key=rank_key)[:limit]
