"""Consumer-first, offline Gherkin context provenance from existing context_flow.

No extra source discovery or guessed execution: preserve the original analysis
and expose each candidate's evidence, scope, chronology and uncertainty.
"""

from __future__ import annotations

from collections import Counter


def query_context_consumers(
    report,
    *,
    key=None,
    feature=None,
    scenario=None,
    max_consumers=100,
    max_producers=30,
    only_prior=False,
):
    if max_consumers < 1 or max_producers < 1:
        raise ValueError('Los límites deben ser positivos')
    if any(x is not None and (not isinstance(x, str) or not x) for x in (key, feature, scenario)):
        raise ValueError('Los filtros deben ser cadenas no vacías')
    toolium = report.get('toolium') or {}
    flow = toolium.get('context_flow') or {}
    references = toolium.get('references')
    links = flow.get('reference_producer_links')
    producers = flow.get('producers')
    relations = report.get('relations')
    if not all(isinstance(v, list) for v in (references, links, producers, relations)):
        raise ValueError('El informe no contiene referencias y context_flow compatibles')
    output = []
    stats = Counter()
    matched = 0
    for link in links:
        index = link.get('reference_index')
        if not isinstance(index, int) or index < 0 or index >= len(references):
            raise ValueError('reference_index inválido en context_flow')
        reference = references[index]
        if reference.get('kind') != 'context':
            continue
        ri = reference.get('relation_index')
        if not isinstance(ri, int) or ri < 0 or ri >= len(relations):
            raise ValueError('relation_index inválido en referencia CONTEXT')
        relation = relations[ri]
        if key is not None and reference.get('key') != key:
            continue
        if feature is not None and feature not in relation.get('feature_path', ''):
            continue
        if scenario is not None and scenario not in relation.get('scenario', ''):
            continue
        matched += 1
        if len(output) >= max_consumers:
            continue
        candidates = []
        matching_prior = 0
        for c in link.get('candidates', []):
            pid = c.get('producer_id')
            if not isinstance(pid, int) or not 0 <= pid < len(producers):
                raise ValueError('producer_id inválido en context_flow')
            prior = c.get('temporal_evidence') == 'prior_step_witness' and c.get(
                'tier', ''
            ).startswith('preceding_')
            if prior:
                matching_prior += 1
            if only_prior and not prior:
                continue
            if len(candidates) >= max_producers:
                continue
            p = producers[pid]
            assessment = (
                'plausible_prior_writer'
                if prior and c.get('route_classification') == 'static_path_candidate'
                else 'conditional_prior_writer'
                if prior
                else 'future_writer_not_prior'
                if c.get('temporal_evidence') == 'future_step_only'
                else 'insufficient_temporal_evidence'
            )
            candidates.append(
                {
                    'producer_id': pid,
                    'writer': {
                        f: p.get(f)
                        for f in (
                            'repository',
                            'path',
                            'symbol',
                            'chunk_id',
                            'line_approx',
                            'namespace',
                            'key',
                            'operation',
                            'write_via',
                            'value_kind',
                        )
                        if f in p
                    },
                    'classification': assessment,
                    'evidence': {
                        'tier': c.get('tier'),
                        'source': c.get('evidence'),
                        'temporal': c.get('temporal_evidence'),
                        'producer_step_line': c.get('producer_step_line'),
                        'witness_path': c.get('witness_path', []),
                        'scope': c.get('layer_applicability'),
                        'storage_layer': c.get('effective_layer_candidate'),
                        'lookup_rule': c.get('lookup_rule'),
                        'route_conditions': c.get('route_conditions', []),
                        'future_step_lines': c.get('future_step_lines', []),
                        'later_prior_writer_step_lines': c.get('later_prior_writer_step_lines', []),
                    },
                    'runtime_verified': False,
                }
            )
        status = (
            'plausible_prior_producer'
            if any(c['classification'] == 'plausible_prior_writer' for c in candidates)
            else 'conditional_prior_producer'
            if matching_prior
            else 'producer_not_identified'
            if not link.get('candidates')
            else 'no_prior_writer_identified'
        )
        stats[status] += 1
        output.append(
            {
                'consumer': {
                    'reference_index': index,
                    'relation_index': ri,
                    'reference': reference.get('reference'),
                    'key': reference.get('key'),
                    'feature': relation.get('feature_path'),
                    'scenario': relation.get('scenario'),
                    'step_line': relation.get('line_approx'),
                    'step_text': relation.get('resolved_text') or relation.get('text'),
                    'example_row': relation.get('example_row'),
                    'example_values': relation.get('example_values'),
                },
                'status': status,
                'candidate_count': len(link.get('candidates', [])),
                'prior_writer_candidates': matching_prior,
                'returned_candidates': len(candidates),
                'candidates_truncated': max(
                    0,
                    sum(
                        not only_prior
                        or (
                            c.get('temporal_evidence') == 'prior_step_witness'
                            and c.get('tier', '').startswith('preceding_')
                        )
                        for c in link.get('candidates', [])
                    )
                    - len(candidates),
                ),
                'candidates': candidates,
                'diagnostics': link.get('diagnostics', []),
                'hook_applicability': link.get('hook_applicability'),
                'effective_storage_scope': link.get('effective_storage_scope'),
                'runtime_verified': False,
            }
        )
    return {
        'schema_version': 1,
        'source_repository': report.get('source_repository'),
        'query': {
            'key': key,
            'feature': feature,
            'scenario': scenario,
            'max_consumers': max_consumers,
            'max_producers': max_producers,
            'only_prior': only_prior,
        },
        'summary': {
            'matching_consumers': matched,
            'returned_consumers': len(output),
            'truncated_consumers': matched - len(output),
            'status_counts': dict(sorted(stats.items())),
            'returned_producer_candidates': sum(len(x['candidates']) for x in output),
        },
        'consumers': output,
        'guarantees': {
            'runtime_execution_inferred': False,
            'value_provenance_inferred': False,
            'call_path_required_between_separate_steps': False,
            'unknown_writer_is_not_proof_of_absence': True,
        },
        'limitations': [
            'Matching key and prior step witness are static evidence only.',
            'Hooks, dynamic dispatch and actual storage contents are not runtime verified.',
            'The underlying context_flow candidate inventory may be incomplete.',
        ],
    }
