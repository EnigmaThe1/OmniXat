"""Real HTTP plus real Chromium local practice workflow; no external sites."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from browser_lab import normalise, available

class BrowserLabTests(unittest.TestCase):
    def test_exact_amount_validation_and_no_browser_url(self):
        valid = normalise({'company':'Example Demo Ltd','period':'2026-12-31','amount':'1.50'})
        self.assertEqual(valid['amount'],'1.50')
        for amount in ('NaN','Infinity','-1','0.001','100000000','£100'):
            with self.assertRaises(ValueError):
                normalise({'company':'Example Demo Ltd','period':'2026-12-31','amount':amount})
        with self.assertRaises(ValueError):
            normalise({'company':'Example Demo Ltd','period':'2026-13-31','amount':'1.00'})

    @unittest.skipUnless(available(), 'Playwright not installed')
    def test_local_browser_review_requires_approval_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            import socket
            sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
            env=dict(os.environ,OMNIXAT_DEMO_DB=str(Path(tmp)/'state.sqlite3'))
            proc=subprocess.Popen([sys.executable,str(ROOT/'app.py'),'--port',str(port)],cwd=ROOT,env=env,
                                  stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            url=f'http://127.0.0.1:{port}'
            def get(path):
                with urlopen(url+path,timeout=20) as resp:
                    return resp.read()
            def post(path,data):
                request=Request(url+path,method='POST',data=json.dumps(data).encode(),
                                headers={'Content-Type':'application/json','X-OmniXat-Demo':'1'})
                try:
                    with urlopen(request,timeout=35) as resp:
                        return resp.status,json.load(resp)
                except HTTPError as err:
                    return err.code,json.loads(err.read())
            try:
                for _ in range(60):
                    try:
                        json.loads(get('/api/health'));break
                    except Exception:time.sleep(.1)
                else: self.fail('HTTP server did not start')
                self.assertIn(b'Practice Filing Portal',get('/demo-portal'))
                payload={'company':'Synthetic Company Ltd','period':'2027-03-31','amount':'144.45','fictional_only':True}
                code,first=post('/api/browser/run',payload)
                self.assertEqual(code,200,first)
                record=first['browser']['latest']
                self.assertEqual(record['status'],'awaiting_approval')
                self.assertEqual(record['payload']['amount'],'144.45')
                self.assertTrue(first['browser']['preview_available'])
                self.assertTrue(get('/api/browser/preview').startswith(b'\x89PNG'))
                code,unapproved=post('/api/demo-portal/submissions',{'run_id':record['id'],**record['payload']})
                self.assertEqual(code,400,unapproved)
                code,denied=post('/api/browser/approve',{'run_id':record['id'],'approve_demo_submission':False})
                self.assertEqual(code,400,denied)
                code,done=post('/api/browser/approve',{'run_id':record['id'],'approve_demo_submission':True})
                self.assertEqual(code,200,done)
                self.assertEqual(done['browser']['latest']['status'],'demo_submitted')
                self.assertTrue(done['browser']['latest']['receipt'].startswith('DEMO-'))
                self.assertTrue(get('/api/browser/preview').startswith(b'\x89PNG'))
                code,dupe=post('/api/browser/approve',{'run_id':record['id'],'approve_demo_submission':True})
                self.assertEqual(code,400,dupe)
                code,reset=post('/api/reset',{})
                self.assertEqual(code,200,reset)
                self.assertIsNone(reset['browser']['latest'])
                self.assertFalse(reset['browser']['preview_available'])
            finally:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill()
                if proc.stderr:
                    error=proc.stderr.read().decode('utf8','replace')
                    if error:print('Browser Lab subprocess error:',error[:1200])

if __name__=='__main__':unittest.main()
