from unittest.mock import patch
from uuid import uuid4
import httpx
from test_csv_reauthorisation import CSVReauthorisationFixture
from test_customer_csv_requests import REQUEST_SCOPES


class CSVReauthorisationBrowserTests(CSVReauthorisationFixture):
    def open_cancelled(self):
        from playwright.sync_api import expect
        self.cancel_ready()
        page,errors=self.browser(token=self.token(scope=REQUEST_SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        page.get_by_role('button',name='Inspect extraction requests',exact=True).click()
        panel=page.get_by_role('region',name='CSV extraction requests '+self.evidence,exact=True,include_hidden=True)
        expect(panel.get_by_role('button',name='Request extraction again',exact=True)).to_be_enabled()
        return page,errors,panel

    def child(self):
        return self.owner.execute('SELECT job_id FROM omnixat.csv_extraction_requests WHERE tenant_id=%s AND previous_job_id=%s',(self.a,self.job)).fetchone()[0]

    def test_explicit_replacement_preserves_history_and_dispatches_selected_cells(self):
        from playwright.sync_api import expect
        page,errors,panel=self.open_cancelled()
        panel.get_by_role('button',name='Request extraction again',exact=True).click()
        expect(panel).to_contain_text('Replacement request recorded — original cancellation retained')
        expect(panel).to_contain_text('Awaiting an operator-run worker')
        child=self.child(); self.assertEqual(self.rows('csv_extraction_requests'),2)
        self.assertEqual(self.listing(self.job).json()['data']['items'][0]['cancelled_at'],self.cancelled)
        result=self.requested_worker(self.plan()|{'job':str(child)}); self.assertEqual(result[0],0,result[2])
        page.reload(); page.get_by_role('button',name='Inspect extraction requests',exact=True).click()
        expect(panel).to_contain_text('A result is recorded for this job')
        expect(panel).to_contain_text(str(child)); expect(panel).to_contain_text(str(self.job))
        page.get_by_role('button',name='Inspect CSV candidates',exact=True).click()
        candidates=page.get_by_role('region',name='CSV candidates '+self.evidence,exact=True)
        expect(candidates).to_contain_text(str(child)); expect(candidates).to_contain_text('amount · row 2, column 2: 12.00')
        page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        self.assertEqual(self.rows('csv_extraction_results'),1); self.assertEqual(errors,[])

    def test_lost_receipt_and_stale_exact_retry_do_not_restart_cancelled_child(self):
        from playwright.sync_api import expect
        page,errors,panel=self.open_cancelled(); original=self.client.request
        def lose(method,url,**kwargs):
            response=original(method,url,**kwargs)
            if method=='POST' and str(url).endswith('/reauthorisations'):
                return httpx.Response(503,json={'error':{'code':'service_unavailable'}})
            return response
        with patch.object(self.client,'request',side_effect=lose):
            panel.get_by_role('button',name='Request extraction again',exact=True).click()
            expect(panel.get_by_role('button',name='Retry extraction re-authorisation',exact=True)).to_be_visible()
        child=self.child(); self.assertEqual(self.cancel(child).status_code,202)
        other=uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'fictional-renew-switch','human')",(other,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.a,other))
        self.gateway_token=self.token(scope=REQUEST_SCOPES,sub='fictional-renew-switch')
        panel.get_by_role('button',name='Retry extraction re-authorisation',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('same account that started this save')
        self.gateway_token=self.token(scope=REQUEST_SCOPES)
        panel.get_by_role('button',name='Retry extraction re-authorisation',exact=True).click()
        expect(panel.get_by_role('button',name='Retry extraction re-authorisation',exact=True)).to_have_count(0)
        self.assertEqual(self.rows('csv_extraction_requests'),2)
        self.assertEqual(self.listing(child).json()['data']['items'][0]['state'],'cancelled')
        self.assertEqual(self.requested_worker(self.plan()|{'job':str(child)})[0],1)
        self.assertEqual(errors,[])

    def test_expiry_and_viewer_recovery_keep_original_renewal_actor(self):
        from playwright.sync_api import expect
        page,errors,panel=self.open_cancelled()
        self.gateway_token=self.token(scope=REQUEST_SCOPES,iat=self.iat-60,exp=self.iat-1)
        panel.get_by_role('button',name='Request extraction again',exact=True).click()
        expect(page.locator('#content')).to_be_hidden(); self.assertEqual(panel.text_content(),'')
        other=uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'fictional-renew-viewer','human')",(other,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'viewer',NULL)",(self.a,other))
        self.gateway_token=self.token(scope=REQUEST_SCOPES,sub='fictional-renew-viewer')
        page.locator('#retry').click()
        expect(panel.get_by_role('button',name='Request extraction again',exact=True)).to_have_count(0)
        panel.get_by_role('button',name='Retry extraction re-authorisation',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('same account that started this save')
        self.assertEqual(self.rows('csv_extraction_requests'),1)
        self.gateway_token=self.token(scope=REQUEST_SCOPES)
        panel.get_by_role('button',name='Retry extraction re-authorisation',exact=True).click()
        expect(panel).to_contain_text('Replacement request recorded — original cancellation retained')
        self.assertEqual(self.rows('csv_extraction_requests'),2); self.assertEqual(errors,[])
