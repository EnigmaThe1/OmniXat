import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'app.py'
spec=importlib.util.spec_from_file_location('demo_app',path)
app=importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class DemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        app.DB=Path(self.tmp.name)/'test.sqlite3'
        app.init()

    def tearDown(self):
        self.tmp.cleanup()

    def test_sample_seed_contains_fictional_company(self):
        with app.connect() as c:
            s=app.state(c)
        self.assertTrue(s['demo'])
        self.assertFalse(s['filing_enabled'])
        self.assertEqual(s['metrics']['companies'],1)
        self.assertEqual(s['metrics']['unanswered'],12)
        self.assertEqual(s['companies'][0]['origin'],'fictional_demo')

    def test_complete_questionnaire(self):
        with app.connect() as c:
            for k in ('income','equipment','dividends','records'):
                app.mutate('/api/questions/'+k+'/answer',{'answer':'unsure'},c)
            s=app.state(c)
        self.assertEqual(s['metrics']['unanswered'],8)

    def test_company_and_duplicate_rejected(self):
        with app.connect() as c:
            app.mutate('/api/companies',{'name':'Mock Consulting Ltd','number':'MOCK0001'},c)
            with self.assertRaisesRegex(Exception,'UNIQUE'):
                app.mutate('/api/companies',{'name':'Mock Consulting Ltd','number':'MOCK0001'},c)
            c.rollback() # outer transaction includes original insert, so re-add for checking
        with app.connect() as c:
            app.mutate('/api/companies',{'name':'Mock Consulting Ltd','number':'MOCK0001'},c)
            s=app.state(c)
        self.assertEqual(s['metrics']['companies'],2)
        manual=[x for x in s['companies'] if x['number']=='MOCK0001'][0]
        self.assertIsNone(manual['accounts_due'])

    def test_tax_deadline_and_period(self):
        with app.connect() as c:
            app.mutate('/api/years',{'person_id':'demo-person-a','start_year':2026,'required':True,'second_payment':False},c)
            app.mutate('/api/periods',{'company_id':'demo-co','period_end':'2027-03-31','required':True},c)
            s=app.state(c)
        d={(x['kind'],x['date']) for x in s['deadlines']}
        self.assertIn(('self_assessment','2028-01-31'),d)
        self.assertIn(('corporation_payment','2028-01-01'),d)
        self.assertIn(('ct600','2028-03-31'),d)

    def test_second_payment_requires_assessment(self):
        with app.connect() as c:
            with self.assertRaises(ValueError):
                app.mutate('/api/years',{'person_id':'demo-person-a','start_year':2026,'required':False,'second_payment':True},c)

    def test_task_toggle_and_reset(self):
        with app.connect() as c:
            app.mutate('/api/tasks/demo-task-1/toggle',{},c)
            self.assertEqual(sum(x['completed'] for x in app.state(c)['tasks']),1)
            app.mutate('/api/reset',{},c)
            s=app.state(c)
        self.assertEqual(s['metrics']['companies'],1)
        self.assertEqual(s['metrics']['unanswered'],12)
        self.assertTrue(all(not t['completed'] for t in s['tasks']))

    def test_ics_valid_structure(self):
        with app.connect() as c:
            s=app.state(c)
        raw=app.calendar_ics(s['deadlines'])
        self.assertIn(b'BEGIN:VCALENDAR',raw)
        self.assertEqual(raw.count(b'BEGIN:VEVENT'),len(s['deadlines']))
        self.assertIn(b'DEMO:',raw)

    def test_date_checks(self):
        self.assertEqual(app.add_months(date(2026,12,31),9),date(2027,9,30))
        with self.assertRaises(ValueError):app.parse_date('2026-02-30')
        with self.assertRaises(ValueError):app.parse_date('../../etc/passwd')

    def test_http_serves_page_and_persists_api_state(self):
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(base+'/') as res:
                self.assertIn(b'OmniXat',res.read())
                self.assertEqual(res.headers.get('X-Frame-Options'),'DENY')
            with urllib.request.urlopen(base+'/api/state') as res:
                self.assertEqual(json.load(res)['metrics']['companies'],1)
            data=json.dumps({'title':'Demo test task','due':'2027-01-12'}).encode()
            req=urllib.request.Request(base+'/api/tasks',data=data,headers={'Content-Type':'application/json','X-OmniXat-Demo':'1'},method='POST')
            with urllib.request.urlopen(req) as res:
                self.assertEqual(json.load(res)['metrics']['open_tasks'],4)
            req=urllib.request.Request(base+'/api/tasks',data=data,headers={'Content-Type':'application/json'},method='POST')
            with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
            self.assertEqual(e.exception.code,403)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)

if __name__=='__main__':unittest.main()
