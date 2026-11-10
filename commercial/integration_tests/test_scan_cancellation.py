from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from test_customer_scan_requests import CustomerScanRequestFixture, REQUEST_SCOPES
from omnixat_core.evidence_requests_postgres import request_scan


class ScanCancellationTests(CustomerScanRequestFixture):
    def cancel(self,**extra):
        return self.client.post(self.request_url.replace('/scan-requests','/scan-cancellations'),
            content=b'{}',headers=self.headers(scope=REQUEST_SCOPES)|{'Content-Type':'application/json'}|extra)

    def test_cancel_is_durable_idempotent_and_blocks_worker(self):
        self.policy(); self.assertEqual(self.request().status_code,202); self.worker_admit()
        first=self.cancel(); self.assertEqual(first.status_code,202,first.text)
        row=self.owner.execute('SELECT requested_by,cancelled_by,cancelled_at FROM omnixat.evidence_scan_requests WHERE tenant_id=%s',(self.a,)).fetchone()
        self.assertEqual(row[:2],(self.user,self.user)); self.assertIsNotNone(row[2])
        self.assertEqual(self.cancel().json()['data'],first.json()['data'])
        self.assertEqual(self.owner.execute('SELECT cancelled_at FROM omnixat.evidence_scan_requests WHERE tenant_id=%s',(self.a,)).fetchone()[0],row[2])
        self.assertEqual(self.status().json()['data']['status'],'cancelled')
        with self.assertRaises(PermissionError): self.worker_admit()
        self.request()  # A normal retry cannot silently re-authorise a cancellation.
        with self.assertRaises(PermissionError): self.worker_admit()
        self.assertEqual(self.rows('evidence_quarantine'),1); self.assertEqual(self.rows('evidence_scan_verdicts'),0)

    def test_concurrent_cancel_preserves_first_receipt(self):
        self.policy(); self.request(); token=self.token(scope=REQUEST_SCOPES)
        def cancel(_):
            with self.request_connections() as connection:
                return request_scan(connection,self.verifier,token,self.a,self.org,self.evidence,cancel=True)
        with ThreadPoolExecutor(max_workers=3) as executor: results=list(executor.map(cancel,range(3)))
        self.assertTrue(all(row==results[0] for row in results))

    def test_authority_scope_actor_parent_and_strict_body(self):
        self.policy(); self.request()
        self.assertEqual(self.cancel(**{'X-OmniXat-Expected-Actor':str(uuid4())}).status_code,409)
        self.assertEqual(self.cancel(**self.headers()).status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.cancel().status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='editor' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.client.post(self.request_url.replace('/scan-requests','/scan-cancellations'),json={'policy':'chosen'},headers=self.headers(scope=REQUEST_SCOPES)).status_code,400)
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        self.assertEqual(self.cancel().status_code,403)
        self.assertIsNone(self.owner.execute('SELECT cancelled_at FROM omnixat.evidence_scan_requests WHERE tenant_id=%s',(self.a,)).fetchone()[0])

    def test_existing_verdicts_take_precedence_and_new_policy_is_independent(self):
        self.policy(); self.request(); self.cancel(); self.verdict('clean')
        self.assertEqual(self.status().json()['data']['status'],'scanned')
        self.verdict('blocked'); self.assertEqual(self.status().json()['data']['status'],'blocked')
        self.policy('fictional-v2'); self.assertEqual(self.status().json()['data']['status'],'awaiting_scan')
        self.assertEqual(self.cancel().status_code,409)
        self.request(); self.worker_admit('fictional-v2')
