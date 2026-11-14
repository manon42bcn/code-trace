import argparse
import json
from pathlib import Path

from .core import analyze_index, index_repository, inspect_index
from .repository_paths import repository_index_path, repository_relationships_path


def main():
    import sys

    if sys.argv[1:2] == ['chat']:
        from .chat import main as chat_main

        return chat_main(sys.argv[2:])
    if sys.argv[1:2] == ['evaluate-real']:
        from .real_evaluation import main as evaluation_main

        return evaluation_main(sys.argv[2:])
    if sys.argv[1:2] == ['doctor']:
        from .doctor import main as doctor_main

        return doctor_main(sys.argv[2:])
    if sys.argv[1:2] == ['inventory']:
        from .inventory import main as inventory_main

        return inventory_main(sys.argv[2:])
    if sys.argv[1:2] == ['query']:
        from .agent_query import main as query_main

        return query_main(sys.argv[2:])
    if sys.argv[1:2] == ['check-provider']:
        from .provider_check import main as check_main

        return check_main(sys.argv[2:])
    if sys.argv[1:2] == ['embed']:
        from .prepare_embeddings import main as embed_main

        return embed_main(sys.argv[2:])
    parser = argparse.ArgumentParser(prog='code-trace')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('index')
    p.add_argument('repository', nargs='?', type=Path)
    p.add_argument('--config', type=Path, default=Path('config.json'))
    p.add_argument('--repo')
    p.add_argument('--output', type=Path)
    p.add_argument(
        '--verbose', action='store_true', help='Mostrar el archivo que se está procesando'
    )
    p.add_argument(
        '--exclude',
        action='append',
        default=[],
        metavar='GLOB',
        help='Excluir ruta relativa (repetible, se suma a config.json)',
    )
    p.add_argument(
        '--incremental', action='store_true', help='Reutilizar chunks de archivos sin cambios'
    )
    p = sub.add_parser('link')
    p.add_argument('--config', type=Path, default=Path('config.json'))
    p.add_argument('--repo', required=True)
    p.add_argument('--output', type=Path)
    p.add_argument('--behave-dry-run', type=Path)
    p.add_argument('--test-plan', type=Path)
    p = sub.add_parser('provenance')
    p.add_argument('relationships', type=Path)
    p.add_argument('--key', required=True)
    p.add_argument('--namespace')
    p.add_argument('--repository')
    p.add_argument('--max-depth', type=int, default=4)
    p.add_argument('--max-nodes', type=int, default=80)
    p.add_argument('--max-pairs', type=int, default=200)
    p.add_argument('--output', type=Path)
    p = sub.add_parser('provenance-context')
    p.add_argument('relationships', type=Path)
    p.add_argument('--key')
    p.add_argument('--feature')
    p.add_argument('--scenario')
    p.add_argument('--max-consumers', type=int, default=100)
    p.add_argument('--max-producers', type=int, default=30)
    p.add_argument('--only-prior', action='store_true')
    p.add_argument('--output', type=Path)
    p = sub.add_parser('inspect')
    p.add_argument('index', type=Path)
    p = sub.add_parser('analyze')
    p.add_argument('index', type=Path, nargs='?')
    p.add_argument('--config', type=Path, default=Path('config.json'))
    p.add_argument('--repo')
    p.add_argument('--output', type=Path)
    p = sub.add_parser('show')
    p.add_argument('index', type=Path)
    p.add_argument('chunk_id')
    p = sub.add_parser('search')
    p.add_argument('index', type=Path)
    p.add_argument('term')
    p.add_argument('--limit', type=int, default=50)
    p.add_argument('--kind', choices=('any', 'symbol', 'path', 'content'), default='any')
    p.add_argument('--exact', action='store_true')
    p = sub.add_parser('hybrid-search')
    p.add_argument('index', type=Path)
    p.add_argument('relationships', type=Path)
    p.add_argument('term')
    p.add_argument('--limit', type=int, default=50)
    p.add_argument('--lexical-kind', choices=('any', 'symbol', 'path', 'content'), default='any')
    p.add_argument('--structural-kind', choices=('any', 'symbol', 'path', 'key'), default='any')
    p.add_argument('--access', choices=('all', 'writes', 'reads'), default='all')
    p.add_argument('--semantic-profile', choices=('default', 'two_stage'), default='default')
    p.add_argument('--semantic-initial-k', type=int, default=1)
    p.add_argument('--semantic-v2-weight', type=float, default=0.05)
    p.add_argument('--exact', action='store_true')
    p = sub.add_parser('answer')
    p.add_argument('query')
    p.add_argument('--index', type=Path)
    p.add_argument('--relationships', type=Path)
    p.add_argument('--config', type=Path)
    p.add_argument('--report', type=Path)
    p.add_argument('--resolve-only', action='store_true', help='Inspect repository routing only')
    p.add_argument('--relevant-chunks', type=Path)
    p.add_argument('--allow-remote', action='store_true')
    p.add_argument('--repo', help='Explicit configured repository selector')
    p.add_argument('--default-repo', help='Route the question with this fallback repository')
    p.add_argument('--output-format', choices=('json', 'text', 'markdown'), default='json')
    p.add_argument(
        '--include-evidence', action='store_true', help='Append source excerpts to text output'
    )
    p.add_argument('--limit', type=int)
    p.add_argument('--max-chunks', type=int)
    p.add_argument('--max-chars', type=int)
    p = sub.add_parser('evaluate-rag')
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--index', type=Path, required=True)
    p.add_argument('--relationships', type=Path, required=True)
    p.add_argument('--config', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--allow-remote', action='store_true')
    sub.add_parser('check-provider', help='Verify the generation provider (check-provider --help)')
    sub.add_parser('embed', help='Prepare configured semantic vectors (embed --help)')
    sub.add_parser('evaluate-real', help='Evaluate curated real questions (evaluate-real --help)')
    sub.add_parser('chat', help='Open the local web chat (chat --help)')
    sub.add_parser('doctor', help='Diagnose repository preparation (doctor --help)')
    sub.add_parser('inventory', help='Count all entries in an indexed YAML/JSON list')
    sub.add_parser('query', help='Compact versioned JSON for agents (query --help)')
    args = parser.parse_args()
    try:
        if args.command == 'index':
            confpath = args.config.resolve()
            conf = json.loads(confpath.read_text(encoding='utf-8'))
            name = args.repo or conf.get('default_repository')
            if args.repository is not None:
                source = args.repository.resolve()
                output = args.output or confpath.parent / 'indexes' / 'repo.chunks.json'
            else:
                if name not in conf.get('repositories', {}):
                    raise ValueError(f'Repositorio no configurado: {name}')
                settings = conf['repositories'][name]
                source = (confpath.parent / settings['path']).resolve()
                output = args.output or repository_index_path(conf, confpath, name)
            if args.verbose:
                print(f'Repositorio: {source}', flush=True)  # noqa: T201 - CLI output
                print(f'Salida: {output}', flush=True)  # noqa: T201 - CLI output
            result = index_repository(
                source,
                output,
                {
                    **conf,
                    'indexing': {
                        **conf['indexing'],
                        'exclude': [
                            *conf['indexing'].get('exclude', []),
                            *settings.get('exclude', []),
                        ]
                        if args.repository is None
                        else conf['indexing'].get('exclude', []),
                    },
                },
                progress=(lambda msg: print(msg, flush=True)) if args.verbose else None,  # noqa: T201 - CLI output
                excludes=args.exclude,
                incremental=args.incremental,
            )
            for diagnostic in result.get('diagnostics', []):
                if diagnostic.get('type') == 'python_syntax_warning':
                    location = source / diagnostic['path']
                    print(  # noqa: T201 - CLI diagnostics
                        f'{location}:{diagnostic["line"]}: {diagnostic["category"]}: '
                        f'{diagnostic["message"]}',
                        file=sys.stderr,
                    )
            print(  # noqa: T201 - CLI output
                f'Indexados {result["files_discovered"]} archivos, '
                f'{len(result["chunks"])} fragmentos: {output}'
            )
            if result['skipped_files']:
                print(f'Advertencia: {len(result["skipped_files"])} archivos omitidos')  # noqa: T201 - CLI output
            if result['excluded_paths']:
                print(  # noqa: T201 - CLI output
                    f'Exclusiones aplicadas: {len(result["excluded_paths"])} rutas '
                    '(los directorios incluyen sus descendientes)'
                )
        elif args.command == 'link':
            from .repo_links import build_repository_links, save_links

            config_path = args.config.resolve()
            conf = json.loads(config_path.read_text(encoding='utf-8'))
            report = build_repository_links(conf, config_path, args.repo)
            from .behave_reconcile import apply_reconciliation

            apply_reconciliation(report, dry_run_path=args.behave_dry_run, plan_path=args.test_plan)
            out = args.output or repository_relationships_path(config_path, args.repo)
            from .evidence_graph import build_evidence_graph
            from .repo_links import _transitive

            repos_to_load = [args.repo, *_transitive(conf, args.repo)]
            indexes = {}
            for name in repos_to_load:
                settings = conf.get('repositories', {}).get(name)
                if settings:
                    index_path = repository_index_path(conf, config_path, name)
                    if index_path.exists():
                        indexes[name] = json.loads(index_path.read_text(encoding='utf-8'))
            report['evidence_graph'] = build_evidence_graph(indexes, report)
            save_links(out, report)
            print(f'Relaciones: {report["summary"]} → {out}')  # noqa: T201 - CLI output
        elif args.command == 'provenance':
            from .provenance_query import query_provenance

            report = json.loads(args.relationships.read_text(encoding='utf-8'))
            graph = report.get('evidence_graph')
            if not isinstance(graph, dict):
                raise ValueError('El informe no contiene evidence_graph')
            result = query_provenance(
                graph,
                key=args.key,
                namespace=args.namespace,
                repository=args.repository,
                max_depth=args.max_depth,
                max_nodes=args.max_nodes,
                max_pairs=args.max_pairs,
            )
            payload = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(payload, encoding='utf-8')
                print(f'Candidatos: {result["summary"]} → {args.output}')  # noqa: T201 - CLI output
            else:
                print(payload, end='')  # noqa: T201 - CLI output
        elif args.command == 'provenance-context':
            from .consumer_provenance import query_context_consumers

            report = json.loads(args.relationships.read_text(encoding='utf-8'))
            result = query_context_consumers(
                report,
                key=args.key,
                feature=args.feature,
                scenario=args.scenario,
                max_consumers=args.max_consumers,
                max_producers=args.max_producers,
                only_prior=args.only_prior,
            )
            payload = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(payload, encoding='utf-8')
                print(f'Consumidores: {result["summary"]} → {args.output}')  # noqa: T201 - CLI output
            else:
                print(payload, end='')  # noqa: T201 - CLI output
        elif args.command == 'search':
            from .lexical_search import search_index

            index = json.loads(args.index.read_text(encoding='utf-8'))
            print(  # noqa: T201 - CLI output
                json.dumps(
                    search_index(
                        index, args.term, kind=args.kind, exact=args.exact, limit=args.limit
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == 'hybrid-search':
            from .search import search_hybrid

            index = json.loads(args.index.read_text(encoding='utf-8'))
            relationships = json.loads(args.relationships.read_text(encoding='utf-8'))
            results = search_hybrid(
                index,
                relationships.get('evidence_graph', {}),
                args.term,
                lexical_kind=args.lexical_kind,
                structural_kind=args.structural_kind,
                exact=args.exact,
                access=args.access,
                limit=args.limit,
                semantic_profile=args.semantic_profile,
                semantic_initial_k=args.semantic_initial_k,
                semantic_v2_weight=args.semantic_v2_weight,
            )
            print(json.dumps(results, ensure_ascii=False, indent=2))  # noqa: T201 - CLI output
        elif args.command == 'evaluate-rag':
            import time

            from .generation_config import GenerationConfig
            from .generation_factory import build_generation_provider
            from .rag_batch import evaluate_rag_dataset
            from .rag_dataset import load_rag_dataset
            from .rag_pipeline import answer

            dataset = load_rag_dataset(args.dataset)
            index = json.loads(args.index.read_text(encoding='utf-8'))
            relationships = json.loads(args.relationships.read_text(encoding='utf-8'))
            raw = json.loads(args.config.read_text(encoding='utf-8')) if args.config else {}
            from .config_context import context_limits_from_mapping
            from .semantic_config import load_retrieval

            context_limits = context_limits_from_mapping(raw.get('context'))
            retrieval, stores, embedding_provider = load_retrieval(
                raw, args.config or Path.cwd() / 'config.json', args.index
            )
            generation = GenerationConfig.from_mapping(raw.get('generation'))
            provider = build_generation_provider(generation)
            started = time.perf_counter()

            def run(query):
                result = answer(
                    query,
                    index=index,
                    graph=relationships.get('evidence_graph', {}),
                    retrieval_config=retrieval,
                    generation_provider=provider,
                    context_limits=context_limits,
                    allow_remote=args.allow_remote,
                    semantic_store=stores,
                    embedding_provider=embedding_provider,
                )
                return result

            report = evaluate_rag_dataset(dataset, run)
            report['elapsed_seconds'] = time.perf_counter() - started
            print(json.dumps(report, ensure_ascii=False, indent=2))  # noqa: T201 - CLI output
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
                )
        elif args.command == 'answer':
            from contextlib import redirect_stdout

            answer_stdout = sys.stdout
            with redirect_stdout(sys.stderr):
                import time

                from .generation_config import GenerationConfig
                from .generation_factory import build_generation_provider
                from .rag_pipeline import answer

                raw = json.loads(args.config.read_text(encoding='utf-8')) if args.config else {}
                routing = None
                query = args.query
                if not query.strip():
                    raise ValueError('query must not be empty')
                if args.default_repo is not None or args.repo is not None:
                    if (
                        args.config is None
                        or args.index is not None
                        or args.relationships is not None
                    ):
                        raise ValueError(
                            'Routed answers require --config without explicit index paths'
                        )
                    from .repository_routing import select_repository

                    routing = select_repository(
                        query,
                        raw.get('repositories', {}),
                        args.default_repo or args.repo,
                        repo=args.repo,
                    )
                    args.index = repository_index_path(raw, args.config, routing['repository'])
                    args.relationships = repository_relationships_path(
                        args.config, routing['repository']
                    )
                    query = routing['query']
                if args.resolve_only:
                    if routing is None or args.report:
                        raise ValueError('--resolve-only requires routing and cannot save a report')
                    from .agent_query import envelope

                    answer_stdout.write(
                        json.dumps(
                            envelope(
                                'answer',
                                routing_only=True,
                                repository=routing['repository'],
                                routing=routing,
                            ),
                            ensure_ascii=False,
                        )
                        + '\n'
                    )
                    return
                if args.index is None or args.relationships is None:
                    raise ValueError(
                        'Supply --index and --relationships, or --config with --default-repo'
                    )
                index = json.loads(args.index.read_text(encoding='utf-8'))
                relationships = json.loads(args.relationships.read_text(encoding='utf-8'))
                from .preparation import assess_sources, needs_update, rebuild_command, source_spec

                repo = routing['repository'] if routing else None
                source_state = assess_sources(source_spec(index, raw, repo, args.index))
                index_state = {
                    'source': source_state,
                    'git': source_state['git'],
                    'needs_update': needs_update(source_state),
                    'remedy': rebuild_command(args.config, repo) if args.config else None,
                }
                from .config_context import context_limits_from_mapping
                from .semantic_config import load_retrieval

                context_limits = context_limits_from_mapping(raw.get('context'))
                retrieval, stores, embedding_provider = load_retrieval(
                    raw, args.config or Path.cwd() / 'config.json', args.index
                )
                from dataclasses import replace

                for key in ('limit', 'max_chunks', 'max_chars'):
                    value = getattr(args, key)
                    if value is not None and value < 1:
                        raise ValueError(f'{key} must be positive')
                if args.limit is not None:
                    retrieval = replace(retrieval, limit=args.limit)
                for key in ('max_chunks', 'max_chars'):
                    value = getattr(args, key)
                    if value is not None:
                        context_limits[key] = min(context_limits.get(key, value), value)
                generation = GenerationConfig.from_mapping(raw.get('generation'))
                if args.output_format in {'text', 'markdown'} and generation.provider == 'none':
                    raise ValueError('Text output requires a configured generation provider')
                provider = build_generation_provider(generation)
                started = time.perf_counter()
                result = answer(
                    query,
                    index=index,
                    graph=relationships.get('evidence_graph', {}),
                    retrieval_config=retrieval,
                    semantic_store=stores,
                    embedding_provider=embedding_provider,
                    generation_provider=provider,
                    context_limits=context_limits,
                    allow_remote=args.allow_remote,
                )
                from .generation import GenerationResult
                from .generation_serialization import generation_result_dict

                result['index_state'] = index_state
                output = dict(result)
                if isinstance(output.get('answer'), GenerationResult):
                    output['answer'] = generation_result_dict(output['answer'])
                elapsed = time.perf_counter() - started
                answer_metrics = {
                    'citation_recall': None,
                    'invalid_citations': None,
                    'claim_coverage': None,
                }
                if args.relevant_chunks and isinstance(output.get('answer'), dict):
                    from .rag_evaluation import evaluate_answer

                    labels = json.loads(args.relevant_chunks.read_text(encoding='utf-8'))
                    from .generation_serialization import generation_result_dict

                    answer_data = output['answer']
                    from .generation import Claim, GenerationResult

                    structured = GenerationResult(
                        answer_data['answer'],
                        answer_data['provider'],
                        answer_data['model'],
                        claims=[
                            Claim(c['text'], c['certainty'], c.get('citations', []))
                            for c in answer_data.get('claims', [])
                        ],
                        citations=answer_data.get('citations', []),
                        limitations=answer_data.get('limitations', []),
                        refusal=answer_data.get('refusal', False),
                    )
                    answer_metrics = evaluate_answer(
                        structured,
                        relevant_citations=labels.get('relevant_citations', []),
                        required_claims=labels.get('required_claims', 0),
                    )
                output['latency_seconds'] = elapsed
                if args.report:
                    from .rag_run_report import save_rag_run_report

                    save_rag_run_report(
                        args.report,
                        query=args.query,
                        result=result,
                        context=result.get('context', {}),
                        retrieval_config=retrieval.__dict__,
                        generation_config=generation.__dict__,
                        latency_seconds=elapsed,
                        answer_metrics=answer_metrics,
                        metadata={
                            'index_state': index_state,
                            **({'routing': routing} if routing is not None else {}),
                        },
                    )
                if routing is not None:
                    output.update(repository=routing['repository'], routing=routing)
                if args.output_format in {'text', 'markdown'}:
                    from .answer_display import render_answer

                    rendered = render_answer(
                        result,
                        include_evidence=args.include_evidence,
                        markdown=args.output_format == 'markdown',
                        repository=routing['repository'] if routing else None,
                    )
                else:
                    rendered = json.dumps(output, ensure_ascii=False, indent=2) + '\n'
            sys.stdout.write(rendered)
        elif args.command == 'analyze':
            if args.index is not None:
                index_path = args.index
            else:
                confpath = args.config.resolve()
                conf = json.loads(confpath.read_text(encoding='utf-8'))
                name = args.repo or conf.get('default_repository')
                index_path = repository_index_path(conf, confpath, name)
            report = analyze_index(inspect_index(index_path))
            rendered = json.dumps(report, ensure_ascii=False, indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered + '\n', encoding='utf-8')
                print(f'Informe guardado en {args.output}')  # noqa: T201 - CLI output
            else:
                print(rendered)  # noqa: T201 - CLI output
        elif args.command == 'inspect':
            d = inspect_index(args.index)
            print(  # noqa: T201 - CLI output
                f'Origen: {d["source_root"]}\nArchivos: {d["files_discovered"]}\n'
                f'Fragmentos: {len(d["chunks"])}'
            )
            for c in d['chunks'][:30]:
                print(  # noqa: T201 - CLI output
                    f'{c["id"]} {c["path"]}:{c["start_line"]}-{c["end_line"]} '
                    f'{c["symbol"] or "-"} ({c["estimated_tokens"]} tokens estimados)'
                )
        else:
            d = inspect_index(args.index)
            ch = next((c for c in d['chunks'] if c['id'] == args.chunk_id), None)
            if ch is None:
                raise ValueError('Fragmento no encontrado')
            print(  # noqa: T201 - CLI output
                f'{ch["path"]}:{ch["start_line"]}-{ch["end_line"]}  '
                f'símbolo={ch["symbol"]}\n{ch["content"]}'
            )
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        if args.command == 'answer':
            print(  # noqa: T201 - CLI output
                json.dumps(
                    {
                        'generated': False,
                        'error': {
                            'type': type(exc).__name__,
                            'message': str(exc),
                            **(
                                {'code': exc.code, 'candidates': exc.candidates}
                                if hasattr(exc, 'candidates')
                                else {}
                            ),
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            raise SystemExit(2) from exc
        parser.exit(2, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
