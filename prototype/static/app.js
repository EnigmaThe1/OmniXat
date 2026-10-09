'use strict';
let appState = null;
let page = 'overview';
let scope = 'all';
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (s) => new Date(s+'T12:00:00Z').toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});
const month = (s) => new Date(s+'T12:00:00Z').toLocaleDateString('en-GB',{month:'short',timeZone:'UTC'});
const day = (s) => String(Number(s.slice(8,10)));
const pill = (s) => s === 'past-unverified'?'Past · verify':s==='soon'?'Due soon':'Scheduled';
const titleList={overview:['YOUR FINANCIAL WORKSPACE','Welcome back.',"Here's an overview of what needs your attention."],calendar:['YOUR OBLIGATIONS','Tax calendar','Track known dates. Demo and standard-rule dates are not official confirmations.'],companies:['COMPANY MANAGEMENT','Your companies','Manage fictional and manually entered company profiles.'],tax:['TAX PROFILE','Tax settings','Declare demo tax obligations and see standard deadlines.'],questions:['GUIDED INFORMATION GATHERING','Questions to answer','Try the working, rules-based questionnaire before AI is connected.'],tasks:['WORKFLOW','Tasks and reminders','Add and complete preparation tasks. Automatic notifications are not yet connected.'],people:['FAMILY WORKSPACE','People & activities','Keep each person’s personal taxes and self-employment activities separate.'],filings:['FILING EVIDENCE','Return status register','Record preparation and self-reported submission evidence for the selected person or company.'],browser:['BROWSER CAPABILITIES','Browser Lab','See OmniXat open a practice website, fill forms, review and submit a fictional record with your approval.']};

