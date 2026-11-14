"""Versioned, compact CLI contract for agent consumers."""

from __future__ import annotations

import argparse
import json
import sys
import time
from contextlib import redirect_stdout
from dataclasses import asdict, replace
from pathlib import Path

from .config_context import context_limits_from_mapping
from .generation_config import GenerationConfig
from .generation_factory import build_generation_provider
from .match_ranking import RANKING_PROFILE
from .query_planning import PLANNING_PROFILE, active_sources, plan_query
from .rag_pipeline import answer
from .repository_paths import repository_index_path, repository_relationships_path
from .source_filters import SourceFilters


def envelope(mode, *, status='ok', **values):
    return {
        'schema_version': '1',
        'status': status,
        'mode': mode,
        'answer': None,
        'claims': [],
        'citations': [],
        'evidence': [],
        'limitations': [],
        'error': None,
        'retrieval': None,
        'context': None,
        'pagination': None,
        'matches': [],
        'readiness': None,
        **values,
    }


class QueryParser(argparse.ArgumentParser):
    def error(self, message):
        print(  # noqa: T201 - CLI output
            json.dumps(
                envelope(None, status='error', error={'type': 'ArgumentError', 'message': message})
            )
        )
        self.exit(2)


def configure_parser(parser):
    parser.add_argument('query')
    parser.add_argument('--index', type=Path)
    parser.add_argument('--relationships', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--default-repo', help='Route using repository metadata and this fallback')
    parser.add_argument(
        '--resolve-only',
        action='store_true',
        help='Show routing without reading indexes or calling models',
    )
    parser.add_argument('--repo', help='Explicit configured repository selector')
    parser.add_argument('--mode', choices=('evidence', 'answer'), default='evidence')
    parser.add_argument('--retrieval-mode', choices=('configured', 'lexical', 'semantic'))
    parser.add_argument('--limit', type=int)
    parser.add_argument('--max-chunks', type=int)
    parser.add_argument('--max-chars', type=int)
    parser.add_argument('--budget-profile', choices=('code-trace-inventory', 'code-inventory'))
    parser.add_argument('--file', action='append', help='Exact repository-relative source path')
    parser.add_argument(
        '--directory', action='append', help='Repository-relative directory subtree'
    )
    parser.add_argument(
        '--source-type', action='append', help='Indexed language, e.g. python/yaml/json'
    )
    parser.add_argument('--page-size', type=int, help='Opt into evidence result pages (1-200)')
    parser.add_argument('--cursor', help='Continue a previous evidence search')
    parser.add_argument('--session-dir', type=Path)
    parser.add_argument('--session-ttl', type=int, help='New session lifetime, 1-86400 seconds')
    parser.add_argument(
        '--no-session', action='store_true', help='Use stateless hash-verified pagination'
    )
    parser.add_argument('--readiness', choices=('quick', 'full', 'off'), default='quick')
    parser.add_argument(
        '--require-fresh', action='store_true', help='Require full source hash verification'
    )
    parser.add_argument('--report', type=Path)
    parser.add_argument('--allow-remote', action='store_true')


def run(args):
    started = time.perf_counter()
    if not args.query.strip():
        raise ValueError('query must not be empty')
    for name in ('limit', 'max_chunks', 'max_chars'):
        if getattr(args, name) is not None and getattr(args, name) < 1:
            raise ValueError(f'{name} must be positive')
    if args.budget_profile and args.mode != 'evidence':
        raise ValueError('Budget profiles require evidence mode')
    filters = SourceFilters(
        files=args.file or (), directories=args.directory or (), source_types=args.source_type or ()
    )
    paging = args.page_size is not None or args.cursor is not None
    if paging and (args.mode != 'evidence' or args.resolve_only):
        raise ValueError('Pagination requires evidence mode and cannot use --resolve-only')
    if args.page_size is not None and not 1 <= args.page_size <= 200:
        raise ValueError('page-size must be between 1 and 200')
    from .query_pagination import CursorError, decode_cursor
    from .query_sessions import file_stamps, request_identity, session_directory

    if args.require_fresh and args.readiness == 'off':
        raise ValueError('--require-fresh cannot disable readiness checks')
    if args.session_ttl is not None and not 1 <= args.session_ttl <= 86400:
        raise ValueError('Session TTL must be between 1 and 86400 seconds')
    if not paging and (args.no_session or args.session_dir or args.session_ttl is not None):
        raise ValueError('Session options require --page-size or --cursor')
    if args.no_session and (args.session_dir or args.session_ttl is not None):
        raise ValueError('--no-session cannot use session directory/TTL')
    cursor = decode_cursor(args.cursor) if args.cursor else None
    if cursor and cursor['version'] == 1 and (args.session_dir or args.session_ttl is not None):
        raise ValueError('Legacy cursors cannot configure sessions; start a new search')
    request = request_identity(args, filters)
    request.update(
        ranking_profile=RANKING_PROFILE,
        planning_profile=PLANNING_PROFILE,
        session_profile='snapshot-v5',
    )
    if cursor and cursor['version'] == 2:
        if args.no_session:
            raise CursorError('invalid_cursor', 'Session cursor cannot use --no-session.')
        return resume_session(args, filters, cursor, request, started)
    use_session = paging and not args.no_session and cursor is None
    cache_directory = session_directory(args) if use_session else None
    watched = file_stamps([args.config]) if use_session and args.config else {}
    raw = json.loads(args.config.read_text(encoding='utf-8')) if args.config else {}
    if not isinstance(raw, dict):
        raise ValueError('configuration must be an object')
    from .query_budgets import apply_budget_profile, resolve_cli_budgets

    raw, budget_defaults = apply_budget_profile(raw, args.budget_profile)
    resolve_cli_budgets(args, budget_defaults)
    routing = None
    query = args.query
    if args.default_repo is not None or args.repo is not None:
        if args.config is None or args.index is not None or args.relationships is not None:
            raise ValueError('Routed queries require --config and cannot override index paths')
        from .repository_routing import select_repository

        routing = select_repository(
            query, raw.get('repositories', {}), args.default_repo or args.repo, repo=args.repo
        )
        if args.resolve_only:
            if args.report:
                raise ValueError('--report is not available with --resolve-only')
            return envelope(
                args.mode, routing_only=True, repository=routing['repository'], routing=routing
            )
        name = routing['repository']
        args.index = repository_index_path(raw, args.config, name)
        args.relationships = repository_relationships_path(args.config, name)
        if not args.index.is_file() or not args.relationships.is_file():
            raise ValueError(
                f'Missing index or relationships for {name}; run CodeTrace index and link first'
            )
        query = routing['query']
    elif args.resolve_only or args.index is None or args.relationships is None:
        raise ValueError('Supply --index and --relationships, or --config with --default-repo')
    if args.retrieval_mode:
        raw = json.loads(json.dumps(raw))
        raw.setdefault('retrieval', {})['mode'] = args.retrieval_mode
        for settings in raw.get('repositories', {}).values():
            settings.setdefault('retrieval', {})['mode'] = args.retrieval_mode
    if use_session:
        from .semantic_config import resolve_retrieval

        settings, vector_paths, _ = resolve_retrieval(
            raw, args.config or Path.cwd() / 'config.json', args.index, resolve_paths=False
        )
        if settings.get('mode') == 'lexical':
            vector_paths = None
        watched.update(
            file_stamps([args.index, args.relationships, *(vector_paths or {}).values()])
        )
    index = json.loads(args.index.read_text(encoding='utf-8'))
    relationships = json.loads(args.relationships.read_text(encoding='utf-8'))
    if not isinstance(index, dict) or not isinstance(index.get('chunks'), list):
        raise ValueError('index must contain a chunks list')
    if not isinstance(relationships, dict) or not isinstance(
        relationships.get('evidence_graph'), dict
    ):
        raise ValueError('relationships must contain an evidence_graph object')
    from .preparation import evaluate_readiness, inspect_preparation

    if args.readiness == 'off':
        preparation = {'spec': None, 'checks': [], 'dependencies': {}, 'remedy': None}
    else:
        name = routing['repository'] if routing else relationships.get('source_repository')
        if name is None and args.config:
            name = next(
                (
                    name
                    for name in raw.get('repositories', {})
                    if repository_index_path(raw, args.config, name) == args.index.resolve()
                ),
                None,
            )
        preparation = inspect_preparation(index, relationships, raw, args.config, args.index, name)
    readiness = evaluate_readiness(preparation, args.readiness, require_fresh=args.require_fresh)
    if use_session:
        watched.update(preparation['dependencies'])
    pagination = None
    page_results = None
    if paging and not use_session:
        from .query_pagination import CursorError, decode_cursor, digest
        from .semantic_config import resolve_retrieval

        cursor = decode_cursor(args.cursor) if args.cursor else None
        settings, paths, _ = resolve_retrieval(
            raw, args.config or Path.cwd() / 'config.json', args.index
        )
        if settings.get('mode') == 'lexical':
            paths = None
        snapshot = digest(
            {
                'query': query,
                'original_query': args.query,
                'index_path': str(args.index.resolve()),
                'relationships_path': str(args.relationships.resolve()),
                'index': index,
                'relationships': relationships,
                'config': raw,
                'limit': args.limit,
                **({'budget_profile': args.budget_profile} if args.budget_profile else {}),
                'filters': filters.describe(),
                'ranking_profile': RANKING_PROFILE,
                'planning_profile': PLANNING_PROFILE,
                'vectors': {
                    key: digest(path.read_text(encoding='utf-8'))
                    for key, path in (paths or {}).items()
                },
            }
        )
        if cursor and cursor['snapshot'] != snapshot:
            raise CursorError(
                'stale_cursor', 'Search artifacts/settings changed; restart the search.'
            )
    from .semantic_config import load_retrieval

    try:
        options = {'index': index} if args.readiness != 'off' else {}
        retrieval, stores, embedding_provider = load_retrieval(
            raw, args.config or Path.cwd() / 'config.json', args.index, **options
        )
    except ValueError as exc:
        if args.readiness == 'off':
            raise
        from .preparation import ReadinessError

        preparation['checks'].append(
            {
                'code': 'retrieval_artifacts',
                'status': 'error',
                'message': str(exc),
                'remedy': preparation['remedy'],
            }
        )
        raise ReadinessError(
            {**readiness, 'status': 'error', 'checks': preparation['checks']}
        ) from exc
    if args.readiness != 'off':
        preparation['checks'].append(
            {
                'code': 'vectors',
                'status': 'ok' if stores else 'skipped',
                'message': 'Vector identifiers/metadata/dimensions checked.'
                if stores
                else 'Semantic stores not used by this retrieval mode.',
                'remedy': preparation['remedy'],
            }
        )

    configured_limit = retrieval.limit
    retrieval = replace(retrieval, limit=min(configured_limit, args.limit))
    limits = context_limits_from_mapping(raw.get('context'))
    limits['max_chunks'] = min(limits.get('max_chunks', args.max_chunks), args.max_chunks)
    limits['max_chars'] = min(limits.get('max_chars', args.max_chars), args.max_chars)
    for key, value in limits.items():
        if not isinstance(value, int) or value < 0:
            raise ValueError(f'context {key} must be a non-negative integer')
    if paging:
        from .query_pagination import paginate
        from .retrieval import retrieve

        ranked = retrieve(
            index,
            relationships['evidence_graph'],
            query,
            config=retrieval,
            semantic_store=stores,
            provider=embedding_provider,
            filters=filters,
        )
        if use_session:
            from .query_pagination import digest, unique_results
            from .query_sessions import (
                DEFAULT_TTL,
                evidence_view,
                save_session,
                session_page,
                validate_files,
            )

            validate_files(watched)
            ranked = unique_results(ranked)
            index_view, links_view, source_scope = evidence_view(
                index, relationships['evidence_graph'], ranked, filters
            )
            sources = active_sources(
                plan_query(query, kind=retrieval.lexical_kind),
                retrieval.mode,
                semantic_available=bool(stores and embedding_provider),
            )
            payload = {
                'budget_defaults': budget_defaults,
                'preparation': preparation,
                'readiness': readiness,
                'request': request,
                'watched': watched,
                'snapshot': digest({'request': request, 'watched': watched}),
                'query': query,
                'routing': routing,
                'ranked': ranked,
                'index': index_view,
                'relationships': links_view,
                'source_scope': source_scope,
                'context_defaults': context_limits_from_mapping(raw.get('context')),
                'retrieval_config': asdict(retrieval),
                'configured_limit': configured_limit,
                'active_sources': sources,
                'query_plan': {
                    **plan_query(query, kind=retrieval.lexical_kind),
                    'original_query': args.query,
                    'routed_query': query,
                    'active_sources': sources,
                },
            }
            try:
                data, identifier, checksum = save_session(
                    cache_directory, payload, ttl=args.session_ttl or DEFAULT_TTL
                )
            except OSError as exc:
                raise CursorError(
                    'session_unavailable',
                    'Cannot write search cache; choose --session-dir or --no-session.',
                ) from exc
            page_results, pagination = session_page(
                data, identifier, checksum, page_size=args.page_size
            )
            index, relationships = index_view, links_view
        else:
            page_results, pagination = paginate(
                ranked, snapshot, cursor=cursor, page_size=args.page_size
            )

        # Pagination explores ranked matches; expansion could repeat chunks on later pages.
        limits['expansion_depth'] = 0
    return render_query(
        args,
        query=query,
        index=index,
        relationships=relationships,
        raw=raw,
        routing=routing,
        retrieval=retrieval,
        configured_limit=configured_limit,
        limits=limits,
        filters=filters,
        stores=stores,
        embedding_provider=embedding_provider,
        page_results=page_results,
        pagination=pagination,
        started=started,
        source_scope=source_scope if use_session else None,
        sources_override=sources if use_session else None,
        watched=watched if use_session else None,
        query_plan_override=payload['query_plan'] if use_session else None,
        readiness=readiness,
    )


def resume_session(args, filters, cursor, request, started):
    from .query_sessions import load_session, session_directory, session_page, validate_files
    from .retrieval import RetrievalConfig

    data = load_session(session_directory(args), cursor, request)
    payload = data['payload']
    from .query_budgets import resolve_cli_budgets

    resolve_cli_budgets(args, payload['budget_defaults'])
    page, pagination = session_page(
        data, cursor['session'], cursor['digest'], cursor=cursor, page_size=args.page_size
    )
    limits = dict(payload['context_defaults'])
    limits['max_chunks'] = min(limits.get('max_chunks', args.max_chunks), args.max_chunks)
    limits['max_chars'] = min(limits.get('max_chars', args.max_chars), args.max_chars)
    limits['expansion_depth'] = 0
    from .preparation import evaluate_readiness
    from .query_sessions import readiness_assessment, save_readiness_assessment

    previous = payload['readiness']
    if args.readiness == 'quick' and not args.require_fresh:
        previous = readiness_assessment(session_directory(args), cursor, previous)
    readiness = evaluate_readiness(
        payload['preparation'], args.readiness, previous=previous, require_fresh=args.require_fresh
    )
    if (
        args.readiness == 'quick'
        and not args.require_fresh
        and not readiness['source'].get('reused')
    ):
        try:
            save_readiness_assessment(session_directory(args), cursor, readiness)
        except OSError:
            # Persistence is optional: report the new assessment; retry checking on the next page.
            pass
    result = render_query(
        args,
        query=payload['query'],
        index=payload['index'],
        relationships=payload['relationships'],
        raw={},
        routing=payload['routing'],
        retrieval=RetrievalConfig(**payload['retrieval_config']),
        configured_limit=payload['configured_limit'],
        limits=limits,
        filters=filters,
        started=started,
        page_results=page,
        pagination=pagination,
        source_scope=payload['source_scope'],
        sources_override=payload['active_sources'],
        watched=payload['watched'],
        query_plan_override=payload['query_plan'],
        readiness=readiness,
    )
    validate_files(payload['watched'])
    return result


def render_query(
    args,
    *,
    query,
    index,
    relationships,
    raw,
    routing,
    retrieval,
    configured_limit,
    limits,
    filters,
    started,
    stores=None,
    embedding_provider=None,
    page_results=None,
    pagination=None,
    source_scope=None,
    sources_override=None,
    watched=None,
    query_plan_override=None,
    readiness=None,
):
    paging = pagination is not None
    generation = GenerationConfig.from_mapping(
        raw.get('generation') if args.mode == 'answer' else None
    )
    if args.mode == 'answer' and generation.provider == 'none':
        raise ValueError('answer mode requires a configured generation provider')
    provider = build_generation_provider(generation)
    result = answer(
        query,
        index=index,
        graph=relationships['evidence_graph'],
        retrieval_config=retrieval,
        retrieval_results=page_results,
        context_limits=limits,
        semantic_store=stores,
        embedding_provider=embedding_provider,
        generation_provider=provider,
        allow_remote=args.allow_remote,
        search_filters=filters if source_scope is None else None,
    )
    context = result['context']
    if source_scope is not None:
        context['source_scope'] = source_scope
    generated = result.get('answer')
    items = context.get('items', [])
    citations = [{**item['citation'], 'certainty': item['certainty']} for item in items]
    limitations = list(
        dict.fromkeys(note for item in items for note in item.get('limitations', []))
    )
    limitations.append(
        'Retrieval is bounded; returned results are not an exhaustive repository match count.'
    )
    selection = context['selection']
    if selection['excluded_chunks']:
        limitations.append('Context budgets excluded candidate chunks; inspect context.selection.')
    if selection['truncated_chunks']:
        limitations.append('Some evidence excerpts were truncated by the character budget.')
    insufficient = not items or (generated is not None and generated.refusal)
    if not items:
        limitations.append('No evidence fits the retrieval and context budgets.')
    if generated is not None:
        limitations = list(dict.fromkeys([*limitations, *generated.limitations]))
    output = envelope(
        args.mode,
        status='insufficient_evidence' if insufficient else 'ok',
        answer=generated.answer if generated else None,
        claims=[asdict(claim) for claim in generated.claims] if generated else [],
        citations=citations,
        evidence=[
            {
                'chunk_id': item['citation']['chunk_id'],
                'content': item['content'],
                'truncated': item['content_truncated'],
                'original_chars': item['original_content_chars'],
                'returned_chars': len(item['content']),
                'ranking': item.get('retrieval', {}).get('ranking'),
            }
            for item in items
        ],
        limitations=limitations,
        retrieval={
            'requested_limit': args.limit,
            'configured_limit': configured_limit,
            'effective_limit': retrieval.limit,
            'returned_results': selection['retrieved_results'],
            'limit_reached': selection['retrieved_results'] >= retrieval.limit,
            'total_matches': None,
            'exhaustive': False,
            'ranking_profile': RANKING_PROFILE,
        },
        context={
            'effective_limits': {
                key: context[key]
                for key in (
                    'max_chunks',
                    'max_chars',
                    'max_tokens',
                    'max_relations',
                    'related_limit',
                    'expansion_depth',
                )
            },
            'content_chars': context['content_chars'],
            'estimated_tokens': context['budget_estimated_tokens'],
            'selection': selection,
        },
    )
    output['retrieval']['budget_profile'] = args.budget_profile
    output['readiness'] = readiness
    if readiness and readiness['status'] == 'warning':
        output['limitations'].append(
            'Preparation warnings: inspect readiness before treating this snapshot as current.'
        )
    output['retrieval']['mode'] = retrieval.mode
    if query_plan_override is not None:
        output['retrieval']['query_plan'] = query_plan_override
    else:
        output['retrieval']['query_plan'] = {
            **plan_query(query, kind=retrieval.lexical_kind),
            'original_query': args.query,
            'routed_query': query,
        }
        output['retrieval']['query_plan']['active_sources'] = (
            sources_override
            if sources_override is not None
            else active_sources(
                output['retrieval']['query_plan'],
                retrieval.mode,
                semantic_available=bool(stores and embedding_provider),
            )
        )
    if filters.active:
        output['retrieval']['source_scope'] = context['source_scope']
        output['limitations'].append(
            'Source filters restrict both retrieval and structural context expansion.'
        )
    if paging:
        chunks = {chunk['id']: chunk for chunk in index['chunks']}
        selected = {item['citation']['chunk_id'] for item in items}
        output['pagination'] = pagination
        output['matches'] = [
            {
                'chunk_id': match['chunk_id'],
                'path': chunks[match['chunk_id']].get('path'),
                'start_line': chunks[match['chunk_id']].get('start_line'),
                'end_line': chunks[match['chunk_id']].get('end_line'),
                'score': match.get('score'),
                'ranking': match.get('ranking'),
                'source': match.get('source'),
                'evidence_included': match['chunk_id'] in selected,
            }
            for match in page_results
        ]
        output['retrieval']['returned_results'] = pagination['pool_results']
        output['retrieval']['limit_reached'] = pagination['pool_results'] >= retrieval.limit
        output['limitations'].append(
            'Pagination covers only the bounded retrieval pool; structural expansion is disabled.'
        )
    if routing is not None:
        output.update(repository=routing['repository'], routing=routing)
    if watched is not None:
        from .query_sessions import validate_files

        validate_files(watched)
    if args.report:
        from .rag_run_report import save_rag_run_report

        save_rag_run_report(
            args.report,
            query=args.query,
            result=result,
            context=context,
            retrieval_config=asdict(retrieval),
            generation_config=asdict(generation),
            latency_seconds=time.perf_counter() - started,
            metadata={
                'readiness': output['readiness'],
                'retrieval': output['retrieval'],
                'context': output['context'],
                'pagination': output['pagination'],
                'matches': output['matches'],
                **({'routing': routing} if routing is not None else {}),
            },
        )
    return output


def main(argv=None):
    parser = QueryParser(prog='code-trace query', description=__doc__)
    configure_parser(parser)
    args = parser.parse_args(argv)
    try:
        # Dependencies and providers may print progress; stdout is reserved for JSON.
        with redirect_stdout(sys.stderr):
            output = run(args)
    except Exception as exc:
        print(  # noqa: T201 - CLI output
            json.dumps(
                envelope(
                    args.mode,
                    status='error',
                    readiness=getattr(exc, 'readiness', None),
                    error={
                        'type': type(exc).__name__,
                        'message': str(exc),
                        **({'code': exc.code} if hasattr(exc, 'code') else {}),
                        **({'candidates': exc.candidates} if hasattr(exc, 'candidates') else {}),
                    },
                ),
                ensure_ascii=False,
            )
        )
        raise SystemExit(2) from exc
    print(json.dumps(output, ensure_ascii=False))  # noqa: T201 - CLI output
