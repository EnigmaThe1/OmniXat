from test_customer_scan_status import CustomerScanStatusFixture


class CustomerScanStatusBrowserTests(CustomerScanStatusFixture):
    def test_chromium_status_refresh_policy_change_and_blocking(self):
        from playwright.sync_api import expect
        from test_customer_evidence import SCOPES
        page,errors=self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        button=page.get_by_role('button',name='Check scan status',exact=True)
        button.click()
        panel=page.get_by_role('region',name='Scan status '+self.evidence,exact=True)
        expect(panel).to_contain_text('Scanning is not configured')
        self.policy(); self.verdict('clean')
        page.get_by_role('button',name='Refresh scan status',exact=True).click()
        expect(panel).to_contain_text('Scan completed — no detections under this policy')
        expect(panel).to_contain_text('does not validate figures')
        self.verdict('blocked')
        page.get_by_role('button',name='Refresh scan status',exact=True).click()
        expect(panel).to_contain_text('Blocked by the scan policy')
        self.policy('fictional-v2')
        page.get_by_role('button',name='Refresh scan status',exact=True).click()
        expect(panel).to_contain_text('Awaiting a trusted scanner')
        page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        self.assertEqual(errors,[])

    def test_chromium_expiry_clears_displayed_status(self):
        from playwright.sync_api import expect
        from test_customer_evidence import SCOPES
        self.policy(); self.verdict('clean')
        page,errors=self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Check scan status',exact=True).click()
        panel=page.get_by_role('region',name='Scan status '+self.evidence,exact=True)
        expect(panel).to_contain_text('Scan completed')
        self.gateway_token=self.token(scope=SCOPES,iat=self.iat-60,exp=self.iat-1)
        page.get_by_role('button',name='Refresh scan status',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('Your session has ended.')
        expect(page.locator('#content')).to_be_hidden()
        self.assertEqual(panel.text_content(),'')
        self.assertEqual(errors,[])
