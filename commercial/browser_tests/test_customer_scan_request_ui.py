from test_customer_scan_requests import CustomerScanRequestFixture, REQUEST_SCOPES


class CustomerScanRequestBrowserTests(CustomerScanRequestFixture):
    def test_chromium_request_survives_reload_without_duplicates(self):
        from playwright.sync_api import expect
        self.policy()
        page,errors=self.browser(token=self.token(scope=REQUEST_SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Check scan status',exact=True).click()
        page.get_by_role('button',name='Request scan',exact=True).click()
        panel=page.get_by_role('region',name='Scan status '+self.evidence,exact=True)
        expect(panel).to_contain_text('Scan requested — awaiting an operator-run worker')
        expect(page.get_by_role('button',name='Request scan',exact=True)).to_have_count(0)
        page.reload(); page.get_by_role('button',name='Check scan status',exact=True).click()
        expect(panel).to_contain_text('Scan requested')
        self.assertEqual(self.rows('evidence_scan_requests'),1)
        self.assertEqual(self.rows('evidence_scan_verdicts'),0)
        self.assertEqual(errors,[])

    def test_chromium_viewer_has_no_request_action_and_revoked_editor_is_denied(self):
        from playwright.sync_api import expect
        self.policy()
        page,errors=self.browser(token=self.token(scope=REQUEST_SCOPES))
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Check scan status',exact=True).click()
        expect(page.get_by_role('button',name='Request scan',exact=True)).to_have_count(0)
        self.owner.execute("UPDATE omnixat.memberships SET role='editor' WHERE user_id=%s",(self.user,))
        page.reload(); page.get_by_role('button',name='Check scan status',exact=True).click()
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        page.get_by_role('button',name='Request scan',exact=True).click()
        expect(page.locator('#content')).to_be_hidden()
        expect(page.locator('#error-message')).to_contain_text('Your access has changed')
        self.assertEqual(self.rows('evidence_scan_requests'),0)
        self.assertEqual(errors,[])
