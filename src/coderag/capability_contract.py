"""Framework-neutral, offline capability and evidence inventory.

Capability detection is based on indexed source artifacts, not installed packages,
imports, or successful test execution. It is descriptive and conservative.
"""

from collections import Counter

CONTRACT_VERSION = 1


def _cap(status, basis, count=0, note=''):
    return {
        'status': status,
        'evidence_kind': basis,
        'observations': count,
        'runtime_verified': False,
        'note': note,
    }


def build_capability_contract(indexes, report, *, dry_run_supplied=False, test_plan_supplied=False):
    """Produce compact, framework-independent metadata without changing relations."""
    source_repo = report['source_repository']
    index = indexes.get(source_repo, {})
    chunks = index.get('chunks', [])
    languages = Counter(c.get('language') for c in chunks if c.get('language'))
    gherkin = languages.get('gherkin', 0)
    python = languages.get('python', 0)
    definitions = [r for r in report.get('relations', []) if r.get('definitions')]
    flow = report.get('toolium', {}).get('context_flow', {})
    producers = flow.get('producers', [])
    consumers = flow.get('consumers', [])
    scoped = flow.get('scoped_environments', [])
    # Toolium semantics are indicated by explicit analyzed storage namespaces,
    # rather than the mere presence of the word Toolium in a package or filename.
    storage_count = sum(
        x.get('namespace', '').startswith('toolium.') for x in [*producers, *consumers]
    )
    caps = {
        'structural_index': _cap(
            'available' if chunks else 'not_evaluated', 'indexed_chunks', len(chunks)
        ),
        'python_ast': _cap(
            'available' if python else 'not_applicable', 'indexed_python_chunks', python
        ),
        'gherkin': _cap(
            'available' if gherkin else 'not_applicable', 'indexed_gherkin_chunks', gherkin
        ),
        'behave_static_matching': _cap(
            'available' if gherkin else 'not_applicable',
            'gherkin_relations',
            len(report.get('relations', [])),
            'Static candidates; imports do not prove runtime registration',
        ),
        'toolium_storage': _cap(
            'available' if storage_count else 'not_evaluated' if python else 'not_applicable',
            'storage_namespace_analysis',
            storage_count,
        ),
        'behave_lifecycle': _cap(
            'available' if scoped else 'not_evaluated' if gherkin else 'not_applicable',
            'static_environment_scopes',
            len(scoped),
        ),
        'behave_dry_run': _cap(
            'available' if dry_run_supplied else 'not_evaluated' if gherkin else 'not_applicable',
            'external_report' if dry_run_supplied else 'none',
            int(bool(dry_run_supplied)),
            'Matches definitions but does not execute step bodies',
        ),
        'test_plan': _cap(
            'available' if test_plan_supplied else 'not_evaluated' if gherkin else 'not_applicable',
            'explicit_manifest' if test_plan_supplied else 'none',
            int(bool(test_plan_supplied)),
        ),
    }
    status = Counter(r.get('status', 'unknown') for r in report.get('relations', []))
    evidence = {
        'contract_version': CONTRACT_VERSION,
        'analysis_mode': 'offline_static_with_optional_external_observations',
        'runtime_verified': False,
        'resolution_counts': dict(status),
        'source_records': {
            'indexed_chunks': len(chunks),
            'python_chunks': python,
            'gherkin_chunks': gherkin,
            'step_relations': len(report.get('relations', [])),
            'static_producer_records': len(producers),
            'static_consumer_records': len(consumers),
            'step_relations_with_definition_candidates': len(definitions),
        },
        'external_observations': {
            'behave_dry_run': 'supplied' if dry_run_supplied else 'not_supplied',
            'test_plan': 'supplied' if test_plan_supplied else 'not_supplied',
        },
        'guarantees': {
            'static_match_means_runtime_registration': False,
            'static_writer_means_executed_write': False,
            'dry_run_means_test_executed': False,
            'unresolved_means_planned': False,
        },
    }
    return {
        'schema_version': CONTRACT_VERSION,
        'source_repository': source_repo,
        'capabilities': caps,
        'evidence': evidence,
        'supported_evidence_levels': [
            'static_candidate',
            'external_match_observation',
            'explicit_test_plan',
            'runtime_execution',
        ],
        'note': (
            'Supported levels describe the vocabulary; runtime execution evidence is not collected.'
        ),
    }


def attach_capability_contract(
    report, indexes, *, dry_run_supplied=False, test_plan_supplied=False
):
    report['analysis_capabilities'] = build_capability_contract(
        indexes, report, dry_run_supplied=dry_run_supplied, test_plan_supplied=test_plan_supplied
    )
    return report
