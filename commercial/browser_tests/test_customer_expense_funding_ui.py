"""Real Chromium funding declaration and recovery with fictional configuration."""
from uuid import uuid4
from unittest.mock import patch
import httpx
from test_customer_expense_funding import ExpenseFundingFixture
from test_customer_evidence import SCOPES


class ExpenseFundingBrowserTests(ExpenseFundingFixture):
    def open_funding(self):
        from playwright.sync_api import expect
        self.prepare_funding()
        page,errors=self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        page.get_by_role('button',name='Inspect expense draft '+str(self.saved.id),exact=True).click()
        page.get_by_role('button',name='Inspect funding',exact=True).click()
        panel=page.get_by_role('region',name='Expense funding '+str(self.saved.id),exact=True)
        form=page.get_by_role('form',name='Select expense funding '+str(self.saved.id),exact=True)
        expect(panel).to_contain_text('Who funded this expense?')
        expect(form.get_by_label('Payer and funding source',exact=True)).to_have_value('')
        form.get_by_label('Payer and funding source',exact=True).select_option(str(self.personal_source))
        return page,panel,form,errors

    def test_explicit_personal_selection_persisted_viewer_history_and_mobile(self):
        from playwright.sync_api import expect
        page,panel,form,errors=self.open_funding()
        page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        form.get_by_role('button',name='Record funding selection',exact=True).click()
        expect(panel).to_contain_text('Personal funds');expect(panel).to_contain_text(str(self.personal_payer))
        expect(panel).to_contain_text(str(self.user));expect(panel).to_contain_text('does not move money')
        expect(panel.get_by_role('form')).to_have_count(0)
        expect(page.get_by_role('button',name='Refresh funding',exact=True)).to_be_enabled()
        self.owner.execute('UPDATE omnixat.expense_funding_sources SET eligible_for_drafts=false WHERE tenant_id=%s AND id=%s',(self.a,self.personal_source))
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        page.reload()
        page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        page.get_by_role('button',name='Inspect expense draft '+str(self.saved.id),exact=True).click()
        page.get_by_role('button',name='Inspect funding',exact=True).click()
        expect(panel).to_contain_text('No longer eligible for draft preparation')
        expect(panel).to_contain_text(str(self.personal_payer))
        self.assertEqual(panel.get_by_role('form').count(),0)
        self.assertEqual(self.rows('expense_funding_context'),1);self.assertEqual(self.rows('expense_journal_drafts'),0)
        self.assertEqual(errors,[])

    def test_lost_receipt_preserves_pair_and_initiating_actor(self):
        from playwright.sync_api import expect
        page,panel,form,errors=self.open_funding();original=self.client.request
        def lost(method,url,**kwargs):
            response=original(method,url,**kwargs)
            if method=='POST' and str(url).endswith('/funding'):
                return httpx.Response(503,json={'error':{'code':'service_unavailable'}})
            return response
        with patch.object(self.client,'request',side_effect=lost):
            form.get_by_role('button',name='Record funding selection',exact=True).click()
            expect(form.get_by_role('button',name='Retry funding selection',exact=True)).to_be_enabled()
        expect(form.get_by_label('Payer and funding source',exact=True)).to_be_disabled()
        self.assertEqual(self.rows('expense_funding_context'),1)
        other=uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'fictional-funding-switch','human')",(other,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.a,other))
        self.gateway_token=self.token(scope=SCOPES,sub='fictional-funding-switch')
        form.get_by_role('button',name='Retry funding selection',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('same account that started this save')
        self.gateway_token=self.token(scope=SCOPES)
        form.get_by_role('button',name='Retry funding selection',exact=True).click()
        expect(panel).to_contain_text(str(self.personal_payer));expect(panel).to_contain_text('Personal funds')
        expect(panel).to_contain_text(str(self.user));expect(panel.get_by_role('form')).to_have_count(0)
        self.assertEqual(self.rows('expense_funding_context'),1);self.assertEqual(errors,[])

    def test_expiry_clears_draft_and_recovers_same_funding_selection(self):
        from playwright.sync_api import expect
        page,panel,form,errors=self.open_funding()
        self.gateway_token=self.token(scope=SCOPES,iat=self.iat-60,exp=self.iat-1)
        form.get_by_role('button',name='Record funding selection',exact=True).click()
        expect(page.locator('#content')).to_be_hidden()
        draft_panel=page.get_by_role('region',name='Saved expense drafts '+self.evidence,exact=True,include_hidden=True)
        self.assertEqual(draft_panel.text_content(),'')
        self.gateway_token=self.token(scope=SCOPES)
        page.locator('#retry').click()
        expect(form.get_by_label('Payer and funding source',exact=True)).to_have_value(str(self.personal_source))
        expect(form.get_by_label('Payer and funding source',exact=True)).to_be_disabled()
        form.get_by_role('button',name='Retry funding selection',exact=True).click()
        expect(panel).to_contain_text(str(self.personal_payer))
        expect(panel).to_contain_text(str(self.user));expect(panel.get_by_role('form')).to_have_count(0)
        self.assertEqual(self.rows('expense_funding_context'),1);self.assertEqual(errors,[])
