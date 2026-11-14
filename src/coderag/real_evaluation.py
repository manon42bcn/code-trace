"""Evaluate source-labeled real questions without generation or source execution."""

import argparse
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from .config_context import context_limits_from_mapping
from .context_api import build_context
from .context_evaluation import evaluate_context_package
from .inventory import inventory
from .match_ranking import RANKING_PROFILE
from .query_planning import PLANNING_PROFILE, active_sources, plan_query
from .repository_paths import repository_index_path, repository_relationships_path
from .repository_routing import select_repository
from .retrieval import retrieve
from .semantic_config import load_retrieval, resolve_retrieval
from .source_filters import SourceFilters, scope_sources


def load_suite(path):
    suite = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(suite, dict) or suite.get('schema_version') != 1:
        raise ValueError('Expected a version 1 evaluation suite')
    cases = suite.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('Suite must contain cases')
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not all(
            isinstance(case.get(key), str) and case[key].strip()
            for key in ('id', 'question', 'query', 'default_repo', 'kind')
        ):
            raise ValueError('Cases require id, question, query, default_repo and kind')
        if case['id'] in seen or case['kind'] not in {'evidence', 'absent', 'inventory', 'routing'}:
            raise ValueError('Duplicate case ID or unsupported case kind')
        seen.add(case['id'])
        if 'filters' in case:
            if case['kind'] not in {'evidence', 'absent'} or not isinstance(case['filters'], dict):
                raise ValueError('Source filters require evidence/absence cases and an object')
            SourceFilters(**case['filters'])
        expected = case.get('expected')
        if not isinstance(expected, dict):
            raise ValueError('Cases require expected results')
        if case['kind'] != 'routing' and not isinstance(expected.get('repository'), str):
            raise ValueError('Expected repository required')
        if case['kind'] == 'evidence':
            sources = expected.get('sources')
            if (
                not isinstance(sources, list)
                or not sources
                or any(
                    not isinstance(source, dict) or not isinstance(source.get('path'), str)
                    for source in sources
                )
            ):
                raise ValueError('Evidence cases require non-empty source labels')
        if case['kind'] == 'inventory' and (
            not all(
                isinstance(case.get(key), str)
                for key in (
                    ('file', 'decorator')
                    if case.get('inventory_kind') == 'python-decorators'
                    else ('file', 'path')
                )
            )
            or type(expected.get('total')) is not int
            or expected['total'] < 0
        ):
            raise ValueError('Inventory cases require file, path and a non-negative expected total')
        if case['kind'] == 'routing' and not isinstance(expected.get('error'), str):
            raise ValueError('Routing cases require expected error code')
    return suite


def read_artifact(path):
    content = path.read_bytes()
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError('Artifact must be an object')
    return data, hashlib.sha256(content).hexdigest()


def matches(chunk, label):
    return (
        chunk.get('path') == label['path']
        and all(chunk.get(key) == label[key] for key in ('symbol', 'data_path') if key in label)
        and all(text in chunk.get('content', '') for text in label.get('contains', []))
    )


