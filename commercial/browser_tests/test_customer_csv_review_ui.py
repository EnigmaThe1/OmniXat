from test_customer_csv_review import CustomerCSVReviewFixture
from test_customer_evidence import SCOPES


class CustomerCSVReviewBrowserTests(CustomerCSVReviewFixture):
    def test_candidate_sources_questions_and_stale_scan_refresh(self):
        from playwright.sync_api import expect
        self.prepare()
        page,errors=self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Inspect CSV candidates',exact=True).click()
        panel=page.get_by_role('region',name='CSV candidates '+self.evidence,exact=True)
        expect(panel).to_contain_text('amount · row 2, column 2: 12.00')
        expect(panel).to_contain_text('Which cell contains this amount')
        expect(panel).to_contain_text(str(self.job)); expect(panel).to_contain_text('do not post entries')
        self.verdict('blocked')
        page.get_by_role('button',name='Refresh CSV candidates',exact=True).click()
        expect(panel).to_contain_text('No eligible CSV extraction')
        expect(panel).not_to_contain_text('12.00')
        page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        self.assertEqual(errors,[])

    def test_expired_session_clears_candidate_dom(self):
        from playwright.sync_api import expect
        self.prepare()
        page,errors=self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Inspect CSV candidates',exact=True).click()
        panel=page.get_by_role('region',name='CSV candidates '+self.evidence,exact=True,include_hidden=True)
        expect(panel).to_contain_text('12.00')
        self.gateway_token=self.token(scope=SCOPES,iat=self.iat-60,exp=self.iat-1)
        page.get_by_role('button',name='Refresh CSV candidates',exact=True).click()
        expect(page.locator('#content')).to_be_hidden()
        self.assertEqual(panel.text_content(),''); self.assertEqual(errors,[])
