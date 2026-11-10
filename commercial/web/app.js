'use strict';
const $ = id => document.getElementById(id);
const state = {workspaces: [], directoryCursor: null, tenant: null, org: null, context: null,
  organisations: [], orgCursor: null, notes: [], noteCursor: null, evidence: [], evidenceCursor: null, epoch: 0, pending: {}, saving: false};
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
  constructor(status, code) { super(code); this.status = status; this.code = code; }
}
async function request(url, options = {}) {
  const response = await fetch(url, {credentials: 'same-origin', redirect: 'error',
    signal: AbortSignal.timeout(15000), ...options});
  if (!response.ok) {
    let code = 'request_failed';
    try { if ((await response.json()).error?.code === 'session_changed') code = 'session_changed'; } catch (_) { /* Generic error on invalid responses. */ }
    throw new RequestError(response.status, code);
  }
  const document = await response.json();
  if (!document || !('data' in document)) throw new RequestError(502, 'invalid_response');
  return document.data;
}
function clearMessage() { show('error', false); show('notice', false); }
function tell(text) { $('notice').textContent = text; show('notice', true); }
function errorMessage(error) {
  if (error.code === 'session_changed') return 'Sign in with the same account that started this save, then retry. If your provider shows another account, use its account-change or restart option. Your pending work is still in this tab.';
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
  if (state.org && ($('note-body').value.trim() || $('evidence-file').files.length)) {
    tell('Save or clear the note or selected file before leaving this organisation.'); workspaceOptions(); return;
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
      show('evidence-panel', context.evidence_access); show('evidence-form', context.can_upload_evidence);
      if (context.evidence_access) {
        const evidence = await request(`${apiBase()}/organisations/${organisation}/evidence`);
        if (epoch !== state.epoch) return;
        state.evidence = evidence.items; state.evidenceCursor = evidence.next_cursor; renderEvidence();
      }
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
function renderEvidence() {
  const list = $('evidence-list'); list.replaceChildren();
  const formats = {'application/pdf':'PDF', 'image/jpeg':'JPEG image', 'image/png':'PNG image', 'text/csv':'CSV'};
  for (const item of state.evidence) {
    const row = element('li');
    row.append(element('strong', `${formats[item.media_type] || 'Document'} · ${item.byte_size.toLocaleString('en-GB')} bytes`),
      element('p', item.stored_at ? 'Stored in quarantine' : 'Upload incomplete — upload the same file again to finish'),
      element('small', `Evidence ${item.id} · ${dateText(item.registered_at)}`));
    const button = element('button', 'View receipt', 'button secondary');
    button.type = 'button'; button.setAttribute('aria-expanded', 'false');
    const receipt = element('div', undefined, 'evidence-receipt');
    receipt.id = `receipt-${item.id}`; receipt.hidden = true;
    receipt.setAttribute('role', 'region'); receipt.setAttribute('aria-label', `Evidence receipt ${item.id}`);
    button.setAttribute('aria-controls', receipt.id);
    button.addEventListener('click', () => viewReceipt(item, button, receipt));
    row.append(button, receipt); list.append(row);
  }
  $('evidence-count').textContent = `${state.evidence.length} loaded`;
  show('empty-evidence', state.evidence.length === 0); show('more-evidence', Boolean(state.evidenceCursor));
}
async function viewReceipt(item, button, panel) {
  if (!panel.hidden) {
    panel.hidden = true; panel.replaceChildren(); button.setAttribute('aria-expanded', 'false');
    button.textContent = 'View receipt'; return;
  }
  const epoch = state.epoch;
  const url = `${apiBase()}/organisations/${state.org}/evidence/${item.id}`;
  panel.hidden = false; panel.replaceChildren(element('p', 'Loading receipt…'));
  panel.setAttribute('aria-busy', 'true'); button.setAttribute('aria-expanded', 'true'); button.disabled = true;
  try {
    const receipt = await request(url);
    if (epoch !== state.epoch || !panel.isConnected) return;
    const fields = element('dl');
    for (const [label, value] of [
      ['Evidence ID', receipt.id], ['Organisation ID', receipt.organisation_id],
      ['Declared format', receipt.media_type], ['Byte count', receipt.byte_size.toLocaleString('en-GB')],
      ['SHA-256 of original bytes', receipt.content_sha256],
      ['Registered', dateText(receipt.registered_at)],
      ['Quarantine storage', receipt.stored_at ? dateText(receipt.stored_at) : 'Incomplete — upload the same file again to finish']
    ]) fields.append(element('dt', label), element('dd', value));
    panel.replaceChildren(fields, element('p', 'This fingerprint identifies the uploaded bytes. It does not establish a valid file, malware scan, extracted figures, accounting entry or filing approval.'));
    button.textContent = 'Hide receipt';
  } catch (error) {
    if (epoch !== state.epoch || !panel.isConnected) return;
    const message = element('p', errorMessage(error) + ' Close and reopen this receipt to try again.');
    message.setAttribute('role', 'alert'); panel.replaceChildren(message); button.textContent = 'Close receipt';
    if (error.status === 401 || error.status === 403) { panel.replaceChildren(); fail(error); }
  } finally {
    panel.setAttribute('aria-busy', 'false'); button.disabled = false;
  }
}
async function loadMore(kind, button) {
  const epoch = state.epoch; button.disabled = true; clearMessage();
  try {
    if (kind === 'workspaces') await directory(true);
    else {
      const cursor = kind === 'organisations' ? state.orgCursor : kind === 'evidence' ? state.evidenceCursor : state.noteCursor;
      const url = kind === 'organisations' ? `${apiBase()}/organisations` : `${apiBase()}/organisations/${state.org}/${kind === 'evidence' ? 'evidence' : 'notes'}`;
      const page = await request(`${url}?after=${cursor}`);
      if (epoch !== state.epoch) return;
      if (kind === 'organisations') { state.organisations.push(...page.items); state.orgCursor = page.next_cursor; renderOrganisations(); }
      else if (kind === 'evidence') { for (const item of page.items) if (!state.evidence.some(old => old.id === item.id)) state.evidence.push(item); state.evidenceCursor = page.next_cursor; renderEvidence(); }
      else { for (const note of page.items) if (!state.notes.some(item => item.id === note.id)) state.notes.push(note);
        state.noteCursor = page.next_cursor; renderNotes(); }
    }
  } catch (error) { if (epoch === state.epoch) fail(error); }
  finally { button.disabled = false; }
}
async function save(kind, url, payload, input, button) {
  if (state.saving) return;
  if (Object.keys(state.pending).some(key => key !== kind)) { tell('Confirm the pending save before starting another.'); return; }
  const pending = state.pending[kind] || {url, payload, key: crypto.randomUUID(), actor: state.context.actor_id};
  state.pending[kind] = pending; state.saving = true;
  input.disabled = true; button.disabled = true; clearMessage(); show('dialog-error', false); show('dialog-reauth', false);
  try {
    const record = await request(pending.url, {method: 'POST', headers: {'Content-Type': 'application/json',
      'Idempotency-Key': pending.key, 'X-OmniXAT-Expected-Actor': pending.actor}, body: JSON.stringify(pending.payload)});
    delete state.pending[kind]; input.value = ''; input.disabled = false;
    if (kind === 'organisation') {
      $('organisation-dialog').close(); state.saving = false;
      navigate(`${tenantPath(state.tenant)}/organisations/${record.id}`);
    } else {
      if (!state.notes.some(note => note.id === record.id)) state.notes.unshift(record);
      renderNotes(); tell('Note saved.');
    }
  } catch (error) {
    const definiteRejection = error.code !== 'session_changed' && [400,403,404,409,413,415,422].includes(error.status);
    if (definiteRejection) { delete state.pending[kind]; input.disabled = false; }
    const message = errorMessage(error) + (definiteRejection ? '' : ' Use Retry save to confirm this same request before editing.');
    if (kind === 'organisation') { $('dialog-error').textContent = message; show('dialog-error', true); show('dialog-reauth', error.status === 401 || error.code === 'session_changed'); }
    else { $('error-message').textContent = message; show('error', true); show('retry', false); show('reauth', error.status === 401 || error.code === 'session_changed'); }
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
for (const kind of ['workspaces','organisations','notes','evidence']) $('more-' + kind).addEventListener('click', event => loadMore(kind, event.currentTarget));
$('clear-evidence').addEventListener('click', () => {
  if (!state.saving && !state.pending.evidence) { $('evidence-file').value = ''; $('evidence-type').value = ''; }
});
$('evidence-file').addEventListener('change', () => {
  const file = $('evidence-file').files[0];
  $('evidence-type').value = file && ['application/pdf','image/jpeg','image/png','text/csv'].includes(file.type) ? file.type : '';
});
$('evidence-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (state.saving || Object.keys(state.pending).some(key => key !== 'evidence')) return;
  const input = $('evidence-file'), format = $('evidence-type'), button = $('upload-evidence');
  const pending = state.pending.evidence || {file:input.files[0], media:format.value,
    url:`${apiBase()}/organisations/${state.org}/evidence`, actor:state.context.actor_id};
  if (!pending.file || !pending.file.size || pending.file.size > 20 * 1024 * 1024) {
    tell('Choose a non-empty file no larger than 20 MiB.'); return;
  }
  state.pending.evidence = pending; state.saving = true;
  input.disabled = true; format.disabled = true; $('clear-evidence').disabled = true; button.disabled = true; clearMessage();
  try {
    const receipt = await request(pending.url, {method:'POST', headers:{'Content-Type':pending.media, 'X-OmniXAT-Expected-Actor':pending.actor},
      body:pending.file, signal:AbortSignal.timeout(30000)});
    delete state.pending.evidence; input.value = ''; format.value = '';
    const item = receipt;
    const old = state.evidence.findIndex(row => row.id === item.id);
    if (old >= 0) state.evidence[old] = {...state.evidence[old], ...item}; else state.evidence.unshift(item);
    renderEvidence(); tell('Evidence stored in quarantine. Processing is not enabled here.');
  } catch (error) {
    const definite = error.code !== 'session_changed' && [400,403,404,409,413,415,422].includes(error.status);
    if (definite) delete state.pending.evidence;
    const uploadMessage = error.code === 'session_changed' ? errorMessage(error) : error.status === 413 ? 'The upload exceeds the server size limit. Choose a file no larger than 20 MiB.'
      : error.status === 415 ? 'Choose PDF, JPEG, PNG or CSV and select the matching document format.'
      : error.status === 409 ? 'This upload conflicts with an existing evidence record. Check the format and saved evidence before trying again.'
      : errorMessage(error);
    $('error-message').textContent = uploadMessage + (definite ? '' : ' Use Retry upload to confirm the same file.');
    show('error',true); show('retry',false); show('reauth',error.status===401 || error.code === 'session_changed');
    if (error.status===403) fail(error);
  } finally {
    state.saving = false; button.disabled = false;
    input.disabled = format.disabled = $('clear-evidence').disabled = Boolean(state.pending.evidence);
    button.textContent = state.pending.evidence ? 'Retry upload' : 'Upload to quarantine';
    $('workspace-select').disabled = Boolean(Object.keys(state.pending).length);
  }
});
$('back').addEventListener('click', () => navigate(tenantPath(state.tenant)));
$('retry').addEventListener('click', () => boot());
document.addEventListener('click', event => {
  const link = event.target.closest('a[href^="/app"]');
  if (link && !event.ctrlKey && !event.metaKey && event.button === 0) { event.preventDefault(); navigate(link.getAttribute('href')); }
});
window.addEventListener('popstate', () => {
  if (state.tenant && (state.saving || Object.keys(state.pending).length || $('note-body').value.trim() || $('evidence-file').files.length)) {
    history.pushState({}, '', tenantPath(state.tenant) + (state.org ? `/organisations/${state.org}` : ''));
    tell('Save or clear the note or selected file before leaving this organisation.');
  } else loadRoute();
});
window.addEventListener('beforeunload', event => { if (state.saving || Object.keys(state.pending).length || $('note-body').value.trim() || $('evidence-file').files.length) { event.preventDefault(); event.returnValue = ''; } });
async function boot() {
  clearMessage(); show('loading', true); show('content', false);
  try { await directory(); await loadRoute(); }
  catch (error) { show('loading', false); fail(error); }
}
async function checkRecoveredSession() {
  show('recovery-ready', false); show('recovery-actions', false); $('recovery-check').disabled = true;
  $('recovery-status').textContent = 'Checking your sign-in…';
  try {
    await request('/v1/workspaces?limit=1');
    $('recovery-status').textContent = 'Sign-in checked. Return to your original tab.';
    show('recovery-ready', true);
  } catch (error) {
    $('recovery-status').textContent = errorMessage(error);
    show('recovery-actions', true);
  } finally { $('recovery-check').disabled = false; }
}
$('recovery-check').addEventListener('click', checkRecoveredSession);
if (location.pathname === '/app/reauthenticated') {
  document.title = 'Return to your work · OmniXAT';
  document.querySelector('.skip').href = '#recovery-main'; show('session-recovery', true); checkRecoveredSession();
}
else if (location.pathname === '/') { show('welcome', true); document.querySelector('.skip').href = '#welcome-main'; }
else { show('workspace-app', true); boot(); }
