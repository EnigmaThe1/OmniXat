import psycopg
from test_csv_extract_worker import CSVExtractWorkerFixture
from test_customer_evidence import SCOPES
from omnixat_core.clamd_scanner import ClamdScanner
from omnixat_core.evidence_scan_postgres import scan_quarantined_evidence
from qualification.clamd import ClamdFixture


class CSVExtractionQualificationTests(CSVExtractWorkerFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.daemon=ClamdFixture().__enter__()
        cls.addClassCleanup(cls.daemon.__exit__,None,None,None)

    def test_real_daemon_to_explicit_extraction_worker_and_browser_candidates(self):
        from playwright.sync_api import expect
        self.policy(self.daemon.policy_version)
        with psycopg.connect(self.scanner_dsn,autocommit=True) as connection:
            receipt=scan_quarantined_evidence(connection,self.a,self.org,self.evidence,
                policy_version=self.daemon.policy_version,
                scan=ClamdScanner(self.daemon.socket_path,expected_version=self.daemon.expected_version))
            self.assertEqual(receipt.verdict,'clean')
        result,output,error=self.run_worker(); self.assertEqual(result,0,error)
        self.assertEqual(self.run_worker()[1],output)
        page,errors=self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Inspect CSV candidates',exact=True).click()
        panel=page.get_by_role('region',name='CSV candidates '+self.evidence,exact=True)
        expect(panel).to_contain_text('amount · row 2, column 2: 12.00')
        expect(panel).to_contain_text('Which cell contains this amount')
        expect(panel).to_contain_text(str(self.job))
        expect(panel).to_contain_text(self.daemon.policy_version)
        self.assertEqual(errors,[]); self.assertEqual(self.rows('csv_extraction_results'),1)
