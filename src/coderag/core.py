"""Local structural indexer. Token count uses a documented lexical proxy, not LLM tokenizer."""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import heapq
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path

from .artifact_state import file_stamp
from .configuration_chunks import CONFIGURATION_CHUNKING_VERSION, configuration_units
from .generation_safety import SENSITIVE_NAMES
from .python_parsing import PYTHON_DIAGNOSTICS_VERSION, parse_python

EXT = {
    '.py': 'python',
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.mjs': 'javascript',
    '.cjs': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'typescript',
    '.mts': 'typescript',
    '.cts': 'typescript',
    '.java': 'java',
    '.cs': 'csharp',
    '.go': 'go',
    '.c': 'c',
    '.i': 'c',
    '.cpp': 'cpp',
    '.cc': 'cpp',
    '.cxx': 'cpp',
    '.c++': 'cpp',
    '.hpp': 'cpp',
    '.hh': 'cpp',
    '.hxx': 'cpp',
    '.h++': 'cpp',
    '.h': 'c/cpp',
    '.sh': 'shell',
    '.bash': 'shell',
    '.zsh': 'shell',
    '.mk': 'makefile',
    '.lock': 'lock',
    '.feature': 'gherkin',
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.json': 'json',
}
SPECIAL = {
    'Makefile': 'makefile',
    'makefile': 'makefile',
    'GNUmakefile': 'makefile',
    'package-lock.json': 'lock',
    'npm-shrinkwrap.json': 'lock',
    'Cargo.lock': 'lock',
    'poetry.lock': 'lock',
    'Pipfile.lock': 'lock',
    'yarn.lock': 'lock',
    'pnpm-lock.yaml': 'lock',
    'Gemfile.lock': 'lock',
    'uv.lock': 'lock',
    'composer.lock': 'lock',
}
SKIP = {
    '.git',
    '.hg',
    '.svn',
    '.venv',
    'venv',
    'node_modules',
    'vendor',
    'dist',
    'build',
    'target',
    '.next',
    '__pycache__',
    '.idea',
    '.gradle',
    'coverage',
    'indexes',
}
MAX_FILE_BYTES = 1_048_576
# Conservative, dependency-free lexical accounting; not the tokenizer of an embedding model.
TOK = re.compile(r'\w+|[^\w\s]', re.UNICODE)
TREE_LANG = {
    'javascript': 'javascript',
    'typescript': 'typescript',
    'java': 'java',
    'csharp': 'c_sharp',
    'go': 'go',
    'c': 'c',
    'cpp': 'cpp',
    'shell': 'bash',
}
NODE_TYPES = {
    'javascript': {
        'function_declaration',
        'class_declaration',
        'method_definition',
        'arrow_function',
        'generator_function_declaration',
    },
    'typescript': {
        'function_declaration',
        'class_declaration',
        'method_definition',
        'interface_declaration',
        'type_alias_declaration',
        'enum_declaration',
        'arrow_function',
    },
    'java': {
        'class_declaration',
        'interface_declaration',
        'method_declaration',
        'constructor_declaration',
        'enum_declaration',
        'record_declaration',
    },
    'csharp': {
        'class_declaration',
        'interface_declaration',
        'method_declaration',
        'constructor_declaration',
        'struct_declaration',
        'record_declaration',
    },
    'go': {'function_declaration', 'method_declaration', 'type_declaration'},
    'c': {'function_definition', 'struct_specifier', 'enum_specifier', 'type_definition'},
    'cpp': {
        'function_definition',
        'class_specifier',
        'struct_specifier',
        'namespace_definition',
        'template_declaration',
        'enum_specifier',
    },
    'shell': {'function_definition'},
}


def token_count(s: str) -> int:
    return len(TOK.findall(s))


def detect_language(path: Path, overrides: dict) -> str | None:
    return overrides.get(path.suffix.lower(), SPECIAL.get(path.name, EXT.get(path.suffix.lower())))


