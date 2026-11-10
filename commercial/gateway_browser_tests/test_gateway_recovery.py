"""Real gateway/provider reauthentication, original-tab work and actor binding."""
from hashlib import sha256
from uuid import uuid4
from urllib.parse import parse_qs, urlsplit

from test_customer_gateway import CustomerGatewayFixture
from test_customer_evidence import CustomerEvidenceFixture


class GatewayRecoveryTests(CustomerGatewayFixture, CustomerEvidenceFixture):
    # Cooperative fixtures add the existing constrained quarantine grants/spool.
    recovery_profile = True

    def setUp(self):
        super().setUp()
        other = uuid4()
        self.owner.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,%s,'human')",
                           (other,self.provider.issuer,self.provider.secondary_subject))
        self.addCleanup(self.owner.execute,'DELETE FROM omnixat.identities WHERE id=%s',(other,))
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.a,other))
        self.addCleanup(self.owner.execute,'DELETE FROM omnixat.memberships WHERE user_id=%s',(other,))

    def sign_out_elsewhere(self, page):
        from playwright.sync_api import expect
        tab = page.context.new_page()
        tab.goto(self.origin+'/oauth2/sign_out?rd=/')
        expect(tab.get_by_role('link',name='Sign in',exact=True)).to_be_visible()
        tab.close()
        self.assertFalse(any(c['name'].startswith('__Host-omnixat-customer') for c in page.context.cookies(self.origin)))

    def recovery_tab(self, page, link, *, second=False):
        from playwright.sync_api import expect
        expect(link).to_be_visible()
        expect(link).to_have_attribute('target','_blank')
        expect(link).to_have_attribute('rel','noopener noreferrer')
        # Context event works even when noopener/COOP severs the opener relation.
        with page.context.expect_page() as opened:
            link.click()
        tab = opened.value
        expect(tab.locator('#username')).to_be_visible()
        self.assertEqual(parse_qs(urlsplit(tab.url).query).get('prompt'),['login'])
        tab.locator('#username').fill('fictional-second-editor' if second else 'fictional-editor')
        tab.locator('#password').fill(self.provider.secondary_password if second else self.provider.password)
        tab.locator('#kc-login').click()
        expect(tab.locator('#recovery-ready')).to_be_visible()
        self.assertEqual(tab.url,self.origin+'/app/reauthenticated')
        self.assertIsNone(tab.evaluate('window.opener'))
        self.assertEqual(tab.evaluate('Object.keys(localStorage).length + Object.keys(sessionStorage).length'),0)
        return tab

    def test_real_new_tab_login_recovery_keeps_pending_organisation(self):
        from playwright.sync_api import expect
        page = self.page(); self.login(page)
        original_url = page.url
        page.get_by_role('button',name='+ New organisation').click()
        name = 'Fictional gateway recovered organisation'
        field = page.get_by_label('Organisation name',exact=True)
        field.fill(name)
        self.sign_out_elsewhere(page)
        with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/organisations')) as failed:
            page.get_by_role('button',name='Create organisation',exact=True).click()
        self.assertEqual(failed.value.status,401)
        expect(field).to_be_disabled()
        expect(field).to_have_value(name)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.organisations WHERE tenant_id=%s AND display_name=%s',(self.a,name)).fetchone(),(0,))
        recovery = self.recovery_tab(page,page.locator('#dialog-reauth'))
        self.assertEqual(self.gateway.observed[-1][2],self.provider.subject)
        self.assertEqual(page.url,original_url)
        expect(field).to_have_value(name)
        expect(field).to_be_disabled()
        recovery.close()
        page.get_by_role('button',name='Retry save',exact=True).click()
        expect(page.get_by_role('heading',name=name,exact=True)).to_be_visible()
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.organisations WHERE tenant_id=%s AND display_name=%s AND created_by=%s',(self.a,name,str(self.user))).fetchone(),(1,))

    def test_real_new_tab_recovery_keeps_exact_upload_and_deduplicates(self):
        from playwright.sync_api import expect
        page = self.page(); self.login(page)
        url = self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}'
        page.goto(url)
        expect(page.get_by_role('heading',name='Evidence',exact=True)).to_be_visible()
        file = page.get_by_label('Document or image',exact=True)
        file.set_input_files({'name':'fictional-gateway-recovery.csv','mimeType':'text/csv','buffer':self.original})
        self.sign_out_elsewhere(page)
        with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/evidence')) as failed:
            page.get_by_role('button',name='Upload to quarantine',exact=True).click()
        self.assertEqual(failed.value.status,401)
        expect(file).to_be_disabled()
        expect(page.get_by_label('Document format',exact=True)).to_be_disabled()
        self.assertEqual(self.rows('evidence_quarantine'),0)
        recovery = self.recovery_tab(page,page.locator('#reauth'))
        self.assertEqual(page.url,url)
        self.assertEqual(file.evaluate('(input) => input.files[0].name'),'fictional-gateway-recovery.csv')
        digest = file.evaluate("""async input => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await input.files[0].arrayBuffer()))).map(b=>b.toString(16).padStart(2,'0')).join('')""")
        self.assertEqual(digest,sha256(self.original).hexdigest())
        expect(file).to_be_disabled()
        recovery.close()
        page.get_by_role('button',name='Retry upload',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Evidence stored in quarantine.')).to_be_visible()
        # Re-select the same bytes after success; real service deduplication keeps one original.
        file.set_input_files({'name':'fictional-same-bytes.csv','mimeType':'text/csv','buffer':self.original})
        page.get_by_role('button',name='Upload to quarantine',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Evidence stored in quarantine.')).to_be_visible()
        expect(page.locator('#evidence-list li')).to_have_count(1)
        self.assertEqual(self.rows('evidence_quarantine'),1)
        self.assertEqual(self.rows('evidence_registrations'),1)
        row = self.owner.execute('SELECT q.original_bytes,e.content_sha256,e.registered_by FROM omnixat.evidence_quarantine q JOIN omnixat.evidence_registrations e ON e.tenant_id=q.tenant_id AND e.id=q.evidence_id WHERE e.tenant_id=%s',(self.a,)).fetchone()
        self.assertEqual(row,(self.original,sha256(self.original).digest(),str(self.user)))

    def test_real_account_switch_cannot_retry_another_actors_pending_note(self):
        from playwright.sync_api import expect
        page = self.page(); self.login(page)
        url = self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}'
        page.goto(url)
        field = page.get_by_label('Note',exact=True)
        body = 'Fictional gateway account-bound retry'
        field.fill(body)
        self.sign_out_elsewhere(page)
        page.get_by_role('button',name='Save note',exact=True).click()
        expect(page.get_by_role('button',name='Retry save',exact=True)).to_be_visible()
        recovery = self.recovery_tab(page,page.locator('#reauth'),second=True)
        self.assertEqual(self.gateway.observed[-1][2],self.provider.secondary_subject)
        recovery.close()
        with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/notes')) as denied:
            page.get_by_role('button',name='Retry save',exact=True).click()
        self.assertEqual(denied.value.status,409)
        self.assertEqual(denied.value.json()['error']['code'],'session_changed')
        expect(page.locator('#error-message')).to_contain_text('same account that started this save')
        expect(field).to_have_value(body)
        expect(field).to_be_disabled()
        self.assertEqual(page.url,url)
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.notes WHERE tenant_id=%s AND body=%s',(self.a,body)).fetchone(),(0,))
        self.sign_out_elsewhere(page)
        recovery = self.recovery_tab(page,page.locator('#reauth'),second=False)
        self.assertEqual(self.gateway.observed[-1][2],self.provider.subject)
        recovery.close()
        page.get_by_role('button',name='Retry save',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Note saved.')).to_be_visible()
        self.assertEqual(self.owner.execute('SELECT count(*) FROM omnixat.notes WHERE tenant_id=%s AND body=%s AND created_by=%s',(self.a,body,str(self.user))).fetchone(),(1,))
