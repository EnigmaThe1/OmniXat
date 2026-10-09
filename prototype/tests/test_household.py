"""Persistent multi-person and multi-company schema acceptance tests with fake data."""
import importlib.util
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen,Request

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('household_app',ROOT/'app.py')
app=importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class HouseholdTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        app.DB=Path(self.tmp.name)/'family.sqlite3'
        app.init()
    def tearDown(self):
        self.tmp.cleanup()

    def test_two_people_independent_same_tax_year_and_scoped_deadlines(self):
        with app.connect() as c:
            app.mutate('/api/years',{'person_id':'demo-person-a','start_year':2026,'required':True,'second_payment':True},c)
            app.mutate('/api/years',{'person_id':'demo-person-b','start_year':2026,'required':True,'second_payment':False},c)
            a=app.state(c,'person:demo-person-a')
            b=app.state(c,'person:demo-person-b')
        self.assertEqual([r['person_id'] for r in a['years']],['demo-person-a','demo-person-a'])
        self.assertEqual([r['person_id'] for r in b['years']],['demo-person-b','demo-person-b'])
        self.assertIn(('payment','2028-07-31'), {(r['kind'],r['date']) for r in a['deadlines']})
        self.assertNotIn(('payment','2028-07-31'), {(r['kind'],r['date']) for r in b['deadlines']})
        self.assertEqual(len([y for y in a['years'] if y['start_year']==2026]),1)
        self.assertEqual(len([y for y in b['years'] if y['start_year']==2026]),1)

    def test_one_person_two_companies_two_people_one_company(self):
        with app.connect() as c:
            app.mutate('/api/companies',{'name':'Fictional Company Two Ltd','number':'MOCK0002'},c)
            co_id=c.execute('SELECT id FROM companies WHERE number="MOCK0002"').fetchone()[0]
            app.mutate('/api/company-roles',{'person_id':'demo-person-a','company_id':co_id,'role':'director'},c)
            r=app.state(c)['roles']
        self.assertEqual(len([x for x in r if x['person_id']=='demo-person-a']),2)
        self.assertEqual(len([x for x in r if x['company_id']=='demo-co']),2)
        self.assertEqual(len([x for x in r if x['company_id']==co_id]),1)

    def test_activity_and_question_isolation(self):
        with app.connect() as c:
            app.mutate('/api/activities',{'person_id':'demo-person-a','name':'Repair services demo'},c)
            added=c.execute('SELECT id FROM activities WHERE name="Repair services demo"').fetchone()[0]
            a=app.state(c,'person:demo-person-a')
            activity=app.state(c,'activity:'+added)
            b=app.state(c,'person:demo-person-b')
            self.assertEqual(len(activity['questions']),4)
            key=activity['questions'][0]['key']
            app.mutate('/api/questions/'+key+'/answer',{'answer':'yes'},c)
            self.assertEqual(app.state(c,'activity:'+added)['metrics']['unanswered'],3)
            self.assertEqual(app.state(c,'person:demo-person-a')['metrics']['unanswered'],4)
            self.assertEqual(app.state(c,'person:demo-person-b')['metrics']['unanswered'],4)
            self.assertEqual(len(a['questions']),4)
            self.assertEqual(len(b['questions']),4)

    def test_task_scope_and_activity_isolation(self):
        with app.connect() as c:
            app.mutate('/api/tasks',{'title':'Demo: prepare example invoices','due':'2027-01-03',
                                      'subject_type':'person','subject_id':'demo-person-b'},c)
            s1=app.state(c,'person:demo-person-a')
            s2=app.state(c,'person:demo-person-b')
        self.assertFalse(any(t['title']=='Demo: prepare example invoices' for t in s1['tasks']))
        self.assertTrue(any(t['title']=='Demo: prepare example invoices' for t in s2['tasks']))

    def test_filing_status_is_self_reported_and_needs_evidence(self):
        with app.connect() as c:
            info={'subject_type':'person','subject_id':'demo-person-a','kind':'self_assessment',
                  'period_key':'2025–26','status':'reported_submitted','evidence':''}
            with self.assertRaisesRegex(ValueError,'reference or evidence'):
                app.mutate('/api/filings',info,c)
            info['evidence']='FICTIONAL-DEMO-001'
            app.mutate('/api/filings',info,c)
            x=app.state(c,'person:demo-person-a')
            y=app.state(c,'person:demo-person-b')
            self.assertEqual(x['filings'][0]['status'],'reported_submitted')
            self.assertEqual(y['filings'],[])
            self.assertTrue(x['filing_enabled'] is False)
            info['status']='reported_accepted'
            app.mutate('/api/filings',info,c)
            self.assertEqual(len(app.state(c,'person:demo-person-a')['filings']),1)

    def test_invalid_subject_rejected_and_scope_validation(self):
        with app.connect() as c:
            with self.assertRaises(ValueError):app.state(c,'person:nonexistent')
            with self.assertRaises(ValueError):app.mutate('/api/years',{'person_id':'nosuch','start_year':2025,'required':True,'second_payment':False},c)
            with self.assertRaises(ValueError):app.mutate('/api/company-roles',{'person_id':'demo-person-a','company_id':'nosuch','role':'director'},c)
            with self.assertRaises(ValueError):app.mutate('/api/filings',{'subject_type':'company','subject_id':'demo-co','kind':'self_assessment','period_key':'2025','status':'preparing','evidence':''},c)

    def test_persistence_after_restart_preserves_people_and_relations(self):
        with app.connect() as c:
            app.mutate('/api/people',{'name':'Taylor Example (DEMO)'},c)
            person=c.execute('SELECT id FROM people WHERE name="Taylor Example (DEMO)"').fetchone()[0]
            app.mutate('/api/years',{'person_id':person,'start_year':2025,'required':True,'second_payment':False},c)
        app.init()  # idempotent schema upgrades and seeding
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM people WHERE id=?',(person,)).fetchone()[0],1)
            self.assertEqual(len(app.state(c,'person:'+person)['years']),1)
            self.assertEqual(len(app.state(c)['people']),3)

    def test_unassigned_v03_years_are_preserved_not_attributed(self):
        app.DB=Path(self.tmp.name)/'old.sqlite3'
        with sqlite3.connect(app.DB) as c:
            c.executescript('''
            CREATE TABLE companies(id TEXT PRIMARY KEY,number TEXT UNIQUE,name TEXT,origin TEXT,accounts_due TEXT,confirmation_due TEXT);
            CREATE TABLE years(start_year INTEGER PRIMARY KEY,required INTEGER,second_payment INTEGER);
            CREATE TABLE periods(id TEXT PRIMARY KEY,company_id TEXT,period_end TEXT,required INTEGER);
            CREATE TABLE questions(key TEXT PRIMARY KEY,topic TEXT,question TEXT,help TEXT,answer TEXT,updated_at TEXT);
            CREATE TABLE tasks(id TEXT PRIMARY KEY,title TEXT,due TEXT,completed INTEGER);
            CREATE TABLE activity(id INTEGER PRIMARY KEY AUTOINCREMENT,event TEXT,created_at TEXT);
            CREATE TABLE browser_runs(id TEXT PRIMARY KEY,payload TEXT,status TEXT,steps TEXT,receipt TEXT,created_at TEXT);
            CREATE TABLE portal_submissions(run_id TEXT PRIMARY KEY,receipt TEXT,created_at TEXT);
            ''')
            c.execute('INSERT INTO companies VALUES ("legacy-c","OLD00001","Older Fictional Company","manual_unverified",NULL,NULL)')
            c.execute('INSERT INTO years VALUES (2025,1,1)')
            c.execute('INSERT INTO activity(event,created_at) VALUES ("Earlier demonstration","2026-10-09")')
        app.init()
        with app.connect() as c:
            old=app.state(c)
            self.assertEqual(old['people'],[])
            self.assertEqual(old['years'],[])
            self.assertEqual(old['legacy_unassigned_years'][0]['start_year'],2025)
            self.assertEqual(old['deadlines'],[])
            self.assertEqual(old['companies'][0]['id'],'legacy-c')
            app.mutate('/api/people',{'name':'Demo replacement taxpayer'},c)
            ident=c.execute('SELECT id FROM people').fetchone()[0]
            app.mutate('/api/years',{'person_id':ident,'start_year':2025,'required':True,'second_payment':False},c)
            self.assertEqual(len(app.state(c,'person:'+ident)['years']),1)
            self.assertEqual(len(app.state(c)['legacy_unassigned_years']),1)

    def test_http_scope_and_export_filters(self):
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        try:
            base='http://127.0.0.1:'+str(server.server_port)
            with urlopen(base+'/api/state?scope=person%3Ademo-person-a') as r:
                person=json.load(r)
            with urlopen(base+'/api/state?scope=person%3Ademo-person-b') as r:
                spouse=json.load(r)
            with urlopen(base+'/api/calendar.ics?scope=person%3Ademo-person-a') as r:
                ics=r.read().decode()
            self.assertEqual(person['metrics']['deadlines'],1)
            self.assertEqual(spouse['metrics']['deadlines'],0)
            self.assertNotIn('Northstar',ics)
            self.assertIn('Alex Morgan',ics)
        finally:
            server.shutdown();server.server_close();t.join(timeout=3)

if __name__=='__main__':unittest.main()
