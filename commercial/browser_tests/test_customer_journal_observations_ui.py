"""Real Chromium current-snapshot review history; no approval or mutation UI."""
from test_customer_journal_observations import JournalObservationFixture
from test_customer_evidence import SCOPES


class JournalObservationBrowserTests(JournalObservationFixture):
    def open_history(self,count=1):
        from playwright.sync_api import expect
        self.prepare_observations(count);page,errors=self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        page.get_by_role('button',name='Inspect expense draft '+str(self.saved.id),exact=True).click()
        page.get_by_role('button',name='Inspect journal draft',exact=True).click()
        page.get_by_role('button',name='Inspect review observations',exact=True).click()
        history=page.get_by_role('region',name='Journal review observations '+self.journal['id'],exact=True)
        expect(history).to_contain_text('Recorded review observations')
        return page,history,errors

    def test_paginated_viewer_history_mobile_and_no_mutation(self):
        from playwright.sync_api import expect
        page,history,errors=self.open_history(23)
        expect(history).to_contain_text('fictional-reviewer-019');expect(history).not_to_contain_text('fictional-reviewer-020')
        history.get_by_role('button',name='Load more review observations',exact=True).click()
        expect(history).to_contain_text('fictional-reviewer-022');expect(history.locator('article')).to_have_count(23)
        expect(history.get_by_role('button',name='Load more review observations',exact=True)).to_have_count(0)
        page.set_viewport_size({'width':390,'height':844});self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        page.get_by_role('button',name='Inspect review observations',exact=True).click()
        expect(history.locator('article')).to_have_count(20);expect(history).to_contain_text('not posting instructions')
        self.assertEqual(self.rows('expense_journal_review_decisions'),23);self.assertEqual(errors,[])

    def test_changed_snapshot_clears_old_history_until_journal_refresh(self):
        from playwright.sync_api import expect
        page,history,errors=self.open_history(23)
        self.owner.execute("UPDATE omnixat.expense_journal_drafts SET created_by='fictional-changed-author' WHERE id=%s",(self.journal['id'],))
        history.get_by_role('button',name='Load more review observations',exact=True).click()
        journal=page.get_by_role('region',name='Expense journal '+str(self.saved.id),exact=True)
        expect(journal).to_contain_text('Refresh the journal draft before reading review observations.')
        expect(journal).not_to_contain_text('fictional-reviewer-000')
        page.get_by_role('button',name='Refresh journal draft',exact=True).click()
        page.get_by_role('button',name='Inspect review observations',exact=True).click()
        expect(history).to_contain_text('No review observations are recorded for this saved snapshot.')
        self.assertEqual(self.rows('expense_journal_review_decisions'),23);self.assertEqual(errors,[])

    def test_expiry_clears_source_and_history_before_recovery(self):
        from playwright.sync_api import expect
        page,history,errors=self.open_history()
        self.gateway_token=self.token(scope=SCOPES,iat=self.iat-60,exp=self.iat-1)
        page.get_by_role('button',name='Inspect review observations',exact=True).click()
        expect(page.locator('#content')).to_be_hidden()
        draft_panel=page.get_by_role('region',name='Saved expense drafts '+self.evidence,exact=True,include_hidden=True)
        self.assertEqual(draft_panel.text_content(),'')
        self.gateway_token=self.token(scope=SCOPES);page.locator('#retry').click()
        page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        page.get_by_role('button',name='Inspect expense draft '+str(self.saved.id),exact=True).click()
        page.get_by_role('button',name='Inspect journal draft',exact=True).click()
        page.get_by_role('button',name='Inspect review observations',exact=True).click()
        expect(history).to_contain_text('fictional-reviewer-000');self.assertEqual(errors,[])
