from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from test_customer_csv_review import CustomerCSVReviewFixture
from omnixat_core.csv_extract_worker import main


class CSVExtractWorkerFixture(CustomerCSVReviewFixture):
    def plan(self):
        return {'tenant':self.a,'organisation':str(self.org),'evidence':self.evidence,'job':str(self.job),
            'selections':[{'field_name':'amount','row':2,'column':2},
                          {'field_name':'missing_amount','row':3,'column':2}]}

    def run_worker(self,plan=None,dsn=None,raw=None):
        plan_file=Path(self.spool.name)/'extraction-plan.json'
        dsn_file=Path(self.spool.name)/'extraction.dsn'
        plan_file.write_text(raw if raw is not None else json.dumps(plan or self.plan()))
        dsn_file.write_text(dsn or self.extract_dsn)
        plan_file.chmod(0o600); dsn_file.chmod(0o600)
        output,error=StringIO(),StringIO()
        with patch.dict(os.environ,{'OMNIXAT_EXTRACTION_DSN_FILE':str(dsn_file)}),redirect_stdout(output),redirect_stderr(error):
            result=main(['--plan-file',str(plan_file)])
        return result,output.getvalue(),error.getvalue()


class CSVExtractWorkerTests(CSVExtractWorkerFixture):
    def test_cli_creates_durable_candidates_and_retry_receipt_for_customer(self):
        self.policy(); self.verdict('clean')
        first=self.run_worker(); self.assertEqual(first[0],0,first[2])
        self.assertEqual(first[2],''); receipt=json.loads(first[1])
        self.assertEqual(set(receipt),{'job_id','evidence_id','stored_at'})
        self.assertEqual(receipt['job_id'],str(self.job))
        self.assertEqual(self.run_worker()[1],first[1])
        data=self.review().json()['data']; self.assertEqual(data['job_id'],str(self.job))
        self.assertEqual(data['amounts'][0]['amount'],'12.00')
        self.assertEqual(len(data['questions']),1)
        self.assertEqual(self.rows('csv_extraction_results'),1)
        self.assertEqual(self.rows('evidence_quarantine'),1)

    def test_missing_policy_verdict_live_claim_and_wrong_scope_fail_closed(self):
        self.assertEqual(self.run_worker()[0],1)
        self.policy(); self.assertEqual(self.run_worker()[0],1)
        self.verdict('clean')
        self.owner.execute("INSERT INTO omnixat.evidence_scan_claims VALUES (%s,%s,'fictional-v1',%s,now()+interval '1 minute')",(self.a,self.evidence,uuid4()))
        self.assertEqual(self.run_worker()[0],1)
        self.owner.execute('DELETE FROM omnixat.evidence_scan_claims WHERE tenant_id=%s',(self.a,))
        self.assertEqual(self.run_worker(self.plan()|{'organisation':str(uuid4())})[0],1)
        self.assertEqual(self.run_worker(self.plan()|{'tenant':self.b})[0],1)
        self.verdict('blocked'); result,output,error=self.run_worker()
        self.assertEqual(result,1); self.assertEqual(output,'')
        self.assertNotIn(self.extract_dsn,error); self.assertEqual(self.rows('csv_extraction_results'),0)

    def test_same_job_changed_selection_conflicts_without_overwriting(self):
        self.policy(); self.verdict('clean'); self.assertEqual(self.run_worker()[0],0)
        plan=self.plan(); plan['selections'][0]['row']=3
        result,output,error=self.run_worker(plan)
        self.assertEqual(result,1); self.assertEqual(output,'')
        self.assertNotIn('12.00',error)
        self.assertEqual(self.review().json()['data']['amounts'][0]['amount'],'12.00')
        self.assertEqual(self.rows('csv_extraction_results'),1)

    def test_invalid_plan_precedes_connection_and_overprivileged_login_denies(self):
        with patch('omnixat_core.csv_extract_worker.psycopg.connect',side_effect=AssertionError('Must not connect')):
            self.assertEqual(self.run_worker(self.plan()|{'amount':'invented'})[0],1)
            self.assertEqual(self.run_worker(raw='{"tenant":"x","tenant":"y"}')[0],1)
            nested=self.run_worker(raw='['*2000+']'*2000)
            self.assertEqual(nested[0],1); self.assertEqual(nested[1],'')
            self.assertNotIn('Traceback',nested[2])
        self.policy(); self.verdict('clean')
        self.assertEqual(self.run_worker(dsn=self.runtime_dsn)[0],1)
        self.assertEqual(self.run_worker(dsn=self.owner_dsn)[0],1)
        self.assertEqual(self.rows('csv_extraction_results'),0)
