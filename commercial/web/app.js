'use strict';
const $ = id => document.getElementById(id);
const state = {workspaces: [], directoryCursor: null, tenant: null, org: null, context: null,
  organisations: [], orgCursor: null, notes: [], noteCursor: null, epoch: 0, pending: {}, saving: false};
const uuidPattern = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
const routePattern = new RegExp(`^/app/workspaces/(${uuidPattern})(?:/organisations/(${uuidPattern}))?$`);
const tenantPath = tenant => `/app/workspaces/${tenant}`;
const apiBase = () => `/v1/workspaces/${state.tenant}`;
const sentence = text => text.charAt(0).toUpperCase() + text.slice(1);
function show(id, visible) { $(id).hidden = !visible; }
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
class RequestError extends Error {
  constructor(status, code) { super(code); this.status = status; }
}
async function request(url, options = {}) {
  const response = await fetch(url, {credentials: 'same-origin', redirect: 'error',
    signal: AbortSignal.timeout(15000), ...options});
  if (!response.ok) throw new RequestError(response.status, 'request_failed');
  const document = await response.json();
  if (!document || !('data' in document)) throw new RequestError(502, 'invalid_response');
  return document.data;
}
function clearMessage() { show('error', false); show('notice', false); }
function tell(text) { $('notice').textContent = text; show('notice', true); }
function errorMessage(error) {
  if (error.status === 401) return 'Your session has ended. Sign in again to continue.';
  if (error.status === 403) return 'Your access has changed, or this action is not permitted. Sign in again or contact your workspace owner.';
  if (error.status === 404) return 'This record is unavailable in this workspace.';
  if (error.status === 409) return 'This save conflicts with an earlier request. Reload the records before trying a new save.';
  if (error.status === 422) return 'Check the information you entered and try again.';
  return 'We could not confirm the request. Check your connection and try again.';
}
function fail(error) {
  $('error-message').textContent = errorMessage(error); show('error', true);
  const denied = error.status === 401 || error.status === 403;
  show('reauth', denied); show('retry', !denied);
  if (denied) { show('content', false); $('organisation-dialog').close(); state.context = null; }
}
function dateText(value) {
  if (!value) return 'Saved note';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Saved note' : new Intl.DateTimeFormat('en-GB', {dateStyle: 'medium', timeStyle: 'short'}).format(date);
}
function workspaceOptions() {
  const select = $('workspace-select'); select.replaceChildren();
  for (const workspace of state.workspaces) {
    const option = element('option', workspace.display_name); option.value = workspace.id;
    select.append(option);
  }
  if (state.tenant) select.value = state.tenant;
  show('more-workspaces', Boolean(state.directoryCursor));
}
async function directory(more = false) {
  const page = await request('/v1/workspaces' + (more && state.directoryCursor ? `?after=${state.directoryCursor}` : ''));
  const combined = more ? [...state.workspaces, ...page.items] : page.items;
  state.workspaces = [...new Map(combined.map(item => [item.id, item])).values()];
  state.directoryCursor = page.next_cursor; workspaceOptions();
}
function navigate(path) {
  if (state.saving || Object.keys(state.pending).length) {
    tell('Please confirm the pending save before changing records.'); workspaceOptions(); return;
  }
  if (state.org && $('note-body').value.trim()) {
    tell('Save or clear the note before leaving this organisation.'); workspaceOptions(); return;
  }
  history.pushState({}, '', path); loadRoute();
}
async function loadRoute() {
  const epoch = ++state.epoch;
  clearMessage(); show('loading', true); show('content', false);
  $('main').setAttribute('aria-busy', 'true');
  try {
    let match = location.pathname.match(routePattern);
    if (location.pathname === '/app') {
      if (!state.workspaces.length) {
        $('loading').textContent = 'You do not have an active workspace membership. Ask your workspace owner for access.';
        return;
      }
      history.replaceState({}, '', tenantPath(state.workspaces[0].id));
      match = location.pathname.match(routePattern);
    }
    if (!match) throw new RequestError(404, 'not_found');
    const tenant = match[1], organisation = match[2] || null;
    const context = await request(`/v1/workspaces/${tenant}/context`);
    if (epoch !== state.epoch) return;
    state.tenant = tenant; state.org = organisation; state.context = context;
    if (!state.workspaces.some(item => item.id === tenant)) state.workspaces.push(context);
    workspaceOptions();
    $('workspace-name').textContent = context.display_name;
    $('role').textContent = `${sentence(context.role)} access`;
    $('access-label').textContent = context.can_write ? 'Can edit' : 'Read only';
    $('overview-link').href = tenantPath(tenant); $('organisations-link').href = tenantPath(tenant);
    $('overview-link').classList.toggle('active', !organisation);
    $('organisations-link').classList.toggle('active', Boolean(organisation));
    $('breadcrumb').textContent = organisation ? 'Workspace / Organisations / Notes' : 'Workspace / Overview';
    show('add-organisation', context.can_write); show('note-form', context.can_write);
    if (organisation) {
      const [record, page] = await Promise.all([request(`${apiBase()}/organisations/${organisation}`),
        request(`${apiBase()}/organisations/${organisation}/notes`)]);
      if (epoch !== state.epoch) return;
      $('organisation-name').textContent = record.display_name;
      document.title = `${record.display_name} · OmniXAT`;
      state.notes = page.items; state.noteCursor = page.next_cursor; renderNotes();
    } else {
      const page = await request(`${apiBase()}/organisations`);
      if (epoch !== state.epoch) return;
      state.organisations = page.items; state.orgCursor = page.next_cursor;
      $('filter').value = ''; renderOrganisations(); document.title = `${context.display_name} · OmniXAT`;
    }
    show('overview', !organisation); show('organisation-detail', Boolean(organisation));
    show('loading', false); show('content', true);
  } catch (error) { if (epoch === state.epoch) { show('loading', false); fail(error); } }
  finally { if (epoch === state.epoch) $('main').setAttribute('aria-busy', 'false'); }
}
function renderOrganisations() {
  $('organisation-count').textContent = state.organisations.length;
  const list = $('organisations'); list.replaceChildren();
  const filter = $('filter').value.toLocaleLowerCase('en-GB');
  const visible = state.organisations.filter(item => item.display_name.toLocaleLowerCase('en-GB').includes(filter));
  for (const organisation of visible) {
    const item = element('li'); const link = element('a');
    link.href = `${tenantPath(state.tenant)}/organisations/${organisation.id}`;
    const initials = organisation.display_name.trim().split(/\s+/).slice(0,2).map(word => word[0]).join('').toUpperCase();
    const info = element('span', undefined, 'org-info');
    info.append(element('strong', organisation.display_name), element('small', 'View notes and records'));
    link.append(element('span', initials, 'org-avatar'), info, element('span', '↗', 'arrow'));
    item.append(link); list.append(item);
  }
  show('empty-organisations', state.organisations.length === 0);
  show('no-results', state.organisations.length > 0 && visible.length === 0);
  show('more-organisations', Boolean(state.orgCursor));
}
function renderNotes() {
  const list = $('notes'); list.replaceChildren();
  for (const note of state.notes) {
    const article = element('article');
    const time = element('time', dateText(note.created_at));
    if (note.created_at) time.dateTime = note.created_at;
    article.append(time, element('p', note.body)); list.append(article);
  }
  $('note-count').textContent = `${state.notes.length} loaded`;
  show('empty-notes', state.notes.length === 0); show('more-notes', Boolean(state.noteCursor));
}
async function loadMore(kind, button) {
  const epoch = state.epoch; button.disabled = true; clearMessage();
  try {
    if (kind === 'workspaces') await directory(true);
    else {
      const cursor = kind === 'organisations' ? state.orgCursor : state.noteCursor;
      const url = kind === 'organisations' ? `${apiBase()}/organisations` : `${apiBase()}/organisations/${state.org}/notes`;
      const page = await request(`${url}?after=${cursor}`);
      if (epoch !== state.epoch) return;
      if (kind === 'organisations') { state.organisations.push(...page.items); state.orgCursor = page.next_cursor; renderOrganisations(); }
      else { for (const note of page.items) if (!state.notes.some(item => item.id === note.id)) state.notes.push(note);
        state.noteCursor = page.next_cursor; renderNotes(); }
    }
  } catch (error) { if (epoch === state.epoch) fail(error); }
  finally { button.disabled = false; }
}
async function save(kind, url, payload, input, button) {
  if (state.saving) return;
  const pending = state.pending[kind] || {url, payload, key: crypto.randomUUID()};
  state.pending[kind] = pending; state.saving = true;
  input.disabled = true; button.disabled = true; clearMessage(); show('dialog-error', false); show('dialog-reauth', false);
  try {
    const record = await request(pending.url, {method: 'POST', headers: {'Content-Type': 'application/json',
      'Idempotency-Key': pending.key}, body: JSON.stringify(pending.payload)});
    delete state.pending[kind]; input.value = ''; input.disabled = false;
    if (kind === 'organisation') {
      $('organisation-dialog').close(); state.saving = false;
      navigate(`${tenantPath(state.tenant)}/organisations/${record.id}`);
    } else {
      if (!state.notes.some(note => note.id === record.id)) state.notes.unshift(record);
      renderNotes(); tell('Note saved.');
    }
  } catch (error) {
    const definiteRejection = [400,403,404,409,413,415,422].includes(error.status);
    if (definiteRejection) { delete state.pending[kind]; input.disabled = false; }
    const message = errorMessage(error) + (definiteRejection ? '' : ' Use Retry save to confirm this same request before editing.');
    if (kind === 'organisation') { $('dialog-error').textContent = message; show('dialog-error', true); show('dialog-reauth', error.status === 401); }
    else { $('error-message').textContent = message; show('error', true); show('retry', false); show('reauth', error.status === 401); }
    if (error.status === 403) fail(error);
  } finally {
    state.saving = false; button.disabled = false;
    button.textContent = state.pending[kind] ? 'Retry save' : kind === 'organisation' ? 'Create organisation' : 'Save note';
    $('workspace-select').disabled = Boolean(Object.keys(state.pending).length);
  }
}
function closeDialog() {
  if (state.saving || state.pending.organisation) return;
  $('organisation-dialog').close();
}
$('organisation-form').addEventListener('submit', event => {
  event.preventDefault(); const input = $('organisation-display-name');
  if (!input.value.trim() && !state.pending.organisation) return;
  save('organisation', `${apiBase()}/organisations`, {display_name: input.value}, input, $('save-organisation'));
});
$('note-form').addEventListener('submit', event => {
  event.preventDefault(); const input = $('note-body');
  if (!input.value.trim() && !state.pending.note) return;
  save('note', `${apiBase()}/organisations/${state.org}/notes`, {body: input.value}, input, $('save-note'));
});
$('add-organisation').addEventListener('click', () => {
  if (Object.keys(state.pending).length) { tell('Confirm the pending save before creating another record.'); return; }
  show('dialog-error', false); show('dialog-reauth', false); $('organisation-dialog').showModal(); $('organisation-display-name').focus();
});
$('close-dialog').addEventListener('click', closeDialog); $('cancel-dialog').addEventListener('click', closeDialog);
$('organisation-dialog').addEventListener('cancel', event => { if (state.saving || state.pending.organisation) event.preventDefault(); });
$('workspace-select').addEventListener('change', () => navigate(tenantPath($('workspace-select').value)));
$('filter').addEventListener('input', renderOrganisations);
for (const kind of ['workspaces','organisations','notes']) $('more-' + kind).addEventListener('click', event => loadMore(kind, event.currentTarget));
$('back').addEventListener('click', () => navigate(tenantPath(state.tenant)));
$('retry').addEventListener('click', () => boot());
document.addEventListener('click', event => {
  const link = event.target.closest('a[href^="/app"]');
  if (link && !event.ctrlKey && !event.metaKey && event.button === 0) { event.preventDefault(); navigate(link.getAttribute('href')); }
});
window.addEventListener('popstate', () => {
  if (state.tenant && (state.saving || Object.keys(state.pending).length || $('note-body').value.trim())) {
    history.pushState({}, '', tenantPath(state.tenant) + (state.org ? `/organisations/${state.org}` : ''));
    tell('Save or clear the note before leaving this organisation.');
  } else loadRoute();
});
window.addEventListener('beforeunload', event => { if (state.saving || Object.keys(state.pending).length || $('note-body').value.trim()) { event.preventDefault(); event.returnValue = ''; } });
async function boot() {
  clearMessage(); show('loading', true); show('content', false);
  try { await directory(); await loadRoute(); }
  catch (error) { show('loading', false); fail(error); }
}
if (location.pathname === '/') { show('welcome', true); document.querySelector('.skip').href = '#welcome-main'; }
else { show('workspace-app', true); boot(); }
