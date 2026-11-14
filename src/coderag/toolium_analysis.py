"""Offline, built-in Toolium reference analysis. Never imports analyzed projects."""

from __future__ import annotations

import configparser
import re

MARKER = re.compile(r'\[(LANG|CONF|CONTEXT):([^\]\r\n]+)\]')
MAP_CALL = re.compile(r'\bcontext\s*\.\s*map_param\s*\(')


# Scan balanced markers instead of matching until the first closing bracket.
# Each parent is emitted once; nested markers remain linked to that parent.
PREFIXES = ('LANG', 'CONF', 'CONTEXT')


def _references(text):
    stack = []
    nodes = []
    for i, ch in enumerate(text):
        if ch == '[':
            stack.append((i, []))
        elif ch == ']' and stack:
            start, children = stack.pop()
            expression = text[start + 1 : i]
            if ':' in expression:
                kind, key = expression.split(':', 1)
                if kind in PREFIXES:
                    node = {
                        'kind': kind.lower(),
                        'key': key.strip(),
                        'reference': text[start : i + 1],
                        'start': start,
                        'dependencies': children,
                    }
                    nodes.append(node)
                    if stack:
                        stack[-1][1].append(
                            {
                                'kind': node['kind'],
                                'key': node['key'],
                                'reference': node['reference'],
                            }
                        )
    return sorted(nodes, key=lambda n: n['start'])


def _toolium_mode(config, repo):
    setting = config.get('analysis', {}).get('toolium', 'auto')
    if isinstance(setting, dict):
        setting = setting.get(repo, setting.get('default', 'auto'))
    if setting not in ('auto', 'enabled', 'disabled'):
        raise ValueError('analysis.toolium debe ser auto, enabled o disabled')
    return setting


def _detected(config, repo, index):
    if 'toolium' in repo.lower():
        return True
    deps = config.get('relationships', {}).get(repo, {})
    dependencies = deps if isinstance(deps, list) else deps.get('dependencies', [])
    if any('toolium' in name.lower() for name in dependencies):
        return True
    for chunk in index.get('chunks', []):
        if chunk.get('language') != 'python':
            continue
        code = chunk.get('content', '')
        if re.search(r'^\s*(?:from|import)\s+toolium(?:_telefonica)?(?:\.|\b)', code, re.M):
            return True
    return False


def _find_language(repo_root, config):  # noqa: ARG001 - Preserve public callable signature
    config_files = sorted(repo_root.rglob('toolium.cfg')) if repo_root.is_dir() else []
    # Never parse config files from virtual environments.
    config_files = [
        p for p in config_files if not any(s in p.parts for s in ('.venv', 'node_modules', '.git'))
    ]
    for path in config_files:
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(path, encoding='utf-8')
            language = parser.get('TestExecution', 'language', fallback=None)
            if language:
                return language.strip(), path.relative_to(repo_root).as_posix()
        except (OSError, configparser.Error):
            continue
    return None, None


def _yaml_files(repo_root):
    if not repo_root.is_dir():
        return []
    files = list(repo_root.rglob('resources/language/*.yaml')) + list(
        repo_root.rglob('resources/language/*.yml')
    )
    return sorted(
        p for p in files if not any(s in p.parts for s in ('.venv', '.git', 'node_modules'))
    )


def _get_nested(data, segments):
    for part in segments:
        if not isinstance(data, dict) or part not in data:
            return False, None
        data = data[part]
    return True, data


def analyze_toolium(config, config_path, repo, index, relations, indexes=None):
    """Add a self-contained Toolium section without changing Behave links or chunks."""
    mode = _toolium_mode(config, repo)
    detected = _detected(config, repo, index)
    if mode == 'disabled' or (mode == 'auto' and not detected):
        return {
            'enabled': False,
            'mode': mode,
            'detected': detected,
            'references': [],
            'map_param_calls': [],
            'summary': {'references': 0},
        }
    root = (config_path.parent / config['repositories'][repo]['path']).resolve()
    lang, lang_config = _find_language(root, config)
    yaml_paths = _yaml_files(root)
    yaml_data = []
    if yaml_paths:
        try:
            import yaml
        except ImportError:
            yaml = None
        for path in yaml_paths:
            if yaml is None:
                yaml_data.append((path, None, 'yaml_dependency_missing'))
                continue
            try:
                with path.open(encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                yaml_data.append((path, data, None))
            except (OSError, yaml.YAMLError):
                yaml_data.append((path, None, 'yaml_parse_error'))
    refs = []
    calls = []
    # Read step text after Examples substitution; preserve original and parent-child links.
    for pos, rel in enumerate(relations):
        for node in _references(rel.get('resolved_text', rel.get('text', ''))):
            kind, key = node['kind'], node['key']
            item = {
                'relation_index': pos,
                'chunk_id': rel.get('chunk_id'),
                'feature_path': rel.get('feature_path'),
                'scenario': rel.get('scenario'),
                'example_row': rel.get('example_row'),
                'kind': kind,
                'reference': node['reference'],
                'key': key,
                'status': 'dynamic',
            }
            if node['dependencies']:
                item['dependencies'] = node['dependencies']
            if kind == 'lang':
                # Toolium get_message_property supports an explicit ::language override.
                lang_key, explicit_lang = key.split('::', 1) if '::' in key else (key, None)
                selected_lang = explicit_lang or lang
                item['language'] = selected_lang
                item['language_config_path'] = lang_config
                if node['dependencies']:
                    item['status'] = 'runtime_dependent'
                elif not root.is_dir():
                    item['status'] = 'source_unavailable'
                elif not selected_lang:
                    item['status'] = 'language_not_configured'
                elif not yaml_paths:
                    item['status'] = 'language_resources_missing'
                else:
                    for path, data, error in yaml_data:
                        if error or data is None:
                            continue
                        found, value = _get_nested(data, [*lang_key.split('.'), selected_lang])
                        if found:
                            item.update(
                                status='resolved',
                                resource_path=path.relative_to(root).as_posix(),
                                value=value,
                            )
                            break
                    if item['status'] != 'resolved':
                        item['status'] = (
                            'yaml_dependency_missing'
                            if any(e == 'yaml_dependency_missing' for _, _, e in yaml_data)
                            else 'yaml_parse_error'
                            if yaml_data and all(e for _, _, e in yaml_data)
                            else 'language_key_not_found'
                        )
            refs.append(item)
    # Also record direct literal markers in Python code; map_param is dynamic.
    for chunk in index.get('chunks', []):
        if chunk.get('language') != 'python':
            continue
        content = chunk.get('content', '')
        if MAP_CALL.search(content):
            calls.append(
                {
                    'chunk_id': chunk['id'],
                    'path': chunk['path'],
                    'symbol': chunk.get('symbol'),
                    'kind': 'toolium_map_param_call',
                    'status': 'runtime_dependent',
                }
            )
    from collections import Counter

    from .context_flow import context_flow

    flow = context_flow(indexes or {repo: index}, refs, relations)
    return {
        'context_flow': flow,
        'enabled': True,
        'mode': mode,
        'detected': detected,
        'language': lang,
        'language_config_path': lang_config,
        'references': refs,
        'map_param_calls': calls,
        'summary': {
            'references': len(refs),
            'by_status': dict(Counter(r['status'] for r in refs)),
            'by_kind': dict(Counter(r['kind'] for r in refs)),
            'map_param_calls': len(calls),
        },
        'disclaimer': (
            'Las referencias LANG se resuelven desde YAML local cuando su '
            'clave es estática; las expresiones anidadas y CONTEXT dependen '
            'del runtime. No se ejecuta Toolium.'
        ),
    }