def evaluate_case(case, raw, config_path, profile, cache):
    expected = case['expected']
    try:
        routing = select_repository(case['query'], raw['repositories'], case['default_repo'])
    except ValueError as exc:
        if case['kind'] == 'routing' and getattr(exc, 'code', None) == expected.get('error'):
            return {'passed': True, 'routing_error': exc.code}
        raise
    if case['kind'] == 'routing':
        return {
            'passed': False,
            'reason': 'Expected routing error was not raised',
            'routing': routing,
        }
    name = routing['repository']
    if name != expected['repository']:
        return {'passed': False, 'reason': 'Wrong repository', 'routing': routing}
    if name not in cache:
        index_path = repository_index_path(raw, config_path, name)
        index, index_hash = read_artifact(index_path)
        cache[name] = {
            'index': index,
            'index_sha256': index_hash,
            'index_created_at': index.get('created_at'),
            'index_path': str(index_path),
        }
    artifacts = cache[name]
    index = artifacts['index']
    if case['kind'] == 'inventory':
        result = inventory(
            index,
            repository=name,
            file=case['file'],
            path=case.get('path'),
            unique_by=case.get('unique_by'),
            where=case.get('where'),
            group_by=case.get('group_by'),
            kind=case.get('inventory_kind', 'list'),
            decorator=case.get('decorator'),
        )
        return {
            'passed': result['status'] == 'ok'
            and result['complete']
            and result['total'] == expected['total']
            and (
                expected.get('groups') is None
                or len(result.get('groups', [])) == expected['groups']
            ),
            'routing': routing,
            'total': result['total'],
            'entries': result.get('entries'),
            'scope': result.get('scope'),
            'complete': result['complete'],
        }
    if 'retrieval' not in artifacts:
        links, links_hash = read_artifact(repository_relationships_path(config_path, name))
        artifacts['relationships_sha256'] = links_hash
        effective = json.loads(json.dumps(raw))
        if profile in {'lexical', 'semantic'}:
            effective.setdefault('retrieval', {})['mode'] = profile
            effective['repositories'][name].setdefault('retrieval', {})['mode'] = profile
        if profile == 'lexical':
            effective.setdefault('retrieval', {})['semantic_enabled'] = False
            effective['repositories'][name].setdefault('retrieval', {})['semantic_enabled'] = False
        retrieval, stores, provider = load_retrieval(
            effective, config_path, Path(artifacts['index_path'])
        )
        _, vector_paths, _ = resolve_retrieval(
            effective, config_path, Path(artifacts['index_path'])
        )
        artifacts['embedding_metadata'] = {
            key: asdict(store.metadata) for key, store in (stores or {}).items()
        }
        artifacts['retrieval_config'] = asdict(retrieval)
        artifacts['vectors_sha256'] = {
            version: hashlib.sha256(path.read_bytes()).hexdigest()
            for version, path in (vector_paths or {}).items()
        }
        artifacts.update(
            links=links,
            relationships_sha256=links_hash,
            retrieval=retrieval,
            stores=stores,
            provider=provider,
        )
    filters = SourceFilters(**case.get('filters', {}))
    scoped_index, scoped_graph = scope_sources(index, artifacts['links']['evidence_graph'], filters)
    results = retrieve(
        index,
        artifacts['links']['evidence_graph'],
        routing['query'],
        config=artifacts['retrieval'],
        semantic_store=artifacts['stores'],
        provider=artifacts['provider'],
        filters=filters,
    )
    limits = context_limits_from_mapping(raw.get('context'))
    context = build_context(scoped_index, scoped_graph, routing['query'], results, **limits)
    chunks = index['chunks']
    groups = [
        {c['id'] for c in chunks if matches(c, label)} for label in expected.get('sources', [])
    ]
    relevant = set().union(*groups) if groups else set()
    retrieved_ids = {r['chunk_id'] for r in results}
    selected_ids = {item['citation']['chunk_id'] for item in context['items']}
    gold_found = all(groups) if groups else True
    coverage = sum(bool(group & selected_ids) for group in groups) / len(groups) if groups else None
    retrieved_coverage = (
        sum(bool(group & retrieved_ids) for group in groups) / len(groups) if groups else None
    )
    citations_valid = all(
        any(
            c['id'] == item['citation']['chunk_id']
            and c['path'] == item['citation']['path']
            and c.get('start_line') == item['citation']['start_line']
            and c.get('end_line') == item['citation']['end_line']
            for c in chunks
        )
        for item in context['items']
    )
    passed = (
        (not results and not context['items'])
        if case['kind'] == 'absent'
        else (
            gold_found and coverage >= expected.get('min_context_coverage', 1.0) and citations_valid
        )
    )
    metrics = evaluate_context_package(context, relevant)
    if not groups or not gold_found:
        metrics['coverage'] = None
    return {
        'passed': passed,
        'source_scope': {
            'filters': filters.describe(),
            'indexed_chunks': len(index['chunks']),
            'eligible_chunks': len(scoped_index['chunks']),
        },
        'routing': routing,
        'gold_sources_found': gold_found,
        'retrieved_source_coverage': retrieved_coverage,
        'context_source_coverage': coverage,
        'citations_valid': citations_valid,
        'retrieved_chunks': len(results),
        'query_plan': {
            **plan_query(routing['query'], kind=artifacts['retrieval'].lexical_kind),
            'active_sources': active_sources(
                plan_query(routing['query'], kind=artifacts['retrieval'].lexical_kind),
                artifacts['retrieval'].mode,
                semantic_available=bool(artifacts['stores']),
            ),
        },
        'retrieval_ranking': [
            {key: result.get(key) for key in ('chunk_id', 'path', 'symbol', 'score', 'ranking')}
            for result in results[:10]
        ],
        'context_metrics': metrics,
        'coverage_status': 'evaluated'
        if groups and gold_found
        else ('gold_sources_missing' if groups else 'not_applicable'),
        'selection': context['selection'],
        'citations': [item['citation'] for item in context['items']],
        'reason': None
        if passed
        else 'Expected sources absent, insufficient coverage or unexpected results',
    }


