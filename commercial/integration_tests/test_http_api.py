from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4
import json

import psycopg
from starlette.testclient import TestClient

from test_identity_postgres import MembershipFixture
from omnixat_core.http_api import create_app, MAX_BODY_BYTES


class HttpRecordsTests(MembershipFixture):
    def setUp(self):
        super().setUp()
        self.connections = []
        @contextmanager
        def factory():
            with psycopg.connect(self.runtime_dsn, autocommit=True, connect_timeout=2) as connection:
                self.connections.append(connection)
                yield connection
        self.app = create_app(verifier=self.verifier, connection_factory=factory, allowed_hosts=['testserver'])
        self.client = TestClient(self.app, base_url='https://testserver')
        self.addCleanup(self.client.close)
        self.base = '/v1/workspaces/' + self.a

    def auth(self, **changes):
        return {'Authorization':'Bearer ' + self.token(**changes)}

    def get(self, path=None, **kwargs):
        return self.client.get(path or self.base+'/organisations/'+str(self.org),
                               headers=kwargs.pop('headers',self.auth()),**kwargs)

    def post(self, path=None, **kwargs):
        return self.client.post(path or self.base+'/organisations',
                                headers=kwargs.pop('headers',self.auth()),**kwargs)

    def test_http_round_trip_uses_shared_record_service(self):
        response = self.post(json={'display_name':'Fictional HTTP company'})
        self.assertEqual(response.status_code,201,response.text)
        org = response.json()['data']['id']
        self.assertEqual(response.json()['data']['created_by'],str(self.user))
        note = self.post(self.base+'/organisations/'+org+'/notes',json={'body':'Fictional HTTP note'})
        self.assertEqual(note.status_code,201,note.text)
        retrieved = self.get(self.base+'/notes/'+note.json()['data']['id'])
        self.assertEqual(retrieved.json()['data']['body'],'Fictional HTTP note')
        self.assertTrue(all(c.closed for c in self.connections))

    def test_missing_duplicate_invalid_and_cookie_auth_do_not_open_database(self):
        for headers in ({},{'Cookie':'session=fictional'}, {'Authorization':'Bearer invalid'},
                        [('Authorization','Bearer '+self.token()),('Authorization','Bearer '+self.token())],
                        {'X-User-Role':'owner','X-Tenant-ID':self.a}):
            response = self.get(headers=headers)
            self.assertEqual(response.status_code,401,response.text)
            self.assertEqual(response.headers['www-authenticate'],'Bearer')
        self.assertEqual(self.connections,[])

    def test_http_cross_tenant_read_and_note_link_are_hidden(self):
        self.owner.execute("INSERT INTO omnixat.memberships(tenant_id,user_id,role) VALUES (%s,%s,'editor')",(self.b,self.user))
        other = '/v1/workspaces/'+self.b
        for response in (self.get(other+'/organisations/'+str(self.org)),
                         self.post(other+'/organisations/'+str(self.org)+'/notes',json={'body':'Forbidden'}),
                         self.get(other+'/notes/'+str(self.note)),
                         self.get(other+'/notes/'+str(uuid4()))):
            self.assertEqual(response.status_code,404,response.text)
            self.assertEqual(response.json()['error']['code'],'not_found')

    def test_unknown_workspace_and_revoked_membership_are_denied(self):
        self.assertEqual(self.get('/v1/workspaces/'+self.b+'/organisations/'+str(self.org)).status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s",(self.user,))
        self.assertEqual(self.get().status_code,403)

    def test_viewer_and_token_scopes_cannot_write_despite_role_headers(self):
        self.assertEqual(self.post(json={'display_name':'Denied'},headers=self.auth(scope='records:read')).status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        headers = self.auth(role='owner',staff_role='platform_owner') | {'X-Role':'owner'}
        self.assertEqual(self.post(json={'display_name':'Denied'},headers=headers).status_code,403)
        self.assertEqual(self.get().status_code,200)

    def test_strict_payload_rejects_mass_assignment_and_bad_field_types(self):
        for body in ({'display_name':'Valid','tenant_id':self.b}, {'display_name':False},
                     {'display_name':' '}, {'display_name':'x'*201}, {'display_name':'nul\x00text'},
                     [], {'body':'Wrong field'}):
            response=self.post(json=body)
            self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.connections,[])

    def test_malformed_duplicate_and_nonfinite_json_are_rejected(self):
        for body in ('{', '{"display_name":"first","display_name":"second"}', '{"display_name":NaN}'):
            self.assertEqual(self.post(content=body,headers=self.auth()|{'Content-Type':'application/json'}).status_code,400)
        self.assertEqual(self.connections,[])

    def test_body_limit_counts_actual_streamed_bytes(self):
        body=json.dumps({'display_name':'x'*(MAX_BODY_BYTES+1)}).encode()
        for extra in ({},{'Content-Length':'1'}):
            response=self.post(content=iter([body[:100],body[100:]]),headers=self.auth()|{'Content-Type':'application/json'}|extra)
            self.assertEqual(response.status_code,413,response.text)
        self.assertEqual(self.connections,[])

    def test_content_headers_are_checked(self):
        for extra,status in [({'Content-Type':'text/plain'},415),
                             ({'Content-Type':'application/json','Content-Encoding':'gzip'},415),
                             ({'Content-Type':'application/json','Content-Length':'-1'},400)]:
            self.assertEqual(self.post(content='{}',headers=self.auth()|extra).status_code,status)
        self.assertEqual(self.connections,[])

    def test_host_tls_and_proxy_header_spoofing_are_rejected(self):
        self.assertEqual(self.get(headers=self.auth()|{'Host':'attacker.example.test'}).status_code,400)
        self.assertEqual(self.client.get('http://testserver'+self.base+'/organisations/'+str(self.org),
                                        headers=self.auth()|{'X-Forwarded-Proto':'https'}).status_code,400)
        self.assertEqual(self.connections,[])

    def test_errors_and_success_have_generated_request_ids_and_no_cache(self):
        for response in (self.get(headers=self.auth()|{'X-Request-ID':'untrusted'}),self.get(headers={}),self.get('/absent')):
            self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertEqual(response.headers['x-content-type-options'],'nosniff')
            self.assertEqual(response.json()['request_id'],response.headers['x-request-id'])
            self.assertNotEqual(response.json()['request_id'],'untrusted')

    def test_database_errors_are_generic_and_connections_are_closed(self):
        with patch('omnixat_core.http_api.authenticated_records',side_effect=psycopg.OperationalError('PRIVATE database password fictional')):
            response=self.get()
        self.assertEqual(response.status_code,503)
        self.assertNotIn('PRIVATE',response.text)
        self.assertTrue(self.connections[-1].closed)
        with patch('omnixat_core.http_api.authenticated_records',side_effect=RuntimeError('PRIVATE SQL payload')):
            response=self.get()
        self.assertEqual(response.status_code,500)
        self.assertNotIn('PRIVATE',response.text)
        self.assertTrue(self.connections[-1].closed)

    def test_no_filing_approval_billing_or_admin_routes_exist(self):
        for path in ('/admin/v1/metrics',self.base+'/approvals',self.base+'/submissions',self.base+'/billing'):
            self.assertEqual(self.post(path,json={}).status_code,404)
        self.assertEqual(self.connections,[])

    def test_identifiers_query_tokens_and_unimplemented_idempotency_are_rejected(self):
        self.assertEqual(self.get('/v1/workspaces/not-a-uuid/notes/'+str(self.note)).status_code,400)
        self.assertEqual(self.get(self.base+'/notes/not-a-uuid').status_code,400)
        self.assertEqual(self.get(self.base+'/notes/'+str(self.note)+'?access_token=fictional',headers={}).status_code,401)
        self.assertEqual(self.post(json={'display_name':'Fictional'},headers=self.auth()|{'Idempotency-Key':'unsupported'}).status_code,400)
        self.assertEqual(self.connections,[])

    def test_method_errors_are_json_and_do_not_open_database(self):
        response=self.client.delete(self.base+'/organisations/'+str(self.org),headers=self.auth())
        self.assertEqual(response.status_code,405)
        self.assertEqual(response.json()['error']['code'],'method_not_allowed')
        self.assertEqual(self.connections,[])

    def test_host_configuration_requires_explicit_hosts(self):
        for hosts in ([],['*'],'testserver',['https://testserver']):
            with self.assertRaises(ValueError):
                create_app(verifier=self.verifier,connection_factory=lambda:None,allowed_hosts=hosts)

    def test_invalid_unicode_and_huge_content_length_are_controlled(self):
        response=self.post(content=r'{"display_name":"\ud800"}',headers=self.auth()|{'Content-Type':'application/json'})
        self.assertEqual(response.status_code,422)
        response=self.post(content='{}',headers=self.auth()|{'Content-Type':'application/json','Content-Length':'9'*5000})
        self.assertEqual(response.status_code,413)
        self.assertEqual(self.connections,[])

    def test_slow_body_times_out_before_opening_database(self):
        import asyncio
        from starlette.requests import Request
        from omnixat_core.http_api import _payload, ApiError
        async def check():
            async def receive():
                await asyncio.sleep(.05)
                return {'type':'http.request','body':b'{}','more_body':False}
            request=Request({'type':'http','headers':[(b'content-type',b'application/json')]},receive)
            with patch('omnixat_core.http_api.BODY_TIMEOUT_SECONDS',.01):
                with self.assertRaises(ApiError) as result:
                    await _payload(request,'display_name',200)
            self.assertEqual(result.exception.status,408)
        asyncio.run(check())
        self.assertEqual(self.connections,[])
