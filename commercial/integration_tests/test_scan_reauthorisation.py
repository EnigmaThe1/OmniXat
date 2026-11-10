from concurrent.futures import ThreadPoolExecutor
from test_customer_scan_requests import CustomerScanRequestFixture, REQUEST_SCOPES
from omnixat_core.evidence_requests_postgres import request_scan


class ScanReauthorisationTests(CustomerScanRequestFixture):
    def cancel(self):
        with self.request_connections() as connection:
            request_scan(connection,self.verifier,self.token(scope=REQUEST_SCOPES),self.a,self.org,self.evidence,cancel=True)
        return self.status().json()['data']['recorded_at']

    def renew(self,stamp,headers=None):
        return self.client.post(self.request_url.replace('/scan-requests','/scan-reauthorisations'),content=b'{}',
            headers=self.headers(scope=REQUEST_SCOPES)|{'Content-Type':'application/json','X-OmniXat-Cancellation':stamp}|(headers or {}))

    def test_explicit_reauthorisation_preserves_history_and_stale_retries_fail(self):
        self.policy(); original=self.request().json()['data']; stamp=self.cancel()
        self.assertIsNotNone(stamp)
        response=self.renew(stamp); self.assertEqual(response.status_code,202,response.text)
        self.worker_admit(); self.assertEqual(self.status().json()['data']['status'],'requested')
        self.assertEqual(self.renew(stamp).json()['data'],response.json()['data'])
        self.assertNotEqual(original['requested_at'],response.json()['data']['requested_at'])
        row=self.owner.execute('SELECT previous_request,reauthorised_by FROM omnixat.evidence_scan_request_history WHERE tenant_id=%s',(self.a,)).fetchone()
        self.assertEqual(row[0]['requested_by'],str(self.user)); self.assertIsNotNone(row[0]['cancelled_at'])
        self.assertEqual(row[1],self.user)
        second=self.cancel(); self.assertNotEqual(second,stamp)
        self.assertEqual(self.renew(stamp).status_code,409)
        with self.assertRaises(PermissionError): self.worker_admit()
        self.assertEqual(self.renew(second).status_code,202); self.worker_admit()
        self.assertEqual(self.rows('evidence_scan_request_history'),2)

    def test_concurrent_reauthorisation_returns_one_receipt(self):
        self.policy(); self.request(); stamp=self.cancel(); token=self.token(scope=REQUEST_SCOPES)
        def renew(_):
            with self.request_connections() as connection:
                return request_scan(connection,self.verifier,token,self.a,self.org,self.evidence,reauthorise_at=stamp)
        with ThreadPoolExecutor(max_workers=4) as executor: results=list(executor.map(renew,range(4)))
        self.assertTrue(all(row==results[0] for row in results)); self.assertEqual(self.rows('evidence_scan_request_history'),1)

    def test_header_format_scope_and_revocation_are_rechecked(self):
        self.policy(); self.request(); stamp=self.cancel()
        for value in ['bad','2026-11-10','2026-11-10T12:00:00']:
            self.assertEqual(self.renew(value).status_code,400)
        self.assertEqual(self.renew(stamp, self.headers()).status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.renew(stamp).status_code,403)
        self.assertEqual(self.rows('evidence_scan_request_history'),0)