async function getState(){const r=await fetch('/api/state?scope='+encodeURIComponent(scope),{cache:'no-store'});if(!r.ok)throw Error('Cannot reach local demo API');appState=await r.json();render();}
async function post(path,data={}){
 const r=await fetch(path+(path.includes('?')?'&':'?')+'scope='+encodeURIComponent(scope),{method:'POST',headers:{'Content-Type':'application/json','X-OmniXat-Demo':'1'},body:JSON.stringify(data)});
 const v=await r.json().catch(()=>({error:'Unexpected response'}));
 if(!r.ok)throw Error(v.error||'Request failed');appState=v;scope=v.scope||'all';render();return v;
}
let noticeTimer;
function toast(message,isError=false){const e=$('toast');e.textContent=message;e.classList.toggle('error',isError);e.classList.add('show');clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>e.classList.remove('show'),3900);}
function navigate(next){page=next;render();window.scrollTo({top:0,behavior:'instant'});}
async function selectScope(newScope){scope=newScope;try{await getState();toast('Switched workspace view.')}catch(e){scope='all';await getState();toast(e.message,true);}}
function displayPerson(id){return appState.people.find(p=>p.id===id)?.name||'Unknown person';}
function displaySubject(t,id){if(t==='person')return displayPerson(id);if(t==='company')return appState.companies.find(c=>c.id===id)?.name||'Unknown company';if(t==='activity')return appState.activities.find(a=>a.id===id)?.name||'Unknown activity';return 'Shared workspace';}
function button(text,modal,type='primary'){return `<button class="btn btn-${type}" data-modal="${modal}">${text}</button>`;}
function render(){
 if(!appState)return;
 const [label,title,desc]=titleList[page];$('section-label').textContent=label;$('page-title').textContent=title;$('page-subtitle').textContent=desc;$('crumb').textContent=page==='tax'?'Tax profiles':page[0].toUpperCase()+page.slice(1);
 document.querySelectorAll('[data-page]').forEach(b=>b.classList.toggle('active',b.dataset.page===page));
 $('question-count').textContent=appState.metrics.unanswered;
 const picker=$('scope-picker');if(picker){picker.innerHTML=appState.scope_options.map(o=>`<option value="${escapeHtml(o.id)}" ${o.id===scope?'selected':''}>${escapeHtml(o.label)}</option>`).join('');}
 const context=$('context-name');if(context)context.textContent=appState.scope_options.find(o=>o.id===scope)?.label||'Entire workspace';
 $('head-actions').innerHTML=({overview:button('＋ Add a company','company'),calendar:`<a href="/api/calendar.ics?scope=${encodeURIComponent(scope)}" class="btn btn-primary" download="omnixat-demo-calendar.ics">↓ Export calendar</a>`,companies:'',people:'',filings:button('＋ Record return status','filing'),tax:button('＋ Add tax year','year'),questions:'',tasks:button('＋ New task','task'),browser:'<a class="btn btn-quiet" target="_blank" rel="noopener" href="/demo-portal">↗ Open practice website</a>'})[page];
 const body={overview:overview,calendar:calendar,companies:companies,people:peoplePage,filings:filingsPage,tax:tax,questions:questions,tasks:tasks,browser:browserLab}[page]();
 $('page-view').innerHTML=body;
}
function deadlineRows(list,limit=0){
 const items=limit?list.slice(0,limit):list;
 return items.length?items.map(d=>`<div class="deadline-row"><div class="daybox"><strong>${day(d.date)}</strong><small>${month(d.date)}</small></div><div><p class="row-title">${escapeHtml(d.title)}</p><div class="row-sub">${escapeHtml(d.entity)} · ${fmt(d.date)}</div></div><span class="pill ${d.status}">${pill(d.status)}</span></div>`).join(''):'<div class="empty">Nothing tracked yet. Add a tax profile to get started.</div>';
}
function taskRows(limit=0){const a=limit?appState.tasks.slice(0,limit):appState.tasks;return a.length?a.map(t=>`<label class="task-row"><input type="checkbox" data-toggle-task="${escapeHtml(t.id)}" ${t.completed?'checked':''}/><span><span class="task-title ${t.completed?'finished':''}">${escapeHtml(t.title)}</span><span class="task-date">${fmt(t.due)} · ${t.completed?'Completed':'To do'}</span></span></label>`).join(''):'<div class="empty">No tasks yet.</div>'}
function overview(){const m=appState.metrics;const answered=appState.questions.length-m.unanswered;const pct=appState.questions.length?Math.round(answered/appState.questions.length*100):100;
return `<div class="stats">
<div class="stat"><div class="stat-top">Companies <span class="stat-icon">▥</span></div><div class="stat-num">${m.companies}</div><div class="stat-note">Demo & unverified profiles</div></div>
<div class="stat"><div class="stat-top">Tracked deadlines <span class="stat-icon">▦</span></div><div class="stat-num">${m.deadlines}</div><div class="stat-note">Based on demo/user inputs</div></div>
<div class="stat"><div class="stat-top">Questions pending <span class="stat-icon">◇</span></div><div class="stat-num">${m.unanswered}</div><div class="stat-note">Guided questionnaire</div></div>
<div class="stat"><div class="stat-top">Open tasks <span class="stat-icon">☑</span></div><div class="stat-num">${m.open_tasks}</div><div class="stat-note">Preparation checklist</div></div></div>
<div class="scope-hint"><strong>Selected view: ${escapeHtml(appState.scope_options.find(o=>o.id===scope)?.label||'Workspace')}</strong> · ${appState.metrics.people} people · ${appState.metrics.filings} recorded filing statuses. <button class="link-btn" data-nav="people">Manage people →</button></div>
<div class="columns"><div class="stack"><section class="panel"><div class="panel-heading"><div><h2>Upcoming & tracked deadlines</h2><div class="panel-hint">Standard rules or demo dates — verify against HMRC</div></div><button class="link-btn" data-nav="calendar">View all →</button></div>${deadlineRows(appState.deadlines,5)}</section>
<section class="panel panel-pad"><div class="panel-topline"><h2>Your preparation checklist</h2><div class="panel-hint">Tasks you can mark complete in this prototype</div></div>${taskRows(4)}<div style="margin-top:13px"><button class="link-btn" data-nav="tasks">Manage tasks →</button></div></section></div>
<div class="stack"><section class="panel panel-pad"><div class="panel-topline"><h2>Information readiness</h2><div class="panel-hint">The guided questions are interactive</div></div><div class="progress"><span style="width:${pct}%"></span></div><div class="progress-meta"><strong>${answered} of ${appState.questions.length} answered</strong><span>${pct}% complete</span></div><p class="muted" style="font-size:12px;margin:22px 0 12px">Your answers save locally and change the readiness score. No tax return is generated from them yet.</p><button class="btn btn-primary" data-nav="questions">Continue questionnaire →</button></section>
<section class="panel panel-pad"><div class="panel-topline"><h2>Recent activity</h2><div class="panel-hint">Changes in this local workspace</div></div>${appState.activity.slice(0,5).map(a=>`<div class="mini-item"><div class="mini-symbol">↗</div><div><strong>${escapeHtml(a.event)}</strong><small>${escapeHtml(a.created_at.slice(0,16).replace('T',' '))}</small></div></div>`).join('')}</section>
<section class="panel panel-pad"><h2>What works today?</h2><div class="panel-hint">Company forms · tax profiles · question answers · task tracking · calendar export</div><div style="margin-top:17px" class="info-box">Live HMRC connections, tax computations, submissions and AI answers are intentionally disabled.</div></section></div></div>`}
function calendar(){const groups={};appState.deadlines.forEach(d=>{const k=d.date.slice(0,7);(groups[k]??=[]).push(d)});return `<div class="info-box">Dates come from fictional demo profiles or explicitly entered obligations. A past date does <strong>not</strong> prove a missed filing. No official filing status is checked.</div><div class="calendar-groups">${Object.entries(groups).map(([k,items])=>`<section class="panel calendar-block"><h3>${new Date(k+'-01T12:00:00Z').toLocaleDateString('en-GB',{month:'long',year:'numeric',timeZone:'UTC'})}</h3>${items.map(d=>`<div class="cal-entry"><div class="cal-date">${day(d.date)} ${month(d.date)}</div><div><strong>${escapeHtml(d.title)}</strong><p>${escapeHtml(d.entity)}</p><div class="source-note">${escapeHtml(d.source)} · ${escapeHtml(d.note)}</div></div></div>`).join('')}</section>`).join('')||'<section class="panel empty">No calendar entries.</section>'}</div>`}
function peoplePage(){
 const members=appState.people.map(p=>{
   const activities=appState.activities.filter(a=>a.person_id===p.id);
   const roles=appState.roles.filter(r=>r.person_id===p.id);
   const years=appState.years.filter(y=>y.person_id===p.id);
   return `<article class="member-card"><div class="member-head"><span class="member-avatar">${escapeHtml(p.name.charAt(0))}</span><div><strong>${escapeHtml(p.name)}</strong><small>${activities.length} self-employed activities · ${roles.length} company links</small></div><button class="btn btn-quiet" data-open-tax="person:${escapeHtml(p.id)}">View tax profile →</button></div>
   <div class="member-relationships">${activities.map(a=>`<button class="relationship" data-scope="activity:${escapeHtml(a.id)}">${escapeHtml(a.name)}</button>`).join('')}
   ${roles.map(r=>`<button class="relationship" data-scope="company:${escapeHtml(r.company_id)}">${escapeHtml(displaySubject('company',r.company_id))} · ${escapeHtml(r.role)}</button>`).join('')}
   </div></article>`;
 }).join('');
 return `<div class="info-box"><strong>Private household model:</strong> people, self-employment activities and legal companies are separate records. A person may link to several companies; several people may link to one company. This demo does <strong>not</strong> provide separate logins or privacy permissions yet.</div>
 <div class="member-actions">${button('＋ Add person','person','primary')}${button('＋ Add self-employment activity','activity','quiet')}${button('＋ Link person to company','role','quiet')}</div>
 <section class="panel panel-pad"><h2>People in the workspace</h2>${members||'<div class="empty">No people added. Create your first fictional profile.</div>'}</section>`;
}
function companies(){return `<div class="info-box">Companies are independent legal organisations. Use the selector to inspect one company's tax years and return statuses. Manually entered company details are <strong>unverified</strong>.</div>
<div class="member-actions">${button('＋ Add company','company','primary')}${button('＋ Link person to company','role','quiet')}</div>
<section class="panel"><div class="panel-heading"><h2>Companies</h2></div><div class="table-wrap"><table><thead><tr><th>Company</th><th>Linked people</th><th>Accounts</th><th>Confirmation</th><th></th></tr></thead><tbody>${appState.companies.map(c=>`<tr><td><strong>${escapeHtml(c.name)}</strong><small>${escapeHtml(c.number)} · ${c.origin==='fictional_demo'?'Fictional demo':'Unverified manual'}</small></td><td>${appState.roles.filter(r=>r.company_id===c.id).map(r=>`${escapeHtml(displayPerson(r.person_id))} (${escapeHtml(r.role)})`).join('<br>')||'Not linked'}</td><td>${c.accounts_due?fmt(c.accounts_due):'Not verified'}</td><td>${c.confirmation_due?fmt(c.confirmation_due):'Not verified'}</td><td><button class="link-btn" data-open-overview="company:${escapeHtml(c.id)}">Inspect →</button></td></tr>`).join('')}</tbody></table></div></section>`}
function tax(){
 const chosen=scope.startsWith('person:')?scope.slice(7):'';
 const yrRows=appState.years.map(y=>`<div class="mini-item"><div class="mini-symbol">◈</div><div><strong>${escapeHtml(displayPerson(y.person_id))} · ${y.start_year}–${String(y.start_year+1).slice(-2)}</strong><small>${y.required?'Self Assessment marked required':'Not marked required'}${y.second_payment?' · Second payment expected':''}</small></div></div>`).join('');
 const legacy=appState.legacy_unassigned_years.length?`<div class="legacy-warning"><strong>${appState.legacy_unassigned_years.length} unassigned older tax-year record(s)</strong>. Preserved from v0.3 and <em>not</em> allocated to anyone. Review and re-enter under the correct person.</div>`:'';
 return `<div class="columns"><section class="panel panel-pad"><h2>Personal Self Assessment</h2><p class="panel-hint">Every record belongs to a selected person. Two people may record the same tax year independently.</p>${legacy}${yrRows||'<p class="muted">No personal tax-year records in this view.</p>'}<div style="margin-top:18px">${button('＋ Add / edit personal tax year','year','quiet')}</div></section>
 <section class="panel panel-pad"><h2>Corporation Tax periods</h2><p class="panel-hint">Each period belongs to a specific limited company, not to a director personally.</p>${appState.periods.map(p=>`<div class="mini-item"><div class="mini-symbol">▥</div><div><strong>${escapeHtml(displaySubject('company',p.company_id))}</strong><small>Period ends ${fmt(p.period_end)} · ${p.required?'CT600 marked required':'Not marked required'}</small></div></div>`).join('')||'<p class="muted">No company periods in this view.</p>'}<div style="margin-top:18px">${button('＋ Add CT period','period','quiet')}</div></section></div>`;
}
function filingsPage(){
 const labels={'not_determined':'Not determined','preparing':'Preparing','ready_for_review':'Ready to review','reported_submitted':'Submitted (self-reported)','reported_accepted':'Accepted (self-reported)','reported_rejected':'Rejected (self-reported)'};
 return `<div class="info-box"><strong>Filing status is evidence-based and self-reported in this demo.</strong> OmniXat has not checked HMRC or Companies House. A past deadline does not mean a return is unfiled, and a saved demo status does not mean official acceptance.</div><section class="panel"><div class="panel-heading"><h2>Recorded filing statuses</h2>${button('＋ Add / update record','filing','quiet')}</div><div class="table-wrap"><table><thead><tr><th>Person or company</th><th>Return type / period</th><th>Status</th><th>Fictional evidence</th></tr></thead><tbody>${appState.filings.map(f=>`<tr><td>${escapeHtml(displaySubject(f.subject_type,f.subject_id))}</td><td>${escapeHtml(f.kind.replaceAll('_',' '))} · ${escapeHtml(f.period_key)}</td><td><span class="pill">${escapeHtml(labels[f.status]||f.status)}</span></td><td>${escapeHtml(f.evidence||'Not supplied')}</td></tr>`).join('')||'<tr><td colspan="4">No filing statuses recorded for this view.</td></tr>'}</tbody></table></div></section>
<section class="panel panel-pad" style="margin-top:20px"><h2>Tracked dates requiring status review</h2><p class="panel-hint">These dates do not prove a filing is required or outstanding. They are shown separately from the self-reported status register above.</p>${appState.deadlines.filter(d=>d.kind!=='corporation_payment'&&d.kind!=='payment').map(d=>`<div class="deadline-row"><div class="daybox"><strong>${day(d.date)}</strong><small>${month(d.date)}</small></div><div><strong>${escapeHtml(d.title)}</strong><small style="display:block">${escapeHtml(d.entity)} · ${fmt(d.date)}</small></div><span class="pill">Status not independently checked</span></div>`).join('')||'<div class="empty">No filing dates configured for this selected view.</div>'}</section>`;
}
function questions(){let unanswered=appState.questions.filter(q=>!q.answer).length;return `<div class="info-box"><strong>Rules-based demonstration:</strong> these sample questions illustrate future AI-assisted information gathering. They do not constitute tax advice or determine legal treatment.</div><div class="panel panel-pad" style="margin-bottom:20px"><strong>${appState.questions.length-unanswered} / ${appState.questions.length} answered</strong><div class="progress"><span style="width:${Math.round(100*(appState.questions.length-unanswered)/appState.questions.length)}%"></span></div></div><div class="question-grid">${appState.questions.map(q=>`<section class="panel question-card"><div class="question-category">${escapeHtml(q.topic)}</div><h3>${escapeHtml(q.question)}</h3><p>${escapeHtml(q.help)}</p><div class="answer-row">${['yes','no','unsure'].map(a=>`<button class="choice ${q.answer===a?'active':''}" data-answer="${escapeHtml(q.key)}" data-value="${a}">${a==='yes'?'Yes':a==='no'?'No':'Not sure'}</button>`).join('')}</div>${q.answer?`<div class="question-note">✓ Saved answer: ${escapeHtml(q.answer)} · editable</div>`:''}</section>`).join('')}</div>`}
function tasks(){return `<div class="columns"><section class="panel panel-pad"><div class="panel-heading" style="padding:0 0 16px"><h2>Preparation tasks</h2>${button('＋ Add task','task','quiet')}</div>${taskRows()}</section><section class="panel panel-pad"><h2>Activity history</h2><p class="panel-hint">Recent changes to fictional workspace information</p><div style="margin-top:20px">${appState.activity.map(a=>`<div class="timeline-item">${escapeHtml(a.event)}<small>${escapeHtml(a.created_at.slice(0,16).replace('T',' '))}</small></div>`).join('')}</div></section></div>`}
function browserLab(){
 const b=appState.browser||{enabled:false,latest:null,preview_available:false};
 const run=b.latest;
 const last=run?`<section class="panel panel-pad browser-result"><div class="panel-topline"><h2>Latest browser execution</h2><span class="browser-state ${run.status}">${escapeHtml(run.status.replaceAll('_',' '))}</span></div>
 <div class="browser-summary"><div><span>Company</span><strong>${escapeHtml(run.payload.company)}</strong></div><div><span>Period end</span><strong>${escapeHtml(run.payload.period)}</strong></div><div><span>Fictional amount</span><strong>£${escapeHtml(run.payload.amount)}</strong></div></div>
 <h3>Actions performed by the real browser</h3><ol class="browser-steps">${run.steps.map(t=>`<li>${escapeHtml(t)}</li>`).join('')}</ol>
 ${b.preview_available?`<div class="screenshot-label">Actual browser screenshot</div><img class="browser-preview" src="/api/browser/preview?t=${encodeURIComponent(run.id)}-${encodeURIComponent(run.status)}" alt="Playwright screenshot of the practice form review or local demo receipt">`:''}
 ${run.receipt?`<div class="browser-receipt"><strong>Local demo receipt: ${escapeHtml(run.receipt)}</strong><small>No information was sent to HMRC, Companies House or any external service.</small></div>`:''}
 ${run.status==='awaiting_approval'?`<div class="approval"><h3>Approval required</h3><p>The browser has filled and checked the practice website, but it has <strong>not</strong> clicked the final submission button. You must approve that separately.</p><button class="btn btn-primary" id="browser-approve" data-run-id="${escapeHtml(run.id)}">Approve DEMO submission →</button></div>`:''}</section>`:'<section class="panel panel-pad"><h2>Nothing executed yet</h2><p class="panel-hint">Start a practice browser workflow to see the page and action history.</p></section>';
 return `<div class="info-box"><strong>Local practice website only.</strong> This prototype starts real Chromium through Playwright and operates a simulated form hosted on your computer. It cannot open arbitrary websites, access HMRC, handle credentials or make genuine filings. Third-party browser workflows require site-by-site permission checks.</div>
 <div class="browser-grid"><section class="panel panel-pad"><div class="panel-topline"><h2>Prepare browser workflow</h2><p class="panel-hint">Step 1: inspect · Step 2: fill · Step 3: review · Step 4: request approval</p></div>
 ${b.enabled?`<form id="browser-lab-form" class="form">
 <div class="form-field"><label for="browser-company">Fictional company name</label><input id="browser-company" name="company" value="Northstar Studio Ltd (DEMO)" minlength="3" maxlength="70" required></div>
 <div class="form-field"><label for="browser-period">Accounting period end (demo)</label><input id="browser-period" name="period" type="date" value="2026-12-31" min="2026-01-01" max="2028-12-31" required></div>
 <div class="form-field"><label for="browser-amount">Fictional amount in pounds</label><input id="browser-amount" name="amount" type="number" min="0" max="99999999" step="0.01" value="1250.00" required></div>
 <label class="form-check"><input id="browser-fictional" name="fictional_only" type="checkbox" required> I confirm these are fictional practice details, not real tax information.</label>
 <button class="btn btn-primary" type="submit">▶ Inspect and prepare with Playwright</button></form>`:'<div class="browser-missing"><strong>Browser driver is not installed.</strong><p>Run <code>pip install playwright</code> and <code>python -m playwright install chromium</code>, then restart the prototype.</p></div>'}
 </section><section class="panel panel-pad"><h2>Connection strategy</h2><div class="browser-capabilities"><div><b>1</b><strong>Official API</strong><small>Preferred when provided and authorised.</small></div><div><b>2</b><strong>Playwright browser</strong><small>For permitted sites without suitable APIs.</small></div><div><b>3</b><strong>Human hand-off</strong><small>Login, MFA, restricted sites and legally significant decisions.</small></div></div><p class="panel-hint">Government Gateway automation is not permitted under current HMRC policy. Browser access is not a way to bypass a site's rules.</p></section></div>
 ${last}`;
}
function modalBody(type){
 const input=(id,label,placeholder='',required=true,type='text')=>`<div class="form-field"><label for="${id}">${label}</label><input id="${id}" name="${id}" type="${type}" placeholder="${placeholder}" ${required?'required':''}/></div>`;
 const check=(id,label,value=true)=>`<label class="form-check"><input id="${id}" name="${id}" type="checkbox" ${value?'checked':''}/> ${label}</label>`;
 const base=(s)=>s+`<div class="form-actions"><button type="button" class="btn" id="modal-cancel">Cancel</button><button type="submit" class="btn btn-primary">Save</button></div>`;
 if(type==='company')return ['Add unverified company',base(`${input('name','Demo company name','Example Creative Ltd')}${input('number','Eight-character company number','DEMO0002')}<p class="panel-hint">No Companies House connection. Please use fictional information only.</p>`)];
 if(type==='year')return ['Add / update personal tax year',base(`<div class="form-field"><label for="person_id">Person (taxpayer)</label><select id="person_id" name="person_id" required>${appState.people.map(p=>`<option value="${escapeHtml(p.id)}" ${scope==='person:'+p.id?'selected':''}>${escapeHtml(p.name)}</option>`).join('')}</select></div>${input('start_year','Tax year starting 6 April','2025',true,'number')}${check('required','Self Assessment is required for this tax year')}${check('second_payment','I expect a second payment on account',false)}`)];
 if(type==='period')return ['Add Corporation Tax period',base(`<div class="form-field"><label for="company_id">Company</label><select id="company_id" name="company_id" required>${appState.companies.map(c=>`<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)}</option>`).join('')}</select></div>${input('period_end','HMRC accounting period end','',true,'date')}${check('required','CT600 return required for this period')}<p class="panel-hint">Standard deadlines only; special cases may differ.</p>`)];
 if(type==='person')return ['Add person',base(`${input('name','Fictional name','Taylor Morgan')}`)];
 if(type==='activity')return ['Add self-employment activity',base(`<div class="form-field"><label for="person_id">Person</label><select id="person_id" name="person_id" required>${appState.people.map(p=>`<option value="${escapeHtml(p.id)}" ${scope==='person:'+p.id?'selected':''}>${escapeHtml(p.name)}</option>`).join('')}</select></div>${input('name','Trading or activity name','Example Gardening Services')}`)];
 if(type==='role')return ['Link person and company',base(`<div class="form-field"><label for="person_id">Person</label><select id="person_id" name="person_id" required>${appState.people.map(p=>`<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`).join('')}</select></div><div class="form-field"><label for="company_id">Company</label><select id="company_id" name="company_id" required>${appState.companies.map(c=>`<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)}</option>`).join('')}</select></div><div class="form-field"><label for="role">Relationship</label><select id="role" name="role"><option value="director">Director</option><option value="shareholder">Shareholder</option><option value="employee">Employee</option><option value="secretary">Secretary</option><option value="authorised_agent">Authorised agent</option><option value="other">Other</option></select></div>`)];
 if(type==='filing')return ['Record fictional filing status',base(`<div class="form-field"><label for="subject_ref">Person or company</label><select id="subject_ref" name="subject_ref" required>${appState.scope_options.filter(o=>o.type==='person'||o.type==='company').map(o=>`<option value="${escapeHtml(o.id)}" ${scope===o.id?'selected':''}>${escapeHtml(o.label)} (${o.type})</option>`).join('')}</select></div>
 <div class="form-field"><label for="kind">Return type</label><select id="kind" name="kind"><option value="self_assessment">Self Assessment</option><option value="corporation_tax">CT600</option><option value="accounts">Company accounts</option><option value="confirmation_statement">Confirmation statement</option><option value="other">Other</option></select></div>${input('period_key','Tax year or period (label)','2025-26')}
 <div class="form-field"><label for="status">Status (self-reported only)</label><select id="status" name="status"><option value="not_determined">Not determined</option><option value="preparing">Preparing</option><option value="ready_for_review">Ready for review</option><option value="reported_submitted">Submitted (self-reported)</option><option value="reported_accepted">Accepted (self-reported)</option><option value="reported_rejected">Rejected (self-reported)</option></select></div>${input('evidence','Fictional reference/note (required for submitted/accepted/rejected)','DEMO-REFERENCE',false)}<p class="panel-hint">No official filing action occurs. Any submission outcome shown is supplied by you as a demo note.</p>`)];
 if(type==='task')return ['Add a task',base(`${input('title','Task title','Review example receipts')}${input('due','Target date','',true,'date')}`)];
 throw Error('Unsupported form');
}
function showModal(type){const [title,body]=modalBody(type);$('modal-title').textContent=title;$('modal-body').innerHTML=`<form id="record-form" class="form" data-type="${type}">${body}</form>`;$('modal-overlay').hidden=false;const first=$('record-form').querySelector('input,select');first?.focus();}
function closeModal(){$('modal-overlay').hidden=true;$('modal-body').innerHTML='';}
function mapForm(form){
 const d=new FormData(form), type=form.dataset.type;
 if(type==='company')return ['/api/companies',{name:d.get('name'),number:d.get('number')}];
 if(type==='person')return ['/api/people',{name:d.get('name')}];
 if(type==='activity')return ['/api/activities',{person_id:d.get('person_id'),name:d.get('name')}];
 if(type==='role')return ['/api/company-roles',{person_id:d.get('person_id'),company_id:d.get('company_id'),role:d.get('role')}];
 if(type==='year')return ['/api/years',{person_id:d.get('person_id'),start_year:Number(d.get('start_year')),required:d.has('required'),second_payment:d.has('second_payment')}];
 if(type==='period')return ['/api/periods',{company_id:d.get('company_id'),period_end:d.get('period_end'),required:d.has('required')}];
 if(type==='task'){const [kind,id]=scope==='all'?['workspace',null]:scope.split(':');return ['/api/tasks',{title:d.get('title'),due:d.get('due'),subject_type:kind,subject_id:id}];}
 if(type==='filing'){const [subject_type,subject_id]=String(d.get('subject_ref')).split(':');return ['/api/filings',{subject_type,subject_id,kind:d.get('kind'),period_key:d.get('period_key'),status:d.get('status'),evidence:d.get('evidence')}];}
 throw Error('Unknown form');
}