def run_suite(dataset_path, config_path, *, profile='lexical', selected=None):
    """Run independent cases, recording failures rather than dropping unavailable repositories."""
    if profile not in {'lexical', 'semantic', 'configured'}:
        raise ValueError('Unknown evaluation profile')
    suite = load_suite(dataset_path)
    config_path = Path(config_path).resolve()
    raw, config_hash = read_artifact(config_path)
    cases = suite['cases']
    if selected:
        unknown = set(selected) - {case['id'] for case in cases}
        if unknown:
            raise ValueError(f'Unknown cases: {sorted(unknown)}')
        cases = [case for case in cases if case['id'] in selected]
    rows, cache = [], {}
    for case in cases:
        started = time.perf_counter()
        try:
            result = evaluate_case(case, raw, config_path, profile, cache)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            result = {'passed': False, 'error': {'type': type(exc).__name__, 'message': str(exc)}}
        rows.append(
            {
                'id': case['id'],
                'question': case['question'],
                'query': case['query'],
                'kind': case['kind'],
                **result,
                'latency_seconds': round(time.perf_counter() - started, 6),
            }
        )
    passed = sum(row['passed'] for row in rows)
    return {
        'schema_version': 1,
        'status': 'ok' if passed == len(rows) else 'failed',
        'profile': profile,
        'generation_evaluated': False,
        'ranking_profile': RANKING_PROFILE,
        'planning_profile': PLANNING_PROFILE,
        'dataset_sha256': hashlib.sha256(Path(dataset_path).read_bytes()).hexdigest(),
        'config_sha256': config_hash,
        'cases': len(rows),
        'passed': passed,
        'failed': len(rows) - passed,
        'rows': rows,
        'artifacts': {
            name: {
                k: v
                for k, v in data.items()
                if k
                in {
                    'index_path',
                    'index_sha256',
                    'index_created_at',
                    'relationships_sha256',
                    'vectors_sha256',
                    'embedding_metadata',
                    'retrieval_config',
                }
            }
            for name, data in cache.items()
        },
        'limitations': [
            'Source labels are a curated subset, not complete relevance judgments.',
            'Question text is descriptive; query is the exact evaluated search input.',
            'Lexical profile disables semantic retrieval; configured profile may load embeddings.',
            'Latency includes initial loading; no generation or runtime code is evaluated.',
            'Absence means no retrieved evidence, not proof of repository-wide absence.',
        ],
    }


def compare_reports(current, baseline):
    """Compare like-for-like case verdicts without treating noisy latency as correctness."""
    if (current['dataset_sha256'], current['profile']) != (
        baseline.get('dataset_sha256'),
        baseline.get('profile'),
    ):
        raise ValueError('Baseline must use the same dataset hash and profile')
    old = {row['id']: row for row in baseline['rows']}
    new = {row['id']: row for row in current['rows']}
    if set(old) != set(new):
        raise ValueError('Baseline must contain the same selected cases')
    return {
        'improved': [key for key in new if new[key]['passed'] and not old[key]['passed']],
        'regressed': [key for key in new if old[key]['passed'] and not new[key]['passed']],
        'unchanged': [key for key in new if old[key]['passed'] == new[key]['passed']],
        'artifact_changes': {
            name: {k: v for k, v in data.items() if k.endswith('_sha256')}
            for name, data in current['artifacts'].items()
        }
        != {
            name: {k: v for k, v in data.items() if k.endswith('_sha256')}
            for name, data in baseline.get('artifacts', {}).items()
        },
        'config_changed': current['config_sha256'] != baseline.get('config_sha256'),
        'planning_profiles': {
            'baseline': baseline.get('planning_profile', 'unversioned'),
            'current': current.get('planning_profile', 'unversioned'),
        },
        'ranking_profiles': {
            'baseline': baseline.get('ranking_profile', 'unversioned'),
            'current': current.get('ranking_profile', 'unversioned'),
        },
        'metric_deltas': {
            key: {
                metric: (new[key][metric] - old[key][metric])
                if isinstance(new[key].get(metric), (int, float))
                and isinstance(old[key].get(metric), (int, float))
                else None
                for metric in (
                    'retrieved_source_coverage',
                    'context_source_coverage',
                    'latency_seconds',
                )
            }
            for key in new
        },
    }


