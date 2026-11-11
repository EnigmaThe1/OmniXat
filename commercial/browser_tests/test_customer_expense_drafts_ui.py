"""Customer saved expense preparation inspection in actual Chromium."""
from test_customer_expense_drafts import CustomerExpenseDraftFixture
from test_customer_evidence import SCOPES


class CustomerExpenseDraftBrowserTests(CustomerExpenseDraftFixture):
    def open_draft(self,viewer=False):
        from playwright.sync_api import expect
        self.prepare()
        if viewer:
            self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        page,errors=self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        panel=page.get_by_role('region',name='Saved expense drafts '+self.evidence,exact=True,include_hidden=True)
        page.get_by_role('button',name='Inspect expense draft '+str(self.saved.id),exact=True).click()
        expect(panel).to_contain_text('GBP 12.00')
        expect(page.get_by_role('button',name='Refresh saved expense drafts',exact=True)).to_be_enabled()
        return page,panel,errors

    def test_saved_source_accounting_context_read_only_refresh_and_mobile(self):
        from playwright.sync_api import expect
        page,panel,errors=self.open_draft(viewer=True)
        for text in [str(self.saved.id),str(self.job),str(self.period),str(self.account),
                     'amount · row 2, column 2','extracted','2026-11-06','does not approve, post or submit']:
            expect(panel).to_contain_text(text)
        self.assertEqual(panel.get_by_role('button').count(),0)
        page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        page.reload()
        page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        page.get_by_role('button',name='Inspect expense draft '+str(self.saved.id),exact=True).click()
        expect(panel).to_contain_text('GBP 12.00')
        self.owner.execute('UPDATE omnixat.expense_accounting_periods SET open_for_drafts=false WHERE tenant_id=%s',(self.a,))
        page.get_by_role('button',name='Refresh saved expense drafts',exact=True).click()
        expect(panel).to_contain_text('No eligible saved expense drafts')
        expect(panel).not_to_contain_text('12.00')
        self.assertEqual(errors,[])

    def test_policy_change_before_exact_inspection_clears_list_and_source(self):
        from playwright.sync_api import expect
        self.prepare()
        page,errors=self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        open_button=page.get_by_role('button',name='Inspect expense draft '+str(self.saved.id),exact=True)
        expect(open_button).to_be_enabled()
        self.verdict('blocked')
        open_button.click()
        panel=page.get_by_role('region',name='Saved expense drafts '+self.evidence,exact=True)
        expect(panel).to_contain_text('No eligible saved expense draft is available')
        expect(panel).not_to_contain_text('12.00')
        self.assertEqual(errors,[])

    def test_expired_session_clears_draft_dom_and_viewer_can_recover(self):
        from playwright.sync_api import expect
        page,panel,errors=self.open_draft()
        self.gateway_token=self.token(scope=SCOPES,iat=self.iat-60,exp=self.iat-1)
        page.get_by_role('button',name='Refresh saved expense drafts',exact=True).click()
        expect(page.locator('#content')).to_be_hidden()
        self.assertEqual(panel.text_content(),'')
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.gateway_token=self.token(scope=SCOPES)
        page.reload()  # The stand-in gateway now supplies the refreshed signed session.
        page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        page.get_by_role('button',name='Inspect expense draft '+str(self.saved.id),exact=True).click()
        expect(panel).to_contain_text('GBP 12.00')
        self.assertEqual(self.rows('csv_expense_drafts'),1)
        self.assertEqual(errors,[])
