from unittest.mock import patch
from uuid import uuid4
import httpx
from test_csv_request_lifecycle import CSVRequestLifecycleFixture
from test_customer_csv_requests import REQUEST_SCOPES


class CSVRequestLifecycleBrowserTests(CSVRequestLifecycleFixture):
    def open_requests(self):
        from playwright.sync_api import expect
        self.ready(); self.request()
        page,errors=self.browser(token=self.token(scope=REQUEST_SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Inspect extraction requests',exact=True).click()
        panel=page.get_by_role('region',name='CSV extraction requests '+self.evidence,exact=True,include_hidden=True)
        # Inspection is asynchronous; establish readiness before tests expire tokens.
        expect(panel.get_by_role('button',name='Cancel extraction request',exact=True)).to_be_enabled()
        return page,errors,panel

    def test_inspect_reload_cancel_and_retained_history_without_restarting(self):
        from playwright.sync_api import expect
        page,errors,panel=self.open_requests()
        expect(panel).to_contain_text(str(self.job)); expect(panel).to_contain_text('amount · record 2, column 2')
        page.reload(); page.get_by_role('button',name='Inspect extraction requests',exact=True).click()
        expect(panel).to_contain_text('Awaiting an operator-run worker')
        panel.get_by_role('button',name='Cancel extraction request',exact=True).click()
        expect(panel).to_contain_text('Cancelled — requested result storage is stopped')
        expect(panel).to_contain_text(str(self.user)); self.assertEqual(self.requested_worker()[0],1)
        self.assertEqual(self.request().status_code,202)
        page.reload(); page.get_by_role('button',name='Inspect extraction requests',exact=True).click()
        expect(panel).to_contain_text('Cancelled — requested result storage is stopped')
        expect(panel.get_by_role('button',name='Cancel extraction request',exact=True)).to_have_count(0)
        page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        self.assertEqual(self.rows('csv_extraction_results'),0); self.assertEqual(errors,[])

    def test_lost_cancellation_receipt_exact_actor_retry(self):
        from playwright.sync_api import expect
        page,errors,panel=self.open_requests(); original=self.client.request
        def lost(method,url,**kwargs):
            response=original(method,url,**kwargs)
            if method=='POST' and str(url).endswith('/cancellations'):
                return httpx.Response(503,json={'error':{'code':'service_unavailable'}})
            return response
        with patch.object(self.client,'request',side_effect=lost):
            panel.get_by_role('button',name='Cancel extraction request',exact=True).click()
            expect(panel.get_by_role('button',name='Retry extraction cancellation',exact=True)).to_be_visible()
        original_time=self.listing(self.job).json()['data']['items'][0]['cancelled_at']
        other=uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'fictional-cancel-switch','human')",(other,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.a,other))
        self.gateway_token=self.token(scope=REQUEST_SCOPES,sub='fictional-cancel-switch')
        panel.get_by_role('button',name='Retry extraction cancellation',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('same account that started this save')
        self.gateway_token=self.token(scope=REQUEST_SCOPES)
        panel.get_by_role('button',name='Retry extraction cancellation',exact=True).click()
        expect(panel.get_by_role('button',name='Retry extraction cancellation',exact=True)).to_have_count(0)
        self.assertEqual(self.listing(self.job).json()['data']['items'][0]['cancelled_at'],original_time)
        self.assertEqual(self.rows('csv_extraction_results'),0); self.assertEqual(errors,[])

    def test_expiry_clears_metadata_and_viewer_recovery_cannot_cancel(self):
        from playwright.sync_api import expect
        page,errors,panel=self.open_requests()
        self.gateway_token=self.token(scope=REQUEST_SCOPES,iat=self.iat-60,exp=self.iat-1)
        panel.get_by_role('button',name='Cancel extraction request',exact=True).click()
        expect(page.locator('#content')).to_be_hidden(); self.assertEqual(panel.text_content(),'')
        other=uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'fictional-cancel-viewer','human')",(other,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'viewer',NULL)",(self.a,other))
        self.gateway_token=self.token(scope=REQUEST_SCOPES,sub='fictional-cancel-viewer')
        page.locator('#retry').click()
        expect(panel.get_by_role('button',name='Cancel extraction request',exact=True)).to_have_count(0)
        panel.get_by_role('button',name='Retry extraction cancellation',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('same account that started this save')
        self.assertIsNone(self.listing(self.job).json()['data']['items'][0]['cancelled_at'])
        self.gateway_token=self.token(scope=REQUEST_SCOPES)
        panel.get_by_role('button',name='Retry extraction cancellation',exact=True).click()
        expect(panel).to_contain_text('Cancelled — requested result storage is stopped')
        self.assertEqual(self.requested_worker()[0],1); self.assertEqual(errors,[])
