"""OmniXat demo family/workspace entities and subject-scoped records.

No accounts/authentication. Use fictional data only; filtering is NOT access control.
"""
from __future__ import annotations
from datetime import date, timedelta
import sqlite3
import uuid

TEMPLATES = [
    ('income', 'Income sources', 'Were all income sources recorded for this example?', 'Review every source before estimating taxable income.'),
    ('equipment', 'Equipment', 'Were any business tools, computers or equipment bought?', 'Tax treatment may differ from ordinary expenses.'),
    ('records', 'Records', 'Are all sample invoices and receipts accounted for?', 'Incomplete records require review.'),
    ('other', 'Other activities', 'Were there any additional activities or employers?', 'Personal returns may combine multiple income sources.'),
]
KINDS = {'self_assessment', 'corporation_tax', 'accounts', 'confirmation_statement', 'other'}
STATUSES = {'not_determined', 'preparing', 'ready_for_review', 'reported_submitted', 'reported_accepted', 'reported_rejected'}
ROLES = {'director', 'shareholder', 'employee', 'secretary', 'authorised_agent', 'other'}
SUBJECTS = {'person', 'company', 'activity'}

def uid():
    return str(uuid.uuid4())

def text(value, label, limit=140):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f'{label} must contain 1–{limit} characters.')
    return value.strip()

def existing(c, subject_type, subject_id):
    if subject_type not in SUBJECTS:
        raise ValueError('Choose a person, company or self-employment activity.')
    table={'person':'people', 'company':'companies','activity':'activities'}[subject_type]
    if not isinstance(subject_id,str) or not c.execute(f'SELECT 1 FROM {table} WHERE id=?', (subject_id,)).fetchone():
        raise ValueError('The chosen record does not exist.')

def scopes(c):
    options=[{'id':'all','label':'Entire workspace','type':'all'}]
    options += [{'id':'person:'+r['id'],'label':r['name'],'type':'person'} for r in c.execute('SELECT id,name FROM people ORDER BY name')]
    options += [{'id':'company:'+r['id'],'label':r['name'],'type':'company'} for r in c.execute('SELECT id,name FROM companies ORDER BY name')]
    options += [{'id':'activity:'+r['id'],'label':r['name']+' (self-employed)','type':'activity'} for r in c.execute('SELECT id,name FROM activities ORDER BY name')]
    return options

def split_scope(c, scope):
    if scope in (None,'','all'):
        return 'all',None
    if not isinstance(scope,str) or ':' not in scope:
        raise ValueError('Unknown workspace selection.')
    typ,identifier=scope.split(':',1)
    existing(c,typ,identifier)
    return typ,identifier

