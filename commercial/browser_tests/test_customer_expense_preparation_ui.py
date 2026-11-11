"""Actual Chromium, shared customer services and fictional source-backed drafts."""
from uuid import uuid4
from unittest.mock import patch
import httpx
from test_customer_expense_preparation import ExpensePreparationFixture
from test_customer_evidence import SCOPES


class ExpensePreparationBrowserTests(ExpensePreparationFixture):
    def open_form(self):
        from playwright.sync_api import expect
        self.prepare_source()
        page,errors=self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Inspect CSV candidates',exact=True).click()
        page.get_by_role('button',name='Prepare expense draft',exact=True).click()
        form=page.get_by_role('form',name='Prepare source-backed expense draft',exact=True)
        expect(form.get_by_label('Source cell',exact=True)).to_have_value('')
        expect(form.get_by_label('Bookkeeping period',exact=True)).to_have_value('')
        expect(form.get_by_label('Accounting date',exact=True)).to_have_value('')
        form.get_by_label('Source cell',exact=True).select_option(index=1)
        form.get_by_label('Bookkeeping period',exact=True).select_option(str(self.period))
        form.get_by_label('Expense account',exact=True).select_option(str(self.account))
        form.get_by_label('Accounting date',exact=True).fill('2026-11-06')
        return page,errors,form

    def test_explicit_preparation_saved_review_and_mobile(self):
        from playwright.sync_api import expect
        page,errors,form=self.open_form()
        page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        form.get_by_role('button',name='Save expense draft',exact=True).click()
        expect(form).to_contain_text('Nothing was posted or approved.')
        saved=self.owner.execute('SELECT id FROM omnixat.csv_expense_drafts WHERE tenant_id=%s',(self.a,)).fetchone()[0]
        page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        page.get_by_role('button',name='Inspect expense draft '+str(saved),exact=True).click()
        panel=page.get_by_role('region',name='Saved expense drafts '+self.evidence,exact=True)
        expect(panel).to_contain_text('GBP 12.00'); expect(panel).to_contain_text(str(self.period))
        self.assertEqual((self.rows('evidence_draft_amounts'),self.rows('csv_expense_drafts')),(1,1))
        page.reload()
        page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        page.get_by_role('button',name='Inspect expense draft '+str(saved),exact=True).click()
        expect(panel).to_contain_text('GBP 12.00'); self.assertEqual(errors,[])

    def test_lost_receipt_frozen_selection_and_other_actor_retry(self):
        from playwright.sync_api import expect
        page,errors,form=self.open_form(); original=self.client.request; bodies=[]
        def lost(method,url,**kwargs):
            response=original(method,url,**kwargs)
            if method=='POST' and str(url).endswith('/expense-drafts'):
                bodies.append(kwargs['content'])
                return httpx.Response(503,json={'error':{'code':'service_unavailable'}})
            return response
        with patch.object(self.client,'request',side_effect=lost):
            form.get_by_role('button',name='Save expense draft',exact=True).click()
            expect(form.get_by_role('button',name='Retry expense preparation',exact=True)).to_be_enabled()
        expect(form.get_by_label('Accounting date',exact=True)).to_be_disabled()
        self.assertEqual(self.rows('csv_expense_drafts'),1)
        other=uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'fictional-expense-switch','human')",(other,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.a,other))
        self.gateway_token=self.token(scope=SCOPES,sub='fictional-expense-switch')
        form.get_by_role('button',name='Retry expense preparation',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('same account that started this save')
        self.gateway_token=self.token(scope=SCOPES)
        form.get_by_role('button',name='Retry expense preparation',exact=True).click()
        expect(form).to_contain_text('Nothing was posted or approved.')
        self.assertEqual((self.rows('evidence_draft_amounts'),self.rows('csv_expense_drafts')),(1,1))
        import json
        self.assertEqual(json.loads(bodies[0]),self.document)
        self.assertEqual(errors,[])

    def test_expiry_clears_source_and_recovers_same_preparation(self):
        from playwright.sync_api import expect
        page,errors,form=self.open_form()
        self.gateway_token=self.token(scope=SCOPES,iat=self.iat-60,exp=self.iat-1)
        form.get_by_role('button',name='Save expense draft',exact=True).click()
        expect(page.locator('#content')).to_be_hidden()
        panel=page.get_by_role('region',name='CSV candidates '+self.evidence,exact=True,include_hidden=True)
        self.assertEqual(panel.text_content(),'')
        self.gateway_token=self.token(scope=SCOPES)
        page.locator('#retry').click()
        expect(form.get_by_label('Accounting date',exact=True)).to_have_value('2026-11-06')
        expect(form.get_by_label('Accounting date',exact=True)).to_be_disabled()
        form.get_by_role('button',name='Retry expense preparation',exact=True).click()
        expect(form).to_contain_text('Nothing was posted or approved.')
        self.assertEqual(self.rows('csv_expense_drafts'),1); self.assertEqual(errors,[])
