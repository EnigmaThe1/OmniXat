"""Real Chromium structured correction requests with fictional journal evidence."""
from unittest.mock import patch
from uuid import uuid4
import httpx
from test_customer_correction_reasons import CorrectionReasonFixture
from test_customer_evidence import SCOPES
from omnixat_core.journal_correction_questions import journal_correction_questions


class CorrectionReasonBrowserTests(CorrectionReasonFixture):
    def open_reasons(self):
        from playwright.sync_api import expect
        self.prepare_reason();page,errors=self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        page.get_by_role('button',name='Inspect expense draft '+str(self.saved.id),exact=True).click()
        page.get_by_role('button',name='Inspect journal draft',exact=True).click()
        page.get_by_role('button',name='Inspect correction requests',exact=True).click()
        panel=page.get_by_role('region',name='Journal correction requests '+self.journal['id'],exact=True)
        form=page.get_by_role('form',name='Record correction reason '+self.journal['id'],exact=True)
        expect(form.get_by_label('Correction reason',exact=True)).to_have_value('');expect(form).to_contain_text(self.snapshot)
        form.get_by_label('Correction reason',exact=True).select_option('amount')
        return page,panel,form,errors

    def test_explicit_reason_question_viewer_retention_and_mobile(self):
        from playwright.sync_api import expect
        page,panel,form,errors=self.open_reasons();page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        form.get_by_role('button',name='Record correction reason',exact=True).click()
        expect(panel).to_contain_text('Your recorded reason: Amount');expect(panel).to_contain_text(str(self.user))
        expect(panel).to_contain_text(journal_correction_questions(['amount'])[0].question);expect(form).to_have_count(0)
        self.assertEqual(self.rows('expense_journal_correction_requests'),1);self.assertEqual(self.rows('expense_journal_review_decisions'),1)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        page.reload();page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        page.get_by_role('button',name='Inspect expense draft '+str(self.saved.id),exact=True).click()
        page.get_by_role('button',name='Inspect journal draft',exact=True).click();page.get_by_role('button',name='Inspect correction requests',exact=True).click()
        expect(panel).to_contain_text('Your recorded reason: Amount');expect(form).to_have_count(0);self.assertEqual(errors,[])

    def test_committed_lost_receipt_actor_switch_and_same_reason_retry(self):
        from playwright.sync_api import expect
        page,panel,form,errors=self.open_reasons();original=self.client.request
        def lost(method,url,**kwargs):
            response=original(method,url,**kwargs)
            if method=='POST' and str(url).endswith('/journal-corrections'):return httpx.Response(503,json={'error':{'code':'service_unavailable'}})
            return response
        with patch.object(self.client,'request',side_effect=lost):
            form.get_by_role('button',name='Record correction reason',exact=True).click()
            expect(form.get_by_role('button',name='Retry correction reason',exact=True)).to_be_enabled()
        expect(form.get_by_label('Correction reason',exact=True)).to_be_disabled();self.assertEqual(self.rows('expense_journal_correction_requests'),1)
        other=uuid4();self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'fictional-correction-switch','human')",(other,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.a,other));self.gateway_token=self.token(scope=SCOPES,sub='fictional-correction-switch')
        form.get_by_role('button',name='Retry correction reason',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('same account that started this save')
        self.gateway_token=self.token(scope=SCOPES);form.get_by_role('button',name='Retry correction reason',exact=True).click()
        expect(panel).to_contain_text('Your recorded reason: Amount');expect(form).to_have_count(0)
        self.assertEqual(self.rows('expense_journal_correction_requests'),1);self.assertEqual(errors,[])

    def test_pending_expiry_clears_source_and_recovers_exact_reason(self):
        from playwright.sync_api import expect
        page,panel,form,errors=self.open_reasons();self.gateway_token=self.token(scope=SCOPES,iat=self.iat-60,exp=self.iat-1)
        form.get_by_role('button',name='Record correction reason',exact=True).click();expect(page.locator('#content')).to_be_hidden()
        source=page.get_by_role('region',name='Saved expense drafts '+self.evidence,exact=True,include_hidden=True);self.assertEqual(source.text_content(),'')
        self.gateway_token=self.token(scope=SCOPES);page.locator('#retry').click()
        expect(form.get_by_label('Correction reason',exact=True)).to_have_value('amount');expect(form.get_by_label('Correction reason',exact=True)).to_be_disabled()
        expect(form).to_contain_text(self.snapshot);form.get_by_role('button',name='Retry correction reason',exact=True).click()
        expect(panel).to_contain_text('Your recorded reason: Amount');expect(form).to_have_count(0)
        self.assertEqual(self.rows('expense_journal_correction_requests'),1);self.assertEqual(errors,[])

    def test_conflicting_reason_guidance_and_paginated_deduplicated_questions(self):
        from playwright.sync_api import expect
        page,panel,form,errors=self.open_reasons()
        self.assertEqual(self.request_reason(self.reason_document|{'reason':'funding'}).status_code,200)
        form.get_by_role('button',name='Record correction reason',exact=True).click()
        expect(form).to_contain_text('A different correction reason is already recorded.')
        expect(form.get_by_role('button',name='Retry correction reason',exact=True)).to_be_disabled()
        for i in range(23):self.add_reason(f'fictional-reviewer-{i:03d}','amount')
        page.get_by_role('button',name='Inspect correction requests',exact=True).click()
        expect(panel.get_by_role('button',name='Load more correction requests',exact=True)).to_be_visible()
        panel.get_by_role('button',name='Load more correction requests',exact=True).click()
        expect(panel.locator('article')).to_have_count(24)
        expect(panel.locator('[data-question-reason="amount"]')).to_have_count(1)
        expect(panel.locator('[data-question-reason="funding"]')).to_have_count(1)
        self.assertEqual(self.rows('expense_journal_correction_requests'),24);self.assertEqual(errors,[])