def is_excluded(relative_path: str, patterns: list[str]) -> bool:
    """Match repository-relative POSIX paths (files or directories) against glob patterns.

    A directory match also excludes all descendants. Leading / is repository-root
    anchored; a pattern starting **/ can match at root or below it.
    """
    relative_path = relative_path.strip('/')
    for raw in patterns:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError('Cada patrón de exclusión debe ser un string no vacío')
        pattern = raw.strip().replace('\\', '/').lstrip('./').strip('/')
        if not pattern:
            continue
        variants = (pattern, pattern[3:]) if pattern.startswith('**/') else (pattern,)
        for variant in variants:
            if fnmatch.fnmatchcase(relative_path, variant):
                return True
            # Also match directory patterns supplied without a final /**.
            base = variant.removesuffix('/**')
            if relative_path == base or relative_path.startswith(base + '/'):
                return True
    return False


def discover_paths(
    root: Path,
    languages: set[str],
    overrides: dict,
    excludes: list[str] | None = None,
    excluded_paths: list | None = None,
):
    excludes = excludes or []
    for current, dirs, names in os.walk(root, followlinks=False):
        included_dirs = []
        for d in sorted(dirs):
            candidate = Path(current) / d
            rel = candidate.relative_to(root).as_posix()
            if d in SKIP or d.startswith('.') or candidate.is_symlink():
                continue
            if is_excluded(rel, excludes):
                if excluded_paths is not None:
                    excluded_paths.append({'path': rel, 'kind': 'directory'})
                continue
            included_dirs.append(d)
        dirs[:] = included_dirs
        for name in sorted(names):
            file = Path(current) / name
            rel = file.relative_to(root).as_posix()
            if name in SENSITIVE_NAMES or is_excluded(rel, excludes):
                if excluded_paths is not None:
                    excluded_paths.append({'path': rel, 'kind': 'file'})
                continue
            if file.is_symlink() or (lang := detect_language(file, overrides)) not in languages:
                continue
            try:
                if file.stat().st_size > MAX_FILE_BYTES:
                    continue
                yield file, lang
            except OSError:
                continue


def discover(root, languages, overrides, excludes=None, excluded_paths=None, *, source_stats=None):
    for file, lang in discover_paths(root, languages, overrides, excludes, excluded_paths):
        try:
            before = file_stamp(file)
            raw = file.read_bytes()
            if b'\0' in raw:
                continue
            source = raw.decode('utf-8-sig')
            after = file_stamp(file)
            if source_stats is not None:
                source_stats[file.relative_to(root).as_posix()] = (
                    before if before == after else None
                )
            yield file, lang, source
        except (OSError, UnicodeDecodeError):
            continue


def python_units(source: str, *, filename='<unknown>', diagnostics=None):
    tree = parse_python(source, filename=filename, diagnostics=diagnostics)
    nodes = []

    def walk(body, prefix=''):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbol = prefix + node.name
                nodes.append(
                    (
                        min([node.lineno] + [d.lineno for d in node.decorator_list]),
                        node.end_lineno,
                        symbol,
                        'python_ast',
                    )
                )
                if isinstance(node, ast.ClassDef):
                    walk(node.body, symbol + '.')

    walk(tree.body)
    return nodes


