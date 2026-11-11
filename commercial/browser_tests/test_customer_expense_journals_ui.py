"""Chromium customer journal preparation; fictional source-backed amounts only."""
from unittest.mock import patch
from uuid import uuid4
import httpx
from test_customer_expense_journals import ExpenseJournalFixture
from test_customer_evidence import SCOPES


class ExpenseJournalBrowserTests(ExpenseJournalFixture):
    def open_journal(self):
        from playwright.sync_api import expect
        self.prepare_journal();page,errors=self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        page.get_by_role('button',name='Inspect expense draft '+str(self.saved.id),exact=True).click()
        page.get_by_role('button',name='Inspect journal draft',exact=True).click()
        panel=page.get_by_role('region',name='Expense journal '+str(self.saved.id),exact=True)
        form=page.get_by_role('form',name='Prepare expense journal '+str(self.saved.id),exact=True)
        expect(form.get_by_label('Counterpart account',exact=True)).to_have_value('')
        expect(form.get_by_role('button',name='Save journal draft',exact=True)).to_be_disabled()
        form.get_by_label('Counterpart account',exact=True).select_option(str(self.counterpart))
        form.get_by_role('button',name='Preview balanced journal',exact=True).click()
        expect(form).to_contain_text('Balanced preview ready.')
        expect(form.get_by_role('button',name='Save journal draft',exact=True)).to_be_enabled()
        return page,panel,form,errors

    def test_explicit_balanced_preview_saved_inspection_viewer_and_mobile(self):
        from playwright.sync_api import expect
        page,panel,form,errors=self.open_journal();page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        expect(form).to_contain_text('Debit');expect(form).to_contain_text('Credit');expect(form).to_contain_text('GBP 12.00')
        self.assertEqual(self.rows('expense_journal_drafts'),0)
        form.get_by_role('button',name='Save journal draft',exact=True).click()
        expect(panel).to_contain_text('Saved journal draft ');expect(panel).to_contain_text(str(self.user))
        expect(panel.get_by_role('form')).to_have_count(0)
        expect(page.get_by_role('button',name='Refresh journal draft',exact=True)).to_be_enabled()
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        page.reload();page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        page.get_by_role('button',name='Inspect expense draft '+str(self.saved.id),exact=True).click()
        page.get_by_role('button',name='Inspect journal draft',exact=True).click()
        expect(panel).to_contain_text('Saved snapshot fingerprint');expect(panel.get_by_role('form')).to_have_count(0)
        self.assertEqual(self.rows('expense_journal_drafts'),1);self.assertEqual(self.rows('expense_journal_review_decisions'),0);self.assertEqual(errors,[])

    def test_lost_receipt_retains_preview_and_initiating_actor(self):
        from playwright.sync_api import expect
        page,panel,form,errors=self.open_journal();original=self.client.request
        def lost(method,url,**kwargs):
            response=original(method,url,**kwargs)
            if method=='POST' and str(url).endswith('/journal'):return httpx.Response(503,json={'error':{'code':'service_unavailable'}})
            return response
        with patch.object(self.client,'request',side_effect=lost):
            form.get_by_role('button',name='Save journal draft',exact=True).click()
            expect(form.get_by_role('button',name='Retry journal draft save',exact=True)).to_be_enabled()
        expect(form.get_by_label('Counterpart account',exact=True)).to_be_disabled();self.assertEqual(self.rows('expense_journal_drafts'),1)
        other=uuid4();self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'fictional-journal-switch','human')",(other,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.a,other))
        self.gateway_token=self.token(scope=SCOPES,sub='fictional-journal-switch')
        form.get_by_role('button',name='Retry journal draft save',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('same account that started this save')
        self.gateway_token=self.token(scope=SCOPES)
        form.get_by_role('button',name='Retry journal draft save',exact=True).click()
        expect(panel).to_contain_text('Saved journal draft ');expect(panel).to_contain_text(str(self.user));expect(panel.get_by_role('form')).to_have_count(0)
        self.assertEqual(self.rows('expense_journal_drafts'),1);self.assertEqual(errors,[])

    def test_expiry_clears_source_and_recovers_same_preview(self):
        from playwright.sync_api import expect
        page,panel,form,errors=self.open_journal()
        self.gateway_token=self.token(scope=SCOPES,iat=self.iat-60,exp=self.iat-1)
        form.get_by_role('button',name='Save journal draft',exact=True).click()
        expect(page.locator('#content')).to_be_hidden()
        draft_panel=page.get_by_role('region',name='Saved expense drafts '+self.evidence,exact=True,include_hidden=True)
        self.assertEqual(draft_panel.text_content(),'')
        self.gateway_token=self.token(scope=SCOPES);page.locator('#retry').click()
        expect(form.get_by_label('Counterpart account',exact=True)).to_have_value(str(self.counterpart))
        expect(form.get_by_label('Counterpart account',exact=True)).to_be_disabled()
        form.get_by_role('button',name='Retry journal draft save',exact=True).click()
        expect(panel).to_contain_text('Saved journal draft ');expect(panel).to_contain_text(str(self.user));expect(panel.get_by_role('form')).to_have_count(0)
        self.assertEqual(self.rows('expense_journal_drafts'),1);self.assertEqual(errors,[])
