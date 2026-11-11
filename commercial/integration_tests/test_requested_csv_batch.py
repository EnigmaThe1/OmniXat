"""Fictional customer requests dispatched by the actual bounded worker CLI."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import psycopg
from test_csv_request_lifecycle import CSVRequestLifecycleFixture
from omnixat_core.csv_extract_worker import main, requested_batch
from omnixat_core.evidence_extraction_postgres import EvidenceNotEligible


class RequestedCSVBatchTests(CSVRequestLifecycleFixture):
    def prepare(self):
        self.ready()
        first=self.plan()
        second=first|{'job':str(uuid4())}
        for plan in [first,second]:
            response=self.request({'job_id':plan['job'],'selections':plan['selections']})
            self.assertEqual(response.status_code,202,response.text)
        return [first,second]

    def batch_cli(self,plans=None,raw=None,requested=True,dsn=None):
        manifest=Path(self.spool.name)/'batch.json'
        secret=Path(self.spool.name)/'batch.dsn'
        manifest.write_text(raw if raw is not None else json.dumps(plans))
        secret.write_text(dsn or self.requested_worker_dsn)
        manifest.chmod(0o600); secret.chmod(0o600)
        output,error=StringIO(),StringIO()
        with patch.dict(os.environ,{'OMNIXAT_EXTRACTION_DSN_FILE':str(secret)}),redirect_stdout(output),redirect_stderr(error):
            status=main(['--batch-file',str(manifest)]+(['--requested'] if requested else []))
        return status,output.getvalue(),error.getvalue()

    def test_cli_receipts_retries_and_customer_review(self):
        plans=self.prepare()
        first=self.batch_cli(plans)
        self.assertEqual(first[0],0,first[2]); self.assertEqual(first[2],'')
        receipts=[json.loads(line) for line in first[1].splitlines()]
        self.assertEqual([r['job_id'] for r in receipts],[p['job'] for p in plans])
        self.assertTrue(all(set(r)=={'job_id','evidence_id','stored_at'} for r in receipts))
        self.assertEqual(self.batch_cli(plans),first)
        self.assertEqual(self.rows('csv_extraction_results'),2)
        review=self.review().json()['data']
        self.assertEqual(review['job_id'],plans[1]['job'])
        self.assertEqual(review['amounts'][0]['amount'],'12.00')
        self.assertEqual(len(review['questions']),1)

    def test_full_validation_before_connection_and_no_operator_batch(self):
        plans=self.prepare()
        with patch('omnixat_core.csv_extract_worker.psycopg.connect',side_effect=AssertionError('Must not connect')):
            for invalid in [[],plans*3,[plans[0],plans[1]|{'selections':[]}],
                            [plans[0],plans[0]],[plans[0],plans[1]|{'tenant':self.b}]]:
                result=self.batch_cli(invalid)
                self.assertEqual(result[0],1); self.assertEqual(result[1],'')
            self.assertEqual(self.batch_cli(plans,requested=False)[0],1)
            for raw in ['[{"job":"x","job":"y"}]','['*2000+']'*2000]:
                self.assertEqual(self.batch_cli(raw=raw)[0],1)
        self.assertEqual(self.rows('csv_extraction_results'),0)

    def test_committed_prefix_survives_failure_and_retry(self):
        plans=self.prepare()
        # The second plan is well formed but not the recorded selection.
        changed=plans[1]|{'selections':[{'field_name':'amount','row':3,'column':2}]}
        failure=self.batch_cli([plans[0],changed])
        self.assertEqual(failure[0],1); self.assertEqual(len(failure[1].splitlines()),1)
        self.assertIn('earlier receipts may be committed',failure[2])
        self.assertNotIn(self.requested_worker_dsn,failure[2]); self.assertNotIn('12.00',failure[2])
        self.assertEqual(self.rows('csv_extraction_results'),1)
        retry=self.batch_cli(plans)
        self.assertEqual(retry[0],0,retry[2])
        self.assertEqual(retry[1].splitlines()[0],failure[1].strip())
        self.assertEqual(self.rows('csv_extraction_results'),2)

    def test_revoked_authority_between_items_stops_dispatch(self):
        plans=self.prepare()
        with psycopg.connect(self.requested_worker_dsn,autocommit=True) as connection:
            iterator=requested_batch(connection,plans)
            next(iterator)
            self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
            with self.assertRaises(EvidenceNotEligible): next(iterator)
        self.assertEqual(self.rows('csv_extraction_results'),1)

    def test_cancelled_request_stops_remaining_items(self):
        plans=self.prepare()
        third=plans[1]|{'job':str(uuid4())}
        self.assertEqual(self.request({'job_id':third['job'],'selections':third['selections']}).status_code,202)
        with psycopg.connect(self.requested_worker_dsn,autocommit=True) as connection:
            iterator=requested_batch(connection,[*plans,third])
            next(iterator)
            self.assertEqual(self.cancel(job=plans[1]['job']).status_code,202)
            with self.assertRaises(EvidenceNotEligible): next(iterator)
        self.assertEqual(self.rows('csv_extraction_results'),1)
        self.assertEqual(self.listing(job=third['job']).json()['data']['items'][0]['state'],'awaiting_worker')

    def test_current_policy_and_dedicated_grants_remain_required(self):
        plans=self.prepare()
        for dsn in [self.extract_dsn,self.runtime_dsn,self.owner_dsn,self.csv_request_dsn]:
            result=self.batch_cli(plans,dsn=dsn)
            self.assertEqual(result[0],1); self.assertEqual(result[1],'')
        self.policy('fictional-v2')
        result=self.batch_cli(plans)
        self.assertEqual(result[0],1); self.assertEqual(result[1],'')
        self.assertEqual(self.rows('csv_extraction_results'),0)

    def test_multiple_sources_and_policy_change_between_items(self):
        plans=self.prepare()
        other=self.upload(content=b'Fictional second description,Amount\r\nFictional second purchase,23.00\r\n').json()['data']['id']
        saved=self.evidence
        try:
            self.evidence=other; self.verdict('clean')
        finally:
            self.evidence=saved
        second=plans[1]|{'evidence':other,'job':str(uuid4())}
        url=self.url+'/'+other+'/csv-requests'
        self.assertEqual(self.request({'job_id':second['job'],'selections':second['selections']},url=url).status_code,202)
        with psycopg.connect(self.requested_worker_dsn,autocommit=True) as connection:
            iterator=requested_batch(connection,[plans[0],second])
            first=next(iterator)
            self.policy('fictional-v2')
            with self.assertRaises(EvidenceNotEligible): next(iterator)
        self.assertEqual(self.rows('csv_extraction_results'),1)
        self.policy('fictional-v1')
        result=self.batch_cli([plans[0],second])
        self.assertEqual(result[0],0,result[2])
        self.assertEqual(json.loads(result[1].splitlines()[0])['stored_at'],first.stored_at.isoformat())
        review=self.client.get(self.url+'/'+other+'/csv-review',headers=self.headers()).json()['data']
        self.assertEqual(review['amounts'][0]['amount'],'23.00')
        self.assertEqual(self.rows('csv_extraction_results'),2)

    def test_helper_validates_and_snapshots_whole_manifest_before_dispatch(self):
        plans=self.prepare()
        with psycopg.connect(self.requested_worker_dsn,autocommit=True) as connection:
            with self.assertRaises(ValueError):
                list(requested_batch(connection,[plans[0],plans[1]|{'selections':[]}]))
            self.assertEqual(self.rows('csv_extraction_results'),0)
            iterator=requested_batch(connection,plans)
            next(iterator)
            plans[1]['selections'][0]['row']=4
            next(iterator)
        self.assertEqual(self.rows('csv_extraction_results'),2)