def treesitter_units(
    source: str, language: str, *, recover: bool = False, diagnostics: list | None = None
):
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError as exc:
        raise ValueError(
            'Falta tree-sitter-language-pack: ejecuta uv sync --extra parsers'
        ) from exc
    try:
        parser = get_parser(TREE_LANG[language])
        root = parser.parse(source.encode('utf-8')).root_node
    except Exception as exc:
        raise ValueError(f'No se pudo analizar {language} con Tree-sitter: {exc}') from exc
    # Tuple access avoids the Point attribute refcount bug in tree-sitter 0.26.0.
    if root.has_error:
        errors = []

        def collect(node):
            if node.type == 'ERROR' or node.is_missing:
                errors.append(
                    {
                        'line': node.start_point[0] + 1,
                        'column': node.start_point[1] + 1,
                        'node': node.type,
                        'end_line': node.end_point[0] + 1,
                    }
                )
                return
            for child in node.children:
                collect(child)

        collect(root)
        if diagnostics is not None:
            diagnostics.extend(
                {'type': 'syntax_error', 'language': language, **e} for e in errors[:100]
            )
        if not recover:
            loc = errors[0] if errors else {'line': '?', 'column': '?'}
            raise ValueError(
                f'Errores de sintaxis detectados por Tree-sitter en {language} '
                f'(línea {loc["line"]}, columna {loc["column"]})'
            )
    units = []

    def visit(node, parent=''):
        for ch in node.named_children:
            if ch.type in NODE_TYPES[language] and not ch.has_error:
                ident = ch.child_by_field_name('name') or ch.child_by_field_name('declarator')
                label = (
                    source.encode('utf-8')[ident.start_byte : ident.end_byte].decode(
                        'utf-8', 'replace'
                    )
                    if ident
                    else ch.type
                )
                label = re.sub(r'\s+', ' ', label)[:100]
                symbol = (parent + '.' if parent else '') + label
                units.append((ch.start_point[0] + 1, ch.end_point[0] + 1, symbol, 'tree_sitter'))
                visit(ch, symbol)
            else:
                visit(ch, parent)

    visit(root)
    return units


def make_units(source: str):
    lines = source.splitlines()
    starts = []
    for i, line in enumerate(lines, 1):
        if (
            line.startswith((' ', '\t', '#', '.PHONY'))
            or '=' in line.split(':', 1)[0]
            or ':' not in line
        ):
            continue
        # Targets may contain substitutions such as $(NAME) and pattern rules.
        if re.match(r'^[^\s:#][^:]*:(?!=)', line) and not line.startswith(
            ('ifeq', 'ifneq', 'ifdef', 'ifndef', 'endif')
        ):
            starts.append(i)
    return [
        (
            a,
            starts[j + 1] - 1 if j + 1 < len(starts) else len(lines),
            lines[a - 1].split(':', 1)[0].strip(),
            'makefile_rules',
        )
        for j, a in enumerate(starts)
    ]


def gherkin_units(source: str):
    """Recognize Gherkin sections, preserving tags and Scenario Outline examples.

    Sections are extracted without execution and tolerate localized keywords.
    """
    lines = source.splitlines()
    pattern = re.compile(
        (
            '^\\s*(Feature|Background|Scenario Outline|Scenario Template|'
            'Scenario|Rule|Examples|Example|Característica|Antecedentes|'
            'Esquema del escenario|Escenario|Regla|Ejemplos)\\s*:'
        ),
        re.I,
    )
    sections = []
    pending = None
    for i, line in enumerate(lines, 1):
        if line.strip().startswith('@'):
            if pending is None:
                pending = i
            continue
        match = pattern.match(line)
        if match:
            start = pending or i
            label = line.strip().split(':', 1)[1].strip()
            kind = match.group(1).lower().replace(' ', '_')
            sections.append((start, i, kind, label))
            pending = None
        elif line.strip() and not line.lstrip().startswith('#'):
            pending = None
    # Keep whole scenarios, incl. Examples (do not make Examples independent chunks).
    primary = [v for v in sections if v[2] not in ('examples', 'example', 'ejemplos')]
    units = []
    for j, (start, head, kind, label) in enumerate(primary):
        end = primary[j + 1][0] - 1 if j + 1 < len(primary) else len(lines)
        # Feature / Rule are parents, not a giant chunk consuming nested scenarios.
        if kind in ('feature', 'característica', 'rule', 'regla'):
            end = head
        units.append((start, end, f'{kind}: {label}', 'gherkin_ast'))
    return units


