"""Real browser uploads via the actual API and PostgreSQL; fictional files only."""
from pathlib import Path
import os
from unittest.mock import patch
from test_customer_evidence import CustomerEvidenceFixture, SCOPES


class CustomerEvidenceBrowserTests(CustomerEvidenceFixture):
    def test_chromium_upload_reload_duplicate_viewer_and_mobile(self):
        from playwright.sync_api import expect
        page,errors = self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        expect(page.get_by_role('heading',name='Evidence',exact=True)).to_be_visible()
        expect(page.locator('#empty-evidence')).to_be_visible()
        page.get_by_label('Document or image',exact=True).set_input_files(
            {'name':'<script>fictional.csv','mimeType':'text/csv','buffer':self.original})
        page.get_by_role('button',name='Upload to quarantine',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Evidence stored in quarantine.')).to_be_visible()
        expect(page.locator('#evidence-list li')).to_have_count(1)
        expect(page.locator('#evidence-list')).to_contain_text('Stored in quarantine')
        self.assertNotIn('<script>',page.locator('#evidence-list').inner_text())
        page.reload()
        expect(page.locator('#evidence-list li')).to_have_count(1)
        page.get_by_label('Document or image',exact=True).set_input_files(
            {'name':'fictional-duplicate.csv','mimeType':'text/csv','buffer':self.original})
        page.get_by_role('button',name='Upload to quarantine',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Evidence stored in quarantine.')).to_be_visible()
        expect(page.locator('#evidence-list li')).to_have_count(1)
        self.assertEqual(self.rows('evidence_quarantine'),1)
        page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        artifacts = os.environ.get('OMNIXAT_BROWSER_ARTIFACTS')
        if artifacts:
            Path(artifacts).mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(Path(artifacts)/'customer-evidence-mobile.png'),full_page=True)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        page.reload()
        expect(page.locator('#evidence-list li')).to_have_count(1)
        expect(page.locator('#evidence-form')).to_be_hidden()
        self.assertEqual(page.evaluate('Object.keys(localStorage).length + Object.keys(sessionStorage).length'),0)
        self.assertEqual(errors,[])

    def test_chromium_lost_upload_response_retries_same_file(self):
        from playwright.sync_api import expect
        import httpx
        page,errors = self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        expect(page.get_by_role('heading',name='Evidence',exact=True)).to_be_visible()
        page.get_by_label('Document or image',exact=True).set_input_files(
            {'name':'fictional.csv','mimeType':'text/csv','buffer':self.original})
        original = self.client.request
        lost = [False]
        def lose(method,url,**kwargs):
            response = original(method,url,**kwargs)
            if method=='POST' and str(url).endswith('/evidence') and not lost[0]:
                lost[0] = True
                return httpx.Response(503,json={'error':{'code':'service_unavailable'}})
            return response
        with patch.object(self.client,'request',side_effect=lose):
            page.get_by_role('button',name='Upload to quarantine',exact=True).click()
            expect(page.get_by_role('button',name='Retry upload',exact=True)).to_be_visible()
            expect(page.get_by_label('Document or image',exact=True)).to_be_disabled()
            page.get_by_role('button',name='Retry upload',exact=True).click()
            expect(page.get_by_role('status').filter(has_text='Evidence stored in quarantine.')).to_be_visible()
        expect(page.locator('#evidence-list li')).to_have_count(1)
        self.assertEqual(self.rows('evidence_quarantine'),1)
        self.assertEqual(self.rows('evidence_registrations'),1)
        self.assertEqual(errors,[])
