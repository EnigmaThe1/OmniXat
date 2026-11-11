"""Real Chromium explicit human bookkeeping observations, never filing approval."""
from unittest.mock import patch
from uuid import uuid4
import httpx
from test_customer_bookkeeping_observations import BookkeepingObservationFixture
from test_customer_evidence import SCOPES


class BookkeepingObservationBrowserTests(BookkeepingObservationFixture):
    def open_observation(self):
        from playwright.sync_api import expect
        self.prepare_bookkeeping();page,errors=self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        page.get_by_role('button',name='Inspect expense draft '+str(self.saved.id),exact=True).click()
        page.get_by_role('button',name='Inspect journal draft',exact=True).click()
        form=page.get_by_role('form',name='Record bookkeeping observation '+self.journal['id'],exact=True)
        expect(form.get_by_label('Bookkeeping observation',exact=True)).to_have_value('')
        expect(form).to_contain_text(self.snapshot)
        form.get_by_label('Bookkeeping observation',exact=True).select_option('changes_requested')
        panel=page.get_by_role('region',name='Expense journal '+str(self.saved.id),exact=True)
        return page,panel,form,errors

    def test_explicit_choice_attribution_history_conflict_and_mobile(self):
        from playwright.sync_api import expect
        page,panel,form,errors=self.open_observation();page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        form.get_by_role('button',name='Record bookkeeping observation',exact=True).click()
        expect(form).to_contain_text('Bookkeeping observation recorded: Changes requested');expect(form).to_contain_text(str(self.user))
        history=page.get_by_role('region',name='Journal review observations '+self.journal['id'],exact=True)
        expect(history).to_contain_text('Changes requested');expect(history).to_contain_text(str(self.user))
        self.assertEqual(self.rows('expense_journal_review_decisions'),1);self.assertEqual(self.rows('expense_journal_drafts'),1)
        expect(page.get_by_role('button',name='Refresh journal draft',exact=True)).to_be_enabled()
        page.get_by_role('button',name='Refresh journal draft',exact=True).click()
        form.get_by_label('Bookkeeping observation',exact=True).select_option('reviewed')
        form.get_by_role('button',name='Record bookkeeping observation',exact=True).click()
        expect(form).to_contain_text('A different observation is already recorded')
        self.assertEqual(self.rows('expense_journal_review_decisions'),1)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        page.reload();page.get_by_role('button',name='Inspect saved expense drafts',exact=True).click()
        page.get_by_role('button',name='Inspect expense draft '+str(self.saved.id),exact=True).click()
        page.get_by_role('button',name='Inspect journal draft',exact=True).click()
        expect(panel).to_contain_text('Saved journal draft ');expect(form).to_have_count(0)
        page.get_by_role('button',name='Inspect review observations',exact=True).click()
        expect(history).to_contain_text(str(self.user));self.assertEqual(errors,[])

    def test_lost_receipt_preserves_snapshot_choice_and_original_actor(self):
        from playwright.sync_api import expect
        page,panel,form,errors=self.open_observation();original=self.client.request
        def lost(method,url,**kwargs):
            response=original(method,url,**kwargs)
            if method=='POST' and str(url).endswith('/journal-observations'):return httpx.Response(503,json={'error':{'code':'service_unavailable'}})
            return response
        with patch.object(self.client,'request',side_effect=lost):
            form.get_by_role('button',name='Record bookkeeping observation',exact=True).click()
            expect(form.get_by_role('button',name='Retry bookkeeping observation',exact=True)).to_be_enabled()
        expect(form.get_by_label('Bookkeeping observation',exact=True)).to_be_disabled();self.assertEqual(self.rows('expense_journal_review_decisions'),1)
        other=uuid4();self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'fictional-observation-switch','human')",(other,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.a,other))
        self.gateway_token=self.token(scope=SCOPES,sub='fictional-observation-switch')
        form.get_by_role('button',name='Retry bookkeeping observation',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('same account that started this save')
        self.gateway_token=self.token(scope=SCOPES)
        form.get_by_role('button',name='Retry bookkeeping observation',exact=True).click()
        expect(form).to_contain_text('Bookkeeping observation recorded: Changes requested');expect(form).to_contain_text(str(self.user))
        self.assertEqual(self.rows('expense_journal_review_decisions'),1);self.assertEqual(errors,[])

    def test_expiry_clears_source_and_recovers_exact_pending_observation(self):
        from playwright.sync_api import expect
        page,panel,form,errors=self.open_observation()
        self.gateway_token=self.token(scope=SCOPES,iat=self.iat-60,exp=self.iat-1)
        form.get_by_role('button',name='Record bookkeeping observation',exact=True).click()
        expect(page.locator('#content')).to_be_hidden()
        source=page.get_by_role('region',name='Saved expense drafts '+self.evidence,exact=True,include_hidden=True)
        self.assertEqual(source.text_content(),'')
        self.gateway_token=self.token(scope=SCOPES);page.locator('#retry').click()
        expect(form.get_by_label('Bookkeeping observation',exact=True)).to_have_value('changes_requested')
        expect(form.get_by_label('Bookkeeping observation',exact=True)).to_be_disabled();expect(form).to_contain_text(self.snapshot)
        form.get_by_role('button',name='Retry bookkeeping observation',exact=True).click()
        expect(form).to_contain_text('Bookkeeping observation recorded: Changes requested');expect(form).to_contain_text(str(self.user))
        self.assertEqual(self.rows('expense_journal_review_decisions'),1);self.assertEqual(errors,[])

    def test_changed_snapshot_requires_fresh_inspection_before_new_choice(self):
        from playwright.sync_api import expect
        page,panel,form,errors=self.open_observation()
        self.owner.execute("UPDATE omnixat.expense_journal_drafts SET created_by='fictional-changed-author' WHERE id=%s",(self.journal['id'],))
        form.get_by_role('button',name='Record bookkeeping observation',exact=True).click()
        expect(form).to_contain_text('The saved snapshot changed.')
        expect(form.get_by_role('button',name='Retry bookkeeping observation',exact=True)).to_be_disabled()
        self.assertEqual(self.rows('expense_journal_review_decisions'),0)
        page.get_by_role('button',name='Refresh journal draft',exact=True).click()
        expect(form.get_by_label('Bookkeeping observation',exact=True)).to_have_value('')
        expect(form).not_to_contain_text(self.snapshot)
        form.get_by_label('Bookkeeping observation',exact=True).select_option('reviewed')
        form.get_by_role('button',name='Record bookkeeping observation',exact=True).click()
        expect(form).to_contain_text('Bookkeeping observation recorded: Reviewed')
        self.assertEqual(self.rows('expense_journal_review_decisions'),1);self.assertEqual(errors,[])
