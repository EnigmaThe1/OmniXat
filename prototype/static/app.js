'use strict';
let appState = null;
let page = 'overview';
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (s) => new Date(s+'T12:00:00Z').toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});
const month = (s) => new Date(s+'T12:00:00Z').toLocaleDateString('en-GB',{month:'short',timeZone:'UTC'});
const day = (s) => String(Number(s.slice(8,10)));
const pill = (s) => s === 'past-unverified'?'Past · verify':s==='soon'?'Due soon':'Scheduled';
const titleList={overview:['YOUR FINANCIAL WORKSPACE','Welcome back.',"Here's an overview of what needs your attention."],calendar:['YOUR OBLIGATIONS','Tax calendar','Track known dates. Demo and standard-rule dates are not official confirmations.'],companies:['COMPANY MANAGEMENT','Your companies','Manage fictional and manually entered company profiles.'],tax:['TAX PROFILE','Tax settings','Declare demo tax obligations and see standard deadlines.'],questions:['GUIDED INFORMATION GATHERING','Questions to answer','Try the working, rules-based questionnaire before AI is connected.'],tasks:['WORKFLOW','Tasks and reminders','Add and complete preparation tasks. Automatic notifications are not yet connected.'],browser:['BROWSER CAPABILITIES','Browser Lab','See OmniXat open a practice website, fill forms, review and submit a fictional record with your approval.']};

