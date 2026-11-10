from test_customer_scan_requests import CustomerScanRequestFixture, REQUEST_SCOPES


class ScanReauthorisationBrowserTests(CustomerScanRequestFixture):
    def test_cancel_and_explicitly_request_again_after_reload(self):
        from playwright.sync_api import expect
        self.policy()
        page,errors=self.browser(token=self.token(scope=REQUEST_SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Check scan status',exact=True).click()
        page.get_by_role('button',name='Request scan',exact=True).click()
        page.get_by_role('button',name='Cancel scan request',exact=True).click()
        panel=page.get_by_role('region',name='Scan status '+self.evidence,exact=True)
        expect(panel).to_contain_text('Scan request cancelled')
        page.reload(); page.get_by_role('button',name='Check scan status',exact=True).click()
        page.get_by_role('button',name='Request scan again',exact=True).click()
        expect(panel).to_contain_text('Scan requested')
        self.worker_admit(); self.assertEqual(self.rows('evidence_scan_request_history'),1)
        self.assertEqual(errors,[])
