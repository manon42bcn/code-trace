'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="chat-token"]').content;
let repositories = [];
let pending = false;
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = String(text);
  if (className) el.className = className;
  return el;
}
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'X-CodeRAG-Token': token, 'Content-Type': 'application/json'}, cache: 'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'No se pudo completar la consulta.');
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
  if (answer.refusal) block.append(node('p', 'El modelo indica que no dispone de evidencia suficiente.', 'limitations'));
  const items = result.context?.items || [];
  const cited = new Set((answer.citations || []).map(c => c.chunk_id));
  if (items.length) {
    const sources = node('div');
    items.forEach((item, i) => {
      const c = item.citation || {};
      const body = node('div');
      body.append(node('p', `${c.symbol || ''} · ${item.certainty || 'static_candidate'} · ${cited.has(c.chunk_id) ? 'Citada' : 'Solo contexto'}`, 'metadata'));
      if (item.content_truncated) body.append(node('p', 'Fragmento truncado; las líneas corresponden al chunk completo.', 'limitations'));
      body.append(node('pre', item.content || ''));
      sources.append(details(`${i + 1}. ${c.path}:${c.start_line}–${c.end_line}`, body));
    });
    block.append(details(`Evidencias (${items.length})`, sources));
  }
  const flow = result.context?.code_flow;
  if (flow) {
    const body = node('div');
    body.append(node('p', `Entradas candidatas: ${flow.matching_entry_candidates}. Se muestran solo relaciones entre evidencias incluidas.`, 'limitations'));
    const labels = new Map(items.map(item => [item.citation.chunk_id, `${item.citation.symbol || item.citation.path} (${item.citation.path}:${item.citation.start_line}–${item.citation.end_line})`]));
    const list = node('ul', undefined, 'limitations');
    flow.entries.forEach(entry => list.append(node('li', `Entrada candidata: ${labels.get(entry.chunk_id)} · ${(entry.methods || []).join('/')} ${entry.route || ''}`)));
    flow.edges.forEach(edge => list.append(node('li', `${labels.get(edge.source)} → ${labels.get(edge.target)}`)));
    body.append(list);
    if (flow.ambiguous_entry) body.append(node('p', 'Hay varias entradas candidatas. Concreta método/ruta o símbolo inicial.', 'limitations warning'));
    body.append(node('p', 'Llamadas estáticas, no orden de ejecución. Middleware, dependencias y montaje del router no resueltos.', 'limitations'));
    block.append(details('Flujo estático del código', body));
  }
  const limitations = [...new Set([...(answer.limitations || []), ...items.flatMap(i => i.limitations || [])])];
  if (limitations.length) {
    const list = node('ul', undefined, 'limitations');
    limitations.forEach(text => list.append(node('li', text)));
    block.append(details('Limitaciones', list));
  }
  const state = result.index_state;
  if (state) {
    const git = state.git || {};
    const update = state.needs_update === true ? 'Sí' : state.needs_update === false ? 'No' : 'Sin verificar';
    const text = `Fuentes: ${state.source?.status || 'desconocido'}\nActualización necesaria: ${update}\nCommit indexado: ${git.indexed?.commit || 'desconocido'}\nCommit actual: ${git.current?.commit || 'desconocido'}\n${git.message || ''}${state.needs_update !== false && state.remedy ? '\n' + state.remedy : ''}`;
    block.append(details(`Estado del índice · ${state.source?.status || 'desconocido'}`, node('div', text, 'index-state')));
    if (state.needs_update === true) block.append(node('p', 'El código ha cambiado desde la indexación. Revisa el estado del índice.', 'limitations warning'));
  }
}
$('repo').addEventListener('change', describe);
$('clear').addEventListener('click', () => {
  $('messages').replaceChildren(node('p', 'Conversación vacía. Escribe una nueva pregunta.', 'limitations'));
  $('question').focus();
});
$('form').addEventListener('submit', async event => {
  event.preventDefault();
  const question = $('question').value.trim();
  if (pending || !question || !$('repo').value) return;
  pending = true;
  ['send', 'repo', 'remote', 'clear'].forEach(id => $(id).disabled = true);
  message(`Tú · ${$('repo').value}`, 'question').append(node('div', question, 'question-text'));
  $('question').value = '';
  $('status').textContent = 'CodeTrace está buscando evidencias y consultando el modelo…';
  scroll();
  try {
    showAnswer(await api('/api/answer', {method: 'POST', body: JSON.stringify({question, repo: $('repo').value, allow_remote: $('remote').checked})}));
    $('status').textContent = 'Consulta completada';
  } catch (error) {
    message('No se pudo responder').append(node('div', error.message, 'error'));
    $('question').value = question;
    $('status').textContent = 'Puedes corregir la configuración y volver a intentarlo';
  } finally {
    pending = false;
    ['send', 'repo', 'remote', 'clear'].forEach(id => $(id).disabled = false);
    scroll();
    $('question').focus();
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
  $('status').textContent = 'Listo para consultar';
}).catch(error => { $('status').textContent = error.message; });
