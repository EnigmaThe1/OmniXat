"""Fictional originals through real HTTP, signed identity and PostgreSQL."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
import psycopg
from psycopg import sql
from starlette.testclient import TestClient
from test_customer_web import CustomerWebFixture
from omnixat_core.customer_web import create_app
from omnixat_core import customer_evidence
SCOPES = 'records:read records:write evidence:read evidence:register'


class CustomerEvidenceFixture(CustomerWebFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for grants in ('SELECT, INSERT ON omnixat.evidence_registrations',
                       'INSERT (tenant_id, evidence_id, original_bytes) ON omnixat.evidence_quarantine',
                       'SELECT (tenant_id, evidence_id, stored_at) ON omnixat.evidence_quarantine'):
            cls.owner.execute(sql.SQL('GRANT '+grants+' TO {}').format(sql.Identifier(cls.role)))

    def setUp(self):
        super().setUp()
        self.spool = TemporaryDirectory(); self.addCleanup(self.spool.cleanup)
        self.app = create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,
            evidence_quarantine_dir=self.spool.name)
        self.client = TestClient(self.app,base_url=self.origin); self.addCleanup(self.client.close)
        self.url = self.base+f'/organisations/{self.org}/evidence'
        self.original = b'Fictional description,Amount\r\nFictional purchase,12.00\r\n'

    def headers(self, **changes):
        return super().headers(**({'scope':SCOPES} | changes))

    def upload(self, *, content=None, headers=None, url=None):
        return self.client.post(url or self.url,content=self.original if content is None else content,
            headers=self.headers() | {'Content-Type':'text/csv'} | (headers or {}))

    def rows(self, table):
        return self.owner.execute(sql.SQL('SELECT count(*) FROM omnixat.{} WHERE tenant_id=%s').format(
            sql.Identifier(table)),(self.a,)).fetchone()[0]


class CustomerEvidenceTests(CustomerEvidenceFixture):
    def test_upload_retry_list_and_payload_privileges(self):
        first, retry = self.upload(), self.upload()
        self.assertEqual(first.status_code,201,first.text)
        self.assertEqual(retry.json()['data'],first.json()['data'])
        self.assertEqual(self.rows('evidence_registrations'),1); self.assertEqual(self.rows('evidence_quarantine'),1)
        row = self.owner.execute('SELECT q.original_bytes,e.content_sha256,e.registered_by FROM omnixat.evidence_quarantine q JOIN omnixat.evidence_registrations e ON e.tenant_id=q.tenant_id AND e.id=q.evidence_id WHERE e.tenant_id=%s',(self.a,)).fetchone()
        self.assertEqual(row,(self.original,sha256(self.original).digest(),str(self.user)))
        response = self.client.get(self.url,headers=self.headers())
        self.assertEqual(response.status_code,200,response.text)
        item = response.json()['data']['items'][0]
        self.assertEqual(item['id'],first.json()['data']['id']); self.assertIsNotNone(item['stored_at'])
        self.assertEqual(set(item),{'id','media_type','byte_size','registered_at','stored_at'})
        self.assertEqual(set(response.headers['cache-control'].split(', ')),{'no-store'})
        self.assertEqual(list(Path(self.spool.name).iterdir()),[])
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.runtime.execute('SELECT original_bytes FROM omnixat.evidence_quarantine')

    def test_viewer_reads_but_cannot_upload_and_agent_cannot_impersonate_human(self):
        self.upload()
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.client.get(self.url,headers=self.headers()).status_code,200)
        self.assertEqual(self.upload(headers=self.headers(role='owner')).status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='owner' WHERE user_id=%s",(self.user,))
        self.owner.execute("UPDATE omnixat.identities SET actor_kind='agent' WHERE id=%s",(self.user,))
        self.assertEqual(self.upload(headers=self.headers(actor_kind='human')).status_code,403)
        self.assertEqual(self.rows('evidence_quarantine'),1)

    def test_scopes_revocation_and_expiry_reject_before_storage(self):
        for scope in ('records:read records:write','records:read evidence:read evidence:register',
                      'records:read records:write evidence:register','records:read records:write evidence:read'):
            with self.subTest(scope=scope):
                self.assertEqual(self.upload(headers=self.headers(scope=scope)).status_code,403)
        self.assertEqual(self.upload(headers=self.headers(iat=self.iat-60,exp=self.iat-1)).status_code,401)
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        self.assertEqual(self.upload().status_code,403); self.assertEqual(self.rows('evidence_quarantine'),0)

    def test_tenant_and_parent_binding_on_upload_and_list(self):
        self.upload()
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.b,self.user))
        for url in (self.url.replace(self.a,self.b),self.url.replace(str(self.org),str(uuid4()))):
            self.assertEqual(self.upload(url=url).status_code,404)
            self.assertEqual(self.client.get(url,headers=self.headers()).status_code,404)
        self.assertEqual(self.rows('evidence_quarantine'),1)

    def test_stream_limits_media_origin_and_no_client_digest(self):
        for extra,status in [({'Content-Type':'application/octet-stream'},415),({'Content-Encoding':'gzip'},415),
                             ({'Content-Length':'20971521'},413),({'Origin':'https://other.example.test'},403),
                             ({'Idempotency-Key':'client-digest'},400)]:
            self.assertEqual(self.upload(headers=extra).status_code,status)
        self.assertEqual(self.upload(content=b'').status_code,413)
        with patch.object(customer_evidence,'MAX_EVIDENCE_BYTES',8):
            self.assertEqual(self.upload(content=(x for x in [b'1234',b'56789'])).status_code,413)
        self.assertEqual(self.rows('evidence_registrations'),0)
        self.assertEqual(list(Path(self.spool.name).iterdir()),[])

    def test_partial_registration_is_visible_and_same_file_retry_finishes(self):
        with patch.object(customer_evidence,'store_quarantined_evidence',side_effect=OSError('fictional private diagnostic')):
            response = self.upload(); self.assertEqual(response.status_code,503)
            self.assertNotIn('diagnostic',response.text)
        item = self.client.get(self.url,headers=self.headers()).json()['data']['items'][0]
        self.assertIsNone(item['stored_at'])
        retry = self.upload(); self.assertEqual(retry.status_code,201,retry.text)
        self.assertEqual(retry.json()['data']['id'],item['id'])
        self.assertEqual(self.rows('evidence_registrations'),1); self.assertEqual(self.rows('evidence_quarantine'),1)

    def test_membership_rechecked_before_payload_storage(self):
        original = customer_evidence.register_evidence
        def revoke(*args,**kwargs):
            result = original(*args,**kwargs)
            self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
            return result
        with patch.object(customer_evidence,'register_evidence',side_effect=revoke):
            self.assertEqual(self.upload().status_code,403)
        self.assertEqual(self.rows('evidence_quarantine'),0)
        self.assertEqual(list(Path(self.spool.name).iterdir()),[])

    def test_paging_conflict_and_live_capabilities(self):
        self.upload(); self.upload(content=b'Fictional second file')
        page = self.client.get(self.url+'?limit=1',headers=self.headers()).json()['data']
        other = self.client.get(self.url+'?limit=1&after='+page['next_cursor'],headers=self.headers()).json()['data']
        self.assertNotEqual(page['items'][0]['id'],other['items'][0]['id']); self.assertIsNone(other['next_cursor'])
        for query in ('?limit=0','?limit=01','?limit=1&limit=2','?after=bad','?filename=private'):
            self.assertEqual(self.client.get(self.url+query,headers=self.headers()).status_code,400)
        self.assertEqual(self.upload(headers={'Content-Type':'application/pdf'}).status_code,409)
        context = self.client.get(self.base+'/context',headers=self.headers()).json()['data']
        self.assertTrue(context['evidence_access']); self.assertTrue(context['can_upload_evidence'])
        self.assertFalse(self.client.get(self.base+'/context',headers=self.headers(scope='records:read')).json()['data']['evidence_access'])

    def test_private_spool_and_opt_in_routes(self):
        Path(self.spool.name).chmod(0o755)
        try:
            with self.assertRaises(ValueError):
                create_app(verifier=self.verifier,connection_factory=self.records_factory,
                    directory_connection_factory=self.directory_factory,public_origin=self.origin,evidence_quarantine_dir=self.spool.name)
        finally:
            Path(self.spool.name).chmod(0o700)
        app = create_app(verifier=self.verifier,connection_factory=self.records_factory,
                         directory_connection_factory=self.directory_factory,public_origin=self.origin)
        with TestClient(app,base_url=self.origin) as client:
            self.assertEqual(client.get(self.url,headers=self.headers()).status_code,404)

    def test_slow_body_and_disconnect_cleanup_without_registry_writes(self):
        import anyio
        def scope():
            headers = self.headers() | {'Host':'workspace.example.test','Content-Type':'text/csv'}
            return {'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST',
                    'scheme':'https','path':self.url,'raw_path':self.url.encode(), 'query_string':b'',
                    'server':('workspace.example.test',443),'client':('127.0.0.1',1),
                    'headers':[(key.lower().encode(),value.encode()) for key,value in headers.items()]}
        async def exercise(disconnect):
            sent = []
            count = 0
            async def receive():
                nonlocal count
                count += 1
                if count == 1:
                    return {'type':'http.request','body':b'Fictional partial','more_body':True}
                if disconnect:
                    return {'type':'http.disconnect'}
                await anyio.sleep_forever()
            async def send(message):
                sent.append(message)
            await self.app(scope(),receive,send)
            return next(message['status'] for message in sent if message['type']=='http.response.start')
        with patch.object(customer_evidence,'UPLOAD_TIMEOUT_SECONDS',0.05):
            self.assertEqual(anyio.run(exercise,False),408)
            self.assertEqual(anyio.run(exercise,True),400)
        self.assertEqual(self.rows('evidence_registrations'),0)
        self.assertEqual(list(Path(self.spool.name).iterdir()),[])
        self.assertEqual(self.upload().status_code,201)

    def test_truncated_length_and_duplicate_headers_cannot_register(self):
        self.assertEqual(self.upload(headers={'Content-Length':str(len(self.original)+1)}).status_code,400)
        self.assertEqual(self.upload(headers={'Content-Length':'1'}).status_code,413)
        base = list(self.headers().items())
        for extra, status in [([('Content-Type','text/csv'),('Content-Type','application/pdf')],415),
                              ([('Content-Type','text/csv'),('Content-Encoding','identity'),('Content-Encoding','gzip')],415),
                              ([('Content-Type','text/csv'),('Content-Length','1'),('Content-Length','2')],400)]:
            response = self.client.post(self.url,content=self.original,headers=base+extra)
            self.assertEqual(response.status_code,status,response.text)
        self.assertEqual(self.rows('evidence_registrations'),0)
        self.assertEqual(list(Path(self.spool.name).iterdir()),[])

    def test_four_inflight_bodies_bound_admission_and_slots_recover(self):
        import anyio
        headers = self.headers() | {'Host':'workspace.example.test','Content-Type':'text/csv'}
        scope = {'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST',
                 'scheme':'https','path':self.url,'raw_path':self.url.encode(),'query_string':b'',
                 'server':('workspace.example.test',443),'client':('127.0.0.1',1),
                 'headers':[(key.lower().encode(),value.encode()) for key,value in headers.items()]}
        async def exercise():
            release = anyio.Event()
            sender, receiver = anyio.create_memory_object_stream(4)
            statuses = []
            async def upload_body():
                first = True
                async def receive():
                    nonlocal first
                    if first:
                        first = False
                        await sender.send(True)
                        return {'type':'http.request','body':self.original,'more_body':True}
                    await release.wait()
                    return {'type':'http.request','body':b'','more_body':False}
                async def send(message):
                    if message['type']=='http.response.start':
                        statuses.append(message['status'])
                await self.app(dict(scope),receive,send)
            with anyio.fail_after(5):
                async with anyio.create_task_group() as group:
                    for _ in range(4):
                        group.start_soon(upload_body)
                    for _ in range(4):
                        await receiver.receive()
                    try:
                        response = await anyio.to_thread.run_sync(self.upload)
                        self.assertEqual(response.status_code,503)
                    finally:
                        release.set()
            return statuses
        self.assertEqual(anyio.run(exercise),[201]*4)
        self.assertEqual(self.rows('evidence_quarantine'),1)
        self.assertEqual(self.upload().status_code,201)
        self.assertEqual(list(Path(self.spool.name).iterdir()),[])

    def test_token_expiry_after_staging_or_registration_returns_sign_in_recovery(self):
        from contextlib import contextmanager
        from datetime import datetime, timedelta, timezone
        original_stage = customer_evidence.stage_evidence
        original_register = customer_evidence.register_evidence
        # Advance only JWT validation's clock, using a genuinely signed token.
        class Clock(datetime):
            instant = datetime.now(timezone.utc)

            @classmethod
            def now(cls, tz=None):
                return cls.instant.astimezone(tz)
        expired_time = datetime.now(timezone.utc) + timedelta(seconds=600)
        for phase in ('staged', 'registered'):
            with self.subTest(phase=phase):
                self.owner.execute('DELETE FROM omnixat.evidence_registrations WHERE tenant_id=%s',(self.a,))
                Clock.instant = datetime.now(timezone.utc)
                @contextmanager
                def staged(*args, **kwargs):
                    with original_stage(*args, **kwargs) as result:
                        if phase == 'staged':
                            Clock.instant = expired_time
                        yield result
                def registered(*args, **kwargs):
                    result = original_register(*args, **kwargs)
                    if phase == 'registered':
                        Clock.instant = expired_time
                    return result
                with patch('jwt.api_jwt.datetime', Clock), patch.object(customer_evidence, 'stage_evidence', staged), patch.object(
                        customer_evidence, 'register_evidence', registered):
                    response = self.upload()
                self.assertEqual(response.status_code,401,response.text)
                self.assertEqual(response.json()['error']['code'],'invalid_token')
                self.assertEqual(self.rows('evidence_quarantine'),0)
                self.assertEqual(self.rows('evidence_registrations'),int(phase=='registered'))
                self.assertEqual(list(Path(self.spool.name).iterdir()),[])
                # A fresh token and the same original finish any partial receipt.
                self.assertEqual(self.upload().status_code,201)
                self.assertEqual(self.rows('evidence_registrations'),1)
                self.assertEqual(self.rows('evidence_quarantine'),1)
                self.owner.execute('DELETE FROM omnixat.evidence_quarantine WHERE tenant_id=%s',(self.a,))

    def test_receipt_exposes_exact_original_fingerprint_without_payload_or_actor(self):
        created = self.upload().json()['data']
        response = self.client.get(self.url+'/'+created['id'],headers=self.headers())
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['data'], created | {'organisation_id':str(self.org),
                                           'content_sha256':sha256(self.original).hexdigest()})
        self.assertEqual(set(response.headers['cache-control'].split(', ')),{'no-store'})
        self.assertEqual(response.headers['referrer-policy'],'no-referrer')
        self.assertNotIn(self.original.decode(),response.text)
        self.assertNotIn(str(self.user),response.text)
        self.assertEqual(self.client.head(self.url+'/'+created['id'],headers=self.headers()).content,b'')
        self.assertEqual(self.rows('evidence_quarantine'),1)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.runtime.execute('SELECT original_bytes FROM omnixat.evidence_quarantine')

    def test_receipt_is_bound_to_tenant_organisation_and_current_membership(self):
        evidence = self.upload().json()['data']['id']
        url = self.url+'/'+evidence
        other = self.client.post(self.base+'/organisations',headers=self.headers(),
                                 json={'display_name':'Other fictional organisation'}).json()['data']['id']
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'viewer',NULL)",(self.b,self.user))
        for wrong in (url.replace(self.a,self.b),url.replace(str(self.org),other),self.url+'/'+str(uuid4())):
            self.assertEqual(self.client.get(wrong,headers=self.headers()).status_code,404)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE tenant_id=%s AND user_id=%s",(self.a,self.user))
        self.assertEqual(self.client.get(url,headers=self.headers()).status_code,200)
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE tenant_id=%s AND user_id=%s',(self.a,self.user))
        denied = self.client.get(url,headers=self.headers(role='owner'))
        self.assertEqual(denied.status_code,403)
        self.assertNotIn(sha256(self.original).hexdigest(),denied.text)

    def test_receipt_rechecks_authority_between_parent_check_and_metadata_read(self):
        evidence = self.upload().json()['data']['id']
        original = customer_evidence.CustomerEvidence.authorize
        def revoke(*args,**kwargs):
            result = original(*args,**kwargs)
            self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
            return result
        with patch.object(customer_evidence.CustomerEvidence,'authorize',revoke):
            response = self.client.get(self.url+'/'+evidence,headers=self.headers())
        self.assertEqual(response.status_code,403)
        self.assertNotIn(sha256(self.original).hexdigest(),response.text)

    def test_receipt_incomplete_registration_and_retry_keep_same_fingerprint(self):
        with patch.object(customer_evidence,'store_quarantined_evidence',side_effect=OSError('private')):
            self.assertEqual(self.upload().status_code,503)
        item = self.client.get(self.url,headers=self.headers()).json()['data']['items'][0]
        url = self.url+'/'+item['id']
        before = self.client.get(url,headers=self.headers()).json()['data']
        self.assertIsNone(before['stored_at'])
        self.assertEqual(before['content_sha256'],sha256(self.original).hexdigest())
        self.assertEqual(self.upload().status_code,201)
        after = self.client.get(url,headers=self.headers()).json()['data']
        self.assertIsNotNone(after['stored_at'])
        self.assertEqual(after | {'stored_at':None},before)

    def test_receipt_authentication_scope_request_validation_and_opt_in(self):
        evidence = self.upload().json()['data']['id']
        url = self.url+'/'+evidence
        self.assertEqual(self.client.get(url).status_code,401)
        self.assertEqual(self.client.get(url,headers=self.headers(scope='records:read')).status_code,403)
        self.assertEqual(self.client.get(url,headers=self.headers(scope='evidence:read')).status_code,403)
        self.assertEqual(self.client.get(url,headers=self.headers(iat=self.iat-60,exp=self.iat-1)).status_code,401)
        self.assertEqual(self.client.get(self.url+'/invalid',headers=self.headers()).status_code,400)
        for query in ('?limit=1','?after='+str(uuid4()),'?download=true'):
            self.assertEqual(self.client.get(url+query,headers=self.headers()).status_code,400)
        self.assertEqual(self.client.get(url,headers=self.headers() | {'Idempotency-Key':'unsupported'}).status_code,400)
        self.assertEqual(self.client.post(url,headers=self.headers(),content=b'fictional').status_code,405)
        disabled = create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin)
        with TestClient(disabled,base_url=self.origin) as client:
            self.assertEqual(client.get(url,headers=self.headers()).status_code,404)

    def test_actor_bound_upload_denies_account_change_without_intake(self):
        wrong = self.headers() | {'X-OmniXAT-Expected-Actor':str(uuid4())}
        response = self.upload(headers=wrong)
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(response.json()['error']['code'],'session_changed')
        self.assertEqual(self.rows('evidence_registrations'),0)
        self.assertEqual(self.rows('evidence_quarantine'),0)
        self.assertEqual(list(Path(self.spool.name).iterdir()),[])
        headers = self.headers() | {'X-OmniXAT-Expected-Actor':str(self.user)}
        first = self.upload(headers=headers)
        self.assertEqual(first.status_code,201,first.text)
        self.assertEqual(self.upload(headers=headers).json()['data'],first.json()['data'])
        self.assertEqual(self.client.get(self.url,headers=headers).status_code,400)
        self.assertEqual(self.upload(headers={'X-OmniXAT-Expected-Actor':'bad'}).status_code,400)
        duplicates = list(self.headers().items())+[('Content-Type','text/csv')]+[('X-OmniXAT-Expected-Actor',str(self.user))]*2
        self.assertEqual(self.client.post(self.url,content=self.original,headers=duplicates).status_code,400)
        self.assertEqual(self.rows('evidence_quarantine'),1)