def ensure_schema(c):
    """Add v0.4 structures without changing legacy personal years or guessing an owner.

    A v0.3 'years' record is deliberately left unassigned; a human must create
    an explicitly person-scoped record after reviewing it.
    """
    c.executescript('''
    CREATE TABLE IF NOT EXISTS people (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS activities (id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(id), name TEXT NOT NULL, started_on TEXT,
        UNIQUE(person_id,name));
    CREATE TABLE IF NOT EXISTS company_roles (id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(id),
        company_id TEXT NOT NULL REFERENCES companies(id), role TEXT NOT NULL, UNIQUE(person_id,company_id,role));
    CREATE TABLE IF NOT EXISTS personal_years (person_id TEXT NOT NULL REFERENCES people(id), start_year INTEGER NOT NULL,
        required INTEGER NOT NULL, second_payment INTEGER NOT NULL, PRIMARY KEY (person_id,start_year));
    CREATE TABLE IF NOT EXISTS filings (id TEXT PRIMARY KEY, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
        kind TEXT NOT NULL, period_key TEXT NOT NULL, status TEXT NOT NULL, evidence TEXT NOT NULL,
        updated_at TEXT NOT NULL, UNIQUE(subject_type,subject_id,kind,period_key));
    ''')
    for table in ('tasks','questions','activity'):
        names={r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
        if 'subject_type' not in names:
            c.execute(f"ALTER TABLE {table} ADD COLUMN subject_type TEXT NOT NULL DEFAULT 'workspace'")
        if 'subject_id' not in names:
            c.execute(f'ALTER TABLE {table} ADD COLUMN subject_id TEXT')
    c.execute('PRAGMA user_version=4')

def add_questions(c,typ,identifier):
    for key,topic,question,help_text in TEMPLATES:
        token=typ+':'+identifier+':'+key
        c.execute('INSERT INTO questions (key,topic,question,help,subject_type,subject_id) VALUES (?,?,?,?,?,?)',
                  (token,topic,question,help_text,typ,identifier))

def seed(c,log):
    """Fictional demo people and relationships; called only on new/reset DB."""
    people=[('demo-person-a','Alex Morgan (DEMO)'),('demo-person-b','Sam Morgan (DEMO)')]
    for ident,name in people:
        c.execute('INSERT INTO people VALUES (?,?,?)',(ident,name,'2026-10-10'))
        add_questions(c,'person',ident)
        c.execute('INSERT INTO personal_years VALUES (?,?,?,?)',(ident,2025,1 if ident=='demo-person-a' else 0,0))
    c.execute('INSERT INTO activities VALUES (?,?,?,?)',('demo-activity-a','demo-person-a','Creative consulting (DEMO)','2025-04-06'))
    c.execute('INSERT INTO activities VALUES (?,?,?,?)',('demo-activity-b','demo-person-b','Craft services (DEMO)','2025-04-06'))
    c.execute('INSERT INTO company_roles VALUES (?,?,?,?)',('demo-role-a','demo-person-a','demo-co','director'))
    c.execute('INSERT INTO company_roles VALUES (?,?,?,?)',('demo-role-b','demo-person-b','demo-co','shareholder'))
    c.execute('INSERT INTO tasks (id,title,due,completed,subject_type,subject_id) VALUES (?,?,?,?,?,?)',
              ('demo-person-task','Check fictional personal expenses','2027-01-15',0,'person','demo-person-a'))
    log(c,'Created two fictional people and linked business profiles')

def mutate(c,path,data,log,parse_date):
    """Return True when mutation handled; none of these are live filings."""
    if path == '/api/people':
        name=text(data.get('name'),'Person name',100)
        ident=uid()
        c.execute('INSERT INTO people VALUES (?,?,datetime("now"))',(ident,name))
        add_questions(c,'person',ident)
        log(c,f'Added fictional person {name}','person',ident)
    elif path == '/api/activities':
        pid=data.get('person_id')
        existing(c,'person',pid)
        name=text(data.get('name'),'Activity name')
        ident=uid()
        c.execute('INSERT INTO activities VALUES (?,?,?,NULL)',(ident,pid,name))
        add_questions(c,'activity',ident)
        log(c,f'Added self-employment activity {name}','person',pid)
    elif path == '/api/company-roles':
        pid,cid=data.get('person_id'),data.get('company_id')
        existing(c,'person',pid)
        existing(c,'company',cid)
        role=data.get('role')
        if role not in ROLES:raise ValueError('Select a recognised company relationship.')
        c.execute('INSERT INTO company_roles VALUES (?,?,?,?)',(uid(),pid,cid,role))
        log(c,f'Added company relationship: {role}','company',cid)
    elif path == '/api/years':
        pid=data.get('person_id')
        existing(c,'person',pid)
        year=data.get('start_year')
        if type(year) is not int or not 2020 <= year <= 2098:
            raise ValueError('Enter a valid tax-year starting year.')
        required=data.get('required')
        second=data.get('second_payment')
        if type(required) is not bool or type(second) is not bool:
            raise ValueError('Tax year flags must be true or false.')
        if second and not required:raise ValueError('Second payment requires a declared Self Assessment obligation.')
        c.execute('INSERT INTO personal_years VALUES (?,?,?,?) ON CONFLICT(person_id,start_year) DO UPDATE SET '
                  'required=excluded.required,second_payment=excluded.second_payment',(pid,year,int(required),int(second)))
        log(c,f'Updated personal tax year {year}–{year+1}','person',pid)
    elif path == '/api/filings':
        typ,ident=data.get('subject_type'),data.get('subject_id')
        existing(c,typ,ident)
        kind,status=data.get('kind'),data.get('status')
        if kind not in KINDS or status not in STATUSES:
            raise ValueError('Unknown return type or evidence status.')
        if typ=='person' and kind in ('corporation_tax','accounts','confirmation_statement'):
            raise ValueError('Company returns must be linked to a company.')
        if typ=='company' and kind=='self_assessment':
            raise ValueError('Self Assessment must be linked to a person.')
        if typ=='activity' and kind!='other':
            raise ValueError('Tax filings for a self-employed activity are recorded under its person.')
        period=text(data.get('period_key'),'Return period',32)
        evidence=data.get('evidence','')
        if not isinstance(evidence,str) or len(evidence)>240:
            raise ValueError('Evidence notes must be 240 characters or fewer.')
        evidence=evidence.strip()
        if status.startswith('reported_') and not evidence:
            raise ValueError('Enter a fictional reference or evidence note for a reported submission outcome.')
        c.execute('INSERT INTO filings VALUES (?,?,?,?,?,?,?,datetime("now")) ON CONFLICT(subject_type,subject_id,kind,period_key) '
                  'DO UPDATE SET status=excluded.status,evidence=excluded.evidence,updated_at=excluded.updated_at',
                  (uid(),typ,ident,kind,period,status,evidence))
        log(c,f'Updated {kind.replace("_"," ")} status: {status.replace("_"," ")} (self-reported demo only)',typ,ident)
    else:
        return False
    return True

def build_state(c,scope,helpers):
    """Return scoped dashboard data and unfiltered picker catalogues.

    This is UI isolation in a no-auth demo, NOT a security boundary.
    """
    deadline,add_months,now_uk,browser_state=helpers
    kind,ident=split_scope(c,scope)
    companies=[dict(r) for r in c.execute('SELECT * FROM companies ORDER BY name')]
    people=[dict(r) for r in c.execute('SELECT * FROM people ORDER BY name')]
    activities=[dict(r) for r in c.execute('SELECT * FROM activities ORDER BY name')]
    roles=[dict(r) for r in c.execute('SELECT * FROM company_roles')]
    years=[dict(r) for r in c.execute('SELECT * FROM personal_years ORDER BY start_year DESC,person_id')]
    periods=[dict(r) for r in c.execute('SELECT * FROM periods ORDER BY period_end DESC')]
    filings=[dict(r) for r in c.execute('SELECT * FROM filings ORDER BY updated_at DESC')]
    questions=[dict(r) for r in c.execute('SELECT * FROM questions ORDER BY rowid')]
    tasks=[dict(r) for r in c.execute('SELECT * FROM tasks ORDER BY completed,due')]
    history=[dict(r) for r in c.execute('SELECT * FROM activity ORDER BY id DESC LIMIT 100')]
    person_names={p['id']:p['name'] for p in people}
    companies_by_id={p['id']:p for p in companies}
    activities_by_id={a['id']:a for a in activities}
    def scope_match(record):
        if kind=='all':return True
        return record.get('subject_type')==kind and record.get('subject_id')==ident
    qs=[q for q in questions if scope_match(q)]
    ts=[t for t in tasks if scope_match(t)]
    hs=[h for h in history if scope_match(h)][:12]
    fy=[f for f in filings if scope_match(f)]
    ys=[y for y in years if kind=='all' or (kind=='person' and y['person_id']==ident)]
    ps=[p for p in periods if kind=='all' or (kind=='company' and p['company_id']==ident)]
    selected_cos=[co for co in companies if kind=='all' or (kind=='company' and co['id']==ident)]
    deadlines=[]
    for co in selected_cos:
        for label,field,dtkind in [('Annual accounts','accounts_due','accounts'),('Confirmation statement','confirmation_due','confirmation')]:
            if co[field]:
                d=deadline(dtkind,label,co[field],co['name'],'fictional demonstration date' if co['origin']=='fictional_demo' else 'unverified manual date','Not an official filing-status check.')
                d.update(subject_type='company',subject_id=co['id'])
                deadlines.append(d)
    for y in ys:
        if not y['required']:continue
        for k,label,raw in [('self_assessment',f'Self Assessment {y["start_year"]}–{str(y["start_year"]+1)[-2:]}',f'{y["start_year"]+2}-01-31'),
                            ('payment','Second payment on account',f'{y["start_year"]+2}-07-31')]:
            if k=='payment' and not y['second_payment']:continue
            d=deadline(k,label,raw,person_names.get(y['person_id'],'Unknown person'),'user-declared standard rule','Verify applicability and HMRC notices; MTD obligations can differ.')
            d.update(subject_type='person',subject_id=y['person_id'])
            deadlines.append(d)
    for p in ps:
        if not p['required'] or p['company_id'] not in companies_by_id:continue
        company=companies_by_id[p['company_id']]
        end=date.fromisoformat(p['period_end'])
        for dk,label,due in [('corporation_payment','Corporation Tax payment',(add_months(end,9)+timedelta(days=1)).isoformat()),
                              ('ct600','CT600 return',add_months(end,12).isoformat())]:
            d=deadline(dk,label,due,company['name'],'user-declared standard rule','Standard small-company rule only; check HMRC notices and exceptions.')
            d.update(subject_type='company',subject_id=p['company_id'])
            deadlines.append(d)
    deadlines.sort(key=lambda row:(row['date'],row['title'],row['entity']))
    legacy_years=[dict(x) for x in c.execute('SELECT * FROM years ORDER BY start_year DESC')]
    return {
        'scope': 'all' if kind=='all' else f'{kind}:{ident}',
        'scope_options':scopes(c), 'people':people, 'companies':companies,
        'activities':activities, 'roles':roles, 'years':ys, 'periods':ps, 'filings':fy,
        'questions':qs, 'tasks':ts, 'activity':hs, 'deadlines':deadlines,
        'legacy_unassigned_years':legacy_years if kind=='all' else [],
        'today':now_uk().date().isoformat(), 'demo':True, 'filing_enabled':False,
        'browser':browser_state(c) if kind=='all' else {'enabled':False,'mode':'workspace_only','latest':None,'preview_available':False},
        'metrics': {'companies':len(selected_cos), 'people':len(people) if kind=='all' else (1 if kind=='person' else 0),
                    'deadlines':len(deadlines),'unanswered':sum(q['answer'] is None for q in qs),
                    'open_tasks':sum(not t['completed'] for t in ts), 'filings':len(fy)}
    }
