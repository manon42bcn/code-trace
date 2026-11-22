"""Language detection and extraction settings for the shared chunker."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Protocol

from .extractors import (
    extract_configuration,
    finalize_configuration,
    finalize_gherkin,
    gherkin_units,
    make_units,
    parse_treesitter_units,
    python_units,
)

Unit = tuple[int, int, str, str]


class UnitExtractor(Protocol):
    def __call__(
        self,
        source: str,
        *,
        language: str,
        filename: str,
        syntax_policy: str,
        diagnostics: list | None,
    ) -> list[Unit]: ...


@dataclass(frozen=True)
class TreeSitter:
    grammar: str
    node_types: frozenset[str]


@dataclass(frozen=True)
class Language:
    extensions: tuple[str, ...] = ()
    filenames: tuple[str, ...] = ()
    extractor: UnitExtractor | None = None
    tree_sitter: TreeSitter | None = None
    leading_docs: bool = False
    fallback_strategy: str = 'surrounding_code'
    finalize: Callable[[list, list[dict], dict], None] | None = None


def _python(source, *, filename, diagnostics, **_options):
    return python_units(source, filename=filename, diagnostics=diagnostics)


def _simple(extractor, source, **_options):
    return extractor(source)


def tree_language(extensions, grammar, *node_types, leading_docs=True):
    return Language(
        extensions=extensions,
        tree_sitter=TreeSitter(grammar, frozenset(node_types)),
        leading_docs=leading_docs,
    )


LANGUAGES = {
    'python': Language(extensions=('.py',), extractor=_python),
    'javascript': tree_language(
        ('.js', '.jsx', '.mjs', '.cjs'),
        'javascript',
        'function_declaration',
        'class_declaration',
        'method_definition',
        'arrow_function',
        'generator_function_declaration',
    ),
    'typescript': tree_language(
        ('.ts', '.tsx', '.mts', '.cts'),
        'typescript',
        'function_declaration',
        'class_declaration',
        'method_definition',
        'interface_declaration',
        'type_alias_declaration',
        'enum_declaration',
        'arrow_function',
    ),
    'java': tree_language(
        ('.java',),
        'java',
        'class_declaration',
        'interface_declaration',
        'method_declaration',
        'constructor_declaration',
        'enum_declaration',
        'record_declaration',
    ),
    'csharp': tree_language(
        ('.cs',),
        'c_sharp',
        'class_declaration',
        'interface_declaration',
        'method_declaration',
        'constructor_declaration',
        'struct_declaration',
        'record_declaration',
    ),
    'go': tree_language(
        ('.go',), 'go', 'function_declaration', 'method_declaration', 'type_declaration'
    ),
    'c': tree_language(
        ('.c', '.i'),
        'c',
        'function_definition',
        'struct_specifier',
        'enum_specifier',
        'type_definition',
    ),
    'cpp': tree_language(
        ('.cpp', '.cc', '.cxx', '.c++', '.hpp', '.hh', '.hxx', '.h++'),
        'cpp',
        'function_definition',
        'class_specifier',
        'struct_specifier',
        'namespace_definition',
        'template_declaration',
        'enum_specifier',
    ),
    'c/cpp': Language(extensions=('.h',)),
    'shell': tree_language(
        ('.sh', '.bash', '.zsh'), 'bash', 'function_definition', leading_docs=False
    ),
    'makefile': Language(
        extensions=('.mk',),
        filenames=('Makefile', 'makefile', 'GNUmakefile'),
        extractor=partial(_simple, make_units),
    ),
    'lock': Language(
        extensions=('.lock',),
        filenames=(
            'package-lock.json',
            'npm-shrinkwrap.json',
            'Cargo.lock',
            'poetry.lock',
            'Pipfile.lock',
            'yarn.lock',
            'pnpm-lock.yaml',
            'Gemfile.lock',
            'uv.lock',
            'composer.lock',
        ),
        fallback_strategy='lock_document',
    ),
    'gherkin': Language(
        extensions=('.feature',),
        extractor=partial(_simple, gherkin_units),
        finalize=finalize_gherkin,
    ),
    'yaml': Language(
        extensions=('.yaml', '.yml'),
        extractor=extract_configuration,
        fallback_strategy='yaml_document',
        finalize=finalize_configuration,
    ),
    'json': Language(
        extensions=('.json',),
        extractor=extract_configuration,
        fallback_strategy='json_document',
        finalize=finalize_configuration,
    ),
}

EXT = {suffix: name for name, spec in LANGUAGES.items() for suffix in spec.extensions}
SPECIAL = {filename: name for name, spec in LANGUAGES.items() for filename in spec.filenames}


def detect_language(path: Path, overrides: dict) -> str | None:
    suffix = path.suffix.lower()
    return overrides.get(suffix, SPECIAL.get(path.name, EXT.get(suffix)))


def treesitter_units(
    source: str, language: str, *, recover: bool = False, diagnostics: list | None = None
):
    grammar = LANGUAGES[language].tree_sitter
    if grammar is None:
        raise ValueError(f'No Tree-sitter grammar configured for {language}')
    return parse_treesitter_units(
        source,
        language,
        grammar.grammar,
        grammar.node_types,
        recover=recover,
        diagnostics=diagnostics,
    )


def units_for(
    source: str,
    language: str,
    missing: str,
    syntax_policy: str = 'error',
    diagnostics: list | None = None,
    *,
    filename='<unknown>',
):
    spec = LANGUAGES.get(language)
    if spec is None:
        return []
    try:
        if spec.extractor is not None:
            return spec.extractor(
                source,
                language=language,
                filename=filename,
                syntax_policy=syntax_policy,
                diagnostics=diagnostics,
            )
        if spec.tree_sitter is not None:
            return treesitter_units(
                source, language, recover=syntax_policy == 'recover', diagnostics=diagnostics
            )
        return []
    except (SyntaxError, ValueError) as exc:
        if missing == 'skip':
            return None
        if missing == 'error':
            raise ValueError(
                f'No se puede aplicar fragmentación estructural ({language}): {exc}'
            ) from exc
        raise ValueError(f'on_missing_parser inválido: {missing}') from exc
