"""Conservative, version-aware static/Behave reconciliation (never executes steps)."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError(f'No se puede leer JSON {path}: {exc}') from exc


def _location(value):
    if not isinstance(value, str):
        return '', None
    normalized = value.replace('\\', '/').removeprefix('./')
    match = re.match(r'^(.*?):(\d+)(?::\d+)?$', normalized)
    return (match.group(1), int(match.group(2))) if match else (normalized, None)


def _path(value):
    return _location(value)[0]


def _equivalent_paths(a, b):
    a, b = _path(a), _path(b)
    if not a or not b:
        return False
    return a == b or a.endswith('/' + b) or b.endswith('/' + a)


def _normalized_feature(path):
    path = _path(path)
    anchor = '/features/'
    if anchor in path:
        return path.rsplit(anchor, 1)[1]
    return path.removeprefix('features/')


def _dry_steps(payload):
    """Produce one record per expanded step with authoritative Behave match presence."""
    if isinstance(payload, dict) and isinstance(payload.get('steps'), list):
        for s in payload['steps']:
            if not isinstance(s, dict):
                continue
            path, embedded_line = _location(s.get('location', ''))
            status = s.get('status') or (s.get('result') or {}).get('status')
            match = s.get('match')
            yield {
                'feature_path': s.get('feature_path') or s.get('feature') or s.get('uri') or path,
                'line': s.get('line') or embedded_line,
                'text': s.get('text', s.get('name', '')),
                'status': status,
                'defined': bool(match)
                if 'match' in s
                else (False if status is None else _status_defined(status)),
                'match_location': _path((match or {}).get('location'))
                if isinstance(match, dict)
                else '',
                'scenario': s.get('scenario'),
                'example_row': s.get('example_row'),
            }
        return
    features = (
        payload
        if isinstance(payload, list)
        else payload.get('features', [])
        if isinstance(payload, dict)
        else []
    )
    for feature in features:
        if not isinstance(feature, dict):
            continue
        path = _path(feature.get('location') or feature.get('uri') or feature.get('filename'))
        for element in feature.get('elements', []):
            for step in element.get('steps', []):
                locpath, lineno = _location(step.get('location', ''))
                status = (step.get('result') or {}).get('status') or step.get('status')
                match = step.get('match')
                yield {
                    'feature_path': locpath or path,
                    'line': step.get('line') or lineno,
                    'text': step.get('name', ''),
                    'status': status,
                    'defined': bool(match)
                    if 'match' in step
                    else (False if status is None else _status_defined(status)),
                    'match_location': _path((match or {}).get('location'))
                    if isinstance(match, dict)
                    else '',
                    'scenario': element.get('name'),
                    'example_row': None,
                }


def _status_defined(status):
    if status == 'undefined':
        return False
    if status in ('passed', 'failed', 'untested', 'skipped'):
        return True if status != 'skipped' else None
    return None


def _static_defined(status):
    return status in ('resolved_local', 'resolved_external')


def _reference_candidates(relation, index):
    key = _normalized_feature(relation.get('feature_path', ''))
    candidates = index.get(key, [])
    candidates = [
        r for r in candidates if _equivalent_paths(relation.get('feature_path'), r['feature_path'])
    ]
    # Do not fall back to a different line or text: live-version diffs remain unmatched.
    if isinstance(relation.get('line_approx'), int):
        candidates = [r for r in candidates if r['line'] == relation['line_approx']]
    return [
        r for r in candidates if r['text'] == relation.get('resolved_text', relation.get('text'))
    ]


def _resolution(rel, candidates):  # noqa: ARG001 - Preserve public callable signature
    if not candidates:
        return 'not_matched', 'not_comparable', 'none'
    signals = {c['defined'] for c in candidates}
    if len(signals) != 1 or None in signals:
        if len(candidates) == 1 and candidates[0]['status'] == 'skipped':
            return 'skipped', 'exact_step_identity_version_unverified', 'not_executed'
        return 'ambiguous_dry_run', 'uncertain', 'mixed_or_unknown'
    value = next(iter(signals))
    statuses = {c['status'] for c in candidates}
    status = 'undefined' if not value else ('untested' if statuses == {'untested'} else 'defined')
    return (
        status,
        'exact_step_identity_version_unverified',
        'matched_definition' if value else 'missing_definition',
    )


def _matching_diagnostic(relation, candidates, reconciliation):
    """Explain observed matcher disagreements, without claiming a root cause."""
    if reconciliation not in (
        'behave_defined_but_static_unresolved',
        'static_resolved_but_behave_not_defined',
    ):
        return None
    locations = sorted({c['match_location'] for c in candidates if c['match_location']})
    origins = set()
    for location in locations:
        location = location.replace('\\', '/')
        if '/site-packages/' in location or '/dist-packages/' in location:
            origins.add('installed_dependency')
        elif location.startswith(('common/', 'steps/', 'acceptance/')) or '/steps/' in location:
            origins.add('repository_or_custom_steps')
        else:
            origins.add('unclassified_path')
    if not locations:
        origins.add('no_definition_location')
    if reconciliation == 'behave_defined_but_static_unresolved':
        investigation = (
            'dependency_scope_or_pattern_match'
            if origins == {'installed_dependency'}
            else 'local_scope_or_pattern_match'
            if origins == {'repository_or_custom_steps'}
            else 'mixed_definition_origins_or_pattern_match'
        )
    else:
        investigation = 'runtime_registration_or_source_version_difference'
    return {
        'category': investigation,
        'definition_origins': sorted(origins),
        'definition_locations': locations[:12],
        'static_reason': relation.get('reason'),
        'static_resolution_tier': relation.get('resolution_tier'),
        'possible_causes': (
            ['version_drift', 'pattern_matching', 'definition_scope_or_loading']
            if reconciliation == 'behave_defined_but_static_unresolved'
            else ['version_drift', 'conditional_registration', 'definition_scope_or_loading']
        ),
        'conclusion_verified': False,
        'next_action': (
            'Compare the exact feature and step-definition commit; inspect '
            'pattern and import/registration path in the recorded definition '
            'file.'
        ),
    }


def apply_reconciliation(report, *, dry_run_path=None, plan_path=None):
    """Add evidence only; preserve static resolution and context relations."""
    if not dry_run_path and not plan_path:
        return report
    dry = list(_dry_steps(_read(dry_run_path))) if dry_run_path else []
    manifest = _read(plan_path) if plan_path else {}
    entries = manifest.get('steps', []) if isinstance(manifest, dict) else []
    if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
        raise ValueError('El manifiesto test-plan debe contener una lista steps de objetos')
    for e in entries:
        if e.get('implementation_status') not in ('planned', 'implemented', 'unknown'):
            raise ValueError('implementation_status debe ser planned, implemented o unknown')
        if not e.get('feature_path') or (not isinstance(e.get('line'), int) and not e.get('text')):
            raise ValueError('Cada step del test-plan requiere feature_path y line o text')
    index = defaultdict(list)
    for i, step in enumerate(dry):
        index[_normalized_feature(step['feature_path'])].append({**step, '_index': i})
    counts, mismatches, matched = Counter(), Counter(), set()
    diagnostic_categories = Counter()
    diagnostic_examples = defaultdict(list)
    for rel in report.get('relations', []):
        candidates = _reference_candidates(rel, index) if dry_run_path else []
        for s in candidates:
            matched.add(s['_index'])
        status, comparability, match_evidence = (
            _resolution(rel, candidates) if dry_run_path else ('not_checked', 'not_checked', 'none')
        )
        plans = [
            p
            for p in entries
            if _equivalent_paths(rel.get('feature_path'), p['feature_path'])
            and (not isinstance(p.get('line'), int) or p['line'] == rel.get('line_approx'))
            and (not p.get('text') or p['text'] in (rel.get('text'), rel.get('resolved_text')))
        ]
        plan_states = {p['implementation_status'] for p in plans}
        implementation = next(iter(plan_states)) if len(plan_states) == 1 else 'unknown'
        if len(plan_states) > 1:
            mismatches['conflicting_test_plan_entries'] += 1
        static = rel.get('status')
        if status == 'undefined':
            reconciliation = (
                'static_resolved_but_behave_not_defined'
                if _static_defined(static)
                else 'both_unresolved'
                if static == 'unresolved'
                else 'no_detected_conflict'
            )
        elif status in ('defined', 'untested'):
            reconciliation = (
                'behave_defined_but_static_unresolved'
                if static == 'unresolved'
                else 'no_detected_conflict'
            )
        elif status == 'skipped':
            reconciliation = 'no_detected_conflict'
        else:
            reconciliation = status
        if reconciliation in (
            'static_resolved_but_behave_not_defined',
            'behave_defined_but_static_unresolved',
        ):
            mismatches[reconciliation] += 1
        diagnosis = _matching_diagnostic(rel, candidates, reconciliation)
        if diagnosis:
            diagnostic_categories[diagnosis['category']] += 1
            if len(diagnostic_examples[diagnosis['category']]) < 8:
                diagnostic_examples[diagnosis['category']].append(
                    {
                        'feature_path': rel.get('feature_path'),
                        'line': rel.get('line_approx'),
                        'step': rel.get('resolved_text', rel.get('text')),
                        'definition_locations': diagnosis['definition_locations'],
                    }
                )
        rel['implementation_evidence'] = {
            'static_resolution': static,
            'implementation_status': implementation,
            'implementation_source': 'explicit_test_plan' if len(plan_states) == 1 else 'unknown',
            'behave_status': status,
            'reconciliation': reconciliation,
            'comparability': comparability,
            'version_verified': False,
            'match_evidence': match_evidence,
            'dry_run_instances': len(candidates),
            'dry_run_match_locations': sorted(
                {c['match_location'] for c in candidates if c['match_location']}
            )[:12],
            'runtime_verified': False,
            'discrepancy_diagnostic': diagnosis,
        }
        counts[status] += 1
    from .capability_contract import _cap

    # Standalone reconciliation is also used by clients with a minimal report.
    contract = report.get('analysis_capabilities')
    if contract is not None:
        caps = contract['capabilities']
        if dry_run_path:
            caps['behave_dry_run'] = _cap(
                'available',
                'external_report',
                1,
                'Matches definitions but does not execute step bodies',
            )
        if plan_path:
            caps['test_plan'] = _cap('available', 'explicit_manifest', 1)
        contract['evidence']['external_observations'] = {
            'behave_dry_run': 'supplied' if dry_run_path else 'not_supplied',
            'test_plan': 'supplied' if plan_path else 'not_supplied',
        }
    # Reconciliation enriches the contract without altering static candidates.
    report['behave_reconciliation'] = {
        'dry_run_supplied': bool(dry_run_path),
        'test_plan_supplied': bool(plan_path),
        'dry_run_step_records': len(dry),
        'dry_run_unmatched_records': len(dry) - len(matched),
        'dry_run_defined_records': sum(s['defined'] is True for s in dry),
        'dry_run_undefined_records': sum(s['defined'] is False for s in dry),
        'dry_run_uncertain_records': sum(s['defined'] is None for s in dry),
        'relation_behave_statuses': dict(counts),
        'mismatches': dict(mismatches),
        'diagnostic_categories': dict(diagnostic_categories),
        'diagnostic_examples': dict(diagnostic_examples),
        'disclaimer': (
            'Una identidad exacta de step no certifica igualdad de versiones. '
            'Dry-run confirma matching, no ejecucion; undefined no implica '
            'planned.'
        ),
    }
    return report