async function getState(){const r=await fetch('/api/state',{cache:'no-store'});if(!r.ok)throw Error('Cannot reach local demo API');appState=await r.json();render();}
async function post(path,data={}){
 const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-OmniXat-Demo':'1'},body:JSON.stringify(data)});
 const v=await r.json().catch(()=>({error:'Unexpected response'}));
 if(!r.ok)throw Error(v.error||'Request failed');appState=v;render();return v;
}
let noticeTimer;
function toast(message,isError=false){const e=$('toast');e.textContent=message;e.classList.toggle('error',isError);e.classList.add('show');clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>e.classList.remove('show'),3900);}
function navigate(next){page=next;render();window.scrollTo({top:0,behavior:'instant'});}
function button(text,modal,type='primary'){return `<button class="btn btn-${type}" data-modal="${modal}">${text}</button>`;}
function render(){
 if(!appState)return;
 const [label,title,desc]=titleList[page];$('section-label').textContent=label;$('page-title').textContent=title;$('page-subtitle').textContent=desc;$('crumb').textContent=page==='tax'?'Tax profiles':page[0].toUpperCase()+page.slice(1);
 document.querySelectorAll('[data-page]').forEach(b=>b.classList.toggle('active',b.dataset.page===page));
 $('question-count').textContent=appState.metrics.unanswered;
 $('head-actions').innerHTML=({overview:button('＋ Add a company','company'),calendar:'<a href="/api/calendar.ics" class="btn btn-primary" download="omnixat-demo-calendar.ics">↓ Export calendar</a>',companies:button('＋ Add a company','company'),tax:button('＋ Add tax year','year'),questions:'',tasks:button('＋ New task','task'),browser:'<a class="btn btn-quiet" target="_blank" rel="noopener" href="/demo-portal">↗ Open practice website</a>'})[page];
 const body={overview:overview,calendar:calendar,companies:companies,tax:tax,questions:questions,tasks:tasks,browser:browserLab}[page]();
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
<div class="columns"><div class="stack"><section class="panel"><div class="panel-heading"><div><h2>Upcoming & tracked deadlines</h2><div class="panel-hint">Standard rules or demo dates — verify against HMRC</div></div><button class="link-btn" data-nav="calendar">View all →</button></div>${deadlineRows(appState.deadlines,5)}</section>
<section class="panel panel-pad"><div class="panel-topline"><h2>Your preparation checklist</h2><div class="panel-hint">Tasks you can mark complete in this prototype</div></div>${taskRows(4)}<div style="margin-top:13px"><button class="link-btn" data-nav="tasks">Manage tasks →</button></div></section></div>
<div class="stack"><section class="panel panel-pad"><div class="panel-topline"><h2>Information readiness</h2><div class="panel-hint">The guided questions are interactive</div></div><div class="progress"><span style="width:${pct}%"></span></div><div class="progress-meta"><strong>${answered} of ${appState.questions.length} answered</strong><span>${pct}% complete</span></div><p class="muted" style="font-size:12px;margin:22px 0 12px">Your answers save locally and change the readiness score. No tax return is generated from them yet.</p><button class="btn btn-primary" data-nav="questions">Continue questionnaire →</button></section>
<section class="panel panel-pad"><div class="panel-topline"><h2>Recent activity</h2><div class="panel-hint">Changes in this local workspace</div></div>${appState.activity.slice(0,5).map(a=>`<div class="mini-item"><div class="mini-symbol">↗</div><div><strong>${escapeHtml(a.event)}</strong><small>${escapeHtml(a.created_at.slice(0,16).replace('T',' '))}</small></div></div>`).join('')}</section>
<section class="panel panel-pad"><h2>What works today?</h2><div class="panel-hint">Company forms · tax profiles · question answers · task tracking · calendar export</div><div style="margin-top:17px" class="info-box">Live HMRC connections, tax computations, submissions and AI answers are intentionally disabled.</div></section></div></div>`}
function calendar(){const groups={};appState.deadlines.forEach(d=>{const k=d.date.slice(0,7);(groups[k]??=[]).push(d)});return `<div class="info-box">Dates come from fictional demo profiles or explicitly entered obligations. A past date does <strong>not</strong> prove a missed filing. No official filing status is checked.</div><div class="calendar-groups">${Object.entries(groups).map(([k,items])=>`<section class="panel calendar-block"><h3>${new Date(k+'-01T12:00:00Z').toLocaleDateString('en-GB',{month:'long',year:'numeric',timeZone:'UTC'})}</h3>${items.map(d=>`<div class="cal-entry"><div class="cal-date">${day(d.date)} ${month(d.date)}</div><div><strong>${escapeHtml(d.title)}</strong><p>${escapeHtml(d.entity)}</p><div class="source-note">${escapeHtml(d.source)} · ${escapeHtml(d.note)}</div></div></div>`).join('')}</section>`).join('')||'<section class="panel empty">No calendar entries.</section>'}</div>`}
function companies(){return `<div class="info-box">Companies you add manually will remain <strong>unverified</strong> and will not receive fabricated Companies House deadlines. The seeded Northstar company is fictional.</div><section class="panel"><div class="panel-heading"><h2>Company profiles</h2>${button('＋ Add company','company','quiet')}</div><div class="table-wrap"><table><thead><tr><th>Company</th><th>Data source</th><th>Accounts due</th><th>Confirmation due</th></tr></thead><tbody>${appState.companies.map(c=>`<tr><td><div class="company-name">${escapeHtml(c.name)}</div><div class="company-number">${escapeHtml(c.number)}</div></td><td><span class="pill">${c.origin==='fictional_demo'?'Fictional demo':'Unverified manual'}</span></td><td>${c.accounts_due?fmt(c.accounts_due):'Not verified'}</td><td>${c.confirmation_due?fmt(c.confirmation_due):'Not verified'}</td></tr>`).join('')}</tbody></table></div></section>`}
function tax(){const companyOptions=appState.companies.map(c=>`<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)}</option>`).join('');return `<div class="columns"><section class="panel panel-pad"><div class="panel-topline"><h2>Self Assessment</h2><div class="panel-hint">You specify whether a return is required; we don't infer it.</div></div><div class="stack">${appState.years.map(y=>`<div class="mini-item"><div class="mini-symbol">◈</div><div><strong>Tax year ${y.start_year}–${String(y.start_year+1).slice(-2)}</strong><small>${y.required?'Self Assessment required':'Not marked required'}${y.second_payment?' · Second payment expected':''}</small></div></div>`).join('')||'<p class="muted">No personal tax years entered.</p>'}</div><div style="margin-top:22px">${button('＋ Add / edit tax year','year','quiet')}</div></section><section class="panel panel-pad"><h2>Corporation Tax periods</h2><div class="panel-hint">HMRC accounting periods are not always the same as company accounts periods.</div><div style="margin-top:18px">${appState.periods.map(p=>`<div class="mini-item"><div class="mini-symbol">▥</div><div><strong>${escapeHtml(appState.companies.find(c=>c.id===p.company_id)?.name||'Company')}</strong><small>Period ends ${fmt(p.period_end)} · ${p.required?'CT600 marked required':'Not marked required'}</small></div></div>`).join('')||'<p class="muted">No corporation tax periods.</p>'}</div><div style="margin-top:22px">${button('＋ Add CT period','period','quiet')}</div></section></div>`}
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
 if(type==='year')return ['Add / update personal tax year',base(`${input('start_year','Tax year starting 6 April','2025',true,'number')}${check('required','Self Assessment is required for this tax year')}${check('second_payment','I expect a second payment on account',false)}`)];
 if(type==='period')return ['Add Corporation Tax period',base(`<div class="form-field"><label for="company_id">Company</label><select id="company_id" name="company_id" required>${appState.companies.map(c=>`<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)}</option>`).join('')}</select></div>${input('period_end','HMRC accounting period end','',true,'date')}${check('required','CT600 return required for this period')}<p class="panel-hint">Standard deadlines only; special cases may differ.</p>`)];
 if(type==='task')return ['Add a task',base(`${input('title','Task title','Review example receipts')}${input('due','Target date','',true,'date')}`)];
 throw Error('Unsupported form');
}
function showModal(type){const [title,body]=modalBody(type);$('modal-title').textContent=title;$('modal-body').innerHTML=`<form id="record-form" class="form" data-type="${type}">${body}</form>`;$('modal-overlay').hidden=false;const first=$('record-form').querySelector('input,select');first?.focus();}
function closeModal(){$('modal-overlay').hidden=true;$('modal-body').innerHTML='';}
function mapForm(form){const d=new FormData(form);if(form.dataset.type==='company')return ['/api/companies',{name:d.get('name'),number:d.get('number')}];if(form.dataset.type==='year')return ['/api/years',{start_year:Number(d.get('start_year')),required:d.has('required'),second_payment:d.has('second_payment')}];if(form.dataset.type==='period')return ['/api/periods',{company_id:d.get('company_id'),period_end:d.get('period_end'),required:d.has('required')}];if(form.dataset.type==='task')return ['/api/tasks',{title:d.get('title'),due:d.get('due')}];throw Error('Unknown form');}

document.addEventListener('click',async e=>{
 const b=e.target.closest('button');if(!b)return;
 if(b.dataset.page)return navigate(b.dataset.page);
 if(b.dataset.nav)return navigate(b.dataset.nav);
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
getState().catch(err=>{$('page-view').textContent='Cannot load the local demo: '+err.message;});
