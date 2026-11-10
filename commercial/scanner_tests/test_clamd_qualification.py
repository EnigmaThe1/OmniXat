"""Real daemon/protocol, worker/database and customer status; synthetic rules only."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
from unittest.mock import patch

import psycopg
from test_customer_scan_requests import CustomerScanRequestFixture
from omnixat_core.clamd_scanner import ClamdScanner, ScannerUnavailable
from omnixat_core.evidence_scan_postgres import scan_quarantined_evidence, EvidenceScanError
from omnixat_core.scan_worker import main
from qualification.clamd import ClamdFixture


class ClamdQualificationTests(CustomerScanRequestFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.daemon=ClamdFixture().__enter__()
        cls.addClassCleanup(cls.daemon.__exit__,None,None,None)

    def scanner(self,version=None):
        return ClamdScanner(self.daemon.socket_path,expected_version=version or self.daemon.expected_version)

    def test_real_daemon_worker_receipt_and_customer_status_ui(self):
        from playwright.sync_api import expect
        from test_customer_evidence import SCOPES
        settings=Path(self.spool.name)/'scanner.json'; dsn=Path(self.spool.name)/'scanner.dsn'
        settings.write_text(json.dumps({'socket_path':str(self.daemon.socket_path),
            'expected_version':self.daemon.expected_version,'policy_version':self.daemon.policy_version}))
        dsn.write_text(self.scanner_dsn); settings.chmod(0o600); dsn.chmod(0o600)
        self.policy(self.daemon.policy_version)
        self.assertEqual(self.request().status_code,202)
        output=StringIO()
        with patch.dict(os.environ,{'OMNIXAT_SCANNER_CONFIG_FILE':str(settings),'OMNIXAT_SCANNER_DSN_FILE':str(dsn)}),redirect_stdout(output):
            self.assertEqual(main(['--tenant',self.a,'--organisation',str(self.org),'--evidence',self.evidence,'--requested']),0)
        receipt=json.loads(output.getvalue()); self.assertEqual(receipt['verdict'],'clean')
        self.policy(self.daemon.policy_version)
        self.assertEqual(self.status().json()['data']['status'],'scanned')
        page,errors=self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Check scan status',exact=True).click()
        expect(page.get_by_role('region',name='Scan status '+self.evidence,exact=True)).to_contain_text('Scan completed')
        self.assertEqual(errors,[])
        self.assertEqual(self.rows('evidence_quarantine'),1)

    def test_real_synthetic_detection_is_blocked_and_retry_uses_durable_receipt(self):
        self.evidence=self.upload(content=b'Fictional CSV,Amount\n'+self.daemon.marker+b',1.00\n').json()['data']['id']
        self.status_url=self.url+'/'+self.evidence+'/scan-status'
        with psycopg.connect(self.scanner_dsn,autocommit=True) as connection:
            first=scan_quarantined_evidence(connection,self.a,self.org,self.evidence,
                policy_version=self.daemon.policy_version,scan=self.scanner())
            self.assertEqual(first.verdict,'blocked')
            def unavailable(*args): raise RuntimeError('Must reuse durable receipt')
            retry=scan_quarantined_evidence(connection,self.a,self.org,self.evidence,
                policy_version=self.daemon.policy_version,scan=unavailable)
            self.assertEqual(retry,first)
        self.policy(self.daemon.policy_version)
        self.assertEqual(self.status().json()['data']['status'],'blocked')

    def test_real_version_mismatch_fails_without_verdict_or_live_claim(self):
        with self.assertRaises(ScannerUnavailable): self.scanner('ClamAV unqualified')(b'Fictional document','text/csv')
        with psycopg.connect(self.scanner_dsn,autocommit=True) as connection,self.assertRaises(EvidenceScanError):
            scan_quarantined_evidence(connection,self.a,self.org,self.evidence,
                policy_version=self.daemon.policy_version,scan=self.scanner('ClamAV unqualified'))
        self.assertEqual(self.rows('evidence_scan_verdicts'),0)
        self.assertEqual(self.rows('evidence_scan_claims'),0)
        self.policy(self.daemon.policy_version)
        self.assertEqual(self.status().json()['data']['status'],'awaiting_scan')
