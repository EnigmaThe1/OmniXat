from unittest.mock import Mock
from uuid import uuid4
import psycopg
from test_customer_scan_requests import CustomerScanRequestFixture
from omnixat_core.scan_worker import requested_batch
from omnixat_core.evidence_scan_postgres import EvidenceScanError


class RequestedScanBatchTests(CustomerScanRequestFixture):
    def prepare(self):
        self.policy()
        first=self.evidence
        self.assertEqual(self.request().status_code,202)
        second=self.upload(content=b'Fictional second document').json()['data']['id']
        self.request_url=self.url+'/'+second+'/scan-requests'
        self.assertEqual(self.request().status_code,202)
        return [first,second]

    def test_retry_reuses_committed_prefix_after_scanner_failure(self):
        items=self.prepare(); scanner=Mock(side_effect=['clean',RuntimeError('fictional failure')])
        with psycopg.connect(self.scanner_dsn,autocommit=True) as connection:
            iterator=requested_batch(connection,self.a,self.org,items,policy_version='fictional-v1',scan=scanner)
            first=next(iterator)
            with self.assertRaises(EvidenceScanError): next(iterator)
            retry_scanner=Mock(return_value='clean')
            retry=list(requested_batch(connection,self.a,self.org,items,policy_version='fictional-v1',scan=retry_scanner))
        self.assertEqual(first,retry[0]); self.assertEqual(retry_scanner.call_count,1)
        self.assertEqual(self.rows('evidence_scan_verdicts'),2)
        self.assertEqual(self.rows('evidence_scan_claims'),0)

    def test_revocation_between_items_stops_remaining_work(self):
        items=self.prepare(); scanner=Mock(return_value='clean')
        with psycopg.connect(self.scanner_dsn,autocommit=True) as connection:
            iterator=requested_batch(connection,self.a,self.org,items,policy_version='fictional-v1',scan=scanner)
            next(iterator)
            self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
            with self.assertRaises(PermissionError): next(iterator)
        self.assertEqual(scanner.call_count,1); self.assertEqual(self.rows('evidence_scan_verdicts'),1)

    def test_entire_manifest_validated_before_work_and_unrequested_item_denied(self):
        items=self.prepare(); scanner=Mock(return_value='clean')
        with psycopg.connect(self.scanner_dsn,autocommit=True) as connection:
            with self.assertRaises(ValueError):
                list(requested_batch(connection,self.a,self.org,[items[0],'bad'],policy_version='fictional-v1',scan=scanner))
            with self.assertRaises(PermissionError):
                list(requested_batch(connection,self.a,self.org,[str(uuid4())],policy_version='fictional-v1',scan=scanner))
        scanner.assert_not_called(); self.assertEqual(self.rows('evidence_scan_verdicts'),0)
