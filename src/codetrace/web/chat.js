'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="chat-token"]').content;
const english = document.documentElement.lang === 'en';
const t = (es, en) => english ? en : es;
if (english) {
  document.querySelectorAll('[data-en]').forEach(el => { el.textContent = el.dataset.en; });
  for (const attribute of ['aria-label', 'placeholder']) {
    document.querySelectorAll(`[data-en-${attribute}]`).forEach(el => {
      el.setAttribute(attribute, el.getAttribute(`data-en-${attribute}`));
    });
  }
}
let repositories = [];
let pending = false;
const sessionKey = 'codetrace-conversation';
$('session').value = sessionStorage.getItem(sessionKey) || '';
function storeSession(id) {
  $('session').value = id;
  if (id) sessionStorage.setItem(sessionKey, id);
  else sessionStorage.removeItem(sessionKey);
}
$('session').addEventListener('change', () => storeSession($('session').value.trim()));
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = String(text);
  if (className) el.className = className;
  return el;
}
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'X-CodeRAG-Token': token, 'Content-Type': 'application/json'}, cache: 'no-store'});
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || t('No se pudo completar la consulta.', 'The request could not be completed.'));
    error.candidates = data.candidates;
    throw error;
  }
  return data;
}
function describe() {
  $('description').textContent = repositories.find(r => r.name === $('repo').value)?.description || '';
}
function message(label, className = '') {
  $('empty')?.remove();
  const block = node('article', undefined, `message ${className}`);
  block.append(node('div', label, 'message-label'));
  $('messages').append(block);
  return block;
}
function scroll() { $('messages').scrollTop = $('messages').scrollHeight; }
function details(title, content) {
  const el = node('details');
  el.append(node('summary', title), content);
  return el;
}
function showAnswer(result) {
  const answer = result.answer;
  const block = message('CodeTrace');
  block.append(node('div', `${result.repository || $('repo').value} · ${answer.provider} · ${answer.model}`, 'metadata'));
  // Provider and repository text stays inert: no HTML/Markdown evaluation or remote resources.
  block.append(node('div', answer.answer, 'answer-text'));
  if (answer.refusal) block.append(node('p', t('El modelo indica que no dispone de evidencia suficiente.', 'The model reports insufficient evidence.'), 'limitations'));
  const items = result.context?.items || [];
  const cited = new Set((answer.citations || []).map(c => c.chunk_id));
  if (items.length) {
    const sources = node('div');
    items.forEach((item, i) => {
      const c = item.citation || {};
      const body = node('div');
      body.append(node('p', `${c.symbol || ''} · ${item.certainty || 'static_candidate'} · ${cited.has(c.chunk_id) ? t('Citada', 'Cited') : t('Solo contexto', 'Context only')}`, 'metadata'));
      if (item.content_truncated) body.append(node('p', t('Fragmento truncado; las líneas corresponden al chunk completo.', 'Excerpt truncated. Line numbers refer to the full chunk.'), 'limitations'));
      body.append(node('pre', item.content || ''));
      sources.append(details(`${i + 1}. ${c.path}:${c.start_line}–${c.end_line}`, body));
    });
    block.append(details(`${t('Evidencias (', 'Evidence (')}${items.length})`, sources));
  }
  const flow = result.context?.code_flow;
  if (flow) {
    const body = node('div');
    body.append(node('p', `${t('Entradas candidatas:', 'Candidate entry points:')} ${flow.matching_entry_candidates}. ${t('Se muestran solo relaciones entre evidencias incluidas.', 'Only relationships between included evidence items are shown.')}`, 'limitations'));
    const labels = new Map(items.map(item => [item.citation.chunk_id, `${item.citation.symbol || item.citation.path} (${item.citation.path}:${item.citation.start_line}–${item.citation.end_line})`]));
    const list = node('ul', undefined, 'limitations');
    flow.entries.forEach(entry => list.append(node('li', `${t('Entrada candidata:', 'Candidate entry point:')} ${labels.get(entry.chunk_id)} · ${(entry.methods || []).join('/')} ${entry.route || ''}`)));
    flow.edges.forEach(edge => list.append(node('li', `${labels.get(edge.source)} → ${labels.get(edge.target)}`)));
    body.append(list);
    if (flow.ambiguous_entry) body.append(node('p', t('Hay varias entradas candidatas. Concreta método/ruta o símbolo inicial.', 'Several entry points matched. Specify a method and route or an initial symbol.'), 'limitations warning'));
    body.append(node('p', t('Llamadas estáticas, no orden de ejecución. Middleware, dependencias y montaje del router no resueltos.', 'Calls are static. Execution order, middleware, dependencies, and router mounting are unresolved.'), 'limitations'));
    block.append(details(t('Flujo estático del código', 'Static code flow'), body));
  }
  const limitations = [...new Set([...(answer.limitations || []), ...items.flatMap(i => i.limitations || [])])];
  if (limitations.length) {
    const list = node('ul', undefined, 'limitations');
    limitations.forEach(text => list.append(node('li', text)));
    block.append(details(t('Limitaciones', 'Limitations'), list));
  }
  const state = result.index_state;
  if (state) {
    const git = state.git || {};
    const update = state.needs_update === true ? t('Sí', 'Yes') : state.needs_update === false ? 'No' : t('Sin verificar', 'Unverified');
    const text = `${t('Fuentes:', 'Sources:')} ${state.source?.status || t('desconocido', 'unknown')}\n${t('Actualización necesaria:', 'Update needed:')} ${update}\n${t('Commit indexado:', 'Indexed commit:')} ${git.indexed?.commit || t('desconocido', 'unknown')}\n${t('Commit actual:', 'Current commit:')} ${git.current?.commit || t('desconocido', 'unknown')}\n${git.message || ''}${state.needs_update !== false && state.remedy ? '\n' + state.remedy : ''}`;
    block.append(details(`${t('Estado del índice ·', 'Index status ·')} ${state.source?.status || t('desconocido', 'unknown')}`, node('div', text, 'index-state')));
    if (state.needs_update === true) block.append(node('p', t('El código ha cambiado desde la indexación. Revisa el estado del índice.', 'The code has changed since indexing. Check the index status.'), 'limitations warning'));
  }
}
$('repo').addEventListener('change', describe);
$('clear').addEventListener('click', () => {
  storeSession('');
  $('messages').replaceChildren(node('p', t('Conversación vacía. Escribe una nueva pregunta.', 'Conversation cleared. Ask a new question.'), 'limitations'));
  $('question').focus();
});
$('form').addEventListener('submit', async event => {
  event.preventDefault();
  const question = $('question').value.trim();
  if (pending || !question || !$('repo').value) return;
  pending = true;
  ['send', 'repo', 'remote', 'clear', 'session'].forEach(id => $(id).disabled = true);
  message(`${t('Tú ·', 'You ·')} ${$('repo').value}`, 'question').append(node('div', question, 'question-text'));
  $('question').value = '';
  const indicator = node('div', undefined, 'message pending-answer');
  indicator.setAttribute('aria-hidden', 'true');
  indicator.append(
    node('span', t('Preparando la respuesta…', 'Preparing your answer…')),
    node('div', undefined, 'pending-track')
  );
  $('messages').append(indicator);
  $('status').textContent = t('CodeTrace está buscando evidencias y consultando el modelo…', 'CodeTrace is retrieving evidence and querying the model…');
  scroll();
  let focus = 'question';
  try {
    const result = await api('/api/answer', {
      method: 'POST',
      body: JSON.stringify({
        question, repo: $('repo').value, allow_remote: $('remote').checked,
        session: $('session').value.trim() || 'new'
      })
    });
    if (result.session) storeSession(result.session);
    showAnswer(result);
    $('status').textContent = t('Consulta completada', 'Request completed');
  } catch (error) {
    $('question').value = question;
    if (Array.isArray(error.candidates) && error.candidates.length > 1) {
      const block = message('CodeTrace');
      const list = node('ul', undefined, 'limitations');
      error.candidates.forEach(name => {
        const description = repositories.find(repo => repo.name === name)?.description;
        list.append(node('li', description ? `${name} · ${description}` : name));
      });
      block.append(node('p', error.message), list);
      $('status').textContent = t('Selecciona un repositorio para volver a enviar la pregunta', 'Select a repository to submit the question again');
      focus = 'repo';
    } else {
      message(t('No se pudo responder', 'Could not answer')).append(node('div', error.message, 'error'));
      $('status').textContent = t('Puedes corregir la configuración y volver a intentarlo', 'Check the configuration and try again');
    }
  } finally {
    indicator.remove();
    pending = false;
    ['send', 'repo', 'remote', 'clear', 'session'].forEach(id => $(id).disabled = false);
    scroll();
    $(focus).focus();
  }
});
api('/api/repositories').then(data => {
  repositories = data.repositories;
  $('repo').replaceChildren(...repositories.map(repo => {
    const option = node('option', repo.name); option.value = repo.name; return option;
  }));
  if (repositories.some(r => r.name === data.default_repository)) $('repo').value = data.default_repository;
  describe();
  $('repo').disabled = $('send').disabled = false;
  $('status').textContent = t('Listo para consultar', 'Ready for questions');
}).catch(error => { $('status').textContent = error.message; });
