from uuid import uuid4
from unittest.mock import patch
import httpx
from test_customer_csv_requests import CustomerCSVRequestFixture, REQUEST_SCOPES


class CustomerCSVRequestBrowserTests(CustomerCSVRequestFixture):
    def open_form(self):
        self.ready()
        page,errors=self.browser(token=self.token(scope=REQUEST_SCOPES))
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        form=page.get_by_role('form',name='Request CSV extraction '+self.evidence,exact=True)
        form.get_by_label('Amount label',exact=True).fill('amount')
        form.get_by_label('CSV record number',exact=True).fill('2')
        form.get_by_label('CSV column number',exact=True).fill('2')
        return page,errors,form

    def test_customer_request_explicit_cli_and_candidate_inspection(self):
        from playwright.sync_api import expect
        page,errors,form=self.open_form()
        page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        form.get_by_role('button',name='Request CSV extraction',exact=True).click()
        expect(form).to_contain_text('Awaiting an operator-run worker.')
        self.assertEqual(self.rows('csv_extraction_results'),0)
        job,cells=self.owner.execute('SELECT job_id,selections FROM omnixat.csv_extraction_requests WHERE tenant_id=%s',(self.a,)).fetchone()
        result=self.requested_worker(self.plan()|{'job':str(job),'selections':cells})
        self.assertEqual(result[0],0,result[2])
        page.get_by_role('button',name='Inspect CSV candidates',exact=True).click()
        panel=page.get_by_role('region',name='CSV candidates '+self.evidence,exact=True)
        expect(panel).to_contain_text('amount · row 2, column 2: 12.00'); expect(panel).to_contain_text(str(job))
        page.reload()
        expect(page.get_by_role('form',name='Request CSV extraction '+self.evidence,exact=True)).to_be_visible()
        self.assertEqual(self.rows('csv_extraction_requests'),1); self.assertEqual(self.rows('csv_extraction_results'),1)
        self.assertEqual(errors,[])

    def test_lost_receipt_same_plan_and_wrong_account_retry(self):
        from playwright.sync_api import expect
        page,errors,form=self.open_form(); original=self.client.request; bodies=[]
        def lost(method,url,**kwargs):
            response=original(method,url,**kwargs)
            if method=='POST' and str(url).endswith('/csv-requests'):
                bodies.append(kwargs.get('content'))
                return httpx.Response(503,json={'error':{'code':'service_unavailable'}})
            return response
        with patch.object(self.client,'request',side_effect=lost):
            form.get_by_role('button',name='Request CSV extraction',exact=True).click()
            expect(form.get_by_role('button',name='Retry extraction request',exact=True)).to_be_enabled()
        expect(form.get_by_label('CSV record number',exact=True)).to_be_disabled()
        other=uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'fictional-request-switch','human')",(other,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.a,other))
        self.gateway_token=self.token(scope=REQUEST_SCOPES,sub='fictional-request-switch')
        form.get_by_role('button',name='Retry extraction request',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('same account that started this save')
        self.gateway_token=self.token(scope=REQUEST_SCOPES)
        form.get_by_role('button',name='Retry extraction request',exact=True).click()
        expect(form).to_contain_text('Awaiting an operator-run worker.')
        self.assertEqual(self.rows('csv_extraction_requests'),1); self.assertEqual(self.rows('csv_extraction_results'),0)
        self.assertEqual(errors,[])

    def test_expiry_recovery_preserves_request_and_revocation_denies_dispatch(self):
        from playwright.sync_api import expect
        page,errors,form=self.open_form()
        self.gateway_token=self.token(scope=REQUEST_SCOPES,iat=self.iat-60,exp=self.iat-1)
        form.get_by_role('button',name='Request CSV extraction',exact=True).click()
        expect(page.locator('#content')).to_be_hidden()
        other=uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,'fictional-request-viewer','human')",(other,self.issuer))
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'viewer',NULL)",(self.a,other))
        self.gateway_token=self.token(scope=REQUEST_SCOPES,sub='fictional-request-viewer')
        page.locator('#retry').click()
        expect(form.get_by_label('CSV record number',exact=True)).to_have_value('2')
        expect(form.get_by_label('CSV record number',exact=True)).to_be_disabled()
        form.get_by_role('button',name='Retry extraction request',exact=True).click()
        expect(page.locator('#error-message')).to_contain_text('same account that started this save')
        self.assertEqual(self.rows('csv_extraction_requests'),0)
        self.gateway_token=self.token(scope=REQUEST_SCOPES)
        form.get_by_role('button',name='Retry extraction request',exact=True).click()
        expect(form).to_contain_text('Awaiting an operator-run worker.')
        job,cells=self.owner.execute('SELECT job_id,selections FROM omnixat.csv_extraction_requests WHERE tenant_id=%s',(self.a,)).fetchone()
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        self.assertEqual(self.requested_worker(self.plan()|{'job':str(job),'selections':cells})[0],1)
        self.assertEqual(self.rows('csv_extraction_results'),0); self.assertEqual(errors,[])