def compare_profiles(dataset, config, *, selected=None):
    suite = load_suite(dataset)
    if any(
        case['kind'] not in {'evidence', 'absent'}
        for case in suite['cases']
        if not selected or case['id'] in selected
    ):
        raise ValueError(
            'Profile comparisons require evidence/absence cases; select a retrieval-only suite'
        )
    runs = {
        profile: run_suite(dataset, config, profile=profile, selected=selected)
        for profile in ('lexical', 'semantic')
    }
    lexical, semantic = runs['lexical'], runs['semantic']

    def source_hashes(report):
        return {
            name: {
                key: value
                for key, value in data.items()
                if key in {'index_sha256', 'relationships_sha256'}
            }
            for name, data in report['artifacts'].items()
        }

    comparable = (
        source_hashes(lexical) == source_hashes(semantic)
        and lexical['dataset_sha256'] == semantic['dataset_sha256']
        and lexical['config_sha256'] == semantic['config_sha256']
    )
    rows = []
    for left, right in zip(lexical['rows'], semantic['rows'], strict=True):
        rows.append(
            {
                'id': left['id'],
                'query': left['query'],
                'lexical_passed': left['passed'],
                'semantic_passed': right['passed'],
                'lexical_coverage': left.get('context_source_coverage'),
                'semantic_coverage': right.get('context_source_coverage'),
            }
        )
    return {
        'schema_version': 1,
        'profile': 'comparison',
        'status': 'ok'
        if comparable and all(run['failed'] == 0 for run in runs.values())
        else 'failed',
        'cases': lexical['cases'],
        'passed': sum(row['lexical_passed'] and row['semantic_passed'] for row in rows),
        'failed': sum(not (row['lexical_passed'] and row['semantic_passed']) for row in rows),
        'comparable_source_snapshots': comparable,
        'profile_counts': {
            name: {
                'passed': run['passed'],
                'cases': run['cases'],
                'errors': sum('error' in row for row in run['rows']),
            }
            for name, run in runs.items()
        },
        'rows': rows,
        'runs': runs,
        'limitations': [
            'Same original queries and source expectations; no generation evaluated.',
            'Compare coverage only when source snapshots match; loading affects latency.',
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=Path('evaluations/real_questions.json'))
    parser.add_argument('--config', type=Path, default=Path('config.json'))
    parser.add_argument(
        '--profile', choices=('lexical', 'semantic', 'configured'), default='lexical'
    )
    parser.add_argument(
        '--compare-profiles',
        action='store_true',
        help='Run lexical and semantic on identical cases',
    )
    parser.add_argument('--case', action='append')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, help='Compare a matching previous report')
    args = parser.parse_args(argv)
    if args.compare_profiles and args.profile != 'lexical':
        parser.error('--compare-profiles runs fixed lexical and semantic profiles')
    if args.compare_profiles and args.baseline:
        parser.error('Use individual profile reports for --baseline comparisons')
    import sys
    from contextlib import redirect_stdout

    try:
        with redirect_stdout(sys.stderr):
            result = (
                compare_profiles(args.dataset, args.config, selected=args.case)
                if args.compare_profiles
                else run_suite(args.dataset, args.config, profile=args.profile, selected=args.case)
            )
        if args.baseline:
            result['comparison'] = compare_reports(result, read_artifact(args.baseline)[0])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
        )
        print(  # noqa: T201 - CLI summary
            json.dumps(
                {
                    'status': result['status'],
                    'passed': result['passed'],
                    'failed': result['failed'],
                    'report': str(args.output),
                    **(
                        {'profiles': result['profile_counts']} if 'profile_counts' in result else {}
                    ),
                }
            )
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f'Evaluation error: {exc}\n')
    if result['status'] != 'ok':
        raise SystemExit(1)
