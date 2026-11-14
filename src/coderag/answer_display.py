"""Deterministically display a provider answer and its retrieved source evidence."""

import re

from .generation import GenerationResult


def inline(value):
    """Quote metadata without breaking Markdown tables or inline code spans."""
    value = str(value).replace('\n', ' ').replace('|', '\\|')
    longest = max((len(match.group()) for match in re.finditer(r'`+', value)), default=0)
    fence = '`' * max(1, longest + 1)
    return f'{fence} {value} {fence}'


def render_answer(result, *, include_evidence=False, repository=None, markdown=False):
    generated = result.get('answer')
    if not isinstance(generated, GenerationResult) or not isinstance(generated.answer, str):
        raise ValueError('Text output requires a generated answer')
    text = generated.answer
    if markdown:
        scope = f'**Repositorio:** {inline(repository)} · ' if repository else ''
        metadata = (
            f'{scope}**Proveedor:** {inline(generated.provider)} · '
            f'**Modelo:** {inline(generated.model)}'
        )
        text = f'{metadata}\n\n## Respuesta\n\n{text}'
    if not include_evidence:
        return text
    items = result.get('context', {}).get('items', [])
    cited = {citation['chunk_id'] for citation in generated.citations}
    blocks = []
    if items:
        scope = f' — {repository}' if repository else ''
        blocks.append('## Fuentes' if markdown else f'## Evidencias del contexto{scope}')
        if markdown:
            table = ['| Fuente | Archivo y líneas | Uso | Certeza |', '| --- | --- | --- | --- |']
            for number, item in enumerate(items, 1):
                citation = item.get('citation', {})
                location = (
                    f'{citation.get("path", "")}:'
                    f'{citation.get("start_line")}-{citation.get("end_line")}'
                )
                usage = 'Citada' if citation.get('chunk_id') in cited else 'Solo contexto'
                certainty = item.get('certainty', 'static_candidate')
                table.append(f'| {number} | {inline(location)} | {usage} | {inline(certainty)} |')
            blocks.append('\n'.join(table))
            blocks.append('## Fragmentos de evidencia')
    for number, item in enumerate(items, 1):
        citation = item.get('citation', {})
        chunk_id = citation.get('chunk_id', '')
        location = (
            f'{citation.get("path", "")}: {citation.get("start_line")}-{citation.get("end_line")}'
        )
        label = (
            'Citada en la respuesta'
            if chunk_id in cited
            else 'Contexto recuperado; sin cita en la respuesta'
        )
        content = item.get('content', '')
        # Source text can contain Markdown fences; keep the entire excerpt quoted as code.
        longest = max((len(match.group()) for match in re.finditer(r'`+', content)), default=0)
        fence = '`' * max(3, longest + 1)
        language = item.get('chunk', {}).get('language') or ''
        if not re.fullmatch(r'[a-zA-Z0-9_+-]*', language):
            language = ''
        header = (
            f'### {number}. {location}\n'
            f'Chunk: {chunk_id}\n'
            f'{label}. Certeza: {item.get("certainty", "static_candidate")}'
        )
        if markdown:
            header = (
                f'### Fuente {number}\n\n'
                f'- **Archivo:** {inline(location)}\n'
                f'- **Chunk:** {inline(chunk_id)}\n'
                f'- **Uso:** {label}\n'
                f'- **Certeza:** {inline(item.get("certainty", "static_candidate"))}'
            )
        if citation.get('symbol'):
            header += (
                f'\n- **Símbolo:** {inline(citation["symbol"])}'
                if markdown
                else f'\nSímbolo: {citation["symbol"]}'
            )
        if item.get('content_truncated'):
            warning = 'Fragmento truncado; el rango indica la ubicación del chunk completo.'
            header += f'\n\n> {warning}' if markdown else f'\n{warning}'
        blocks.append(f'{header}\n\n{fence}{language}\n{content}\n{fence}')
    state = result.get('index_state') or {}
    git_state = state.get('git') or {}
    if git_state.get('status') not in {None, 'not_applicable'} and (
        (git_state.get('current') or {}).get('status') == 'available'
        or (git_state.get('indexed') or {}).get('status') == 'available'
    ):
        indexed = git_state.get('indexed') or {}
        current = git_state.get('current') or {}
        lines = [
            '## Estado del índice',
            '',
            f'Commit indexado: {inline(indexed.get("commit") or "desconocido")}',
            f'Commit actual: {inline(current.get("commit") or "desconocido")}',
            f'Rama indexada/actual: {inline(indexed.get("branch"))} / '
            f'{inline(current.get("branch"))}',
            f'Cambios locales al indexar/ahora: {indexed.get("dirty")} / {current.get("dirty")}',
            f'Fuentes indexables: {inline(state["source"]["status"])} '
            f'({state["source"].get("verification", "none")})',
            'Actualización necesaria: '
            + {True: 'sí', False: 'no', None: 'sin verificar'}[state.get('needs_update')],
            git_state.get('message', ''),
        ]
        if state.get('needs_update') is not False and state.get('remedy'):
            lines.append('Preparación incremental: ' + inline(state['remedy']))
        blocks.append('\n'.join(lines))
    flow = result.get('context', {}).get('code_flow')
    if flow is not None:
        labels = {
            item['citation']['chunk_id']: (
                item['citation'].get('symbol') or item['citation'].get('path')
            )
            for item in items
        }
        lines = [
            '## Flujo estático',
            '',
            f'Puntos de entrada candidatos: {flow["matching_entry_candidates"]}.',
        ]
        for entry in flow['entries']:
            route = ' '.join(entry.get('methods', [])) + ' ' + entry.get('route', '')
            lines.append(f'- Entrada candidata: {inline(entry["symbol"])} {inline(route.strip())}')
        for edge in flow['edges']:
            lines.append(f'- {inline(labels[edge["source"]])} → {inline(labels[edge["target"]])}')
        lines.append(
            'Solo llamadas estáticas entre las evidencias incluidas; '
            'no representan el orden de ejecución. Middleware y montaje no resueltos.'
        )
        if flow['ambiguous_entry']:
            lines.append('Hay varias entradas candidatas: concreta método/ruta o símbolo inicial.')
        blocks.append('\n'.join(lines))
    limitations = list(
        dict.fromkeys(
            [
                *generated.limitations,
                *(note for item in items for note in item.get('limitations', [])),
            ]
        )
    )
    if limitations:
        blocks.append('## Limitaciones\n\n' + '\n'.join(f'- {note}' for note in limitations))
    return text + ('\n\n' + '\n\n'.join(blocks) if blocks else '')
