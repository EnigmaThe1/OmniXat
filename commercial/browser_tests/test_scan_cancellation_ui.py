from test_customer_scan_requests import CustomerScanRequestFixture, REQUEST_SCOPES


class ScanCancellationBrowserTests(CustomerScanRequestFixture):
    def test_request_cancel_reload_and_worker_denial(self):
        from playwright.sync_api import expect
        self.policy()
        page,errors=self.browser(token=self.token(scope=REQUEST_SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Check scan status',exact=True).click()
        page.get_by_role('button',name='Request scan',exact=True).click()
        panel=page.get_by_role('region',name='Scan status '+self.evidence,exact=True)
        expect(panel).to_contain_text('Cancellation cannot stop a scan already in progress')
        page.get_by_role('button',name='Cancel scan request',exact=True).click()
        expect(panel).to_contain_text('Scan request cancelled')
        page.reload(); page.get_by_role('button',name='Check scan status',exact=True).click()
        expect(panel).to_contain_text('Scan request cancelled')
        expect(page.get_by_role('button',name='Request scan',exact=True)).to_have_count(0)
        with self.assertRaises(PermissionError): self.worker_admit()
        self.assertEqual(errors,[])
