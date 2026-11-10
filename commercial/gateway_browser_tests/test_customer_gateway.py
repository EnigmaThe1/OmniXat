"""Real Chromium -> real TLS OAuth2 Proxy -> ASGI/PostgreSQL + real Keycloak."""
import os
from urllib.parse import parse_qs, urlsplit

from test_customer_web import CustomerWebFixture
from omnixat_core.customer_web import create_app
from qualification.customer_gateway import CustomerGateway
from qualification.keycloak_customer import KeycloakFixture


class CustomerGatewayBrowserTests(CustomerWebFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = KeycloakFixture(gateway_profile=True).__enter__()
        cls.addClassCleanup(cls.provider.__exit__, None, None, None)

    def setUp(self):
        super().setUp()
        self.addCleanup(self.owner.execute, 'UPDATE omnixat.identities SET issuer=%s,subject=%s WHERE id=%s',
                        (self.issuer,self.subject,self.user))
        self.owner.execute('UPDATE omnixat.identities SET issuer=%s,subject=%s WHERE id=%s',
                           (self.provider.issuer,self.provider.subject,self.user))
        app = create_app(verifier=self.provider.verifier, connection_factory=self.records_factory,
                         directory_connection_factory=self.directory_factory, public_origin=self.origin)
        self.gateway = CustomerGateway(app,self.provider).__enter__()
        self.addCleanup(self.gateway.__exit__,None,None,None)

    def page(self):
        from playwright.sync_api import sync_playwright
        manager = sync_playwright().start(); self.addCleanup(manager.stop)
        executable = os.environ.get('OMNIXAT_CHROMIUM_PATH')
        browser = manager.chromium.launch(headless=True, args=[
            '--ignore-certificate-errors-spki-list='+self.provider.browser_tls_pin,
            # Real DNS/network routing to the high loopback TLS port, no route mocking.
            f'--host-resolver-rules=MAP workspace.example.test 127.0.0.1:{self.gateway.port}',
        ], **({'executable_path':executable} if executable else {}))
        self.addCleanup(browser.close)
        context = browser.new_context(ignore_https_errors=False)
        return context.new_page()

    def login(self, page):
        from playwright.sync_api import expect
        response = page.goto(self.origin+'/')
        self.assertEqual(response.status,200)
        expect(page.get_by_role('heading').filter(has_text='A clearer place')).to_be_visible()
        page.get_by_role('link',name='Sign in',exact=True).click()
        expect(page.locator('#username')).to_be_visible()
        auth = parse_qs(urlsplit(page.url).query)
        self.assertEqual(auth.get('code_challenge_method'),['S256'])
        self.assertTrue(bool(auth.get('code_challenge')) and bool(auth.get('nonce')) and bool(auth.get('state')))
        page.locator('#username').fill('fictional-editor')
        page.locator('#password').fill(self.provider.password)
        page.locator('#kc-login').click()
        expect(page.get_by_role('heading',name='Everything starts here.')).to_be_visible()

    def test_gateway_login_record_write_refresh_and_local_signout(self):
        from playwright.sync_api import expect
        page = self.page(); self.login(page)
        cookies = [c for c in page.context.cookies(self.origin) if c['name'].startswith('__Host-omnixat-customer')]
        self.assertTrue(bool(cookies))
        self.assertTrue(all(c['secure'] and c['httpOnly'] and c['sameSite']=='Lax' and
                            c['path']=='/' and c['domain']=='workspace.example.test' for c in cookies))
        self.assertNotIn('__Host-omnixat-customer',page.evaluate('document.cookie'))
        self.assertEqual(page.evaluate('Object.keys(localStorage).length + Object.keys(sessionStorage).length'),0)
        self.assertTrue(bool(self.gateway.observed))
        original = self.gateway.observed[-1]
        self.assertEqual(original[2],self.provider.subject)
        page.get_by_role('button',name='+ New organisation').click()
        page.get_by_label('Organisation name',exact=True).fill('Fictional gateway organisation')
        page.get_by_role('button',name='Create organisation',exact=True).click()
        expect(page.get_by_role('heading',name='Fictional gateway organisation',exact=True)).to_be_visible()
        page.get_by_label('Note',exact=True).fill('Fictional gateway note')
        page.get_by_role('button',name='Save note',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Note saved.')).to_be_visible()
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.notes WHERE tenant_id=%s AND body='Fictional gateway note' AND created_by=%s",(self.a,str(self.user))).fetchone(),(1,))
        # Accelerated cookie refresh is test-only; compare actual upstream tokens.
        page.wait_for_timeout(6000)
        self.assertEqual(page.evaluate("async () => (await fetch('/v1/workspaces')).status"),200)
        refreshed = self.gateway.observed[-1]
        self.assertTrue(refreshed[0]!=original[0] and refreshed[1]>original[1])
        self.assertEqual(refreshed[2],original[2])
        # The public route does not require auth, so sign-out cannot silently re-login.
        page.get_by_role('link',name='Sign out',exact=True).click()
        expect(page.get_by_role('link',name='Sign in',exact=True)).to_be_visible()
        self.assertFalse(any(c['name'].startswith('__Host-omnixat-customer') for c in page.context.cookies(self.origin)))
        self.assertEqual(page.evaluate("async () => (await fetch('/v1/workspaces',{redirect:'manual'})).status"),401)

    def test_gateway_rejects_spoofing_and_rechecks_database_authority(self):
        from playwright.sync_api import expect
        with self.gateway.client() as client:
            for headers in [{},{'X-Forwarded-Access-Token':self.token(),'X-Forwarded-User':'owner'},
                            {'Authorization':'Bearer '+self.token()}]:
                self.assertEqual(client.get('/v1/workspaces',headers=headers).status_code,401)
            started = client.get('/oauth2/start?rd=/app')
            self.assertEqual(started.status_code,302)
            self.assertTrue(started.headers['location'].startswith(self.provider.issuer+'/'))
            state = parse_qs(urlsplit(started.headers['location']).query)['state'][0]
            client.cookies.clear()
            callback = client.get('/oauth2/callback',params={'state':state,'code':'fictional-never-issued'})
            self.assertEqual(callback.status_code,403)
            self.assertFalse(any(name.startswith('__Host-omnixat-customer') for name in client.cookies))
        page = self.page(); self.login(page)
        # Gateway must overwrite the caller's claimed access token.
        page.set_extra_http_headers({'X-Forwarded-Access-Token':'untrusted','X-Forwarded-User':'owner'})
        self.assertEqual(page.evaluate("async () => (await fetch('/v1/workspaces')).status"),200)
        self.assertEqual(self.gateway.observed[-1][2],self.provider.subject)
        page.set_extra_http_headers({})
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        response = page.evaluate("""async url => (await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':'fictional-gateway-denied'},body:JSON.stringify({display_name:'Denied gateway write'})})).status""",self.base+'/organisations')
        self.assertEqual(response,403)
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.organisations WHERE tenant_id=%s AND display_name='Denied gateway write'",(self.a,)).fetchone(),(0,))
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        page.reload()
        expect(page.get_by_role('alert')).to_contain_text('Your access has changed')
        expect(page.locator('#content')).to_be_hidden()
