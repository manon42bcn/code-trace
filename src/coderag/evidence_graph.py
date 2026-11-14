"""Additive, offline graph of typed nodes and evidence-bearing relationships.

Edges are hypotheses unless a separate observation explicitly supports a match;
no node or edge represents proof that a function executed.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from .execution_paths import call_graph

GRAPH_SCHEMA_VERSION = 1


def _id(kind, *parts):
    raw = json.dumps([kind, *parts], ensure_ascii=False, separators=(',', ':'))
    return kind + ':' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]


def build_evidence_graph(indexes, report):
    """Create stable, deduplicated graph from existing static analysis records."""
    nodes, edges = {}, {}

    def node(kind, parts, **attrs):
        nid = _id(kind, *parts)
        nodes.setdefault(nid, {'id': nid, 'kind': kind, **attrs})
        return nid

    def edge(kind, source, target, evidence, **attrs):
        eid = _id('edge', kind, source, target, evidence, attrs.get('witness_id'))
        edges.setdefault(
            eid,
            {
                'id': eid,
                'type': kind,
                'source': source,
                'target': target,
                'evidence': evidence,
                'runtime_verified': False,
                **attrs,
            },
        )

    symbols = {}
    for repo, index in sorted(indexes.items()):
        for c in index.get('chunks', []):
            chunk = node(
                'chunk',
                (repo, c['id']),
                repository=repo,
                chunk_id=c['id'],
                path=c.get('path'),
                language=c.get('language'),
                **(
                    {'symbol': c.get('symbol'), 'data_path': c.get('data_path')}
                    if c.get('language') in {'yaml', 'json'}
                    else {}
                ),
            )
            if (
                c.get('language') == 'python'
                and c.get('strategy') == 'python_ast'
                and c.get('symbol')
            ):
                sym = node(
                    'python_symbol',
                    (repo, c['id']),
                    repository=repo,
                    chunk_id=c['id'],
                    symbol=c['symbol'],
                    path=c.get('path'),
                )
                symbols[(repo, c['id'])] = sym
                edge('defines', chunk, sym, 'indexed_python_ast')
    graph, diagnostics = call_graph(indexes)
    for caller, targets in graph.items():
        if caller not in symbols:
            continue
        for target in sorted(targets):
            if target in symbols:
                edge(
                    'calls',
                    symbols[caller],
                    symbols[target],
                    'static_unique_call_target',
                    limitations=['syntactic_reachability_not_execution'],
                )
    for r in report.get('relations', []):
        repo = r['source_repository']
        step = node(
            'gherkin_step',
            (
                repo,
                r['feature_path'],
                r['line_approx'],
                r.get('scenario'),
                r.get('resolved_text'),
                r.get('example_row'),
            ),
            repository=repo,
            feature_path=r['feature_path'],
            line_approx=r['line_approx'],
            text=r.get('resolved_text'),
            scenario=r.get('scenario'),
            example_row=r.get('example_row'),
        )
        evidence = r.get('implementation_evidence') or {}
        for d in r.get('definitions', []):
            target = symbols.get((d['repository'], d['chunk_id']))
            if target:
                edge(
                    'implements_step',
                    step,
                    target,
                    'static_gherkin_pattern_match',
                    resolution_tier=r.get('resolution_tier'),
                    limitations=['static_match_not_runtime_registration'],
                    observed_behave_match=(evidence.get('match_evidence') == 'matched_definition'),
                )
    flow = report.get('toolium', {}).get('context_flow', {})
    for access_type, kind in (('producers', 'writes'), ('consumers', 'reads')):
        for record in flow.get(access_type, []):
            parent = symbols.get((record['repository'], record['chunk_id']))
            if not parent:
                continue
            ns, key = record.get('namespace'), record.get('key')
            if not isinstance(ns, str) or not isinstance(key, str):
                continue
            storage_key = node(
                'data_key',
                (record['repository'], ns, key),
                repository=record['repository'],
                namespace=ns,
                key=key,
            )
            edge(
                kind,
                parent,
                storage_key,
                'static_ast_access',
                witness_id=_id(
                    'access',
                    record['repository'],
                    record['chunk_id'],
                    record.get('line_approx'),
                    ns,
                    key,
                    kind,
                ),
                line_approx=record.get('line_approx'),
                limitations=['potential_access_not_executed'],
            )
    counts = Counter(e['type'] for e in edges.values())
    return {
        'schema_version': GRAPH_SCHEMA_VERSION,
        'source_repository': report['source_repository'],
        'nodes': [nodes[k] for k in sorted(nodes)],
        'edges': [edges[k] for k in sorted(edges)],
        'summary': {
            'nodes': len(nodes),
            'edges': len(edges),
            'edge_types': dict(sorted(counts.items())),
            'unresolved_call_origins': len(diagnostics),
        },
        'guarantees': {
            'runtime_execution_inferred': False,
            'step_registration_inferred_from_static_matching': False,
        },
        'disclaimer': (
            'Evidence graph of static candidates; not proof of execution or runtime value flow.'
        ),
    }