document.addEventListener('click',async e=>{
 const b=e.target.closest('button');if(!b)return;
 if(b.dataset.page)return navigate(b.dataset.page);
 if(b.dataset.nav)return navigate(b.dataset.nav);
 if(b.dataset.openTax){await selectScope(b.dataset.openTax);return navigate('tax');}
 if(b.dataset.openOverview){await selectScope(b.dataset.openOverview);return navigate('overview');}
 if(b.dataset.scope)return selectScope(b.dataset.scope);
 if(b.dataset.modal)return showModal(b.dataset.modal);
 if(b.id==='modal-close'||b.id==='modal-cancel')return closeModal();
 if(b.dataset.answer){try{await post('/api/questions/'+encodeURIComponent(b.dataset.answer)+'/answer',{answer:b.dataset.value});toast('Answer saved locally.');}catch(err){toast(err.message,true);}return;}
 if(b.id==='browser-approve'){
   if(!confirm('This will click Submit on the LOCAL FICTIONAL practice website only. No government service is contacted. Proceed?'))return;
   b.disabled=true;
   try{await post('/api/browser/approve',{run_id:b.dataset.runId,approve_demo_submission:true});toast('Demo record submitted locally; receipt verified.');}
   catch(err){toast(err.message,true);b.disabled=false;}
   return;
 }
 if(b.id==='reset-demo'){if(!confirm('Reset every demo change and restore fictional sample data?'))return;try{await post('/api/reset');toast('Fictional demo restored.');navigate('overview');}catch(err){toast(err.message,true);}}
});
document.addEventListener('change',async e=>{const input=e.target;if(input.dataset.toggleTask){try{await post('/api/tasks/'+encodeURIComponent(input.dataset.toggleTask)+'/toggle');toast('Task status updated.');}catch(err){toast(err.message,true);}}});
document.addEventListener('submit',async e=>{if(e.target.id==='browser-lab-form'){
   e.preventDefault();const form=e.target;const action=form.querySelector('button[type=submit]');action.disabled=true;
   action.textContent='Chromium is navigating the practice website…';
   const d=new FormData(form);
   try{
      await post('/api/browser/run',{company:d.get('company'),period:d.get('period'),amount:d.get('amount'),fictional_only:d.has('fictional_only')});
      toast('Playwright filled the practice website and is waiting for approval.');
   }catch(err){toast(err.message,true);action.disabled=false;action.textContent='▶ Inspect and prepare with Playwright';}
   return;
 }
 if(e.target.id!=='record-form')return;e.preventDefault();const form=e.target;try{const [path,data]=mapForm(form);await post(path,data);closeModal();toast('Saved to the local demo database.');}catch(err){toast(err.message,true);}});
$('modal-overlay').addEventListener('click',e=>{if(e.target.id==='modal-overlay')closeModal();});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});
$('scope-picker').addEventListener('change',e=>selectScope(e.target.value));
getState().catch(err=>{$('page-view').textContent='Cannot load the local demo: '+err.message;});
