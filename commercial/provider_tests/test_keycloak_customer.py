"""Real maintained provider + real tenant services. No credential/token fixtures."""
import secrets
import jwt
from urllib.parse import parse_qs, urlsplit
from starlette.testclient import TestClient
from test_customer_web import CustomerWebFixture
from omnixat_core.customer_web import create_app
from omnixat_core.identity import AccessTokenVerifier, AuthenticationError
from qualification.keycloak_customer import KeycloakFixture


class KeycloakCustomerTests(CustomerWebFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = KeycloakFixture().__enter__()
        cls.addClassCleanup(cls.provider.__exit__, None, None, None)

    def setUp(self):
        super().setUp()
        self.addCleanup(self.owner.execute, 'UPDATE omnixat.identities SET issuer=%s,subject=%s WHERE id=%s',
                        (self.issuer,self.subject,self.user))
        self.owner.execute('UPDATE omnixat.identities SET issuer=%s,subject=%s WHERE id=%s',
                           (self.provider.issuer,self.provider.subject,self.user))
        app = create_app(verifier=self.provider.verifier,connection_factory=self.records_factory,
                         directory_connection_factory=self.directory_factory,public_origin=self.origin)
        self.live_client = TestClient(app,base_url=self.origin)
        self.addCleanup(self.live_client.close)

    def test_real_code_login_issues_profiled_access_token_and_id_token_is_rejected(self):
        tokens = self.provider.login()
        token = tokens['access_token']
        self.assertEqual(jwt.get_unverified_header(token)['typ'],'at+jwt')
        verified = self.provider.verifier.verify(token)
        self.assertEqual(verified.subject,self.provider.subject)
        self.assertTrue({'records:read','records:write'} <= verified.scopes)
        for verifier, value in [
            (self.provider.verifier,tokens['id_token']),
            (AccessTokenVerifier(issuer=self.provider.issuer,audience='different-api',public_keys=self.provider.public_keys),token),
        ]:
            with self.assertRaises(AuthenticationError):
                verifier.verify(value)
        headers = {'X-Forwarded-Access-Token':token, 'Origin':self.origin, 'Sec-Fetch-Site':'same-origin'}
        page = self.live_client.get('/v1/workspaces',headers=headers)
        self.assertEqual(page.status_code,200)
        self.assertEqual([item['id'] for item in page.json()['data']['items']],[self.a])
        context = self.live_client.get(self.base+'/context',headers=headers).json()['data']
        self.assertEqual(context['actor_id'],str(self.user))
        headers |= {'X-OmniXAT-Expected-Actor':str(self.user),'Idempotency-Key':'fictional-provider-note'}
        url = self.base+f'/organisations/{self.org}/notes'
        payload = {'body':'Fictional note through real Keycloak login'}
        first = self.live_client.post(url,headers=headers,json=payload)
        retry = self.live_client.post(url,headers=headers,json=payload)
        self.assertEqual(first.status_code,201,first.text)
        self.assertEqual(retry.json()['data'],first.json()['data'])
        self.assertEqual(first.json()['data']['created_by'],str(self.user))
        self.assertEqual(self.live_client.get(self.base.replace(self.a,self.b)+'/context',headers={'X-Forwarded-Access-Token':token}).status_code,403)
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        self.assertEqual(self.live_client.post(url,headers=headers,json=payload).status_code,403)

    def test_provider_enforces_pkce_and_one_time_authorization_codes(self):
        response = self.provider.authorization(challenge=False)
        self.assertEqual(response.status_code,302)
        location = response.headers['location']
        self.assertTrue(location.startswith('https://workspace.example.test/oauth2/callback?'))
        rejection = parse_qs(urlsplit(location).query)
        self.assertEqual(rejection.get('error'),['invalid_request'])
        self.assertNotIn('code',rejection)
        code, verifier, _ = self.provider.authorization()
        self.assertEqual(self.provider.exchange(code,secrets.token_urlsafe(32)).status_code,400)
        code, verifier, _ = self.provider.authorization()
        self.assertEqual(self.provider.exchange(code,verifier).status_code,200)
        self.assertEqual(self.provider.exchange(code,verifier).status_code,400)

    def test_real_provider_token_never_grants_unprovisioned_or_viewer_write_authority(self):
        token = self.provider.login()['access_token']
        headers = {'X-Forwarded-Access-Token':token,'Origin':self.origin,'Sec-Fetch-Site':'same-origin'}
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.live_client.get(self.base+'/context',headers=headers).status_code,200)
        self.assertEqual(self.live_client.post(self.base+'/organisations',headers=headers,json={'display_name':'Denied'}).status_code,403)
        self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=%s WHERE id=%s',
                           (self.provider.verifier.verify(token).issued_at,self.user))
        self.assertEqual(self.live_client.get(self.base+'/context',headers=headers).status_code,403)
        self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=0,subject=%s WHERE id=%s',(self.subject,self.user))
        self.assertEqual(self.live_client.get(self.base+'/context',headers=headers).status_code,403)

    def test_real_refresh_preserves_profile_and_rotated_refresh_cannot_be_reused(self):
        original = self.provider.login()
        data = {'grant_type':'refresh_token','client_id':'omnixat-customer-qualification',
                'client_secret':self.provider.client_secret,'refresh_token':original['refresh_token']}
        endpoint = self.provider.issuer+'/protocol/openid-connect/token'
        with self.provider.client() as client:
            response = client.post(endpoint,data=data)
            self.assertEqual(response.status_code,200)
            tokens = response.json()
            self.assertEqual(self.provider.verifier.verify(tokens['access_token']).subject,self.provider.subject)
            self.assertNotEqual(tokens['refresh_token'],original['refresh_token'])
            self.assertEqual(client.post(endpoint,data=data).status_code,400)
            for grant in ('client_credentials','password'):
                response = client.post(endpoint,data={
                    'grant_type':grant,'client_id':'omnixat-customer-qualification',
                    'client_secret':self.provider.client_secret,
                    'username':'fictional-editor','password':self.provider.password})
                self.assertIn(response.status_code,(400,401))
                self.assertEqual(response.json().get('error'),'unauthorized_client')

    def test_provider_issued_read_only_scope_cannot_write_as_persisted_editor(self):
        tokens = self.provider.login(scope='openid records:read')
        token = tokens['access_token']
        verified = self.provider.verifier.verify(token)
        self.assertIn('records:read',verified.scopes)
        self.assertNotIn('records:write',verified.scopes)
        headers = {'X-Forwarded-Access-Token':token,'Origin':self.origin,'Sec-Fetch-Site':'same-origin'}
        self.assertEqual(self.live_client.get(self.base+'/context',headers=headers).status_code,200)
        self.assertEqual(self.live_client.post(self.base+'/organisations',headers=headers,json={'display_name':'Denied'}).status_code,403)