def units_for(
    source: str,
    language: str,
    missing: str,
    syntax_policy: str = 'error',
    diagnostics: list | None = None,
    *,
    filename='<unknown>',
):
    try:
        if language == 'python':
            return python_units(source, filename=filename, diagnostics=diagnostics)
        if language == 'gherkin':
            return gherkin_units(source)
        if language in {'yaml', 'json'}:
            try:
                return configuration_units(source, language)
            except ValueError as exc:
                if syntax_policy != 'recover':
                    raise
                if diagnostics is not None:
                    diagnostics.append(
                        {
                            'type': 'configuration_parse_error',
                            'language': language,
                            'message': str(exc),
                            'recovery': 'raw_document',
                        }
                    )
                return []
        if language in TREE_LANG:
            return treesitter_units(
                source, language, recover=syntax_policy == 'recover', diagnostics=diagnostics
            )
        if language == 'makefile':
            return make_units(source)
        return []
    except (SyntaxError, ValueError) as exc:
        if missing == 'skip':
            return None
        if missing == 'error':
            raise ValueError(
                f'No se puede aplicar fragmentación estructural ({language}): {exc}'
            ) from exc
        raise ValueError(f'on_missing_parser inválido: {missing}') from exc


def partition(lines, units):
    """Cover every source line, preferring leaf units with stable tie-breaking.

    Sweep structural boundaries instead of comparing every line to every unit;
    configuration files can contain thousands of keys and list entries.
    """
    total = len(lines)
    starts = {}
    boundaries = {1, total + 1}
    for order, unit in enumerate(units):
        start, end = max(1, unit[0]), min(total, unit[1])
        if start > end:
            continue
        starts.setdefault(start, []).append((unit[1] - unit[0], -unit[0], order, unit))
        boundaries.update((start, end + 1))
    points = sorted(boundaries)
    active = []
    runs = []
    for start, stop in pairwise(points):
        for item in starts.get(start, []):
            heapq.heappush(active, item)
        while active and active[0][3][1] < start:
            heapq.heappop(active)
        unit = active[0][3] if active else None
        if runs and runs[-1][2] == unit:
            runs[-1] = (runs[-1][0], stop - 1, unit)
        else:
            runs.append((start, stop - 1, unit))
    return runs


def split_budget(lines, start, end, max_tokens, overlap):
    """Budget at line granularity; long lines are split at lexical token boundaries."""
    result = []
    # Each source line is atomized to keep a hard lexical budget even for minified files.
    atoms = []
    for line_number in range(start, end + 1):
        line = lines[line_number - 1]
        if token_count(line) <= max_tokens:
            atoms.append((line_number, line))
        else:
            # Tokens are source spans, thus concatenation preserves original characters.
            matches = list(TOK.finditer(line))
            cursor = 0
            for j in range(0, len(matches), max_tokens):
                group = matches[j : j + max_tokens]
                cut = group[-1].end()
                atoms.append((line_number, line[cursor:cut]))
                cursor = cut
            if cursor < len(line):
                atoms.append((line_number, line[cursor:]))
    pos = 0
    while pos < len(atoms):
        count = 0
        nxt = pos
        while nxt < len(atoms) and count + token_count(atoms[nxt][1]) <= max_tokens:
            count += token_count(atoms[nxt][1])
            nxt += 1
        if nxt == pos:
            nxt += 1
        part = atoms[pos:nxt]
        result.append((part[0][0], part[-1][0], '\n'.join(v for _, v in part)))
        if nxt == len(atoms):
            break
        back = 0
        nextpos = nxt
        while nextpos > pos + 1 and back + token_count(atoms[nextpos - 1][1]) <= overlap:
            nextpos -= 1
            back += token_count(atoms[nextpos][1])
        pos = nextpos
    return result


def attach_leading_docs(lines, units, language):
    if language not in ('c', 'cpp', 'javascript', 'typescript', 'java', 'csharp', 'go'):
        return units
    ordered = sorted(units, key=lambda x: (x[0], x[1]))
    result = []
    for start, end, symbol, strategy in ordered:
        begin = start
        j = start - 1
        # Capture immediately preceding consecutive documentation comments, not unrelated code.
        while j >= 1 and lines[j - 1].strip() == '':
            j -= 1
        if j >= 1 and lines[j - 1].strip().endswith('*/'):
            k = j
            while k >= 1 and not (
                lines[k - 1].lstrip().startswith('/**') or lines[k - 1].lstrip().startswith('/*!')
            ):
                if '/*' in lines[k - 1]:
                    break
                k -= 1
            if k >= 1 and lines[k - 1].lstrip().startswith(('/**', '/*!')):
                begin = k
        result.append((begin, end, symbol, strategy))
    return result


