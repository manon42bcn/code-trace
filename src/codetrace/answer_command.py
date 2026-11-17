"""Command-line entry point for grounded repository answers."""

import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

from .repository_paths import repository_index_path, repository_relationships_path


def run_answer(args):
    """Run a parsed answer request and write its result to stdout."""
    try:
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
                if args.config is None or args.index is not None or args.relationships is not None:
                    raise ValueError('Routed answers require --config without explicit index paths')
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

            result['index_state'] = index_state
            elapsed = time.perf_counter() - started
            generated_answer = result.get('answer')
            answer_metrics = {
                'citation_recall': None,
                'invalid_citations': None,
                'claim_coverage': None,
            }
            if args.relevant_chunks and isinstance(generated_answer, GenerationResult):
                from .rag_evaluation import evaluate_answer

                labels = json.loads(args.relevant_chunks.read_text(encoding='utf-8'))
                answer_metrics = evaluate_answer(
                    generated_answer,
                    relevant_citations=labels.get('relevant_citations', []),
                    required_claims=labels.get('required_claims', 0),
                )
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
            if args.output_format in {'text', 'markdown'}:
                from .answer_display import render_answer

                rendered = render_answer(
                    result,
                    include_evidence=args.include_evidence,
                    markdown=args.output_format == 'markdown',
                    repository=routing['repository'] if routing else None,
                )
            else:
                output = dict(result)
                if isinstance(generated_answer, GenerationResult):
                    from .generation_serialization import generation_result_dict

                    output['answer'] = generation_result_dict(generated_answer)
                output['latency_seconds'] = elapsed
                if routing is not None:
                    output.update(repository=routing['repository'], routing=routing)
                rendered = json.dumps(output, ensure_ascii=False, indent=2) + '\n'
        sys.stdout.write(rendered)
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
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
