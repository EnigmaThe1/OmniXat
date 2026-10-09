"""OmniXat interactive prototype — local-only, demo data, no external integrations.

Start: python app.py (Python 3.11+). No external packages needed.
Never expose this demo HTTP server to a public network or enter real tax data.
"""
import argparse
import browser_lab
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DB = Path(os.getenv('OMNIXAT_DEMO_DB', str(ROOT / 'demo.sqlite3')))
LOCK = threading.RLock()
BROWSER_LOCK = threading.Lock()
PREVIEW_NAME = 'demo-browser-preview.png'
QUESTIONS = [
    ('income', 'Income sources', 'Did the sample business receive income outside the main business account?', 'Business income from all sources may need reviewing.'),
    ('equipment', 'Business equipment', 'Were any tools, computers or equipment purchased during the sample period?', 'Equipment may require specific accounting or tax treatment.'),
    ('dividends', 'Director dividends', 'Did the sample company pay any dividends to its directors?', 'Dividends need to be recorded separately from salaries.'),
    ('records', 'Records completeness', 'Have all sample invoices and receipts been collected?', 'Missing evidence should be resolved before preparing a return.'),
]

def now_uk():
    return datetime.now(ZoneInfo('Europe/London'))

def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=8)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

def log(c, event):
    c.execute('INSERT INTO activity (event,created_at) VALUES (?,?)', (event, now_uk().isoformat(timespec='seconds')))

