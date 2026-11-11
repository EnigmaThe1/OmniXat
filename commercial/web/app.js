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
    try {
      const received = (await response.json()).error?.code;
      if (['session_changed', 'scan_request_unavailable', 'scan_reauthorisation_unavailable', 'answer_conflict', 'extraction_request_conflict', 'extraction_cancellation_unavailable', 'extraction_reauthorisation_unavailable', 'expense_preparation_conflict', 'funding_conflict'].includes(received)) code = received;
    } catch (_) { /* Generic error on invalid responses. */ }
    throw new RequestError(response.status, code);
  }
  const document = await response.json();
  if (!document || !('data' in document)) throw new RequestError(502, 'invalid_response');
  return document.data;
}
function clearMessage() { show('error', false); show('notice', false); }
function tell(text) { $('notice').textContent = text; show('notice', true); }
function errorMessage(error) {
  if (error.code === 'extraction_reauthorisation_unavailable') return 'This cancellation, source or replacement attempt is unavailable. Refresh requests before starting another attempt.';
  if (error.code === 'extraction_cancellation_unavailable') return 'A result is already recorded for this job. Cancellation cannot undo it. Refresh requests and inspect the candidates.';
  if (error.code === 'extraction_request_conflict') return 'This extraction job belongs to another recorded plan. Inspect the records before starting a new request.';
  if (error.code === 'answer_conflict') return 'An answer is already recorded. Refresh candidates to inspect it; recorded answers cannot be overwritten here.';
  if (error.code === 'scan_reauthorisation_unavailable') return 'This cancellation has changed or is unavailable. Refresh scan status before requesting again.';
  if (error.code === 'scan_request_unavailable') return 'A scan cannot be requested yet. The upload must be complete and an operator must configure the scan policy.';
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
  show('reauth', denied); show('retry', !denied || Boolean(state.pending.csvAnswer || state.pending.csvRequest || state.pending.csvCancellation || state.pending.expenseDraft || state.pending.expenseFunding));
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
  if (document.querySelector('.csv-answer[data-dirty="true"], .csv-request[data-dirty="true"], .expense-preparation[data-dirty="true"], .funding-selection[data-dirty="true"]')) { tell('Save or clear the answer before leaving this organisation.'); workspaceOptions(); return; }
  if (state.org && ($('note-body').value.trim() || $('evidence-file').files.length)) {
    tell('Save or clear the note, selected file or answer before leaving this organisation.'); workspaceOptions(); return;
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
    row.append(button, receipt);
    if (state.context.csv_review_access && item.media_type === 'text/csv') {
      const reviewButton = element('button', 'Inspect CSV candidates', 'button secondary'); reviewButton.type = 'button';
      const reviewPanel = element('div', undefined, 'evidence-receipt'); reviewPanel.hidden = true;
      reviewPanel.id = `csv-review-${item.id}`; reviewPanel.setAttribute('role', 'region');
      reviewPanel.setAttribute('aria-label', `CSV candidates ${item.id}`);
      reviewButton.setAttribute('aria-controls', reviewPanel.id); reviewButton.setAttribute('aria-expanded', 'false');
      reviewButton.addEventListener('click', () => viewCSVCandidates(item, reviewButton, reviewPanel));
      if (state.pending.csvAnswer?.evidence === item.id || state.pending.expenseDraft?.evidence === item.id) queueMicrotask(() => viewCSVCandidates(item, reviewButton, reviewPanel));
      row.append(reviewButton, reviewPanel);
    }
    if (state.context.expense_draft_access && item.media_type === 'text/csv') {
      const inspect = element('button', 'Inspect saved expense drafts', 'button secondary'); inspect.type = 'button';
      const panel = element('div', undefined, 'evidence-receipt'); panel.hidden = true;
      panel.id = `expense-drafts-${item.id}`; panel.setAttribute('role', 'region');
      panel.setAttribute('aria-label', `Saved expense drafts ${item.id}`);
      inspect.setAttribute('aria-controls', panel.id); inspect.setAttribute('aria-expanded', 'false');
      inspect.addEventListener('click', () => viewExpenseDrafts(item, inspect, panel));
      row.append(inspect, panel);
      if (state.pending.expenseFunding?.evidence === item.id) queueMicrotask(() => viewExpenseDrafts(item,inspect,panel,state.pending.expenseFunding.draft));
    }
    if (state.context.csv_request_status_access && item.media_type === 'text/csv') {
      const inspect = element('button', 'Inspect extraction requests', 'button secondary'); inspect.type = 'button';
      const requests = element('div', undefined, 'evidence-receipt'); requests.hidden = true;
      requests.id = `csv-requests-${item.id}`; requests.setAttribute('role', 'region');
      requests.setAttribute('aria-label', `CSV extraction requests ${item.id}`);
      inspect.setAttribute('aria-controls', requests.id); inspect.setAttribute('aria-expanded', 'false');
      inspect.addEventListener('click', () => viewCSVRequests(item, inspect, requests));
      row.append(inspect, requests);
      if (state.pending.csvCancellation?.evidence === item.id) queueMicrotask(() => viewCSVRequests(item, inspect, requests));
    }
    if ((state.context.can_request_csv || state.pending.csvRequest?.evidence === item.id) && item.media_type === 'text/csv') row.append(csvRequestForm(item));
    if (state.context.scan_status_access) {
      const scanButton = element('button', 'Check scan status', 'button secondary');
      scanButton.type = 'button';
      const scanPanel = element('div', undefined, 'evidence-receipt');
      scanPanel.id = `scan-status-${item.id}`; scanPanel.hidden = true;
      scanPanel.setAttribute('role', 'region'); scanPanel.setAttribute('aria-label', `Scan status ${item.id}`);
      scanButton.setAttribute('aria-controls', scanPanel.id); scanButton.setAttribute('aria-expanded', 'false');
      scanButton.addEventListener('click', () => viewScanStatus(item, scanButton, scanPanel));
      row.append(scanButton, scanPanel);
    }
    list.append(row);
  }
  $('evidence-count').textContent = `${state.evidence.length} loaded`;
  show('empty-evidence', state.evidence.length === 0); show('more-evidence', Boolean(state.evidenceCursor));
}
async function viewCSVRequests(item, button, panel) {
  const epoch = state.epoch;
  panel.hidden = false; panel.replaceChildren(element('p', 'Loading extraction requests…'));
  panel.setAttribute('aria-busy', 'true'); button.disabled = true; button.setAttribute('aria-expanded', 'true');
  try {
    const result = await request(`${apiBase()}/organisations/${state.org}/evidence/${item.id}/csv-requests`);
    if (epoch !== state.epoch || !panel.isConnected) return;
    const labels = {reauthorised: 'Replacement request recorded — original cancellation retained', awaiting_worker: 'Awaiting an operator-run worker', cancelled: 'Cancelled — requested result storage is stopped',
      result_recorded: 'A result is recorded for this job — inspect current candidates'};
    const details = [element('strong', 'Latest 20 extraction requests'),
      element('p', 'These are historical request receipts. Worker authority and source eligibility are rechecked before processing. Cancellation does not interrupt parsing or undo a recorded result.')];
    for (const entry of result.items) {
      if (!labels[entry.state]) throw new RequestError(502, 'invalid_response');
      const article = element('article'); article.setAttribute('aria-label', `Extraction request ${entry.job_id}`);
      article.append(element('h4', `Request ${entry.job_id}`), element('p', labels[entry.state]),
        element('p', `Requested ${dateText(entry.requested_at)} by ${entry.requested_by} · Policy ${entry.policy_version}`));
      for (const cell of entry.selections) article.append(element('p', `${cell.field_name} · record ${cell.row}, column ${cell.column}`));
      if (entry.cancelled_at) article.append(element('p', `Cancelled ${dateText(entry.cancelled_at)} by ${entry.cancelled_by}`));
      if (entry.state === 'awaiting_worker' && state.context?.can_request_csv && !state.pending.csvCancellation) {
        const cancel = element('button', 'Cancel extraction request', 'button secondary'); cancel.type = 'button';
        cancel.addEventListener('click', () => cancelCSVRequest(item, entry.job_id, button, panel)); article.append(cancel);
      }
      if (entry.state === 'cancelled' && state.context?.can_request_csv && !state.pending.csvCancellation) {
        article.append(element('p', 'Requesting again creates a fresh request for the same cells and retains this cancellation. Current authority and source eligibility will be checked.'));
        const renew = element('button', 'Request extraction again', 'button secondary'); renew.type = 'button';
        renew.addEventListener('click', () => cancelCSVRequest(item, entry.job_id, button, panel, entry.cancelled_at)); article.append(renew);
      }
      details.push(article);
    }
    if (!result.items.length) details.push(element('p', 'No extraction requests recorded.'));
    if (result.has_more) details.push(element('p', 'Older requests exist. This view shows the latest 20.'));
    if (state.pending.csvCancellation?.evidence === item.id) {
      const pending = state.pending.csvCancellation;
      details.push(element('p', `Confirm the pending ${pending.action === 'reauthorise' ? 're-authorisation' : 'cancellation'} for request ${pending.job}.`));
      const retry = element('button', pending.action === 'reauthorise' ? 'Retry extraction re-authorisation' : 'Retry extraction cancellation', 'button secondary'); retry.type = 'button';
      retry.addEventListener('click', () => cancelCSVRequest(item, pending.job, button, panel)); details.push(retry);
    }
    panel.replaceChildren(...details); button.textContent = 'Refresh extraction requests';
  } catch (error) {
    if (epoch !== state.epoch || !panel.isConnected) return;
    panel.replaceChildren(element('p', errorMessage(error))); button.textContent = 'Retry extraction requests';
    if (error.status === 401 || error.status === 403) { panel.replaceChildren(); fail(error); }
  } finally { panel.setAttribute('aria-busy', 'false'); button.disabled = false; }
}
async function cancelCSVRequest(item, job, button, panel, cancellation = null) {
  if (state.saving) return;
  if (Object.keys(state.pending).some(key => key !== 'csvCancellation')) { tell('Confirm the pending save before starting another.'); return; }
  const operation = state.pending.csvCancellation || {evidence: item.id, job, actor: state.context.actor_id,
    action: cancellation ? 'reauthorise' : 'cancel',
    payload: cancellation ? {job_id: crypto.randomUUID(), cancelled_at: cancellation} : {},
    url: `${apiBase()}/organisations/${state.org}/evidence/${item.id}/csv-requests/${job}/${cancellation ? 'reauthorisations' : 'cancellations'}`};
  state.pending.csvCancellation = operation; state.saving = true; clearMessage();
  const epoch = state.epoch;
  try {
    const receipt = await request(operation.url, {method: 'POST', headers: {'Content-Type': 'application/json',
      'X-OmniXat-Expected-Actor': operation.actor}, body: JSON.stringify(operation.payload)});
    delete state.pending.csvCancellation;
    if (epoch !== state.epoch || !panel.isConnected) return;
    await viewCSVRequests(item, button, panel);
    tell(operation.action === 'reauthorise' ? `Replacement request ${receipt.job_id} confirmed. Inspect its current status below.` : 'Extraction request cancelled. Its plan and attribution are retained.');
  } catch (error) {
    const rejected = error.code !== 'session_changed' && [400,403,404,409,413,415,422].includes(error.status);
    if (rejected) delete state.pending.csvCancellation;
    if (epoch !== state.epoch || !panel.isConnected) return;
    if (error.status === 401 || error.status === 403) { panel.replaceChildren(); fail(error); }
    else {
      await viewCSVRequests(item, button, panel);
      panel.append(element('p', errorMessage(error) + (rejected ? '' : ' Retry this same request action to confirm its outcome.')));
      if (error.code === 'session_changed') { fail(error); show('reauth', true); }
    }
  } finally { state.saving = false; $('workspace-select').disabled = Boolean(Object.keys(state.pending).length); }
}
function csvRequestForm(item) {
  const pending = state.pending.csvRequest?.evidence === item.id ? state.pending.csvRequest : null;
  const form = element('form', undefined, 'form-panel csv-request');
  form.setAttribute('aria-label', `Request CSV extraction ${item.id}`);
  const inputs = {};
  form.append(element('h3', 'Request an amount from this CSV'),
    element('p', 'Select one cell using record and column numbers, starting at 1 and including headers. Quoted multiline cells count as one record. No amount is entered here. A trusted worker must process the request.'));
  for (const [key, title, maximum] of [['field_name', 'Amount label', 64], ['row', 'CSV record number', 5000], ['column', 'CSV column number', 64]]) {
    const id = `csv-request-${item.id}-${key}`;
    const label = element('label', title); label.htmlFor = id;
    const input = element('input'); input.id = id; input.required = true;
    if (key === 'field_name') { input.type = 'text'; input.maxLength = 64; input.pattern = '[a-z][a-z0-9_]{0,63}'; input.placeholder = 'gross_amount'; }
    else { input.type = 'number'; input.min = 1; input.max = maximum; input.step = 1; }
    if (pending) input.value = pending.payload.selections[0][key];
    input.addEventListener('input', () => { form.dataset.dirty = 'true'; });
    inputs[key] = input; form.append(label, input);
  }
  const save = element('button', pending ? 'Retry extraction request' : 'Request CSV extraction', 'button secondary'); save.type = 'submit';
  const clear = element('button', 'Clear extraction selection', 'button secondary'); clear.type = 'button';
  const status = element('p'); status.setAttribute('role', 'status');
  function controls(locked) { for (const input of Object.values(inputs)) input.disabled = locked; clear.disabled = locked; }
  controls(Boolean(pending));
  clear.addEventListener('click', () => { for (const input of Object.values(inputs)) input.value = ''; delete form.dataset.dirty; });
  form.append(save, clear, status);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (state.saving) return;
    if (Object.keys(state.pending).some(key => key !== 'csvRequest')) { tell('Confirm the pending save before starting another.'); return; }
    const operation = state.pending.csvRequest || {evidence: item.id, actor: state.context.actor_id,
      url: `${apiBase()}/organisations/${state.org}/evidence/${item.id}/csv-requests`,
      payload: {job_id: crypto.randomUUID(), selections: [{field_name: inputs.field_name.value,
                row: Number(inputs.row.value), column: Number(inputs.column.value)}]}};
    state.pending.csvRequest = operation; state.saving = true; controls(true); save.disabled = true; clearMessage();
    try {
      const receipt = await request(operation.url, {method: 'POST', headers: {'Content-Type': 'application/json',
        'X-OmniXat-Expected-Actor': operation.actor}, body: JSON.stringify(operation.payload)});
      delete state.pending.csvRequest; delete form.dataset.dirty;
      status.textContent = `Extraction request ${receipt.job_id} recorded ${dateText(receipt.requested_at)} under policy ${receipt.policy_version}. Awaiting an operator-run worker. Inspect CSV candidates after processing; this request does not post or approve anything.`;
      save.textContent = 'Extraction request recorded';
      const another = element('button', 'Select another extraction cell', 'button secondary'); another.type = 'button';
      another.addEventListener('click', () => form.replaceWith(csvRequestForm(item))); form.append(another);
    } catch (error) {
      const rejected = error.code !== 'session_changed' && [400,403,404,409,413,415,422].includes(error.status);
      if (rejected) delete state.pending.csvRequest;
      status.textContent = errorMessage(error) + (rejected ? '' : ' Retry this same selection to confirm its request.');
      controls(!rejected); save.disabled = false; save.textContent = rejected ? 'Request CSV extraction' : 'Retry extraction request';
      if (error.status === 401 || error.status === 403) { form.replaceChildren(); fail(error); }
      else if (error.code === 'session_changed') { fail(error); show('reauth', true); }
    } finally {
      state.saving = false; $('workspace-select').disabled = Boolean(Object.keys(state.pending).length);
    }
  });
  return form;
}
async function viewCSVCandidates(item, button, panel) {
  if (panel.querySelector('.csv-answer[data-dirty="true"], .expense-preparation[data-dirty="true"], .funding-selection[data-dirty="true"]') && !state.pending.csvAnswer && !state.pending.expenseDraft) { tell('Save or clear the answer before refreshing candidates.'); return; }
  const epoch = state.epoch;
  panel.hidden = false; panel.replaceChildren(element('p', 'Loading CSV candidates…'));
  panel.setAttribute('aria-busy', 'true'); button.setAttribute('aria-expanded', 'true'); button.disabled = true;
  try {
    const result = await request(`${apiBase()}/organisations/${state.org}/evidence/${item.id}/csv-review`);
    if (epoch !== state.epoch || !panel.isConnected) return;
    const details = [element('strong', 'Latest eligible CSV extraction'),
      element('p', `Extraction ${result.job_id} · ${result.extractor_version} · stored ${dateText(result.stored_at)}`),
      element('p', `Policy: ${result.policy_version} · SHA-256: ${result.content_sha256}`),
      element('p', 'Candidates require review. These values do not post entries or approve a filing.')];
    const values = element('ul');
    for (const value of result.amounts) {
      values.append(element('li', `${value.field_name} · row ${value.row}, column ${value.column}: ${value.amount ?? value.status}`));
    }
    details.push(values);
    for (const answer of result.answers) {
      details.push(element('p', `Recorded answer for ${answer.field_name} · row ${answer.row}, column ${answer.column}: ${answer.amount ?? 'unavailable'} · ${answer.answered_by} · ${dateText(answer.answered_at)}`));
    }
    for (const question of result.questions) {
      details.push(element('p', `${question.field_name} · row ${question.row}, column ${question.column}: ${question.question}`));
      if (state.context?.can_answer_csv && !state.pending.csvAnswer && question === result.questions[0]) details.push(csvAnswerForm(item, result.job_id, question, button, panel));
    }
    if (!result.questions.length) details.push(element('p', 'No unanswered cell questions.'));
    if (state.pending.csvAnswer?.evidence === item.id) {
      const pending = state.pending.csvAnswer;
      details.push(element('p', 'Confirm the pending answer for extraction ' + pending.payload.job_id + '.'));
      details.push(csvAnswerForm(item, pending.payload.job_id, pending.question, button, panel, pending));
    }
    if (state.pending.expenseDraft?.evidence === item.id) {
      details.push(expensePreparationForm(item, state.pending.expenseDraft.options, state.pending.expenseDraft || state.pending.expenseFunding));
    } else if (state.context?.can_prepare_expense && !Object.keys(state.pending).length) {
      const prepare = element('button', 'Prepare expense draft', 'button secondary'); prepare.type = 'button';
      prepare.addEventListener('click', () => loadExpensePreparation(item, result, prepare, panel)); details.push(prepare);
    }
    panel.replaceChildren(...details); button.textContent = 'Refresh CSV candidates';
  } catch (error) {
    if (epoch !== state.epoch || !panel.isConnected) return;
    panel.replaceChildren(element('p', error.status === 404 ? 'No eligible CSV extraction is available. Refresh after a trusted extraction completes.' : errorMessage(error)));
    button.textContent = 'Retry CSV candidates';
    if (error.status === 404 && state.pending.csvAnswer?.evidence === item.id) {
      const pending = state.pending.csvAnswer;
      panel.append(csvAnswerForm(item, pending.payload.job_id, pending.question, button, panel, pending));
    }
    if (error.status === 404 && state.pending.expenseDraft?.evidence === item.id) {
      panel.append(expensePreparationForm(item,state.pending.expenseDraft.options,state.pending.expenseDraft || state.pending.expenseFunding));
    }
    if (error.status === 401 || error.status === 403) { panel.replaceChildren(); fail(error); }
  } finally { panel.setAttribute('aria-busy', 'false'); button.disabled = false; }
}
function csvAnswerForm(item, job, question, reviewButton, panel, pending = null) {
  const form = element('form', undefined, 'form-panel csv-answer');
  form.setAttribute('aria-label', `Answer ${question.field_name}`);
  const id = `answer-${item.id}-${question.field_name}`;
  const label = element('label', 'Exact decimal amount'); label.htmlFor = id;
  const input = element('input'); input.id = id; input.type = 'text'; input.inputMode = 'decimal';
  input.maxLength = 26; input.pattern = '[+\\-]?[0-9]{1,18}([.][0-9]{1,6})?';
  input.required = true; input.autocomplete = 'off';
  const unavailable = element('input'); unavailable.type = 'checkbox'; unavailable.id = id + '-unavailable';
  const unavailableLabel = element('label', 'Amount unavailable'); unavailableLabel.htmlFor = unavailable.id;
  const save = element('button', pending ? 'Retry answer' : 'Save answer', 'button secondary'); save.type = 'submit';
  const clear = element('button', 'Clear answer', 'button secondary'); clear.type = 'button';
  const status = element('p'); status.setAttribute('role', 'status');
  if (pending) { input.value = pending.payload.amount ?? ''; unavailable.checked = pending.payload.amount === null; }
  function controls(locked) {
    input.disabled = locked || unavailable.checked; unavailable.disabled = locked; clear.disabled = locked;
  }
  controls(Boolean(pending));
  unavailable.addEventListener('change', () => { controls(false); form.dataset.dirty = 'true'; });
  input.addEventListener('input', () => { form.dataset.dirty = 'true'; });
  clear.addEventListener('click', () => { input.value = ''; unavailable.checked = false; controls(false); delete form.dataset.dirty; });
  form.append(label, input, unavailable, unavailableLabel,
    element('p', 'Enter the exact amount without currency symbols or grouping separators, or explicitly mark it unavailable. Saving preserves your answer and does not post or approve anything.'), save, clear, status);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (state.saving) return;
    if (Object.keys(state.pending).some(key => key !== 'csvAnswer')) { tell('Confirm the pending save before starting another.'); return; }
    const operation = state.pending.csvAnswer || {evidence: item.id, question,
      actor: state.context.actor_id, url: `${apiBase()}/organisations/${state.org}/evidence/${item.id}/csv-answers`,
      payload: {job_id: job, field_name: question.field_name, row: question.row, column: question.column,
                amount: unavailable.checked ? null : input.value}};
    state.pending.csvAnswer = operation; state.saving = true; controls(true); save.disabled = true;
    const epoch = state.epoch; clearMessage();
    try {
      await request(operation.url, {method: 'POST', headers: {'Content-Type': 'application/json',
        'X-OmniXat-Expected-Actor': operation.actor}, body: JSON.stringify(operation.payload)});
      delete state.pending.csvAnswer; delete form.dataset.dirty;
      if (epoch !== state.epoch || !panel.isConnected) return;
      tell('Answer recorded. Original candidates remain unchanged.');
      await viewCSVCandidates(item, reviewButton, panel);
    } catch (error) {
      const rejected = error.code !== 'session_changed' && [400,403,404,409,413,415,422].includes(error.status);
      if (rejected) delete state.pending.csvAnswer;
      status.textContent = errorMessage(error) + (rejected ? '' : ' Retry the same answer to confirm its outcome.');
      controls(!rejected); save.textContent = rejected ? 'Save answer' : 'Retry answer';
      if (error.status === 401 || error.status === 403) { panel.replaceChildren(); fail(error); }
      else if (error.code === 'session_changed') { fail(error); show('reauth', true); }
    } finally {
      state.saving = false; save.disabled = false;
      $('workspace-select').disabled = Boolean(Object.keys(state.pending).length);
    }
  });
  return form;
}
async function loadExpensePreparation(item, review, button, panel) {
  if (state.saving || Object.keys(state.pending).length || panel.querySelector('.expense-preparation')) return;
  const epoch = state.epoch; button.disabled = true;
  try {
    const options = await request(`${apiBase()}/organisations/${state.org}/evidence/${item.id}/expense-choices`);
    if (epoch !== state.epoch || !panel.isConnected) return;
    options.job = review.job_id;
    options.sources = review.amounts.filter(value => value.amount !== null || review.answers.some(answer =>
      answer.field_name === value.field_name && answer.row === value.row && answer.column === value.column && answer.amount !== null))
      .map(value => ({field_name: value.field_name, row: value.row, column: value.column}));
    panel.append(expensePreparationForm(item, options)); button.remove();
  } catch (error) {
    if (epoch !== state.epoch || !panel.isConnected) return;
    tell(errorMessage(error));
    if ([401,403].includes(error.status)) { panel.replaceChildren(); fail(error); }
  } finally { button.disabled = false; }
}
function expensePreparationForm(item, options, pending = null) {
  const form = element('form', undefined, 'form-panel expense-preparation');
  form.setAttribute('aria-label', 'Prepare source-backed expense draft');
  form.append(element('h3', 'Prepare expense draft'), element('p',
    'GBP preparation only: confirm the source currency before saving. Choose the source, bookkeeping period, expense account and accounting date explicitly. The amount comes from recorded evidence or clarification. This saves a preparation only; it does not post or approve anything.'));
  const inputs = {};
  for (const [key, labelText, values] of [
    ['source', 'Source cell', options.sources.map(v => [JSON.stringify(v), `${v.field_name} · row ${v.row}, column ${v.column}`])],
    ['period_id', 'Bookkeeping period', options.periods.map(v => [v.id, `${v.starts_on} to ${v.ends_on} · ${v.id}`])],
    ['expense_account_id', 'Expense account', options.accounts.map(v => [v.id, `Account reference ${v.id}`])]
  ]) {
    const id = `prepare-${item.id}-${key}`; const label = element('label', labelText); label.htmlFor = id;
    const select = element('select'); select.id = id; select.required = true;
    const blank = element('option', 'Choose explicitly'); blank.value = ''; select.append(blank);
    for (const [value, text] of values) { const option = element('option', text); option.value = value; select.append(option); }
    if (pending) select.value = key === 'source' ? JSON.stringify({field_name:pending.payload.field_name,
      row:pending.payload.row,column:pending.payload.column}) : pending.payload[key];
    inputs[key] = select; form.append(label, select);
  }
  const dateLabel = element('label', 'Accounting date'); dateLabel.htmlFor = `prepare-${item.id}-date`;
  const date = element('input'); date.id = dateLabel.htmlFor; date.type = 'date'; date.required = true;
  if (pending) date.value = pending.payload.accounting_date;
  inputs.accounting_date = date; form.append(dateLabel, date);
  const save = element('button', pending ? 'Retry expense preparation' : 'Save expense draft', 'button secondary'); save.type = 'submit';
  const clear = element('button', 'Clear expense selection', 'button secondary'); clear.type = 'button';
  const status = element('p'); status.setAttribute('role', 'status');
  function controls(locked) { for (const input of Object.values(inputs)) input.disabled = locked; clear.disabled = locked; }
  for (const input of Object.values(inputs)) input.addEventListener('input', () => { form.dataset.dirty = 'true'; });
  clear.addEventListener('click', () => { for (const input of Object.values(inputs)) input.value = ''; delete form.dataset.dirty; });
  if (!options.sources.length || !options.periods.length || !options.accounts.length) {
    form.append(element('p', 'A resolved source and configured open period and expense account are required. Ask your workspace operator to configure missing bookkeeping choices.'));
    save.disabled = !pending;
  }
  if (options.has_more_periods || options.has_more_accounts) form.append(element('p', 'Only 20 choices per type are shown. Older-choice navigation is not available here yet.'));
  controls(Boolean(pending)); form.append(save, clear, status);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (state.saving) return;
    if (Object.keys(state.pending).some(key => key !== 'expenseDraft')) { tell('Confirm the pending save first.'); return; }
    const operation = state.pending.expenseDraft || {evidence:item.id,actor:state.context.actor_id,options,
      url:`${apiBase()}/organisations/${state.org}/evidence/${item.id}/expense-drafts`,
      payload:{job_id:options.job,...JSON.parse(inputs.source.value),period_id:inputs.period_id.value,
        expense_account_id:inputs.expense_account_id.value,accounting_date:date.value}};
    state.pending.expenseDraft = operation; state.saving = true; controls(true); save.disabled = true;
    const epoch = state.epoch; clearMessage();
    try {
      const receipt = await request(operation.url,{method:'POST',headers:{'Content-Type':'application/json',
        'X-OmniXat-Expected-Actor':operation.actor},body:JSON.stringify(operation.payload)});
      delete state.pending.expenseDraft; delete form.dataset.dirty;
      if (epoch !== state.epoch || !form.isConnected) return;
      form.replaceChildren(element('p', `Expense draft ${receipt.id} saved ${dateText(receipt.created_at)}. Inspect saved expense drafts to review it. Nothing was posted or approved.`));
    } catch (error) {
      if (epoch !== state.epoch || !form.isConnected) return;
      const rejected = error.code !== 'session_changed' && [400,403,404,409,413,415,422].includes(error.status);
      if (rejected) delete state.pending.expenseDraft;
      status.textContent = errorMessage(error) + (rejected ? '' : ' Retry the same preparation to confirm its receipt.');
      controls(!rejected); save.disabled = false; save.textContent = rejected ? 'Save expense draft' : 'Retry expense preparation';
      if ([401,403].includes(error.status)) { form.closest('[role="region"]')?.replaceChildren(); fail(error); }
      else if (error.code === 'session_changed') { fail(error); show('reauth', true); }
    } finally { state.saving = false; $('workspace-select').disabled = Boolean(Object.keys(state.pending).length); }
  });
  return form;
}
async function viewExpenseDrafts(item, button, panel, draft = null) {
  if (panel.querySelector('.funding-selection[data-dirty="true"]') && !state.pending.expenseFunding) { tell('Save or clear the funding selection before refreshing.'); return; }
  const epoch = state.epoch;
  panel.hidden = false; panel.replaceChildren(element('p', 'Checking saved expense drafts…'));
  panel.setAttribute('aria-busy', 'true'); button.setAttribute('aria-expanded', 'true'); button.disabled = true;
  try {
    const base = `${apiBase()}/organisations/${state.org}/evidence/${item.id}/expense-drafts`;
    const result = await request(base + (draft ? `/${draft}` : ''));
    if (epoch !== state.epoch || !panel.isConnected) return;
    panel.replaceChildren(element('h3', 'Saved expense drafts'),
      element('p', 'Preparation records only. This view does not approve, post or submit anything. Source and accounting eligibility are checked again on every read.'));
    if (!result.items.length) panel.append(element('p', 'No eligible saved expense drafts are available for this evidence.'));
    for (const value of result.items) {
      const article = element('article');
      article.append(element('strong', `Expense draft ${value.id}`), element('p', `Created ${dateText(value.created_at)} by ${value.created_by}`));
      if (draft) {
        const fields = element('dl'); const source = value.source;
        for (const [label, text] of [
          ['Amount', `${value.currency} ${value.amount}`], ['Accounting date', value.accounting_date],
          ['Accounting period reference', value.period_id], ['Expense account reference', value.expense_account_id],
          ['Evidence reference', source.evidence_id], ['Extraction job', source.job_id],
          ['Source cell', `${source.field_name} · row ${source.row}, column ${source.column}`],
          ['Amount source', source.kind], ['Source recorded', `${dateText(source.created_at)} by ${source.created_by}`],
          ['Scan policy', source.policy_version], ['Evidence fingerprint', source.content_sha256]
        ]) fields.append(element('dt', label), element('dd', text));
        article.append(fields);
        if (state.context?.funding_access) {
          const inspect = element('button', 'Inspect funding', 'button secondary'); inspect.type = 'button';
          const funding = element('div', undefined, 'evidence-receipt'); funding.hidden = true;
          funding.id = `funding-${value.id}`; funding.setAttribute('role','region'); funding.setAttribute('aria-label',`Expense funding ${value.id}`);
          inspect.setAttribute('aria-controls',funding.id); inspect.setAttribute('aria-expanded','false');
          inspect.addEventListener('click', () => viewExpenseFunding(item,value.id,inspect,funding,panel));
          article.append(inspect,funding);
          if (state.pending.expenseFunding?.draft === value.id) queueMicrotask(() => viewExpenseFunding(item,value.id,inspect,funding,panel));
        }
      } else {
        const open = element('button', `Inspect expense draft ${value.id}`, 'button secondary'); open.type = 'button';
        open.addEventListener('click', () => viewExpenseDrafts(item, button, panel, value.id)); article.append(open);
      }
      panel.append(article);
    }
    if (result.has_more) panel.append(element('p', 'Showing the latest 20 eligible drafts. Older draft navigation is not available here yet.'));
  } catch (error) {
    if (epoch !== state.epoch || !panel.isConnected) return;
    panel.replaceChildren(element('p', error.status === 404 ? 'No eligible saved expense draft is available. Refresh the list to check current records.' : errorMessage(error)));
    if (error.status === 401 || error.status === 403) { panel.replaceChildren(); fail(error); }
  } finally { panel.setAttribute('aria-busy', 'false'); button.disabled = false; button.textContent = 'Refresh saved expense drafts'; }
}
async function viewExpenseFunding(item, draft, button, panel, container) {
  if (panel.querySelector('.funding-selection[data-dirty="true"]') && !state.pending.expenseFunding) { tell('Save or clear the funding selection before refreshing.'); return; }
  const epoch = state.epoch;
  panel.hidden = false; panel.replaceChildren(element('p','Checking expense funding…'));
  button.disabled = true; button.setAttribute('aria-expanded','true'); panel.setAttribute('aria-busy','true');
  try {
    const result = await request(`${apiBase()}/organisations/${state.org}/evidence/${item.id}/expense-drafts/${draft}/funding`);
    if (epoch !== state.epoch || !panel.isConnected) return;
    panel.replaceChildren(element('h4','Declared expense funding'),element('p','This records context only. It does not move money, verify payer ownership or post a journal.'));
    if (result.funding) {
      const value = result.funding; const fields = element('dl');
      for (const [label,text] of [['Funding type',value.funding_kind === 'personal_funds' ? 'Personal funds' : 'Business funds'],
        ['Payer reference',value.payer_id],['Funding source reference',value.funding_source_id],
        ['Recorded',`${dateText(value.recorded_at)} by ${value.recorded_by}`],
        ['Source availability',value.source_eligible ? 'Eligible for draft preparation' : 'No longer eligible for draft preparation']]) {
        fields.append(element('dt',label),element('dd',text));
      }
      panel.append(fields);
    } else panel.append(element('p','Who funded this expense? Select the configured payer and source explicitly.'));
    const pending = state.pending.expenseFunding;
    if (pending?.draft === draft) panel.append(expenseFundingForm(item,draft,pending.choices,button,panel,container,pending));
    else if (!result.funding && state.context?.can_record_funding && !Object.keys(state.pending).length) {
      panel.append(expenseFundingForm(item,draft,result.choices,button,panel,container));
    }
    if (result.has_more) panel.append(element('p','Only the first 20 eligible sources are shown. Older-source navigation is not available here yet.'));
  } catch (error) {
    if (epoch !== state.epoch || !panel.isConnected) return;
    panel.replaceChildren(element('p',errorMessage(error)));
    if ([401,403,404].includes(error.status)) { container.replaceChildren(); if (error.status === 404) container.append(element('p','The expense draft is no longer available for funding inspection. Refresh saved drafts.')); else fail(error); }
  } finally { panel.setAttribute('aria-busy','false'); button.disabled = false; button.textContent = 'Refresh funding'; }
}
function expenseFundingForm(item,draft,choices,button,panel,container,pending = null) {
  const form = element('form',undefined,'form-panel funding-selection'); form.setAttribute('aria-label',`Select expense funding ${draft}`);
  const label = element('label','Payer and funding source'); label.htmlFor = `funding-choice-${draft}`;
  const select = element('select'); select.id = label.htmlFor; select.required = true;
  const blank = element('option','Choose explicitly'); blank.value = ''; select.append(blank);
  for (const value of choices) {
    const option = element('option',`${value.funding_kind === 'personal_funds' ? 'Personal funds' : 'Business funds'} · payer ${value.payer_id} · source ${value.id}`);
    option.value = value.id; select.append(option);
  }
  if (pending) select.value = pending.payload.funding_source_id;
  select.addEventListener('input',()=>{form.dataset.dirty='true';});
  const save = element('button',pending ? 'Retry funding selection' : 'Record funding selection','button secondary'); save.type='submit';
  const clear = element('button','Clear funding selection','button secondary'); clear.type='button';
  clear.addEventListener('click',()=>{select.value='';delete form.dataset.dirty;});
  const status=element('p');status.setAttribute('role','status');
  if (!choices.length) { form.append(element('p','No eligible funding sources are configured. Ask your workspace operator to configure a source.')); save.disabled=!pending; }
  function controls(locked) { select.disabled=locked;clear.disabled=locked; }
  controls(Boolean(pending));form.append(label,select,save,clear,status);
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(state.saving)return;
    if(Object.keys(state.pending).some(key=>key!=='expenseFunding')) { tell('Confirm the pending save first.');return; }
    const selected=choices.find(value=>value.id===select.value);
    const operation=state.pending.expenseFunding||{evidence:item.id,draft,choices,actor:state.context.actor_id,
      url:`${apiBase()}/organisations/${state.org}/evidence/${item.id}/expense-drafts/${draft}/funding`,
      payload:{funding_source_id:selected.id,payer_id:selected.payer_id}};
    state.pending.expenseFunding=operation;state.saving=true;controls(true);save.disabled=true;clearMessage();
    const epoch=state.epoch;
    try {
      await request(operation.url,{method:'POST',headers:{'Content-Type':'application/json','X-OmniXat-Expected-Actor':operation.actor},body:JSON.stringify(operation.payload)});
      delete state.pending.expenseFunding;delete form.dataset.dirty;
      if(epoch!==state.epoch||!panel.isConnected)return;
      tell('Funding selection recorded. No funds moved and no journal was posted.');
      await viewExpenseFunding(item,draft,button,panel,container);
    } catch(error) {
      if(epoch!==state.epoch||!form.isConnected)return;
      const rejected=error.code!=='session_changed'&&[400,403,404,409,413,415,422].includes(error.status);
      if(rejected)delete state.pending.expenseFunding;
      status.textContent=errorMessage(error)+(rejected?' Refresh funding to inspect retained records.':' Retry the same selection to confirm its receipt.');
      controls(!rejected);save.disabled=false;save.textContent=rejected?'Record funding selection':'Retry funding selection';
      if([401,403].includes(error.status)) { container.replaceChildren();fail(error); }
      else if(error.code==='session_changed') { fail(error);show('reauth',true); }
    } finally { state.saving=false;$('workspace-select').disabled=Boolean(Object.keys(state.pending).length); }
  });
  return form;
}
async function viewScanStatus(item, button, panel) {
  const epoch = state.epoch;
  panel.hidden = false; panel.replaceChildren(element('p', 'Checking scan status…'));
  panel.setAttribute('aria-busy', 'true'); button.setAttribute('aria-expanded', 'true'); button.disabled = true;
  try {
    const result = await request(`${apiBase()}/organisations/${state.org}/evidence/${item.id}/scan-status`);
    if (epoch !== state.epoch || !panel.isConnected) return;
    const labels = {upload_incomplete: 'Upload incomplete', not_configured: 'Scanning is not configured',
      awaiting_scan: 'Awaiting a trusted scanner', cancelled: 'Scan request cancelled — future dispatch is stopped', requested: 'Scan requested — awaiting an operator-run worker', scanning: 'Scan in progress',
      blocked: 'Blocked by the scan policy', scanned: 'Scan completed — no detections under this policy'};
    if (!labels[result.status]) throw new RequestError(502, 'invalid_response');
    const details = [element('strong', labels[result.status])];
    if (result.policy_version) details.push(element('p', `Scan policy: ${result.policy_version}`));
    if (result.recorded_at) details.push(element('p', `${result.status === 'cancelled' ? 'Cancelled' : 'Observation recorded'}: ${dateText(result.recorded_at)}`));
    details.push(element('p', 'Evidence stays in quarantine. A scan result does not validate figures, create accounting entries or approve a filing.'));
    panel.replaceChildren(...details); button.textContent = 'Refresh scan status';
    if (state.context?.can_request_scan && ['awaiting_scan', 'requested', 'cancelled'].includes(result.status)) {
      const cancelling = result.status === 'requested';
      const reauthorising = result.status === 'cancelled';
      if (cancelling) panel.append(element('p', 'Cancellation cannot stop a scan already in progress.'));
      const start = element('button', reauthorising ? 'Request scan again' : cancelling ? 'Cancel scan request' : 'Request scan', 'button secondary'); start.type = 'button';
      const actor = state.context.actor_id;
      start.addEventListener('click', async () => {
        start.disabled = true; clearMessage();
        try {
          await request(`${apiBase()}/organisations/${state.org}/evidence/${item.id}/${reauthorising ? 'scan-reauthorisations' : cancelling ? 'scan-cancellations' : 'scan-requests'}`, {
            method: 'POST', headers: {'Content-Type': 'application/json', 'X-OmniXat-Expected-Actor': actor,
              ...(reauthorising ? {'X-OmniXat-Cancellation': result.recorded_at} : {})}, body: '{}'});
          if (epoch !== state.epoch || !panel.isConnected) return;
          await viewScanStatus(item, button, panel);
        } catch (error) {
          if (epoch !== state.epoch || !panel.isConnected) return;
          panel.replaceChildren(); fail(error);
        }
      });
      panel.append(start);
    }
  } catch (error) {
    if (epoch !== state.epoch || !panel.isConnected) return;
    panel.replaceChildren(element('p', errorMessage(error))); button.textContent = 'Retry scan status';
    if (error.status === 401 || error.status === 403 || error.status === 404) {
      panel.replaceChildren(); fail(error);
    }
  } finally { panel.setAttribute('aria-busy', 'false'); button.disabled = false; }
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
  if (state.tenant && (state.saving || Object.keys(state.pending).length || document.querySelector('.csv-answer[data-dirty="true"], .csv-request[data-dirty="true"], .expense-preparation[data-dirty="true"], .funding-selection[data-dirty="true"]') || $('note-body').value.trim() || $('evidence-file').files.length)) {
    history.pushState({}, '', tenantPath(state.tenant) + (state.org ? `/organisations/${state.org}` : ''));
    tell('Save or clear the note, selected file or answer before leaving this organisation.');
  } else loadRoute();
});
window.addEventListener('beforeunload', event => { if (state.saving || Object.keys(state.pending).length || document.querySelector('.csv-answer[data-dirty="true"], .csv-request[data-dirty="true"], .expense-preparation[data-dirty="true"], .funding-selection[data-dirty="true"]') || $('note-body').value.trim() || $('evidence-file').files.length) { event.preventDefault(); event.returnValue = ''; } });
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