def build_chunks(path: str, lang: str, source: str, cfg: dict, diagnostics: list | None = None):
    lines = source.splitlines()
    if not lines:
        return []
    opts = cfg['chunking']
    maximum = opts['max_tokens']
    overlap = opts['overlap_tokens']
    if maximum < 1 or not 0 <= overlap < maximum:
        raise ValueError('max_tokens debe ser > 0 y overlap_tokens entre 0 y max_tokens-1')
    units = units_for(
        source,
        lang,
        opts['on_missing_parser'],
        opts.get('on_syntax_error', 'error'),
        diagnostics,
        filename=path,
    )
    if units is None:
        return []
    units = attach_leading_docs(lines, units, lang)
    rows = []
    # For individual symbols, preserve full block when it fits, then bound/split.
    for start, end, u in partition(lines, units):
        symbol = u[2] if u else None
        strategy = (
            u[3]
            if u
            else (
                f'{lang}_document'
                if lang in {'yaml', 'json'}
                else 'lock_document'
                if lang == 'lock'
                else 'surrounding_code'
            )
        )
        for a, b, content in split_budget(lines, start, end, maximum, overlap):
            if not content.strip():
                continue
            prefix = symbol.rsplit('.', 1)[0] if symbol and '.' in symbol else None
            h = hashlib.sha256(f'{path}\0{a}\0{b}\0{content}'.encode()).hexdigest()
            rows.append(
                {
                    'id': h[:16],
                    'path': path,
                    'language': lang,
                    'strategy': strategy,
                    'symbol': symbol if opts['preserve_symbols'] else None,
                    'parent_symbol': prefix if opts['include_parent_context'] else None,
                    'start_line': a,
                    'end_line': b,
                    'content': content,
                    'estimated_tokens': token_count(content),
                    'sha256': hashlib.sha256(content.encode()).hexdigest(),
                }
            )
    if lang in {'yaml', 'json'}:
        for row in rows:
            row['configuration_chunking_version'] = CONFIGURATION_CHUNKING_VERSION
            row['data_path'] = row['symbol']
            if opts['include_parent_context'] and row['symbol'] and '/' in row['symbol']:
                row['parent_symbol'] = row['symbol'].rsplit('/', 1)[0]
    if lang == 'gherkin':
        # Enrich scenario chunks with their feature context (including inherited tags).
        feature = None
        feature_tags = []
        pending_tags = []
        feature_positions = []
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('@'):
                pending_tags.extend(stripped.split())
            elif re.match(r'^(Feature|Característica)\s*:', stripped, re.I):
                feature = stripped.split(':', 1)[1].strip()
                feature_tags = pending_tags[:]
                feature_positions.append((lineno, feature, feature_tags))
                pending_tags = []
            elif re.match(
                (
                    '^(Scenario|Scenario Outline|Scenario Template|Background|'
                    'Escenario|Esquema del escenario|Antecedentes)\\s*:'
                ),
                stripped,
                re.I,
            ):
                pending_tags = []
            elif stripped and not stripped.startswith('#'):
                pending_tags = []
        for row in rows:
            if row['symbol'] and row['symbol'].startswith(
                (
                    'scenario:',
                    'scenario_outline:',
                    'scenario_template:',
                    'background:',
                    'escenario:',
                    'esquema_del_escenario:',
                    'antecedentes:',
                )
            ):
                ancestors = [
                    (name, tags)
                    for pos, name, tags in feature_positions
                    if pos <= row['start_line']
                ]
                if ancestors:
                    name, tags = ancestors[-1]
                    row['parent_symbol'] = 'feature: ' + name
                    row['feature_tags'] = tags
    return rows