def init():
    with LOCK, connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS companies (id TEXT PRIMARY KEY, number TEXT NOT NULL UNIQUE, name TEXT NOT NULL, origin TEXT NOT NULL, accounts_due TEXT, confirmation_due TEXT);
        CREATE TABLE IF NOT EXISTS years (start_year INTEGER PRIMARY KEY, required INTEGER NOT NULL, second_payment INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS periods (id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id), period_end TEXT NOT NULL, required INTEGER NOT NULL, UNIQUE(company_id,period_end));
        CREATE TABLE IF NOT EXISTS questions (key TEXT PRIMARY KEY, topic TEXT NOT NULL, question TEXT NOT NULL, help TEXT NOT NULL, answer TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL, due TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS browser_runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL, steps TEXT NOT NULL, receipt TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS portal_submissions (run_id TEXT PRIMARY KEY REFERENCES browser_runs(id), receipt TEXT NOT NULL, created_at TEXT NOT NULL);
        
        ''')
        if not c.execute('SELECT count(*) FROM companies').fetchone()[0] and not c.execute('SELECT count(*) FROM activity').fetchone()[0]:
            seed(c)

def seed(c):
    c.execute('INSERT INTO companies VALUES (?,?,?,?,?,?)', ('demo-co', 'DEMO0001', 'Northstar Studio Ltd (DEMO)', 'fictional_demo', '2027-09-30', '2027-04-12'))
    c.execute('INSERT INTO years VALUES (?,?,?)', (2025, 1, 1))
    c.execute('INSERT INTO periods VALUES (?,?,?,?)', ('demo-ct', 'demo-co', '2026-12-31', 1))
    for key, topic, q, help_text in QUESTIONS:
        c.execute('INSERT INTO questions (key,topic,question,help) VALUES (?,?,?,?)', (key, topic, q, help_text))
    c.execute('INSERT INTO tasks VALUES (?,?,?,?)', ('demo-task-1', 'Review the four guided questions', '2026-11-01', 0))
    c.execute('INSERT INTO tasks VALUES (?,?,?,?)', ('demo-task-2', 'Check fictional company records', '2026-11-15', 0))
    log(c, 'Sample workspace created with fictional information')

def parse_date(s):
    if not isinstance(s, str):
        raise ValueError('Enter a date in YYYY-MM-DD format.')
    try:
        v = date.fromisoformat(s)
    except ValueError as exc:
        raise ValueError('Invalid date. Use YYYY-MM-DD.') from exc
    if not 2020 <= v.year <= 2100:
        raise ValueError('Date is outside the demo-supported range.')
    return v

def add_months(d, months):
    from calendar import monthrange
    i = d.year * 12 + d.month - 1 + months
    y, m = divmod(i, 12)
    m += 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))

def deadline(kind, title, raw_date, entity, source, note):
    d = date.fromisoformat(raw_date)
    today = now_uk().date()
    status = 'past-unverified' if d < today else 'soon' if d <= today + timedelta(days=30) else 'scheduled'
    return {'kind':kind,'title':title,'date':raw_date,'entity':entity,'source':source,'note':note,'status':status}

def state(c):
    co = [dict(x) for x in c.execute('SELECT * FROM companies ORDER BY name')]
    yrs = [dict(x) for x in c.execute('SELECT * FROM years ORDER BY start_year DESC')]
    periods = [dict(x) for x in c.execute('SELECT * FROM periods ORDER BY period_end DESC')]
    qs = [dict(x) for x in c.execute('SELECT * FROM questions ORDER BY rowid')]
    tasks = [dict(x) for x in c.execute('SELECT * FROM tasks ORDER BY completed, due')]
    history = [dict(x) for x in c.execute('SELECT * FROM activity ORDER BY id DESC LIMIT 9')]
    by_id = {x['id']:x for x in co}
    dates=[]
    for item in co:
        if item['accounts_due']:
            dates.append(deadline('accounts','Annual accounts',item['accounts_due'],item['name'],'fictional demonstration date' if item['origin']=='fictional_demo' else 'manually entered unverified date','Not obtained from Companies House; confirm official dates.'))
        if item['confirmation_due']:
            dates.append(deadline('confirmation','Confirmation statement',item['confirmation_due'],item['name'],'fictional demonstration date' if item['origin']=='fictional_demo' else 'manually entered unverified date','Not obtained from Companies House; confirm official dates.'))
    for y in yrs:
        if y['required']:
            dates.append(deadline('self_assessment',f"Self Assessment {y['start_year']}–{str(y['start_year']+1)[-2:]}", f"{y['start_year']+2}-01-31",'Personal','user-declared standard rule','May differ if HMRC issued a different deadline; check MTD obligations.'))
            if y['second_payment']:
                dates.append(deadline('payment', 'Second payment on account', f"{y['start_year']+2}-07-31",'Personal','user-declared standard rule','Verify amount and applicability with HMRC.'))
    for period in periods:
        if not period['required']:
            continue
        comp=by_id.get(period['company_id'])
        if not comp:
            continue
        end=date.fromisoformat(period['period_end'])
        dates.append(deadline('corporation_payment','Corporation Tax payment', (add_months(end,9)+timedelta(days=1)).isoformat(),comp['name'],'user-declared standard rule','Standard small-company rule, not appropriate for every company.'))
        dates.append(deadline('ct600','CT600 return', add_months(end,12).isoformat(),comp['name'],'user-declared standard rule','Check the actual HMRC accounting period and HMRC notices.'))
    dates.sort(key=lambda x:(x['date'],x['title']))
    return {'companies':co,'years':yrs,'periods':periods,'questions':qs,'tasks':tasks,'activity':history,'deadlines':dates,
            'today':now_uk().date().isoformat(), 'demo':True,'filing_enabled':False,
            'browser': browser_state(c), 'metrics':{'companies':len(co),'deadlines':len(dates),'unanswered':sum(q['answer'] is None for q in qs),'open_tasks':sum(not t['completed'] for t in tasks)}}

def browser_state(c):
    row = c.execute('SELECT id,payload,status,steps,receipt,created_at FROM browser_runs ORDER BY created_at DESC LIMIT 1').fetchone()
    latest = dict(row) if row else None
    if latest:
        latest['payload'] = json.loads(latest['payload'])
        latest['steps'] = json.loads(latest['steps'])
    return {'enabled': browser_lab.available(), 'mode': 'allowlisted_local_demo_only',
            'latest': latest, 'preview_available': bool(row and (DB.parent / PREVIEW_NAME).is_file())}


def browser_action(path, data, port):
    """Browser run is intentionally outside the SQLite lock; the practice portal
    makes a separate request to the same server to store a DEMO receipt.
    """
    if path == '/api/demo-portal/submissions':
        # Allow this nested request while Playwright runs under BROWSER_LOCK.
        run_id = data.get('run_id')
        if not isinstance(run_id,str) or not re.fullmatch(r'[0-9a-f-]{36}',run_id):
            raise ValueError('Invalid practice run ID.')
        payload = browser_lab.normalise(data)
        with LOCK,connect() as c:
            row = c.execute('SELECT payload,status FROM browser_runs WHERE id=?',(run_id,)).fetchone()
            if not row or row['status']!='approved_demo' or json.loads(row['payload'])!=payload:
                raise ValueError('This practice form is not approved for a matching run.')
            if c.execute('SELECT 1 FROM portal_submissions WHERE run_id=?',(run_id,)).fetchone():
                raise ValueError('This practice record was already submitted.')
            receipt='DEMO-'+run_id.split('-')[0].upper()
            c.execute('INSERT INTO portal_submissions VALUES (?,?,?)',(run_id,receipt,now_uk().isoformat()))
        return {'receipt':receipt}
    if not BROWSER_LOCK.acquire(blocking=False):
        raise ValueError('A Browser Lab action is already running; retry after it completes.')
    try:
        if path == '/api/browser/run':
            if data.get('fictional_only') is not True:
                raise ValueError('Confirm this workflow uses fictional data only.')
            payload = browser_lab.normalise(data)
            run_id = str(uuid.uuid4())
            with LOCK, connect() as c:
                c.execute('INSERT INTO browser_runs VALUES (?,?,?,?,?,?)',
                          (run_id, json.dumps(payload), 'preparing', '[]', None, now_uk().isoformat(timespec='microseconds')))
                log(c, 'Started local Browser Lab practice workflow')
            outcome = browser_lab.execute(port=port, run_id=run_id, payload=payload)
            with LOCK, connect() as c:
                c.execute('UPDATE browser_runs SET status=?, steps=? WHERE id=?',
                          (outcome['status'], json.dumps(outcome['steps']), run_id))
                log(c, 'Browser verified the local practice portal; demo submission awaiting approval')
            (DB.parent / PREVIEW_NAME).write_bytes(outcome['screenshot'])
        elif path == '/api/browser/approve':
            if data.get('approve_demo_submission') is not True:
                raise ValueError('Explicit demo-submission approval is required.')
            run_id = data.get('run_id')
            if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f-]{36}',run_id):
                raise ValueError('Invalid practice run ID.')
            with LOCK,connect() as c:
                row = c.execute('SELECT payload,status FROM browser_runs WHERE id=?',(run_id,)).fetchone()
                if not row:
                    raise ValueError('Browser practice run not found.')
                if row['status'] != 'awaiting_approval':
                    raise ValueError('This practice run is not waiting for approval.')
                if c.execute('SELECT 1 FROM portal_submissions WHERE run_id=?',(run_id,)).fetchone():
                    raise ValueError('Practice record already submitted; no repeat submission.')
                payload=json.loads(row['payload'])
                c.execute('UPDATE browser_runs SET status=? WHERE id=?', ('approved_demo',run_id))
                log(c, 'Owner explicitly approved local demonstration-only submission')
            outcome = browser_lab.execute(port=port,run_id=run_id,payload=payload,submit=True,offline_submit=lambda body: browser_action('/api/demo-portal/submissions', body, port))
            with LOCK,connect() as c:
                receipt = c.execute('SELECT receipt FROM portal_submissions WHERE run_id=?',(run_id,)).fetchone()
                if not receipt or receipt[0] != outcome['receipt']:
                    raise RuntimeError('Practice receipt was not persisted as expected.')
                c.execute('UPDATE browser_runs SET status=?,receipt=?,steps=? WHERE id=?',
                          (outcome['status'], receipt[0],json.dumps(outcome['steps']),run_id))
                log(c, 'Approved and completed local-only demo portal submission')
            (DB.parent / PREVIEW_NAME).write_bytes(outcome['screenshot'])
        else:
            raise KeyError('Unknown browser action')
        with LOCK,connect() as c:
            return state(c)
    finally:
        BROWSER_LOCK.release()


def require_text(v, field, limit=140):
    if not isinstance(v,str) or not v.strip() or len(v)>limit:
        raise ValueError(f'{field} must be between 1 and {limit} characters.')
    return v.strip()

def validate_bool(v,field):
    if type(v) is not bool:
        raise ValueError(f'{field} must be true or false.')
    return int(v)

def mutate(path, data, c):
    if path == '/api/companies':
        name=require_text(data.get('name'),'Company name')
        number=require_text(data.get('number'),'Company number',8).upper()
        if not re.fullmatch('[A-Z0-9]{8}',number):
            raise ValueError('Company number must contain eight letters or digits.')
        c.execute('INSERT INTO companies VALUES (?,?,?,?,?,?)',(str(uuid.uuid4()),number,name,'manual_unverified',None,None))
        log(c,f'Added unverified company {name}')
    elif path == '/api/years':
        y=data.get('start_year')
        if type(y) is not int or not 2020 <= y <= 2098:
            raise ValueError('Enter a valid tax-year starting year.')
        required=validate_bool(data.get('required'),'Self Assessment required')
        second=validate_bool(data.get('second_payment'),'Second payment')
        if second and not required:
            raise ValueError('Second payment requires Self Assessment applicability.')
        c.execute('INSERT INTO years VALUES (?,?,?) ON CONFLICT(start_year) DO UPDATE SET required=excluded.required,second_payment=excluded.second_payment',(y,required,second))
        log(c,f'Updated Self Assessment period {y}–{y+1}')
    elif path == '/api/periods':
        company_id=require_text(data.get('company_id'),'Company ID')
        if not c.execute('SELECT 1 FROM companies WHERE id=?',(company_id,)).fetchone():
            raise ValueError('Select an existing company.')
        end=parse_date(data.get('period_end'))
        required=validate_bool(data.get('required'),'CT600 required')
        c.execute('INSERT INTO periods VALUES (?,?,?,?)',(str(uuid.uuid4()),company_id,end.isoformat(),required))
        log(c,f'Added corporation tax accounting period ending {end.isoformat()}')
    elif path == '/api/tasks':
        title=require_text(data.get('title'),'Task title')
        due=parse_date(data.get('due')).isoformat()
        c.execute('INSERT INTO tasks VALUES (?,?,?,0)',(str(uuid.uuid4()),title,due))
        log(c,f'Created task: {title}')
    elif path.startswith('/api/tasks/') and path.endswith('/toggle'):
        ident=path.removeprefix('/api/tasks/').removesuffix('/toggle')
        if not c.execute('SELECT 1 FROM tasks WHERE id=?',(ident,)).fetchone():
            raise ValueError('Task not found.')
        c.execute('UPDATE tasks SET completed = 1 - completed WHERE id=?',(ident,))
        log(c,'Changed demo task completion')
    elif path.startswith('/api/questions/') and path.endswith('/answer'):
        key=path.removeprefix('/api/questions/').removesuffix('/answer')
        val=data.get('answer')
        if val not in ('yes','no','unsure'):
            raise ValueError('Answer must be yes, no or unsure.')
        res=c.execute('UPDATE questions SET answer=?, updated_at=? WHERE key=?',(val,now_uk().isoformat(timespec='seconds'),key))
        if res.rowcount != 1:
            raise ValueError('Question not found.')
        log(c,f'Answered guided question: {key}')
    elif path == '/api/reset':
        for table in ('portal_submissions','browser_runs','periods','years','companies','questions','tasks','activity'):
            c.execute(f'DELETE FROM {table}')
        seed(c)
        (DB.parent / PREVIEW_NAME).unlink(missing_ok=True)
    else:
        raise KeyError('Unknown action.')

def calendar_ics(items):
    def escape(s):
        return str(s).replace('\\','\\\\').replace(';','\\;').replace(',','\\,').replace('\n','\\n')
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//OmniXat//Local Demo//EN','CALSCALE:GREGORIAN','X-WR-CALNAME:OmniXat Demo Deadlines']
    for i,d in enumerate(items):
        stamp=date.fromisoformat(d['date']).strftime('%Y%m%d')
        lines+=['BEGIN:VEVENT',f'UID:omnixat-demo-{i}-{stamp}@localhost',f'DTSTART;VALUE=DATE:{stamp}',
                f'SUMMARY:{escape("DEMO: "+d["title"])}', f'DESCRIPTION:{escape(d["entity"]+" | "+d["note"])}','END:VEVENT']
    lines.append('END:VCALENDAR')
    return ('\r\n'.join(lines)+'\r\n').encode()

class Handler(BaseHTTPRequestHandler):
    server_version='OmniXatDemo/0.3'
    def log_message(self,fmt,*args):
        pass
    def send_bytes(self,status,content,mime):
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(content)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(content)
    def json(self,status,body):
        self.send_bytes(status,json.dumps(body,default=str).encode('utf8'),'application/json; charset=utf-8')
    def do_GET(self):
        path=urlparse(self.path).path
        if path in ('/','/index.html'):
            return self.send_bytes(200,(ROOT/'static/index.html').read_bytes(),'text/html; charset=utf-8')
        if path=='/static/app.js':
            return self.send_bytes(200,(ROOT/'static/app.js').read_bytes(),'text/javascript; charset=utf-8')
        if path=='/static/styles.css':
            return self.send_bytes(200,(ROOT/'static/styles.css').read_bytes(),'text/css; charset=utf-8')
        if path=='/demo-portal':
            return self.send_bytes(200,(ROOT/'static/demo-portal.html').read_bytes(),'text/html; charset=utf-8')
        if path=='/static/demo-portal.css':
            return self.send_bytes(200,(ROOT/'static/demo-portal.css').read_bytes(),'text/css; charset=utf-8')
        if path=='/static/demo-portal.js':
            return self.send_bytes(200,(ROOT/'static/demo-portal.js').read_bytes(),'text/javascript; charset=utf-8')
        if path=='/api/browser/preview':
            fp=DB.parent / PREVIEW_NAME
            if not fp.is_file():
                return self.json(404,{'error':'No browser preview has been produced.'})
            return self.send_bytes(200,fp.read_bytes(),'image/png')
        if path in ('/api/state','/api/calendar.ics','/api/health'):
            if path=='/api/health':
                return self.json(200,{'status':'ok','demo':True})
            with LOCK,connect() as c:
                s=state(c)
            if path=='/api/calendar.ics':
                return self.send_bytes(200,calendar_ics(s['deadlines']),'text/calendar; charset=utf-8')
            return self.json(200,s)
        return self.json(404,{'error':'Not found'})
    def do_POST(self):
        path=urlparse(self.path).path
        if not path.startswith('/api/'):
            return self.json(404,{'error':'Not found'})
        if self.headers.get('X-OmniXat-Demo')!='1':
            return self.json(403,{'error':'Missing demo request header.'})
        length=self.headers.get('Content-Length','0')
        if not length.isdigit() or int(length)>8192:
            return self.json(413,{'error':'Request too large.'})
        try:
            data=json.loads(self.rfile.read(int(length)))
            if not isinstance(data,dict):
                raise ValueError('Expected JSON object.')
            if path in ('/api/browser/run','/api/browser/approve','/api/demo-portal/submissions'):
                return self.json(200,browser_action(path,data,self.server.server_address[1]))
            with LOCK,connect() as c:
                mutate(path,data,c)
                result=state(c)
            return self.json(200,result)
        except RuntimeError as exc:
            return self.json(503,{'error':str(exc)})
        except (ValueError,sqlite3.IntegrityError) as exc:
            return self.json(400,{'error':str(exc) if not isinstance(exc,sqlite3.IntegrityError) else 'A record with these details already exists.'})
        except KeyError:
            return self.json(404,{'error':'Unknown action.'})
        except json.JSONDecodeError:
            return self.json(400,{'error':'Invalid JSON.'})

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--host',default='127.0.0.1',help='Loopback only by default. Use 0.0.0.0 only INSIDE a container with localhost port publishing.')
    args=parser.parse_args()
    init()
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    print(f'OmniXat local prototype: http://127.0.0.1:{args.port} (demo data only)',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
