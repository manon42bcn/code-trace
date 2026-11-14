"""Conservative, per-reference interpretation of candidate storage writers.

No executions are simulated: phase, step ordering and ChainMap precedence are
independent evidence dimensions. Unknowns never silently become guarantees.
"""

LAYER_PRIORITY = {'scenario': 0, 'feature': 1, 'run': 2, 'behave.context': 3}
PHASES = ('before_all', 'before_feature', 'before_scenario', 'background', 'scenario_steps')


def writer_phase(producer, candidate=None):
    """Phase inferred from a hook symbol or a witnessed preceding Gherkin step.

    An arbitrary helper's declaration is not proof it runs in that phase.
    Candidate witnesses establish a *possible* step-phase invocation only.
    """
    name = str(producer.get('symbol') or '').split('.')[-1]
    if producer.get('path', '').endswith('environment.py') and name in PHASES[:3]:
        return name
    candidate = candidate or {}
    if candidate.get('temporal_evidence') == 'prior_step_witness':
        return 'scenario_steps_or_background'
    if candidate.get('temporal_evidence') == 'future_step_only':
        return 'future_scenario_step'
    return 'unknown_step_or_helper'


def storage_view_at_write(candidate, producer, scope):
    """Use phase evidence without treating static reachability as execution."""
    namespace = candidate['namespace']
    phase = writer_phase(producer, candidate)
    diagnostics = []
    if namespace == 'toolium.feature_storage':
        layer = 'feature'
    elif namespace == 'toolium.run_storage':
        layer = 'run'
    elif namespace == 'behave.context':
        layer = 'behave.context'
    elif namespace == 'toolium.storage':
        layer = {
            'before_all': 'run',
            'before_feature': 'feature',
            'before_scenario': 'scenario',
        }.get(phase)
        if layer is None:
            if phase == 'scenario_steps_or_background' and scope.get('scenario_layer_reachable'):
                layer = 'scenario'
                diagnostics.append('step_phase_witness_not_runtime_execution')
            else:
                layer = 'unknown_storage_view'
                if phase == 'unknown_step_or_helper':
                    diagnostics.append('no_prior_step_or_hook_phase_witness')
                elif phase == 'future_scenario_step':
                    diagnostics.append('writer_only_reachable_after_read')
                else:
                    diagnostics.append('scenario_hook_not_reachable')
    else:
        layer = 'unknown_storage_view'
        diagnostics.append('unsupported_storage_namespace')
    supported = {
        'run': 'run_layer_reachable',
        'feature': 'feature_layer_reachable',
        'scenario': 'scenario_layer_reachable',
    }
    applicability = (
        'fallback_only'
        if layer == 'behave.context'
        else 'static_hook_reachable'
        if supported.get(layer) and scope.get(supported[layer])
        else 'hook_not_established'
    )
    if layer in supported and applicability != 'static_hook_reachable':
        diagnostics.append('storage_lifecycle_hook_not_reachable')
    if namespace == 'behave.context':
        diagnostics.append('fallback_requires_storage_key_absence')
    return {
        'writer_phase_candidate': phase,
        'phase_evidence': (
            'hook_function_symbol'
            if phase in PHASES[:3]
            else 'prior_gherkin_step_witness'
            if phase == 'scenario_steps_or_background'
            else 'future_gherkin_step_only'
            if phase == 'future_scenario_step'
            else 'unresolved'
        ),
        'write_view_layer_candidate': layer,
        'write_view_applicability': applicability,
        'unknown_view_diagnostics': diagnostics,
        'runtime_verified': False,
    }


def assess_reference(candidates, producers, scope):
    """Rank evidence, not runtime values; retain every original candidate."""
    annotated = []
    prior_writers = []
    for c in candidates:
        p = producers[c['producer_id']]
        view = storage_view_at_write(c, p, scope)
        c['write_context_evidence'] = view
        layer = view['write_view_layer_candidate']
        line = c.get('producer_step_line')
        if c.get('temporal_evidence') == 'prior_step_witness' and line is not None:
            prior_writers.append((c, layer, line))
    for c in candidates:
        view = c['write_context_evidence']
        layer = view['write_view_layer_candidate']
        line = c.get('producer_step_line')
        competing = []
        for other, other_layer, other_line in prior_writers:
            if other is c:
                continue
            # Only writers with evidenced preceding steps, and known layers,
            # are useful as potential shadowing/overwrite witnesses.
            if layer not in LAYER_PRIORITY or other_layer not in LAYER_PRIORITY:
                continue
            if other_layer == layer and line is not None and other_line > line:
                reason = 'later_prior_step_same_layer_may_overwrite'
            elif LAYER_PRIORITY[other_layer] < LAYER_PRIORITY[layer]:
                reason = 'higher_priority_layer_may_hide'
            else:
                continue
            competing.append(
                {
                    'producer_id': other['producer_id'],
                    'step_line': other_line,
                    'layer': other_layer,
                    'reason': reason,
                }
            )
        competing.sort(key=lambda x: (x['step_line'], x['producer_id'], x['reason']))
        reasons = []
        if c['temporal_evidence'] == 'future_step_only':
            verdict = 'temporally_incompatible_candidate'
            reasons.append('writer_only_seen_after_read')
        elif c['temporal_evidence'] != 'prior_step_witness':
            verdict = 'insufficient_temporal_evidence'
            reasons.append('no_prior_step_witness')
        elif layer == 'unknown_storage_view':
            verdict = 'conditional_applicability'
            reasons.append('storage_view_at_write_unknown')
        else:
            verdict = 'plausible_prior_writer'
        if (
            layer in ('feature', 'run', 'scenario')
            and view['write_view_applicability'] != 'static_hook_reachable'
        ):
            reasons.append('storage_hook_not_established')
        if c.get('conditional_fallback'):
            reasons.append('storage_key_must_be_absent')
        if c.get('nested_path_status') in ('unknown_dynamic_value', 'literal_path_not_found'):
            reasons.append(c['nested_path_status'])
        reasons += sorted({x['reason'] for x in competing})
        if verdict == 'plausible_prior_writer' and reasons:
            verdict = 'conditional_applicability'
        c['provenance_assessment'] = {
            'status': verdict,
            'layer_candidate': layer,
            'competing_prior_writers': competing,
            'conditions': list(dict.fromkeys(reasons)),
            'effective_value_confirmed': False,
            'runtime_verified': False,
        }
        annotated.append(c)
    # Choice is an explanatory first candidate, NOT a unique effective writer.
    priority = {
        'plausible_prior_writer': 0,
        'conditional_applicability': 1,
        'insufficient_temporal_evidence': 2,
        'temporally_incompatible_candidate': 3,
    }
    ordered = sorted(
        annotated,
        key=lambda c: (
            priority[c['provenance_assessment']['status']],
            LAYER_PRIORITY.get(c['provenance_assessment']['layer_candidate'], 4),
            -(c.get('producer_step_line') or -1),
            c['producer_id'],
        ),
    )
    representative = ordered[0]['producer_id'] if ordered else None
    return {
        'model': 'static_candidate_provenance_not_runtime_resolution',
        'representative_candidate_producer_id': representative,
        'candidate_count': len(candidates),
        'status_counts': {
            status: sum(c['provenance_assessment']['status'] == status for c in candidates)
            for status in priority
            if any(c['provenance_assessment']['status'] == status for c in candidates)
        },
        'runtime_verified': False,
        'effective_value_confirmed': False,
    }