def index_repository(
    repo: Path,
    output: Path,
    config: dict,
    progress=None,
    excludes: list[str] | None = None,
    incremental=False,
):
    from .git_state import capture_git, indexed_git

    root = repo.resolve()
    if not root.is_dir():
        raise ValueError(f'No existe el repositorio: {repo}')
    git_before = capture_git(root)
    settings = config['indexing']
    opts = settings['chunking']
    if opts.get('strategy') != 'structural':
        raise ValueError('Solo se admite strategy=structural')
    languages = set(settings['languages'])
    overrides = settings.get('language_overrides', {})
    chunks = []
    files = 0
    skipped = []
    diagnostics = []
    excluded_paths = []
    previous = {}
    configuration_sources = {}
    source_manifest = {}
    python_sources = {}
    source_stats = {}
    if incremental and output.exists():
        old = json.loads(output.read_text(encoding='utf-8'))
        previous = {c['path']: c for c in old.get('chunks', []) if c.get('file_sha256')}
    isolate = settings.get('isolate_parsers', False)
    timeout = settings.get('timeout_seconds', 30)
    on_file_error = settings.get('on_file_error', 'error')
    if on_file_error not in ('error', 'skip'):
        raise ValueError('on_file_error debe ser error o skip')
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError('timeout_seconds debe ser positivo')
    patterns = [*settings.get('exclude', []), *(excludes or [])]
    for file, lang, source in discover(
        root, languages, overrides, patterns, excluded_paths, source_stats=source_stats
    ):
        rel = file.relative_to(root).as_posix()
        source_manifest[rel] = hashlib.sha256(source.encode()).hexdigest()
        if lang == 'python':
            python_sources[rel] = {'source': source, 'file_sha256': source_manifest[rel]}
        if progress is not None:
            progress(f'START {rel} ({lang})')
        try:
            file_hash = hashlib.sha256(source.encode()).hexdigest()
            if (
                incremental
                and rel in previous
                and previous[rel].get('file_sha256') == file_hash
                and previous[rel].get('language') == lang
                and (
                    lang != 'python'
                    or old.get('python_diagnostics_version') == PYTHON_DIAGNOSTICS_VERSION
                )
                and (
                    lang not in {'yaml', 'json'}
                    or (
                        previous[rel].get('configuration_chunking_version')
                        == CONFIGURATION_CHUNKING_VERSION
                        and rel in old.get('configuration_sources', {})
                    )
                )
            ):
                reused = [c for c in old['chunks'] if c.get('path') == rel]
                chunks.extend(reused)
                diagnostics.extend(d for d in old.get('diagnostics', []) if d.get('path') == rel)
                if lang in {'yaml', 'json'}:
                    configuration_sources[rel] = old['configuration_sources'][rel]
                files += 1
                if progress is not None:
                    progress(f'REUSE  {rel}: {len(reused)} chunks')
                continue
            file_diagnostics = []
            if isolate:
                payload = json.dumps(
                    {'path': rel, 'language': lang, 'source': source, 'config': settings}
                )
                try:
                    result = subprocess.run(
                        [sys.executable, '-m', 'coderag.worker'],
                        input=payload,
                        text=True,
                        capture_output=True,
                        timeout=timeout,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise ValueError(f'Parser timeout ({timeout}s)') from exc
                if result.returncode != 0:
                    try:
                        detail = json.loads(result.stdout).get('error', '')
                    except json.JSONDecodeError:
                        detail = result.stderr[-300:]
                    raise ValueError(f'Parser worker exit={result.returncode}: {detail}')
                parsed = json.loads(result.stdout)
                rows = parsed['chunks']
                file_diagnostics = parsed['diagnostics']
            else:
                rows = build_chunks(rel, lang, source, settings, file_diagnostics)
            diagnostics.extend({'path': rel, **d} for d in file_diagnostics)
        except (ValueError, json.JSONDecodeError) as exc:
            if on_file_error == 'skip' or opts['on_missing_parser'] == 'skip':
                skipped.append({'path': rel, 'reason': str(exc)})
                continue
            raise ValueError(f'{rel}: {exc}') from exc
        if lang in {'yaml', 'json'}:
            configuration_sources[rel] = {
                'language': lang,
                'source': source,
                'file_sha256': file_hash,
                'structure_version': CONFIGURATION_CHUNKING_VERSION,
            }
        if not rows:
            diagnostics.append(
                {'path': rel, 'kind': 'zero_chunks', 'message': 'Archivo sin fragmentos'}
            )
        for row in rows:
            row['file_sha256'] = file_hash
        chunks.extend(rows)
        files += 1
        if progress is not None:
            progress(f'OK    {rel}: {len(rows)} chunks')
    from .behave_links import build_behave_relations

    relationships = build_behave_relations(chunks)
    lexical_index = {kind: {} for kind in ('symbol', 'path', 'content')}
    for chunk in chunks:
        for kind, value in (
            ('symbol', chunk.get('symbol')),
            ('path', chunk.get('path')),
            ('content', chunk.get('content', '')),
        ):
            for term in re.findall(r'[A-Za-z_][A-Za-z0-9_.:/-]*', value or ''):
                lexical_index[kind].setdefault(term, []).append(chunk['id'])
    lexical_index = {
        kind: {term: sorted(set(ids)) for term, ids in terms.items()}
        for kind, terms in lexical_index.items()
    }
    payload = {
        'schema_version': 2,
        'source_root': str(root),
        'git': indexed_git(git_before, capture_git(root)),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'files_discovered': files,
        'skipped_files': skipped,
        'excluded_paths': excluded_paths,
        'exclude_patterns': patterns,
        'diagnostics': diagnostics,
        'chunking': opts,
        'token_count_method': 'lexical_proxy_not_model_tokenizer',
        'chunks': chunks,
        'configuration_sources': configuration_sources,
        'source_manifest': source_manifest,
        'source_stats': source_stats,
        'python_sources': python_sources,
        'python_diagnostics_version': PYTHON_DIAGNOSTICS_VERSION,
        'indexing_settings': {**settings, 'exclude': patterns},
        'behave_relations': relationships,
        'lexical_index': lexical_index,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    # Save atomically so a failed or interrupted run cannot leave a half-written JSON index.
    import tempfile

    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=output.parent,
            prefix=output.name + '.',
            suffix='.tmp',
            delete=False,
        ) as f:
            temp_name = f.name
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(temp_name, output)
    finally:
        if temp_name is not None and os.path.exists(temp_name):
            os.unlink(temp_name)
    return payload


def inspect_index(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def analyze_index(index: dict) -> dict:
    chunks = index['chunks']
    by_language = Counter(c['language'] for c in chunks)
    by_strategy = Counter(c['strategy'] for c in chunks)
    files = {c['path'] for c in chunks}
    sizes = sorted(c['estimated_tokens'] for c in chunks)
    limit = index.get('chunking', {}).get('max_tokens', 0)
    result = {
        'files_indexed': len(files),
        'files_discovered': index.get('files_discovered'),
        'chunks': len(chunks),
        'symbols': sum(c.get('symbol') is not None for c in chunks),
        'languages': dict(sorted(by_language.items())),
        'strategies': dict(sorted(by_strategy.items())),
        'median_estimated_tokens': sizes[len(sizes) // 2] if sizes else 0,
        'over_budget': sum(c['estimated_tokens'] > limit for c in chunks),
        'diagnostics': index.get('diagnostics', []),
        'skipped_files': index.get('skipped_files', []),
        'excluded_paths': index.get('excluded_paths', []),
        'excluded_count': len(index.get('excluded_paths', [])),
    }
    result['behave'] = index.get('behave_relations', {}).get('summary', {})
    result['files_without_chunks'] = max(0, (index.get('files_discovered') or 0) - len(files))
    return result
