"""Actual Chromium/Keycloak login; only the fictional callback page is intercepted."""
import base64
from hashlib import sha256
import os
import secrets
import unittest
from urllib.parse import parse_qs, urlsplit, urlencode
from qualification.keycloak_customer import KeycloakFixture, CALLBACK, CLIENT


class KeycloakBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = KeycloakFixture().__enter__()
        cls.addClassCleanup(cls.provider.__exit__, None, None, None)

    def page(self):
        from playwright.sync_api import sync_playwright
        manager = sync_playwright().start()
        self.addCleanup(manager.stop)
        executable = os.environ.get('OMNIXAT_CHROMIUM_PATH')
        browser = manager.chromium.launch(headless=True,
            args=['--ignore-certificate-errors-spki-list='+self.provider.browser_tls_pin],
            **({'executable_path':executable} if executable else {}))
        self.addCleanup(browser.close)
        context = browser.new_context(ignore_https_errors=False)
        # Prevent any request to the fictional external callback, while allowing
        # actual network requests to Keycloak. Tokens never enter the page.
        context.route(CALLBACK+'?**',lambda route:route.fulfill(
            status=200,content_type='text/html',body='<p>Fictional callback received.</p>'))
        page = context.new_page()
        verifier, nonce, state = (secrets.token_urlsafe(32) for _ in range(3))
        params = {'client_id':CLIENT,'redirect_uri':CALLBACK,'response_type':'code',
                  'scope':'openid records:read records:write','nonce':nonce,'state':state,
                  'code_challenge_method':'S256',
                  'code_challenge':base64.urlsafe_b64encode(sha256(verifier.encode()).digest()).rstrip(b'=').decode()}
        page.goto(self.provider.issuer+'/protocol/openid-connect/auth?'+urlencode(params))
        return page, verifier, nonce, state

    def test_real_browser_login_binds_callback_and_issues_verified_access(self):
        from playwright.sync_api import expect
        page,verifier,nonce,state = self.page()
        expect(page.locator('#username')).to_be_visible()
        page.locator('#username').fill('fictional-editor')
        page.locator('#password').fill(self.provider.password)
        page.locator('#kc-login').click()
        page.wait_for_url(CALLBACK+'?**')
        query = parse_qs(urlsplit(page.url).query)
        self.assertEqual(query.get('state'),[state])
        self.assertEqual(query.get('iss'),[self.provider.issuer])
        self.assertNotIn('error',query)
        self.assertEqual(len(query.get('code',[])),1)
        tokens = self.provider.finish_login(query['code'][0],verifier,nonce)
        verified = self.provider.verifier.verify(tokens['access_token'])
        self.assertEqual(verified.subject,self.provider.subject)
        self.assertTrue({'records:read','records:write'} <= verified.scopes)
        self.assertNotIn(tokens['access_token'],page.content())
        self.assertEqual(self.provider.exchange(query['code'][0],verifier).status_code,400)

    def test_real_browser_wrong_password_does_not_release_authorization_code(self):
        from playwright.sync_api import expect
        page,_,_,_ = self.page()
        page.locator('#username').fill('fictional-editor')
        page.locator('#password').fill(secrets.token_urlsafe(32))
        page.locator('#kc-login').click()
        expect(page.locator('#input-error')).to_be_visible()
        self.assertTrue(page.url.startswith(self.provider.issuer+'/'))
        self.assertNotIn('code',parse_qs(urlsplit(page.url).query))
