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

    def test_chromium_expired_upload_keeps_exact_file_until_authenticated_retry(self):
        from playwright.sync_api import expect
        page,errors = self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        expect(page.get_by_role('heading',name='Evidence',exact=True)).to_be_visible()
        page.get_by_label('Document or image',exact=True).set_input_files(
            {'name':'fictional-expiry.csv','mimeType':'text/csv','buffer':self.original})
        self.gateway_token = self.token(scope=SCOPES,iat=self.iat-60,exp=self.iat-1)
        page.get_by_role('button',name='Upload to quarantine',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('Your session has ended.')
        expect(page.locator('#reauth')).to_be_visible()
        expect(page.get_by_label('Document or image',exact=True)).to_be_disabled()
        expect(page.get_by_label('Document format',exact=True)).to_be_disabled()
        expect(page.get_by_role('button',name='Clear selection',exact=True)).to_be_disabled()
        expect(page.get_by_role('button',name='Retry upload',exact=True)).to_be_visible()
        self.assertEqual(self.rows('evidence_registrations'),0)
        self.gateway_token = self.token(scope=SCOPES)
        page.get_by_role('button',name='Retry upload',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Evidence stored in quarantine.')).to_be_visible()
        expect(page.locator('#evidence-list li')).to_have_count(1)
        self.assertEqual(self.rows('evidence_quarantine'),1)
        self.assertEqual(errors,[])

    def test_chromium_rejected_format_can_be_corrected_without_losing_file(self):
        from playwright.sync_api import expect
        page,errors = self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        expect(page.get_by_role('heading',name='Evidence',exact=True)).to_be_visible()
        page.get_by_label('Document or image',exact=True).set_input_files(
            {'name':'fictional-format.csv','mimeType':'text/csv','buffer':self.original})
        page.get_by_role('button',name='Upload to quarantine',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Evidence stored in quarantine.')).to_be_visible()
        page.get_by_label('Document or image',exact=True).set_input_files(
            {'name':'fictional-format.csv','mimeType':'text/csv','buffer':self.original})
        page.get_by_label('Document format',exact=True).select_option('application/pdf')
        page.get_by_role('button',name='Upload to quarantine',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('Check the format and saved evidence')
        expect(page.get_by_label('Document or image',exact=True)).to_be_enabled()
        self.assertEqual(page.locator('#evidence-file').evaluate('(input) => input.files.length'),1)
        page.get_by_label('Document format',exact=True).select_option('text/csv')
        page.get_by_role('button',name='Upload to quarantine',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Evidence stored in quarantine.')).to_be_visible()
        expect(page.locator('#evidence-list li')).to_have_count(1)
        self.assertEqual(self.rows('evidence_quarantine'),1)
        self.assertEqual(errors,[])

    def test_chromium_receipt_fingerprint_retry_viewer_and_mobile(self):
        from hashlib import sha256
        from playwright.sync_api import expect
        import httpx
        evidence = self.upload().json()['data']['id']
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        page,errors = self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        button = page.get_by_role('button',name='View receipt',exact=True)
        expect(button).to_be_visible()
        panel = page.get_by_role('region',name='Evidence receipt '+evidence,exact=True,include_hidden=True)
        original = self.client.request
        def unavailable(method,url,**kwargs):
            if str(url).endswith('/evidence/'+evidence):
                return httpx.Response(503,json={'error':{'code':'service_unavailable'}})
            return original(method,url,**kwargs)
        with patch.object(self.client,'request',side_effect=unavailable):
            button.click()
            expect(panel.get_by_role('alert')).to_contain_text('Close and reopen')
        page.get_by_role('button',name='Close receipt',exact=True).click()
        button.click()
        expect(panel).to_contain_text(sha256(self.original).hexdigest())
        expect(panel).to_contain_text('SHA-256 of original bytes')
        expect(panel).to_contain_text('does not establish a valid file')
        expect(page.locator('#evidence-form')).to_be_hidden()
        expect(page.get_by_role('button',name='Hide receipt',exact=True)).to_have_attribute('aria-expanded','true')
        page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        artifacts = os.environ.get('OMNIXAT_BROWSER_ARTIFACTS')
        if artifacts:
            Path(artifacts).mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(Path(artifacts)/'customer-receipt-mobile.png'),full_page=True)
        page.get_by_role('button',name='Hide receipt',exact=True).click()
        expect(panel).to_be_hidden()
        self.assertEqual(panel.text_content(),'')
        self.assertEqual(page.evaluate('Object.keys(localStorage).length + Object.keys(sessionStorage).length'),0)
        self.assertEqual(errors,[])

    def test_chromium_receipt_expiry_requires_sign_in_and_hides_metadata(self):
        from playwright.sync_api import expect
        self.upload()
        page,errors = self.browser(token=self.token(scope=SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        expect(page.get_by_role('button',name='View receipt',exact=True)).to_be_visible()
        self.gateway_token = self.token(scope=SCOPES,iat=self.iat-60,exp=self.iat-1)
        page.get_by_role('button',name='View receipt',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('Your session has ended.')
        expect(page.locator('#reauth')).to_be_visible()
        expect(page.locator('#content')).to_be_hidden()
        self.assertEqual(page.locator('.evidence-receipt').text_content(),'')
        self.assertEqual(errors,[])

    def test_chromium_reauthentication_tab_keeps_selected_file_for_exact_retry(self):
        from playwright.sync_api import expect
        page,errors = self.browser(token=self.token(scope=SCOPES))
        url = self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}'
        page.goto(url)
        expect(page.get_by_role('heading',name='Evidence',exact=True)).to_be_visible()
        page.get_by_label('Document or image',exact=True).set_input_files(
            {'name':'fictional-reauth.csv','mimeType':'text/csv','buffer':self.original})
        self.gateway_token = self.token(scope=SCOPES,iat=self.iat-60,exp=self.iat-1)
        page.get_by_role('button',name='Upload to quarantine',exact=True).click()
        expect(page.locator('#reauth')).to_be_visible()
        page.context.route('**/oauth2/start?rd=/app/reauthenticated',lambda route:route.fulfill(
            status=200,content_type='text/html',body='Fictional gateway sign-in'))
        self.gateway_token = self.token(scope=SCOPES)
        with page.expect_popup() as opened:
            page.locator('#reauth').click()
        recovery = opened.value
        # Complete the simulated hosted login as a new navigation; Playwright
        # route handlers do not intercept a fulfilled redirect's follow-up URL.
        recovery.goto(self.origin+'/app/reauthenticated')
        expect(recovery.locator('#recovery-ready')).to_be_visible()
        self.assertIsNone(recovery.evaluate('window.opener'))
        self.assertEqual(page.url,url)
        self.assertEqual(page.locator('#evidence-file').evaluate('(input) => input.files[0].name'),'fictional-reauth.csv')
        expect(page.get_by_label('Document or image',exact=True)).to_be_disabled()
        recovery.close()
        page.get_by_role('button',name='Retry upload',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Evidence stored in quarantine.')).to_be_visible()
        self.assertEqual(self.rows('evidence_quarantine'),1)
        self.assertEqual(self.rows('evidence_registrations'),1)
        self.assertEqual(errors,[])
